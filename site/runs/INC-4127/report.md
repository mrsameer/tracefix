## TraceFix incident `INC-4127`

**Production failure:** `ZeroDivisionError: float division by zero`
**Crash site:** `shopcart/loyalty.py:38` in `loyalty_points()`
**Suspect commit:** `91a7ca50` perf: compute loyalty from average paid item price — Dev Patel

| Stage | Result | Attempts | Time |
| --- | --- | --- | --- |
| Reproduction (Bob) | ✅ verified | 1 | 22.8s |
| Fix (Bob) | ✅ verified | 1 | 12.9s |

Total time: **36.0s**. Branch: `tracefix/INC-4127`.

### Verified regression test
```python
"""Reproduction test for incident INC-4127 — ZeroDivisionError in loyalty_points()."""

from shopcart.api import handle_checkout


def test_checkout_with_only_promo_items_returns_zero_loyalty_points():
    """A cart containing exclusively promotional (free) items crashes at checkout.

    Scenario (INC-4127):
        A customer redeems a campaign where every item in their order is marked
        as a free promotional item (is_promo=True).  When handle_checkout() is
        called, loyalty_points() filters out all promo items, leaving an empty
        paid_items list.  paid_item_count therefore equals 0, and the division
        ``float(paid_subtotal) / paid_item_count`` raises ZeroDivisionError.

        The correct behaviour is that a cart with no paid items earns 0 loyalty
        points rather than crashing.

    References: INC-4127, commit 91a7ca50 "perf: compute loyalty from average
    paid item price".
    """
    payload = {
        "customer_tier": "standard",
        "items": [
            {
                "sku": "PROMO-001",
                "name": "Free Gift",
                "unit_price": "0.00",
                "quantity": 1,
                "is_promo": True,
            }
        ],
    }
    result = handle_checkout(payload)
    assert result["loyalty_points"] == 0
```

### Fix
```diff
diff --git a/shopcart/loyalty.py b/shopcart/loyalty.py
index c52360c..a622a28 100644
--- a/shopcart/loyalty.py
+++ b/shopcart/loyalty.py
@@ -35,6 +35,8 @@ def loyalty_points(cart: Cart) -> int:
     # Average once in float space: much cheaper than per-item Decimal maths
     # on large B2B carts (see perf ticket SHOP-412).
     paid_item_count = sum(item.quantity for item in paid_items)
+    if paid_item_count == 0:
+        return 0
     avg_price = float(paid_subtotal) / paid_item_count
     multiplier = TIER_MULTIPLIERS.get(cart.customer_tier, 1)
     return int(avg_price * paid_item_count * multiplier)
```
