"""
Lease-aware price formatting.

The DB stores every property's price in the same `monthlyRent` field
regardless of `rentType` — for rentType="monthly" it really is a
recurring monthly rent, but for rentType="lease" it's a fixed lease
amount tied to `leaseMonths`. Rendering it the same way in both cases
("₹500000/month") is misleading for lease listings, so this helper
picks the right label/format based on rentType.
"""


def format_price(p: dict) -> str:
    """
    Build a human-readable price string for a property dict (as produced
    by PropertyDBService._serialize — expects "monthlyRent", "rentType",
    "leaseMonths" keys, matching the DB field names exactly).
    """
    price = p.get("monthlyRent")
    if not price:
        return "price on request"

    rentType = (p.get("rentType") or "").strip().lower()

    if rentType == "lease":
        leaseMonths = p.get("leaseMonths")
        if leaseMonths:
            return f"₹{price:,} for {leaseMonths} months"
        return f"₹{price:,} (lease)"

    return f"₹{price:,}/month"
