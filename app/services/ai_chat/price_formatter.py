"""
Lease-aware price formatting.

The DB stores every property's price in the same `monthlyRent` field
regardless of `rentType` — for rentType="monthly" it really is a
recurring monthly rent, but for rentType="lease" it's a fixed lease
amount tied to `leaseMonths`. Rendering it the same way in both cases
("₹500000/month") is misleading for lease listings, so this helper
picks the right label/format based on rent_type.
"""


def format_price(p: dict) -> str:
    """
    Build a human-readable price string for a property dict (as produced
    by PropertyDBService._serialize — expects "price", "rent_type",
    "lease_months" keys).
    """
    price = p.get("price")
    if not price:
        return "price on request"

    rent_type = (p.get("rent_type") or "").strip().lower()

    if rent_type == "lease":
        lease_months = p.get("lease_months")
        if lease_months:
            return f"₹{price:,} for {lease_months} months"
        return f"₹{price:,} (lease)"

    return f"₹{price:,}/month"
