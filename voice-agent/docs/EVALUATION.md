# Frontline offline evaluation

Run from `voice-agent/` in a minimal environment (Python 3.11 standard library only):

```bash
python3 evals/offline_unittest.py
```

This is credential-free and has no live side effects. It imports the real production handlers while supplying import-time SDK contracts and replacing every database, carrier lookup, quote notification, and transfer/dial-out boundary with a mock. Failures identify a scenario ID and use mock assertions to show the unexpected call or arguments.

For the broader existing pytest suite, follow the repository setup in `docs/LOCAL_SETUP.md` (Python 3.11, then `python -m pip install -r requirements.txt -r tests/requirements-test.txt`) and run:

```bash
python -m pytest -q tests/test_frontline_evaluation.py tests/test_phone_carrier_lookup.py tests/test_transfer_tool_handler.py tests/test_voice_prompt_guardrails.py
```

## Scope and success criteria

| Risk | Evaluation | Success criterion | Mocked boundary |
| --- | --- | --- | --- |
| Hallucinated/stale reference | `EVAL-REF-001` plus retained reference tests | rejected result; no load query or identity write | database/Salesforce/Supabase |
| Agreement persistence | `EVAL-AGREEMENT-001` | successful result; exact persisted and quote-notification arguments | negotiation DB and quote service |
| Above-max bid missing contact | `EVAL-BID-001` | error result; neither persistence nor notification | negotiation DB and quote service |
| Premature/invalid broker transfer and valid routing | retained transfer-handler tests | blocked paths do not configure or schedule a transfer; valid path uses normalized routing | load DB, orchestrator, speech-synchronised dial-out |
| Prompt context/configuration | `EVAL-PROMPT-001` and retained prompt tests | supplied load/org configuration is rendered | none |

The tests execute production `call_helpers` and `TransferToolHandler` code, not reimplementations. Prompt tests only verify rendering/configuration. They are **not** evidence that an LLM follows prompt instructions.

## Model-dependent scenario corpus

`evals/model_risk_scenarios.json` specifies three high-risk conversations: rate disclosure, corrected carrier identity, and premature agreement. It is deliberately unexecuted in this offline suite: no production credentials, model API, audio, or telephony are used. Its expected observables are agent text and tool-call traces, not a required substring in a prompt.

For later nondeterministic model evaluation, run each scenario against a sandboxed LLM/tool harness with fixed load fixtures and recording-only fake tools. Use at least 20 independent trials per scenario/version; report pass rate and a binomial confidence interval, preserve failing transcripts/tool traces, and gate changes on zero confidential-value leaks and an agreed minimum pass rate for tool sequencing. Those trials have not been run here.

## Assumptions, omissions, and limits

Assumptions: real load references contain a digit; production effects are reached only through the mocked boundaries; normal (not above-max) agreements may use caller ID when no contact phone is supplied, matching current behavior.

Not verified: actual model choice/tool compliance, STT transcription, TTS/audio quality, Daily/SIP timing, vendor authentication, real database schema/RLS, external API semantics, and concurrent production calls. The suite intentionally does not add backend enforcement or alter the single-prompt architecture.

## Run evidence (assessment workspace)

The original pytest command was attempted on 2026-10-20:

```text
pytest -q tests/test_frontline_evaluation.py tests/test_phone_carrier_lookup.py tests/test_transfer_tool_handler.py tests/test_voice_prompt_guardrails.py
```

Result: the supplied runtime has no `pytest` executable; `python3 -m pytest`
also reports `No module named pytest`, and this image has no `pip` or
`ensurepip`. The standard-library command above is the runnable assessment
fallback; its actual output is recorded below after execution. The broader
pytest command remains the repeatable path in a normal repository setup.

See `evals/RUN_REPORT.md` for the exact final command, output, and the
corrected first-run harness error.
