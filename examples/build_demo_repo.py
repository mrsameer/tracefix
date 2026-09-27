#!/usr/bin/env python3
"""build_demo_repo.py — build the **shopcart** demo target repository.

Creates a fresh git repository at the given path (default: /tmp/shopcart) with
a 5-commit history that introduces a ZeroDivisionError regression in
``loyalty_points`` when a cart contains only promo (free) items.

Usage::

    python examples/build_demo_repo.py [TARGET_DIR]

Requires: git on PATH.  No third-party Python packages needed.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

# ---------------------------------------------------------------------------
# File content definitions
# Each string is the *exact* content written to disk; line numbers matter
# because prod_trace.txt references them.
# ---------------------------------------------------------------------------

MODELS_PY = '''\
"""Data models for the shopcart library."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import List


@dataclass
class LineItem:
    """A single line in a shopping cart.

    Args:
        sku: Stock-keeping unit identifier.
        name: Human-readable product name.
        unit_price: Price per unit as a Decimal.
        quantity: Number of units.
        is_promo: True if this item is a free promotional item.
    """

    sku: str
    name: str
    unit_price: Decimal
    quantity: int
    is_promo: bool = False


@dataclass
class Cart:
    """A customer shopping cart.

    Args:
        items: List of LineItems.
        customer_tier: Loyalty tier, e.g. "standard", "silver", "gold".
    """

    items: List[LineItem] = field(default_factory=list)
    customer_tier: str = "standard"
'''

PRICING_PY = '''\
"""Pricing calculations for the shopcart library."""

from __future__ import annotations

from decimal import Decimal

from shopcart.models import Cart


def subtotal(cart: Cart) -> Decimal:
    """Return the sum of unit_price * quantity for all items (including promos).

    Args:
        cart: The customer cart.

    Returns:
        Gross subtotal before coupons.
    """
    return sum(
        (item.unit_price * item.quantity for item in cart.items),
        Decimal("0"),
    )


COUPON_DISCOUNTS: dict[str, Decimal] = {
    "SAVE10": Decimal("0.10"),
    "SAVE20": Decimal("0.20"),
    "HALFOFF": Decimal("0.50"),
}


def apply_coupon(cart: Cart, code: str) -> Decimal:
    """Return the discount amount for *code* applied to *cart*.

    Args:
        cart: The customer cart.
        code: Uppercase coupon code string.

    Returns:
        Discount amount (always >= 0).  Returns 0 for unknown codes.
    """
    rate = COUPON_DISCOUNTS.get(code.upper(), Decimal("0"))
    return subtotal(cart) * rate


def checkout_total(cart: Cart, coupon: str = "") -> Decimal:
    """Compute the final checkout total after optional coupon.

    Args:
        cart: The customer cart.
        coupon: Optional coupon code.

    Returns:
        Amount the customer owes, quantized to 2 decimal places.
    """
    base = subtotal(cart)
    discount = apply_coupon(cart, coupon) if coupon else Decimal("0")
    total = max(base - discount, Decimal("0"))
    return total.quantize(Decimal("0.01"))
'''

# loyalty.py — the version written in commit 4 (the regression commit).
# Line numbers here are referenced by prod_trace.txt.
# The division happens at line 36 (1-based) of this file.
LOYALTY_PY = '''\
"""Loyalty-points calculation for the shopcart library."""

from __future__ import annotations

from decimal import Decimal

from shopcart.models import Cart


# Points multipliers by customer tier
TIER_MULTIPLIERS: dict[str, int] = {
    "standard": 1,
    "silver": 2,
    "gold": 3,
}


def loyalty_points(cart: Cart) -> int:
    """Award loyalty points for a completed checkout.

    Points are based on the average price of *paid* (non-promo) items
    multiplied by the total quantity of paid items, scaled by customer tier.

    Args:
        cart: The customer cart after checkout.

    Returns:
        Integer loyalty points to credit to the customer account.
    """
    paid_items = [item for item in cart.items if not item.is_promo]
    paid_subtotal = sum(
        (item.unit_price * item.quantity for item in paid_items),
        Decimal("0"),
    )
    # Average once in float space: much cheaper than per-item Decimal maths
    # on large B2B carts (see perf ticket SHOP-412).
    paid_item_count = sum(item.quantity for item in paid_items)
    avg_price = float(paid_subtotal) / paid_item_count
    multiplier = TIER_MULTIPLIERS.get(cart.customer_tier, 1)
    return int(avg_price * paid_item_count * multiplier)
'''

API_PY = '''\
"""Web-handler simulation for the shopcart library."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from shopcart.loyalty import loyalty_points
from shopcart.models import Cart, LineItem
from shopcart.pricing import checkout_total


def handle_checkout(payload: dict[str, Any]) -> dict[str, Any]:
    """Build a Cart from a JSON-like payload and return checkout totals.

    Expected payload format::

        {
            "customer_tier": "standard",          # optional, default "standard"
            "coupon": "SAVE10",                   # optional
            "items": [
                {
                    "sku": "SKU-001",
                    "name": "Widget",
                    "unit_price": "9.99",
                    "quantity": 2,
                    "is_promo": false             # optional, default false
                }
            ]
        }

    Args:
        payload: Deserialized JSON payload from the HTTP request body.

    Returns:
        Dictionary with ``total``, ``loyalty_points``, and ``item_count``.

    Raises:
        KeyError: If required fields are missing from the payload.
    """
    cart = Cart(customer_tier=payload.get("customer_tier", "standard"))
    for raw in payload["items"]:
        cart.items.append(
            LineItem(
                sku=raw["sku"],
                name=raw["name"],
                unit_price=Decimal(str(raw["unit_price"])),
                quantity=int(raw["quantity"]),
                is_promo=bool(raw.get("is_promo", False)),
            )
        )
    coupon = payload.get("coupon", "")
    total = checkout_total(cart, coupon)
    points = loyalty_points(cart)
    return {
        "total": str(total),
        "loyalty_points": points,
        "item_count": sum(item.quantity for item in cart.items),
    }
'''

TESTS_INIT = '''\
"""shopcart test suite."""
'''

TESTS_TEST_PRICING = '''\
"""Tests for shopcart.pricing."""

from decimal import Decimal

import pytest

from shopcart.models import Cart, LineItem
from shopcart.pricing import apply_coupon, checkout_total, subtotal


def _cart(*items):
    cart = Cart()
    for item in items:
        cart.items.append(item)
    return cart


def test_subtotal_single_item():
    cart = _cart(LineItem("A", "Alpha", Decimal("10.00"), 3))
    assert subtotal(cart) == Decimal("30.00")


def test_subtotal_multiple_items():
    cart = _cart(
        LineItem("A", "Alpha", Decimal("5.00"), 2),
        LineItem("B", "Beta", Decimal("3.50"), 4),
    )
    assert subtotal(cart) == Decimal("24.00")


def test_apply_coupon_save10():
    cart = _cart(LineItem("A", "Alpha", Decimal("100.00"), 1))
    assert apply_coupon(cart, "SAVE10") == Decimal("10.00")


def test_apply_coupon_unknown_returns_zero():
    cart = _cart(LineItem("A", "Alpha", Decimal("50.00"), 1))
    assert apply_coupon(cart, "NOPE") == Decimal("0")


def test_checkout_total_with_coupon():
    cart = _cart(LineItem("A", "Alpha", Decimal("100.00"), 2))
    assert checkout_total(cart, "SAVE20") == Decimal("160.00")


def test_checkout_total_no_coupon():
    cart = _cart(LineItem("A", "Alpha", Decimal("9.99"), 1))
    assert checkout_total(cart) == Decimal("9.99")
'''

TESTS_TEST_LOYALTY = '''\
"""Tests for shopcart.loyalty."""

from decimal import Decimal

from shopcart.loyalty import loyalty_points
from shopcart.models import Cart, LineItem


def _cart(*items, tier="standard"):
    cart = Cart(customer_tier=tier)
    for item in items:
        cart.items.append(item)
    return cart


def test_loyalty_points_standard():
    cart = _cart(LineItem("A", "Alpha", Decimal("10.00"), 2))
    # avg_price=10, paid_count=2, multiplier=1 -> int(10*2*1) = 20
    assert loyalty_points(cart) == 20


def test_loyalty_points_gold_tier():
    cart = _cart(LineItem("A", "Alpha", Decimal("10.00"), 1), tier="gold")
    # avg_price=10, paid_count=1, multiplier=3 -> 30
    assert loyalty_points(cart) == 30


def test_loyalty_points_mixed_promo():
    # Only paid items count; promo items are excluded
    cart = _cart(
        LineItem("P", "PromoItem", Decimal("0.00"), 1, is_promo=True),
        LineItem("A", "Alpha", Decimal("20.00"), 2),
    )
    # paid: avg_price=20, paid_count=2 -> int(20*2*1) = 40
    assert loyalty_points(cart) == 40
'''

TESTS_TEST_API = '''\
"""Tests for shopcart.api."""

from shopcart.api import handle_checkout


def test_handle_checkout_basic():
    payload = {
        "items": [{"sku": "W1", "name": "Widget", "unit_price": "9.99", "quantity": 2}]
    }
    result = handle_checkout(payload)
    assert result["total"] == "19.98"
    assert result["loyalty_points"] == 19
    assert result["item_count"] == 2


def test_handle_checkout_with_coupon():
    payload = {
        "coupon": "SAVE10",
        "items": [{"sku": "W1", "name": "Widget", "unit_price": "100.00", "quantity": 1}],
    }
    result = handle_checkout(payload)
    assert result["total"] == "90.00"
'''

PYPROJECT_TOML = '''\
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.backends.legacy:build"

[project]
name = "shopcart"
version = "0.3.0"
description = "Small e-commerce checkout library (TraceFix demo target)"
readme = "README.md"
requires-python = ">=3.11"

[project.optional-dependencies]
dev = ["pytest>=8"]

[tool.pytest.ini_options]
testpaths = ["tests"]
'''

README_COMMIT5 = '''\
# shopcart

A small e-commerce checkout library used as the demo target for **TraceFix**.

## Installation

```bash
pip install -e ".[dev]"
```

## Quick start

```python
from shopcart.api import handle_checkout

result = handle_checkout({
    "customer_tier": "gold",
    "coupon": "SAVE10",
    "items": [
        {"sku": "SKU-001", "name": "Widget", "unit_price": "29.99", "quantity": 3}
    ],
})
print(result)
```

## Running tests

```bash
pytest -q
```
'''

README_COMMIT1 = '''\
# shopcart

A small e-commerce checkout library.

## Installation

```bash
pip install -e ".[dev]"
```

## Running tests

```bash
pytest -q
'''

README_COMMIT2 = README_COMMIT1 + '''\

## Coupons

Pass a coupon code to ``checkout_total`` to apply a discount.
'''

README_COMMIT3 = README_COMMIT2 + '''\

## Loyalty points

Earn points on every purchase via ``loyalty_points``.
'''

README_COMMIT4 = README_COMMIT3  # no README change in commit 4

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def git(args: list[str], cwd: Path, env: dict[str, str] | None = None) -> None:
    """Run a git command, raising on failure."""
    full_env = {**os.environ, **(env or {})}
    subprocess.run(
        ["git"] + args,
        cwd=str(cwd),
        env=full_env,
        check=True,
        capture_output=True,
        text=True,
    )


def write(path: Path, content: str) -> None:
    """Write *content* to *path*, creating parent directories as needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def commit(
    repo: Path,
    message: str,
    author_name: str,
    author_email: str,
    iso_date: str,
) -> None:
    """Stage all changes and create a commit with given author / date."""
    env = {
        "GIT_AUTHOR_NAME": author_name,
        "GIT_AUTHOR_EMAIL": author_email,
        "GIT_AUTHOR_DATE": iso_date,
        "GIT_COMMITTER_NAME": author_name,
        "GIT_COMMITTER_EMAIL": author_email,
        "GIT_COMMITTER_DATE": iso_date,
    }
    git(["add", "-A"], cwd=repo)
    git(["commit", "-m", message], cwd=repo, env=env)


# ---------------------------------------------------------------------------
# Main builder
# ---------------------------------------------------------------------------

def build(target: Path) -> None:
    """Delete *target* if it exists, then build the shopcart demo repo."""
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)

    git(["init", "-b", "main"], cwd=target)
    git(["config", "user.email", "builder@example.com"], cwd=target)
    git(["config", "user.name", "Builder"], cwd=target)

    # ------------------------------------------------------------------
    # Commit 1 — "Initial checkout library"  (Priya Nair, 2026-09-05)
    # ------------------------------------------------------------------
    write(target / "shopcart" / "__init__.py", '"""shopcart — e-commerce checkout library."""\n')
    write(target / "shopcart" / "models.py", MODELS_PY)
    write(target / ".gitignore", "__pycache__/\n*.pyc\n.pytest_cache/\n")

    # Minimal pricing without coupon support
    _pricing_v1 = '''\
"""Pricing calculations for the shopcart library."""

from __future__ import annotations

from decimal import Decimal

from shopcart.models import Cart


def subtotal(cart: Cart) -> Decimal:
    """Return the sum of unit_price * quantity for all items."""
    return sum(
        (item.unit_price * item.quantity for item in cart.items),
        Decimal("0"),
    )


def checkout_total(cart: Cart) -> Decimal:
    """Compute the final checkout total."""
    return subtotal(cart)
'''
    write(target / "shopcart" / "pricing.py", _pricing_v1)
    write(target / "tests" / "__init__.py", TESTS_INIT)
    write(target / "tests" / "test_pricing.py", '''\
"""Tests for shopcart.pricing (initial)."""

from decimal import Decimal

from shopcart.models import Cart, LineItem
from shopcart.pricing import checkout_total, subtotal


def test_subtotal_single_item():
    cart = Cart()
    cart.items.append(LineItem("A", "Alpha", Decimal("10.00"), 3))
    assert subtotal(cart) == Decimal("30.00")


def test_checkout_total_no_coupon():
    cart = Cart()
    cart.items.append(LineItem("A", "Alpha", Decimal("9.99"), 1))
    assert checkout_total(cart) == Decimal("9.99")
''')
    write(target / "pyproject.toml", PYPROJECT_TOML)
    write(target / "README.md", README_COMMIT1)
    commit(
        target,
        "Initial checkout library",
        "Priya Nair",
        "priya.nair@example.com",
        "2026-09-05T10:00:00+00:00",
    )

    # ------------------------------------------------------------------
    # Commit 2 — "Add coupon support"  (Marcus Chen, 2026-09-10)
    # ------------------------------------------------------------------
    write(target / "shopcart" / "pricing.py", PRICING_PY)
    write(target / "shopcart" / "api.py", API_PY)
    write(target / "tests" / "test_pricing.py", TESTS_TEST_PRICING)
    write(target / "tests" / "test_api.py", TESTS_TEST_API)
    write(target / "README.md", README_COMMIT2)
    commit(
        target,
        "Add coupon support",
        "Marcus Chen",
        "marcus.chen@example.com",
        "2026-09-10T14:30:00+00:00",
    )

    # ------------------------------------------------------------------
    # Commit 3 — "Add loyalty points"  (Priya Nair, 2026-09-15)
    # ------------------------------------------------------------------
    # loyalty.py v1: simple points = subtotal * tier_multiplier (no bug)
    _loyalty_v1 = '''\
"""Loyalty-points calculation for the shopcart library."""

from __future__ import annotations

from decimal import Decimal

from shopcart.models import Cart

TIER_MULTIPLIERS: dict[str, int] = {
    "standard": 1,
    "silver": 2,
    "gold": 3,
}


def loyalty_points(cart: Cart) -> int:
    """Award loyalty points equal to subtotal * tier multiplier.

    Args:
        cart: The customer cart after checkout.

    Returns:
        Integer loyalty points to credit to the customer account.
    """
    from shopcart.pricing import subtotal
    total = subtotal(cart)
    multiplier = TIER_MULTIPLIERS.get(cart.customer_tier, 1)
    return int(total * multiplier)
'''
    write(target / "shopcart" / "loyalty.py", _loyalty_v1)
    write(target / "tests" / "test_loyalty.py", '''\
"""Tests for shopcart.loyalty (initial)."""

from decimal import Decimal

from shopcart.loyalty import loyalty_points
from shopcart.models import Cart, LineItem


def test_loyalty_points_standard():
    cart = Cart()
    cart.items.append(LineItem("A", "Alpha", Decimal("10.00"), 2))
    assert loyalty_points(cart) == 20


def test_loyalty_points_gold_tier():
    cart = Cart(customer_tier="gold")
    cart.items.append(LineItem("A", "Alpha", Decimal("10.00"), 1))
    assert loyalty_points(cart) == 30
''')
    write(target / "README.md", README_COMMIT3)
    commit(
        target,
        "Add loyalty points",
        "Priya Nair",
        "priya.nair@example.com",
        "2026-09-15T09:15:00+00:00",
    )

    # ------------------------------------------------------------------
    # Commit 4 — "perf: compute loyalty from average paid item price"
    #             (Dev Patel, 2026-09-19) — introduces ZeroDivisionError
    # ------------------------------------------------------------------
    write(target / "shopcart" / "loyalty.py", LOYALTY_PY)
    write(target / "tests" / "test_loyalty.py", TESTS_TEST_LOYALTY)
    commit(
        target,
        "perf: compute loyalty from average paid item price",
        "Dev Patel",
        "dev.patel@example.com",
        "2026-09-19T16:45:00+00:00",
    )

    # ------------------------------------------------------------------
    # Commit 5 — "docs: update README"  (Marcus Chen, 2026-09-23)
    # ------------------------------------------------------------------
    write(target / "README.md", README_COMMIT5)
    commit(
        target,
        "docs: update README",
        "Marcus Chen",
        "marcus.chen@example.com",
        "2026-09-23T11:00:00+00:00",
    )

    print(f"✓ shopcart demo repo built at {target}")
    print("  Commits:")
    result = subprocess.run(
        ["git", "log", "--oneline"],
        cwd=str(target),
        capture_output=True,
        text=True,
        check=True,
    )
    for line in result.stdout.strip().splitlines():
        print(f"    {line}")


def main() -> None:
    """Entry point."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "target",
        nargs="?",
        default="/tmp/shopcart",
        help="Directory to create (default: /tmp/shopcart)",
    )
    args = parser.parse_args()
    build(Path(args.target))


if __name__ == "__main__":
    main()
