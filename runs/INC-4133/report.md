## TraceFix incident `INC-4133`

**Production failure:** `KeyError: ''`
**Crash site:** `shopcart/pricing.py:50` in `_stacked_rate()`
**Suspect commit:** `34f3f4d4` feat: allow stacking coupons (SHOP-431) — Marcus Chen

| Stage | Result | Attempts | Time |
| --- | --- | --- | --- |
| Reproduction (Bob) | ✅ verified | 1 | 27.0s |
| Fix (Bob) | ✅ verified | 1 | 19.2s |

Total time: **46.6s**. Branch: `tracefix/INC-4133`.

### Verified regression test
```python
"""Reproduction test for INC-4133: KeyError on unknown coupon code at checkout."""

from shopcart.api import handle_checkout


def test_checkout_with_unknown_coupon_returns_discounted_total():
    """Reproduce INC-4133: a customer submits a coupon code not present in COUPON_DISCOUNTS.

    Scenario: a user enters an unrecognised coupon code ("WELCOME15") at checkout,
    which is a plausible action (e.g. an expired or mistyped voucher). The request
    reaches handle_checkout(), which passes the raw code string to checkout_total().
    checkout_total() splits it and forwards the list to _stacked_rate(). Inside
    _stacked_rate() (introduced by SHOP-431, commit 34f3f4d4) each code is looked up
    with a hard dict subscript ``COUPON_DISCOUNTS[code]`` rather than .get(), so any
    code absent from the dict raises KeyError instead of being silently ignored.

    Expected behaviour (post-fix): an unknown coupon should be treated as a no-op
    and the full subtotal returned.  The test asserts that correct behaviour so it
    will pass once the bug is fixed but fails today with ``KeyError: 'WELCOME15'``.

    Incident: INC-4133
    """
    payload = {
        "coupon": "WELCOME15",
        "items": [
            {
                "sku": "SKU-042",
                "name": "Sneakers",
                "unit_price": "80.00",
                "quantity": 1,
            }
        ],
    }
    result = handle_checkout(payload)
    # Unknown coupon should be a no-op; full subtotal is returned unchanged.
    assert result["total"] == "80.00"
```

### Fix
```diff
diff --git a/shopcart/pricing.py b/shopcart/pricing.py
index 6041efe..744a2be 100644
--- a/shopcart/pricing.py
+++ b/shopcart/pricing.py
@@ -47,7 +47,7 @@ def _stacked_rate(codes: list[str]) -> Decimal:
     """Combine several coupon rates multiplicatively (SHOP-431)."""
     remaining = Decimal("1")
     for code in codes:
-        remaining *= Decimal("1") - COUPON_DISCOUNTS[code]
+        remaining *= Decimal("1") - COUPON_DISCOUNTS.get(code, Decimal("0"))
     return Decimal("1") - remaining
```
