You are helping build TraceFix (read docs/DESIGN.md and README if present).

Write pytest unit tests for the modules that are not yet covered:

1. `tests/test_verify.py` for `tracefix/verify.py`:
   - `check_signature` accepts a failing pytest output (use realistic `--tb=native` pytest output text as fixture strings) whose final exception type AND crashing function match the production ParsedTrace.
   - rejects: passing run; failure without a traceback (e.g. collection/syntax error text); wrong exception type; right type but raised from a different function; dotted exception names (`decimal.DivisionByZero` vs `DivisionByZero`) must be treated as equal.
   - `changed_files` in a temp git repo: reports modified + untracked files, ignores `.pyc` files and bare directories.
   - `run_pytest` on a tiny temp project with one passing and one failing test file (use `tmp_path`), checking `.passed` for each target.
2. `tests/test_report.py` for `tracefix/report.py`: build an `Incident` (from `tracefix.pipeline`) by hand with 2 frames (one outside repo), one suspect, successful repro/fix StageResults, and assert that `markdown()` contains the crash site, suspect sha prefix, the stage table rows and the fenced test/diff blocks; `html_report()` embeds the JSON payload, escapes `</script>` sequences inside the data, and sets the title; `write_reports()` writes all three files from an events.jsonl file.
3. `tests/test_prompts.py` for `tracefix/prompts.py`: the repro prompt names the exact test path, the exception type and the crash function and forbids editing other files; the fix prompt forbids editing the test; `retry_prompt` truncates very long details to at most ~4000 chars of detail.

Rules: do not change production code unless a test reveals a real bug (if so, fix it minimally and mention it). Use only pytest + stdlib. Type hints, docstrings on test modules, max line length 88. The project uses uv — run `uv run pytest -q` (never pip) and make the whole suite pass. Keep the final answer short: files created, bugs found, test count.
