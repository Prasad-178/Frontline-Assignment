"""Offline, side-effect-free evaluation of Frontline's production boundaries.

These cases call the production tool handlers directly.  Network/database/
dial-out boundaries are mocked; assertions therefore describe deterministic
backend behavior, not whether an LLM will choose the right tool.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import call_helpers
from call_helpers import get_load_context, record_agreement
from load_context_utils import build_negotiation_prompt, get_initial_system_prompt


def _context(**values):
    defaults = {
        "call_id": "call-123",
        "caller_phone": "+14155550100",
        "caller_mc": "123456",
        "load_uuid": "load-uuid-1",
        "load_context": {"load_id": "REF-100"},
        "messages": [{"role": "system", "content": "initial"}],
    }
    defaults.update(values)
    return SimpleNamespace(**defaults)


def _callback():
    return AsyncMock()


def _result(callback):
    return json.loads(callback.await_args.args[0])


@pytest.mark.asyncio
async def test_eval_ref_001_rejects_premature_reference_without_side_effects():
    """EVAL-REF-001: transcript prose must not trigger lookup or persistence."""
    callback = _callback()
    context = _context(caller_mc="123456", carrier_name="Acme")
    lookup = MagicMock()
    upsert = MagicMock()
    with (
        patch.object(call_helpers.NegotiationDBService, "get_load_by_reference", lookup),
        patch.object(call_helpers.NegotiationDBService, "upsert_carrier_phone", upsert),
    ):
        await get_load_context(
            "get_load_context", "tool-1", {"load_id": "noted down"}, None, context, callback
        )

    assert _result(callback)["status"] == "error", "EVAL-REF-001 must return an actionable rejection"
    lookup.assert_not_called()
    upsert.assert_not_called()


@pytest.mark.asyncio
async def test_eval_agreement_001_records_agreement_and_notifies_quote_service():
    """EVAL-AGREEMENT-001: valid agreement persists exact data then notifies."""
    callback = _callback()
    context = _context()
    negotiation_id = "aaaaaaaa-1111-2222-3333-444444444444"
    save = MagicMock(return_value=negotiation_id)
    notify = MagicMock()
    with (
        patch.object(call_helpers, "save_agreement", save),
        patch.object(call_helpers.NegotiationDBService, "notify_carrier_quote", notify),
    ):
        await record_agreement(
            "record_agreement", "tool-2",
            {"agreed_price": "1875", "carrier_contact_name": "Pat", "carrier_contact_phone": "+15555550123"},
            None, context, callback,
        )

    assert _result(callback)["status"] == "success", "EVAL-AGREEMENT-001 should report persisted agreement"
    save.assert_called_once_with("load-uuid-1", 1875.0, "call-123", False, "Pat", "+15555550123")
    notify.assert_called_once_with(
        load_name="REF-100", agreed_price=1875.0, mc_number="123456", source_type="call",
        carrier_name="Pat", carrier_phone="+15555550123",
    )


@pytest.mark.asyncio
async def test_eval_bid_001_rejects_above_max_bid_without_contact_or_persistence():
    """EVAL-BID-001: above-max follow-up requires a reachable contact."""
    callback = _callback()
    save = MagicMock()
    notify = MagicMock()
    with (
        patch.object(call_helpers, "save_agreement", save),
        patch.object(call_helpers.NegotiationDBService, "notify_carrier_quote", notify),
    ):
        await record_agreement(
            "record_agreement", "tool-3", {"agreed_price": 2500, "above_max": True},
            None, _context(caller_phone=None), callback,
        )

    assert _result(callback)["status"] == "error", "EVAL-BID-001 must fail closed before persistence"
    assert "contact" in _result(callback)["message"].lower()
    save.assert_not_called()
    notify.assert_not_called()


def test_eval_prompt_001_renders_supplied_context_and_configuration():
    """EVAL-PROMPT-001 checks interpolation only; it does not evaluate model compliance."""
    context = {
        "id": "REF-100", "origin": {"city": "Dallas", "state": "TX"},
        "destination": {"city": "Austin", "state": "TX"}, "pickupTime": "Monday 9 AM",
        "dropoffTime": "Tuesday 4 PM", "specialInstructions": "Tracker required",
        "startRate": 1400, "bookNowRate": 1500, "maxRate": 1700,
    }
    negotiation_prompt = build_negotiation_prompt(context)
    greeting_prompt = get_initial_system_prompt("Northstar Logistics", phone_first_enabled=False)

    assert "REF-100" in negotiation_prompt
    assert "Dallas, TX" in negotiation_prompt and "Austin, TX" in negotiation_prompt
    assert "$1400" in negotiation_prompt
    assert "Northstar Logistics" in greeting_prompt
