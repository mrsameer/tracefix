"""Add a second regression to the shopcart demo repo and capture its production trace.

Commit 6 ("feat: allow stacking coupons") indexes the coupon table directly, so a
trailing comma sent by the mobile app ("SAVE10,") crashes checkout with KeyError.

Usage: python examples/add_scenario_coupons.py [/tmp/shopcart]
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
TRACE_OUT = HERE / "prod_trace_coupons.txt"

STACKED = '''def _stacked_rate(codes: list[str]) -> Decimal:
    """Combine several coupon rates multiplicatively (SHOP-431)."""
    remaining = Decimal("1")
    for code in codes:
        remaining *= Decimal("1") - COUPON_DISCOUNTS[code]
    return Decimal("1") - remaining


def checkout_total(cart: Cart, coupon: str = "") -> Decimal:
    """Compute the final checkout total after optional, stackable coupons.

    Args:
        cart: The customer cart.
        coupon: Optional comma-separated coupon codes, e.g. "SAVE10,SAVE20".

    Returns:
        Amount the customer owes, quantized to 2 decimal places.
    """
    base = subtotal(cart)
    codes = [part.strip().upper() for part in coupon.split(",")] if coupon else []
    discount = base * _stacked_rate(codes)
    total = max(base - discount, Decimal("0"))
    return total.quantize(Decimal("0.01"))
'''

STACK_TEST = '''

def test_checkout_total_with_stacked_coupons():
    cart = Cart()
    cart.items.append(LineItem("A", "Thing", Decimal("100.00"), 1))
    assert checkout_total(cart, "SAVE10,SAVE20") == Decimal("72.00")
'''

FRAMEWORK_FRAMES = """\
  File "/srv/app/.venv/lib/python3.11/site-packages/flaskette/serving.py", line 312, in _dispatch_request
    response = view_func(**kwargs)
               ^^^^^^^^^^^^^^^^^^^
  File "/srv/app/.venv/lib/python3.11/site-packages/flaskette/routing.py", line 87, in call_endpoint
    return endpoint.handler(request)
           ^^^^^^^^^^^^^^^^^^^^^^^^^
"""

CRASH = """\
from shopcart.api import handle_checkout
handle_checkout({"customer_tier": "silver", "coupon": "SAVE10,", "items": [
    {"sku": "MUG-01", "name": "Mug", "unit_price": "12.50", "quantity": 2}]})
"""


def main() -> None:
    """Commit the regression and write the production trace next to this script."""
    repo = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/shopcart")
    pricing = repo / "shopcart" / "pricing.py"
    source = pricing.read_text()
    source = re.sub(r"def checkout_total\(.*", STACKED, source, flags=re.S)
    pricing.write_text(source)
    with (repo / "tests" / "test_pricing.py").open("a") as fh:
        fh.write(STACK_TEST)
    _commit(repo)
    TRACE_OUT.write_text(_production_trace(repo))
    print(f"scenario added; trace at {TRACE_OUT}")


def _commit(repo: Path) -> None:
    when = "2026-09-25T14:05:00+00:00"
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "Marcus Chen",
        "GIT_AUTHOR_EMAIL": "marcus.chen@example.com",
        "GIT_AUTHOR_DATE": when,
        "GIT_COMMITTER_NAME": "Marcus Chen",
        "GIT_COMMITTER_EMAIL": "marcus.chen@example.com",
        "GIT_COMMITTER_DATE": when,
    }
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    message = "feat: allow stacking coupons (SHOP-431)"
    subprocess.run(["git", "commit", "-q", "-m", message], cwd=repo, env=env, check=True)


def _production_trace(repo: Path) -> str:
    """Run the crash for real and dress it up as a gunicorn log entry."""
    proc = subprocess.run(
        [sys.executable, "-c", CRASH], cwd=repo, capture_output=True, text=True
    )
    lines = proc.stderr.splitlines()
    start = next(i for i, line in enumerate(lines) if 'File "' in line and "api.py" in line)
    body = "\n".join(lines[start:]).replace(str(repo.resolve()), "/srv/app")
    body = body.replace("/private/srv/app", "/srv/app")
    header = (
        "[2026-09-26 18:42:09 +0000] [1141] [ERROR] "
        "request_id=7c19e0d4-51aa-4c6b-9f3e-0b8d2a7e6f11 "
        "Exception on POST /api/v1/checkout [HTTP/1.1]\n"
        "Traceback (most recent call last):\n"
    )
    return header + FRAMEWORK_FRAMES + body + "\n"


if __name__ == "__main__":
    main()
