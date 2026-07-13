"""
repair_geo_cache.py
====================
Removes geocache entries that are invalid due to Nominatim returning a
city-level fallback instead of the requested locality.  Two detection modes:

  1. Out-of-bbox   — coords outside the configured bounding box.
  2. City-centre   — coords within GEO_CITY_CENTRE_TOLERANCE_KM of the
                     known city-centre point (Nominatim's generic fallback).

Run once after deploying the bbox/city-centre fix in geo_expander.py:

    python scripts/repair_geo_cache.py [--dry-run] [--db PATH]

Purged entries are re-geocoded on next use; if Nominatim still can't resolve
them they're stored as proper cache-misses (found=0).
"""

import argparse
import math
import os
import sqlite3
import sys

# ── Mirror defaults from geo_expander.py ─────────────────────────────────────
LAT_MIN         = float(os.getenv("GEO_BBOX_LAT_MIN",              "12.80"))
LAT_MAX         = float(os.getenv("GEO_BBOX_LAT_MAX",              "13.30"))
LON_MIN         = float(os.getenv("GEO_BBOX_LON_MIN",              "79.95"))
LON_MAX         = float(os.getenv("GEO_BBOX_LON_MAX",              "80.45"))
CITY_CENTRE_LAT = float(os.getenv("GEO_CITY_CENTRE_LAT",          "13.0836939"))
CITY_CENTRE_LON = float(os.getenv("GEO_CITY_CENTRE_LON",          "80.270186"))
CITY_TOL_KM     = float(os.getenv("GEO_CITY_CENTRE_TOLERANCE_KM", "0.5"))

_DEFAULT_DB = os.path.join(
    os.path.dirname(__file__), "..", "app", "services", "geo", "geo_cache.db"
)


def haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return R * 2 * math.asin(math.sqrt(a))


def is_bad(lat, lon):
    if not (LAT_MIN <= lat <= LAT_MAX and LON_MIN <= lon <= LON_MAX):
        return "out-of-bbox"
    if CITY_TOL_KM > 0 and haversine_km(lat, lon, CITY_CENTRE_LAT, CITY_CENTRE_LON) < CITY_TOL_KM:
        return "city-centre-fallback"
    return None


def main():
    parser = argparse.ArgumentParser(description="Purge invalid geo cache entries.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would be deleted without deleting.")
    parser.add_argument("--db", default=_DEFAULT_DB, help="Path to geo_cache.db")
    args = parser.parse_args()

    db_path = os.path.abspath(args.db)
    if not os.path.exists(db_path):
        print(f"ERROR: DB not found at {db_path}", file=sys.stderr)
        sys.exit(1)

    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        "SELECT query, lat, lon FROM geo_cache WHERE found = 1"
    ).fetchall()

    to_purge = []
    for query, lat, lon in rows:
        if lat is None:
            continue
        reason = is_bad(lat, lon)
        if reason:
            to_purge.append((query, lat, lon, reason))

    if not to_purge:
        print("✓ No invalid entries found. Cache is clean.")
        conn.close()
        return

    prefix = "[DRY RUN] " if args.dry_run else ""
    print(f"{prefix}Found {len(to_purge)} invalid entries to purge:")
    for query, lat, lon, reason in to_purge:
        print(f"  [{reason}]  {query!r}  →  ({lat:.4f}, {lon:.4f})")

    if not args.dry_run:
        conn.executemany(
            "DELETE FROM geo_cache WHERE query = ?",
            [(q,) for q, *_ in to_purge]
        )
        conn.commit()
        print(f"\n✓ Purged {len(to_purge)} entries. They will be re-geocoded on next use.")
    else:
        print("\n(dry-run — nothing deleted)")

    conn.close()


if __name__ == "__main__":
    main()
