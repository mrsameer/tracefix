You are helping build TraceFix (read docs/DESIGN.md first for context).

Task: create `examples/build_demo_repo.py`, a standalone Python 3.11+ script (stdlib only,
type hints, docstrings) that builds a realistic demo target service called **shopcart** as a
fresh git repository at a path given on the command line (default: /tmp/shopcart). It must
delete and recreate the target directory each run.

The shopcart package must be a small but realistic e-commerce checkout library:
- `shopcart/models.py`: `LineItem(sku, name, unit_price: Decimal, quantity, is_promo=False)`, `Cart` (list of items, customer tier).
- `shopcart/pricing.py`: `subtotal(cart)`, `apply_coupon(cart, code)`, `checkout_total(cart)`.
- `shopcart/loyalty.py`: `loyalty_points(cart)` awarding points.
- `shopcart/api.py`: `handle_checkout(payload: dict) -> dict` that builds a Cart from a JSON-like payload and returns totals + loyalty points (simulates the web handler).
- `tests/` with ~8 passing pytest tests covering normal behaviour.
- `pyproject.toml`, `README.md`.

Build the git history as 5 commits with distinct fake authors and dates (set GIT_AUTHOR_NAME/EMAIL/DATE and committer equivalents via env; dates spread over the previous 3 weeks relative to a fixed date 2026-09-26):
1. "Initial checkout library" (Priya Nair)
2. "Add coupon support" (Marcus Chen)
3. "Add loyalty points" (Priya Nair)
4. "perf: compute loyalty from average paid item price" (Dev Patel) — THIS commit introduces the regression:
   loyalty_points now computes `avg_price = paid_subtotal / paid_item_count` where paid items exclude promo (free) items. A cart containing only promo items therefore raises ZeroDivisionError (Decimal division -> decimal.DivisionByZero / ZeroDivisionError; make sure it is a plain `ZeroDivisionError` by using int count and Decimal sum -> use `float` or ensure the raised type is ZeroDivisionError or decimal.DivisionByZero consistently, and record which in a comment). Existing tests must still pass after this commit.
5. "docs: update README" (Marcus Chen) — unrelated change.

Also write `examples/prod_trace.txt`: a realistic production traceback as it would appear in a gunicorn log when `handle_checkout` receives a cart with only a free promo item. The frames must reference paths like `/srv/app/.venv/lib/python3.11/site-packages/...` for a web-framework frame (made-up but plausible) and `/srv/app/shopcart/api.py`, `/srv/app/shopcart/loyalty.py` for our code, with line numbers and source lines that EXACTLY match the files your script writes. Include a preceding log line with timestamp and request id.

After writing, run the script to /tmp/shopcart, run `python -m pytest -q` inside it to confirm tests pass, and actually reproduce the crash with a python one-liner to confirm the traceback line numbers in prod_trace.txt match. Fix anything that doesn't match. Keep the final answer short: list files created and verification results.
