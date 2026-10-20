#!/usr/bin/env python3
"""Credential-free smoke evaluation for production Frontline tool handlers.

This uses only Python's standard library so it can run in a minimal reviewer
environment. It installs import-time stubs for unavailable provider SDKs, then
imports and executes the real production handlers. Each business-effect
boundary is replaced with a mock before a handler is invoked.
"""

from __future__ import annotations

import asyncio
import importlib
import importlib.util
import json
import sys
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _load_transfer_routing():
    """Load the production pure routing helper without importing service SDKs."""
    path = ROOT.parent / "shared" / "src" / "transfer_routing.py"
    spec = importlib.util.spec_from_file_location("_frontline_transfer_routing", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _install_import_stubs() -> None:
    """Provide only import-time contracts; no provider implementation is faked."""
    logger_module = types.ModuleType("loguru")
    logger_module.logger = SimpleNamespace(
        info=lambda *args, **kwargs: None,
        warning=lambda *args, **kwargs: None,
        error=lambda *args, **kwargs: None,
        exception=lambda *args, **kwargs: None,
    )
    sys.modules.setdefault("loguru", logger_module)

    pipecat = types.ModuleType("pipecat")
    frames_package = types.ModuleType("pipecat.frames")
    frames = types.ModuleType("pipecat.frames.frames")

    class EndFrame:
        pass

    class FunctionCallResultProperties:
        def __init__(self, *, run_llm=True):
            self.run_llm = run_llm

    frames.EndFrame = EndFrame
    frames.FunctionCallResultProperties = FunctionCallResultProperties
    sys.modules.setdefault("pipecat", pipecat)
    sys.modules.setdefault("pipecat.frames", frames_package)
    sys.modules.setdefault("pipecat.frames.frames", frames)

    carrier_service = types.ModuleType("carrier_service")

    class CarrierServiceError(Exception):
        pass

    carrier_service.CarrierServiceError = CarrierServiceError
    carrier_service.fetch_carrier_by_mc = AsyncMock()
    carrier_service.get_carrier_name = MagicMock()
    sys.modules.setdefault("carrier_service", carrier_service)

    db_operations = types.ModuleType("db_operations")

    class DatabaseOperationError(Exception):
        pass

    db_operations.DatabaseOperationError = DatabaseOperationError
    db_operations.CallRecordResult = object
    db_operations.create_call_record = MagicMock()
    db_operations.end_call_record = MagicMock()
    db_operations.link_negotiation_to_call = MagicMock()
    db_operations.update_call_load = MagicMock()
    db_operations.update_call_mc = MagicMock()
    sys.modules.setdefault("db_operations", db_operations)

    load_context_utils = types.ModuleType("load_context_utils")
    load_context_utils.normalize_load_data = lambda value: value
    load_context_utils.build_negotiation_prompt = lambda value: "rendered"
    sys.modules.setdefault("load_context_utils", load_context_utils)

    src = types.ModuleType("src")
    src.NegotiationDBService = SimpleNamespace(
        get_load_by_reference=MagicMock(),
        get_load=MagicMock(),
        notify_carrier_quote=MagicMock(),
    )
    routing = _load_transfer_routing()
    src.build_transfer_phone_number = routing.build_transfer_phone_number
    src.coerce_e164_transfer_number = routing.coerce_e164_transfer_number
    sys.modules.setdefault("src", src)


_install_import_stubs()
call_helpers = importlib.import_module("call_helpers")
transfer_tool_handler = importlib.import_module("transfer_tool_handler")


async def _capture():
    calls = []

    async def callback(payload, **kwargs):
        calls.append((payload, kwargs))

    return callback, calls


class OfflineHandlerEvaluation(unittest.IsolatedAsyncioTestCase):
    """All cases call production functions; provider effects are mocked."""

    async def test_eval_ref_001_rejects_transcript_prose_before_lookup(self):
        callback, results = await _capture()
        context = SimpleNamespace(messages=[{"role": "system", "content": "initial"}])
        lookup = MagicMock()
        upsert = MagicMock()
        with (
            patch.object(call_helpers.NegotiationDBService, "get_load_by_reference", lookup),
            patch.object(call_helpers.NegotiationDBService, "upsert_carrier_phone", upsert, create=True),
        ):
            await call_helpers.get_load_context(
                "get_load_context", "ref-1", {"load_id": "noted down"}, None, context, callback
            )
        self.assertEqual(json.loads(results[0][0])["status"], "error")
        lookup.assert_not_called()
        upsert.assert_not_called()

    async def test_eval_agreement_001_persists_exact_agreement_then_notifies(self):
        callback, results = await _capture()
        context = SimpleNamespace(
            load_uuid="load-uuid-1", call_id="call-123", caller_phone="+14155550100",
            caller_mc="123456", load_context={"load_id": "REF-100"},
        )
        save = MagicMock(return_value="negotiation-123")
        notify = MagicMock()
        with (
            patch.object(call_helpers, "save_agreement", save),
            patch.object(call_helpers.NegotiationDBService, "notify_carrier_quote", notify),
        ):
            await call_helpers.record_agreement(
                "record_agreement", "agreement-1",
                {"agreed_price": "1875", "carrier_contact_name": "Pat", "carrier_contact_phone": "+15555550123"},
                None, context, callback,
            )
        self.assertEqual(json.loads(results[0][0])["status"], "success")
        save.assert_called_once_with("load-uuid-1", 1875.0, "call-123", False, "Pat", "+15555550123")
        notify.assert_called_once_with(
            load_name="REF-100", agreed_price=1875.0, mc_number="123456", source_type="call",
            carrier_name="Pat", carrier_phone="+15555550123",
        )

    async def test_eval_bid_001_rejects_above_max_without_contact(self):
        callback, results = await _capture()
        save = MagicMock()
        notify = MagicMock()
        context = SimpleNamespace(load_uuid="load-uuid-1", call_id="call-123", caller_phone=None)
        with (
            patch.object(call_helpers, "save_agreement", save),
            patch.object(call_helpers.NegotiationDBService, "notify_carrier_quote", notify),
        ):
            await call_helpers.record_agreement(
                "record_agreement", "bid-1", {"agreed_price": 2500, "above_max": True},
                None, context, callback,
            )
        result = json.loads(results[0][0])
        self.assertEqual(result["status"], "error")
        self.assertIn("contact", result["message"].lower())
        save.assert_not_called()
        notify.assert_not_called()

    async def test_eval_transfer_001_blocks_transfer_without_confirmed_load(self):
        orchestrator = MagicMock()
        speech_sync = SimpleNamespace(schedule_after_speech=AsyncMock())
        handler = transfer_tool_handler.TransferToolHandler(
            orchestrator, MagicMock(), MagicMock(), MagicMock(), MagicMock(), MagicMock(),
            MagicMock(), speech_sync, MagicMock(), MagicMock(),
        )
        callback, results = await _capture()
        await handler.handle_transfer_to_human(
            "transfer_to_human", "transfer-1", {"reason": "asked", "load_number": "REF-100"},
            None, SimpleNamespace(), callback,
        )
        self.assertEqual(json.loads(results[0][0])["status"], "error")
        orchestrator.set_transfer_metadata.assert_not_called()
        speech_sync.schedule_after_speech.assert_not_awaited()

    async def test_eval_transfer_002_uses_normalized_routing_after_load_confirmation(self):
        orchestrator = MagicMock()
        speech_sync = SimpleNamespace(schedule_after_speech=AsyncMock())
        handler = transfer_tool_handler.TransferToolHandler(
            orchestrator, MagicMock(), MagicMock(), MagicMock(), MagicMock(), MagicMock(),
            MagicMock(), speech_sync, MagicMock(), MagicMock(),
        )
        callback, results = await _capture()
        with patch.object(
            transfer_tool_handler.NegotiationDBService, "get_load",
            return_value={"id": "load-uuid-1", "transfer_call_to": "(555) 123-4567", "transfer_country_code": "+1"},
        ):
            await handler.handle_transfer_to_human(
                "transfer_to_human", "transfer-2",
                {"reason": "asked", "load_number": "REF-100", "price_asked_by_carrier": 2000, "best_price_offered_by_bot": 1800},
                None, SimpleNamespace(load_uuid="load-uuid-1"), callback,
            )
        self.assertEqual(json.loads(results[0][0])["status"], "transferring")
        orchestrator.set_transfer_metadata.assert_called_once_with(
            reason="asked", load_number="REF-100", price_asked_by_carrier=2000,
            best_price_offered_by_bot=1800, human_phone_number="+15551234567",
        )
        speech_sync.schedule_after_speech.assert_awaited_once()


if __name__ == "__main__":
    unittest.main(verbosity=2)
