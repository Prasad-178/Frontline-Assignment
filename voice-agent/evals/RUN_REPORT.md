# Offline evaluation run report

Date: 2026-10-20

Command run from `voice-agent/`:

```bash
python3 evals/offline_unittest.py
```

Final result:

```text
Ran 5 tests in 0.008s
OK
```

Passing cases:

- `EVAL-REF-001`: invalid transcript prose returned an error before load lookup or identity persistence.
- `EVAL-AGREEMENT-001`: agreement persistence and carrier-quote notification received the expected arguments.
- `EVAL-BID-001`: an above-max bid without contact details returned an error and did not persist or notify.
- `EVAL-TRANSFER-001`: missing confirmed load blocked transfer before metadata/dial-out scheduling.
- `EVAL-TRANSFER-002`: a confirmed load used normalized broker routing and scheduled transfer.

The first run failed before executing `EVAL-TRANSFER-001` because the evaluation harness passed one fewer constructor dependency to `TransferToolHandler`. This was corrected in `offline_unittest.py`; the final run above passed all five cases. This was a test-harness wiring defect, not a production behavior finding.

Additional checks completed:

```bash
git diff --check
python3 -m compileall -q evals/offline_unittest.py tests/test_frontline_evaluation.py
```

Both completed without output/errors. The fuller pytest suite was not run in this image because `pytest`, `pip`, and `ensurepip` are unavailable; setup and command are documented in `docs/EVALUATION.md`.

The runner ends with `unittest.main()`, whose standard failure behavior is a
nonzero process exit; the final passing run exited `0`. The rejected-transfer
case explicitly asserts that `schedule_after_speech` was not awaited, in
addition to asserting that transfer metadata was not set.
