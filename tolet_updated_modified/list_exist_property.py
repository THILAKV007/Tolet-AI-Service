"""
list_exist_property.py
======================
Lists all APPROVED properties currently in the database.

Displays: Location (locality, city, state), Status, Type
Filters:
  - Only properties where status field EXISTS and is "approved" (case-insensitive)
  - Pending / any other status → excluded
  - Works for all of India (not limited to Chennai / Tamil Nadu)

Also shows km-away from a reference point if you provide one via CLI:
  python list_exist_property.py --near "Koramangala, Bengaluru"
  python list_exist_property.py --near "Andheri West, Mumbai" --radius 5
"""

import os
import sys
import math
import argparse
import sqlite3
import threading
import time
import logging
from typing import Optional, Tuple
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.WARNING,
    format="%(levelname)s  %(message)s"
)
logger = logging.getLogger(__name__)

# ─── MongoDB ──────────────────────────────────────────────────────────────────
try:
    from pymongo import MongoClient
    MONGO_AVAILABLE = True
except ImportError:
    MONGO_AVAILABLE = False
    print("[ERROR] pymongo not installed. Run: pip install 'pymongo[srv]'")
    sys.exit(1)


# =============================================================================
# Haversine distance (km)
# =============================================================================
def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi       = math.radians(lat2 - lat1)
    dlambda    = math.radians(lon2 - lon1)
    a = (math.sin(dphi / 2) ** 2
         + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2)
    return R * 2 * math.asin(math.sqrt(a))


# =============================================================================
# Lightweight geocoder — India-wide, NO city/state bias
# =============================================================================
_GEO_USER_AGENT  = os.getenv("GEO_USER_AGENT", "tolet-list-properties/1.0")
_GEO_TIMEOUT     = int(os.getenv("GEO_TIMEOUT_SEC", "10"))
_GEO_RATE_LIMIT  = float(os.getenv("GEO_RATE_LIMIT_SEC", "1.1"))
_GEO_CACHE_PATH  = os.getenv(
    "GEO_CACHE_PATH",
    os.path.join(os.path.dirname(__file__), "app", "services", "geo", "geo_cache.db")
)

_last_call: float = 0.0
_call_lock        = threading.Lock()


def _rate_limit():
    global _last_call
    with _call_lock:
        now     = time.monotonic()
        elapsed = now - _last_call
        if elapsed < _GEO_RATE_LIMIT:
            time.sleep(_GEO_RATE_LIMIT - elapsed)
        _last_call = time.monotonic()


def _geocode_india(location: str) -> Optional[Tuple[float, float]]:
    """
    Geocode ANY location in India without assuming a city/state context.
    Strategy:
      Layer 1 — "{location}, India"        (Nominatim free-text + countrycodes=in)
      Layer 2 — structured suburb search   (Nominatim structured params)

    Results are cached in the same SQLite DB used by geo_expander so warm
    entries from the main app are reused here too.
    """
    import urllib.request
    import json
    import urllib.parse

    query_key = location.strip().lower()

    # ── check cache ────────────────────────────────────────────────────────
    try:
        conn = sqlite3.connect(_GEO_CACHE_PATH)
        row  = conn.execute(
            "SELECT lat, lon, found FROM geo_cache WHERE query = ?",
            (query_key,)
        ).fetchone()
        conn.close()

        if row is not None:
            if row[2] == 0:
                return None          # previously failed
            return (row[0], row[1])  # cache hit
    except Exception:
        pass  # cache unavailable — proceed to live geocode

    # ── Layer 1: free-text + countrycodes=in ───────────────────────────────
    _rate_limit()
    encoded = urllib.parse.quote(f"{location}, India")
    url = (
        f"https://nominatim.openstreetmap.org/search"
        f"?q={encoded}&format=json&limit=1&countrycodes=in"
    )
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _GEO_USER_AGENT})
        with urllib.request.urlopen(req, timeout=_GEO_TIMEOUT) as resp:
            data = json.loads(resp.read())
            if data:
                lat, lon = float(data[0]["lat"]), float(data[0]["lon"])
                _cache_put(query_key, lat, lon)
                return (lat, lon)
    except Exception as e:
        logger.debug(f"[geocode] Layer-1 error: {e}")

    # ── Layer 2: structured Nominatim ─────────────────────────────────────
    _rate_limit()
    params = urllib.parse.urlencode({
        "suburb":       location,
        "country":      "India",
        "format":       "json",
        "limit":        1,
        "countrycodes": "in",
    })
    url2 = f"https://nominatim.openstreetmap.org/search?{params}"
    try:
        req = urllib.request.Request(url2, headers={"User-Agent": _GEO_USER_AGENT})
        with urllib.request.urlopen(req, timeout=_GEO_TIMEOUT) as resp:
            data = json.loads(resp.read())
            if data:
                lat, lon = float(data[0]["lat"]), float(data[0]["lon"])
                _cache_put(query_key, lat, lon)
                return (lat, lon)
    except Exception as e:
        logger.debug(f"[geocode] Layer-2 error: {e}")

    # ── all layers failed ──────────────────────────────────────────────────
    _cache_put_miss(query_key)
    return None


def _cache_put(query: str, lat: float, lon: float):
    try:
        conn = sqlite3.connect(_GEO_CACHE_PATH)
        conn.execute(
            "INSERT OR REPLACE INTO geo_cache (query, lat, lon, found) VALUES (?, ?, ?, 1)",
            (query, lat, lon)
        )
        conn.commit()
        conn.close()
    except Exception:
        pass


def _cache_put_miss(query: str):
    try:
        conn = sqlite3.connect(_GEO_CACHE_PATH)
        conn.execute(
            "INSERT OR REPLACE INTO geo_cache (query, lat, lon, found) VALUES (?, NULL, NULL, 0)",
            (query,)
        )
        conn.commit()
        conn.close()
    except Exception:
        pass


# =============================================================================
# DB connection
# =============================================================================
def _connect() -> Optional[object]:
    uri     = os.getenv("MONGODB_URI", "mongodb://localhost:27017")
    db_name = os.getenv("MONGODB_DB", "tolet_db")
    try:
        client = MongoClient(uri, serverSelectionTimeoutMS=5000)
        client.admin.command("ping")
        collection = client[db_name]["properties"]
        print(f"[DB] Connected to MongoDB  (db={db_name})\n")
        return collection
    except Exception as e:
        print(f"[ERROR] MongoDB connection failed: {e}")
        return None


# =============================================================================
# Fetch approved properties
# =============================================================================
def fetch_approved_properties(collection) -> list:
    """
    Returns only properties whose status is exactly "approved" (case-insensitive).
    Pending / missing / any other value → excluded.
    Works across all of India — no location filter applied here.
    """
    query = {
        "status": {"$regex": "^approved$", "$options": "i"}
    }

    docs = list(collection.find(query).sort("createdAt", -1))
    results = []
    for doc in docs:
        locality = (doc.get("locality") or "").strip()
        city     = (doc.get("city")     or "").strip()
        state    = (doc.get("state")    or "").strip()

        location_parts = [p for p in [locality, city, state] if p]
        location_str   = ", ".join(location_parts) if location_parts else "—"

        results.append({
            "id":            str(doc["_id"]),
            "locality":      locality,
            "city":          city,
            "state":         state,
            "location_str":  location_str,
            "status":        doc.get("status", ""),
            "type":          doc.get("propertyType", "") or doc.get("apartmentType", "") or "—",
            "posted_by":     doc.get("type", ""),       # "direct owner" / "broker"
            "monthly_rent":  doc.get("monthlyRent", 0),
            "bhk":           doc.get("bedRoomCount", ""),
        })

    return results


# =============================================================================
# Print table
# =============================================================================
def _col(val: str, width: int) -> str:
    val = str(val)
    return val[:width].ljust(width)


def print_properties(properties: list, near_coords: Optional[Tuple[float, float]] = None):
    if not properties:
        print("No approved properties found in the database.")
        return

    show_dist = near_coords is not None

    # ── header ────────────────────────────────────────────────────────────
    header_parts = [
        _col("#",          4),
        _col("Location",   45),
        _col("Status",     10),
        _col("Type",       18),
        _col("Posted By",  14),
        _col("Rent (₹)",   12),
        _col("BHK",        5),
    ]
    if show_dist:
        header_parts.append(_col("Dist (km)", 10))

    header = " | ".join(header_parts)
    sep    = "-" * len(header)

    print(sep)
    print(header)
    print(sep)

    # ── rows ──────────────────────────────────────────────────────────────
    geocode_cache: dict = {}

    for i, p in enumerate(properties, start=1):
        dist_str = ""
        if show_dist:
            loc_key = p["location_str"]
            if loc_key not in geocode_cache:
                coords = _geocode_india(loc_key)
                geocode_cache[loc_key] = coords
            coords = geocode_cache[loc_key]
            if coords:
                d = _haversine_km(near_coords[0], near_coords[1], coords[0], coords[1])
                dist_str = f"{d:.1f} km"
            else:
                dist_str = "N/A"

        rent_str = f"{p['monthly_rent']:,}" if p["monthly_rent"] else "—"
        bhk_str  = str(p["bhk"]) + " BHK" if p["bhk"] else "—"

        row_parts = [
            _col(str(i),           4),
            _col(p["location_str"], 45),
            _col(p["status"],      10),
            _col(p["type"],        18),
            _col(p["posted_by"],   14),
            _col(rent_str,         12),
            _col(bhk_str,          5),
        ]
        if show_dist:
            row_parts.append(_col(dist_str, 10))

        print(" | ".join(row_parts))

    print(sep)
    print(f"\nTotal approved properties: {len(properties)}")


# =============================================================================
# CLI entry point
# =============================================================================
def main():
    parser = argparse.ArgumentParser(
        description="List all APPROVED properties from the ToLet database."
    )
    parser.add_argument(
        "--near",
        metavar="LOCATION",
        help='Show distance from this reference point. E.g. "Koramangala, Bengaluru"',
        default=None,
    )
    parser.add_argument(
        "--radius",
        metavar="KM",
        type=float,
        help="Filter to only show properties within this radius (requires --near)",
        default=None,
    )
    args = parser.parse_args()

    # ── connect ───────────────────────────────────────────────────────────
    collection = _connect()
    if collection is None:
        sys.exit(1)

    # ── fetch approved only ───────────────────────────────────────────────
    print("Fetching approved properties from DB...")
    properties = fetch_approved_properties(collection)
    print(f"Found {len(properties)} approved properties.\n")

    # ── geocode reference point if --near given ───────────────────────────
    near_coords = None
    if args.near:
        print(f"Geocoding reference point: '{args.near}' ...")
        near_coords = _geocode_india(args.near)
        if near_coords is None:
            print(f"[WARNING] Could not geocode '{args.near}'. Distance column will show N/A.")
        else:
            print(f"Reference coords: lat={near_coords[0]:.5f}, lon={near_coords[1]:.5f}\n")

        # filter by radius if requested
        if args.radius and near_coords:
            geocode_cache: dict = {}
            filtered = []
            for p in properties:
                loc_key = p["location_str"]
                if loc_key not in geocode_cache:
                    geocode_cache[loc_key] = _geocode_india(loc_key)
                coords = geocode_cache[loc_key]
                if coords:
                    d = _haversine_km(near_coords[0], near_coords[1], coords[0], coords[1])
                    if d <= args.radius:
                        filtered.append(p)
                # properties we can't geocode are excluded when a radius filter is active
            print(f"After {args.radius} km radius filter: {len(filtered)} properties.\n")
            properties = filtered

    # ── print ─────────────────────────────────────────────────────────────
    print_properties(properties, near_coords=near_coords)


if __name__ == "__main__":
    main()
