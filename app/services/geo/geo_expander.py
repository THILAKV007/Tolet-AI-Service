"""
geo_expander.py — Fully Dynamic Geo Expander
=============================================
No hardcoded coordinate maps. No hardcoded aliases.

Geocoding strategy (3 fallback layers so obscure locality names always resolve):
  Layer 1 — exact query + city + state + country
             e.g. "Iyappanthangal, Chennai, Tamil Nadu, India"
  Layer 2 — query + state + country only
             e.g. "Iyappanthangal, Tamil Nadu, India"
  Layer 3 — query + country only
             e.g. "Iyappanthangal, India"
  Layer 4 — Nominatim structured address params (suburb/city/state/country)

Results cached in SQLite forever — Nominatim called at most once per locality.
Rate limit: 1.1 sec between calls (Nominatim policy).
"""

import os
import math
import time
import sqlite3
import logging
import threading
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

# ── SQLite cache path ─────────────────────────────────────────────────────────
_DEFAULT_CACHE_PATH = os.path.join(os.path.dirname(__file__), "geo_cache.db")
GEO_CACHE_PATH = os.getenv("GEO_CACHE_PATH", _DEFAULT_CACHE_PATH)

# ── Geocoding context — set these in .env for your city ──────────────────────
_USER_AGENT   = os.getenv("GEO_USER_AGENT",    "tolet-ai-geocoder/2.0 (contact@tolet.city)")
_TIMEOUT      = int(os.getenv("GEO_TIMEOUT_SEC", "10"))
_RATE_LIMIT   = float(os.getenv("GEO_RATE_LIMIT_SEC", "1.1"))
_CITY_HINT    = os.getenv("GEO_CITY_HINT",    "")
_STATE_HINT   = os.getenv("GEO_STATE_HINT",   "")
_COUNTRY_HINT = os.getenv("GEO_COUNTRY_HINT", "India")

# ── Optional bounding-box guard — rejects Nominatim results that land outside
#    the expected region (prevents city-level fallback coords from being cached
#    as valid locality hits).  Set to empty string to disable.
#    Defaults to a box that covers Greater Chennai + immediate surroundings.
_BBOX_LAT_MIN = float(os.getenv("GEO_BBOX_LAT_MIN", "12.80"))
_BBOX_LAT_MAX = float(os.getenv("GEO_BBOX_LAT_MAX", "13.30"))
_BBOX_LON_MIN = float(os.getenv("GEO_BBOX_LON_MIN", "79.95"))
_BBOX_LON_MAX = float(os.getenv("GEO_BBOX_LON_MAX", "80.45"))
_BBOX_ENABLED = os.getenv("GEO_BBOX_ENABLED", "true").lower() not in ("false", "0", "no")

# ── City-centre coords — if Nominatim returns exactly these for a *locality*
#    query it almost certainly resolved the city, not the locality.
#    Set GEO_CITY_CENTRE_TOLERANCE_KM=0 to disable this check.
_CITY_CENTRE_LAT = float(os.getenv("GEO_CITY_CENTRE_LAT", "13.0836939"))
_CITY_CENTRE_LON = float(os.getenv("GEO_CITY_CENTRE_LON", "80.270186"))
_CITY_CENTRE_TOL = float(os.getenv("GEO_CITY_CENTRE_TOLERANCE_KM", "0.5"))


def _in_bbox(lat: float, lon: float) -> bool:
    """Return True if (lat, lon) falls within the configured bounding box."""
    if not _BBOX_ENABLED:
        return True
    return _BBOX_LAT_MIN <= lat <= _BBOX_LAT_MAX and _BBOX_LON_MIN <= lon <= _BBOX_LON_MAX


def _is_city_centre_fallback(lat: float, lon: float) -> bool:
    """Return True if the result is suspiciously close to the city centre.

    Nominatim sometimes resolves a locality name to the parent city when it
    cannot find the specific suburb.  We detect this by checking whether the
    returned point is within _CITY_CENTRE_TOL km of the known city-centre
    coordinates.  When that happens we treat the result as a miss so we don't
    cache the wrong point forever.
    """
    if _CITY_CENTRE_TOL <= 0:
        return False
    dist = _haversine_km(lat, lon, _CITY_CENTRE_LAT, _CITY_CENTRE_LON)
    return dist < _CITY_CENTRE_TOL


# =============================================================================
# Haversine Distance
# =============================================================================
def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi    = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return R * 2 * math.asin(math.sqrt(a))


# =============================================================================
# Geocode Cache  (SQLite, thread-safe)
# =============================================================================
class _GeoCache:
    _lock = threading.Lock()

    def __init__(self, db_path: str = GEO_CACHE_PATH):
        self._db_path = db_path
        self._init_db()

    def _init_db(self):
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS geo_cache (
                    query     TEXT PRIMARY KEY,
                    lat       REAL,
                    lon       REAL,
                    found     INTEGER NOT NULL DEFAULT 1,
                    cached_at TEXT DEFAULT (datetime('now'))
                )
            """)
            conn.commit()
            conn.close()

    def get(self, query: str) -> Optional[Tuple[float, float]]:
        """Return (lat, lon), () on cached-miss, or None if not cached yet."""
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            row  = conn.execute(
                "SELECT lat, lon, found FROM geo_cache WHERE query = ?",
                (query.lower(),)
            ).fetchone()
            conn.close()
        if row is None:
            return None
        if row[2] == 0:
            return ()
        return (row[0], row[1])

    def put(self, query: str, lat: float, lon: float):
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            conn.execute(
                "INSERT OR REPLACE INTO geo_cache (query, lat, lon, found) VALUES (?, ?, ?, 1)",
                (query.lower(), lat, lon)
            )
            conn.commit()
            conn.close()

    def put_miss(self, query: str):
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            conn.execute(
                "INSERT OR REPLACE INTO geo_cache (query, lat, lon, found) VALUES (?, NULL, NULL, 0)",
                (query.lower(),)
            )
            conn.commit()
            conn.close()

    def all_cached(self) -> dict:
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            rows = conn.execute(
                "SELECT query, lat, lon FROM geo_cache WHERE found = 1"
            ).fetchall()
            conn.close()
        return {r[0]: (r[1], r[2]) for r in rows}


# =============================================================================
# Nominatim Geocoder — 4-layer fallback
# =============================================================================
class _Geocoder:
    """
    Layer 1: "{locality}, {city}, {state}, {country}"   ← most specific
    Layer 2: "{locality}, {state}, {country}"
    Layer 3: "{locality}, {country}"                     ← last resort text
    Layer 4: Nominatim structured params (suburb/city/state/country)

    Uses geopy if installed, raw urllib otherwise.
    Global rate limit across all threads: 1.1 sec between calls.
    """

    _last_call: float = 0.0
    _lock = threading.Lock()

    def __init__(self):
        self._geopy_ready = False
        self._geocoder    = None
        self._try_geopy()

    def _try_geopy(self):
        try:
            from geopy.geocoders import Nominatim
            self._geocoder    = Nominatim(user_agent=_USER_AGENT, timeout=_TIMEOUT)
            self._geopy_ready = True
            logger.info("[Geocoder] geopy Nominatim ready.")
        except ImportError:
            logger.warning("[Geocoder] geopy not installed — using urllib fallback.")

    def geocode(self, locality: str) -> Optional[Tuple[float, float]]:
        # Build layers dynamically — skip empty city/state hints so they
        # don't corrupt the query (important for India-wide support).
        layers = []
        if _CITY_HINT and _STATE_HINT:
            layers.append(f"{locality}, {_CITY_HINT}, {_STATE_HINT}, {_COUNTRY_HINT}")
        if _STATE_HINT:
            layers.append(f"{locality}, {_STATE_HINT}, {_COUNTRY_HINT}")
        layers.append(f"{locality}, {_COUNTRY_HINT}")

        for i, query in enumerate(layers, start=1):
            self._rate_limit()
            result = (
                self._geocode_geopy(query)
                if self._geopy_ready
                else self._geocode_urllib(query)
            )
            if result:
                if not _in_bbox(result[0], result[1]):
                    logger.warning(
                        f"[Geocoder] Layer {i} result for '{locality}' via '{query}' "
                        f"is outside bbox ({result[0]:.4f}, {result[1]:.4f}) — treating as miss."
                    )
                elif _is_city_centre_fallback(result[0], result[1]):
                    logger.warning(
                        f"[Geocoder] Layer {i} result for '{locality}' via '{query}' "
                        f"landed on city centre ({result[0]:.4f}, {result[1]:.4f}) — "
                        f"likely a generic fallback, treating as miss."
                    )
                else:
                    logger.info(f"[Geocoder] Layer {i} resolved '{locality}' via '{query}'")
                    return result
            logger.debug(f"[Geocoder] Layer {i} miss for '{locality}'")

        # Layer 4 — structured Nominatim params
        self._rate_limit()
        result = self._geocode_structured(locality)
        if result:
            if not _in_bbox(result[0], result[1]):
                logger.warning(
                    f"[Geocoder] Layer 4 result for '{locality}' is outside bbox "
                    f"({result[0]:.4f}, {result[1]:.4f}) — treating as miss."
                )
            elif _is_city_centre_fallback(result[0], result[1]):
                logger.warning(
                    f"[Geocoder] Layer 4 result for '{locality}' landed on city centre "
                    f"({result[0]:.4f}, {result[1]:.4f}) — likely a generic fallback, treating as miss."
                )
            else:
                logger.info(f"[Geocoder] Layer 4 (structured) resolved '{locality}'")
                return result

        logger.warning(f"[Geocoder] All 4 layers failed for '{locality}'")
        return None

    def _geocode_geopy(self, query: str) -> Optional[Tuple[float, float]]:
        try:
            loc = self._geocoder.geocode(query, exactly_one=True)
            return (loc.latitude, loc.longitude) if loc else None
        except Exception as e:
            logger.debug(f"[Geocoder] geopy error: {e}")
            return None

    def _geocode_urllib(self, query: str) -> Optional[Tuple[float, float]]:
        import urllib.request, json, urllib.parse
        encoded = urllib.parse.quote(query)
        url = (
            f"https://nominatim.openstreetmap.org/search"
            f"?q={encoded}&format=json&limit=1&countrycodes=in"
        )
        return self._fetch(url)

    def _geocode_structured(self, locality: str) -> Optional[Tuple[float, float]]:
        import urllib.request, json, urllib.parse
        params_dict = {
            "suburb":       locality,
            "state":        _STATE_HINT,
            "country":      _COUNTRY_HINT,
            "format":       "json",
            "limit":        1,
            "countrycodes": "in",
        }
        # Only include city if a hint is configured
        if _CITY_HINT:
            params_dict["city"] = _CITY_HINT
        # Remove blank state hint too
        if not _STATE_HINT:
            params_dict.pop("state", None)
        params = urllib.parse.urlencode(params_dict)
        url = f"https://nominatim.openstreetmap.org/search?{params}"
        return self._fetch(url)

    def _fetch(self, url: str) -> Optional[Tuple[float, float]]:
        import urllib.request, json
        try:
            req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
            with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
                data = json.loads(resp.read())
                if data:
                    return (float(data[0]["lat"]), float(data[0]["lon"]))
            return None
        except Exception as e:
            logger.debug(f"[Geocoder] fetch error: {e}")
            return None

    def _rate_limit(self):
        with _Geocoder._lock:
            now     = time.monotonic()
            elapsed = now - _Geocoder._last_call
            if elapsed < _RATE_LIMIT:
                time.sleep(_RATE_LIMIT - elapsed)
            _Geocoder._last_call = time.monotonic()


# =============================================================================
# GeoExpander — Main Class
# =============================================================================
class GeoExpander:
    """
    Dynamically geocodes every DB locality via Nominatim (4-layer fallback).
    Results cached in SQLite — Nominatim called at most once per locality.
    No hardcoded coordinate maps. No hardcoded alias tables.
    """

    DEFAULT_RADIUS_KM: float = float(os.getenv("GEO_EXPAND_RADIUS_KM", "4.0"))

    def __init__(self):
        self._cache    = _GeoCache()
        self._geocoder = _Geocoder()
        logger.info(f"[GeoExpander] Initialized. Cache: {GEO_CACHE_PATH}")

    # =========================================================================
    # get_coords — cache-first, 4-layer Nominatim fallback
    # =========================================================================
    def get_coords(self, location: str) -> Optional[Tuple[float, float]]:
        query  = location.strip()
        cached = self._cache.get(query)

        if cached is None:
            logger.info(f"[GeoExpander] Cache miss — geocoding '{query}'")
            result = self._geocoder.geocode(query)
            if result:
                self._cache.put(query, result[0], result[1])
                return result
            else:
                self._cache.put_miss(query)
                return None

        if cached == ():
            return None   # previously failed

        return cached

    # =========================================================================
    # expand_from_db_with_distances  ← PRIMARY METHOD
    # =========================================================================
    def expand_from_db_with_distances(
        self,
        location: str,
        all_localities: list,
        radius_km: Optional[float] = None
    ) -> list:
        """
        Returns: [{"area": str, "distance_km": float}, ...]
          index 0 = origin (distance 0.0)
          rest    = DB localities within radius, sorted nearest-first
        """
        radius_km = radius_km if radius_km is not None else self.DEFAULT_RADIUS_KM

        origin = self.get_coords(location)
        if origin is None:
            logger.warning(
                f"[GeoExpander] Cannot geocode '{location}'. "
                f"Location will be used as-is without distance expansion."
            )
            return [{"area": location.strip().title(), "distance_km": 0.0}]

        origin_lat, origin_lon = origin
        result = [{"area": location.strip().title(), "distance_km": 0.0}]

        for loc in all_localities:
            loc_clean = loc.strip()
            if loc_clean.lower() == location.strip().lower():
                continue

            coords = self.get_coords(loc_clean)
            if coords is None:
                continue

            dist = _haversine_km(origin_lat, origin_lon, coords[0], coords[1])
            if dist <= radius_km:
                title_name = loc_clean.title()
                if not any(r["area"].lower() == title_name.lower() for r in result):
                    result.append({"area": title_name, "distance_km": round(dist, 1)})
                    logger.info(f"[GeoExpander] '{loc_clean}' included at {dist:.1f} km")

        origin_entry = result[0]
        nearby       = sorted(result[1:], key=lambda r: r["distance_km"])
        return [origin_entry] + nearby

    # =========================================================================
    # expand_from_db — plain list (backward-compatible)
    # =========================================================================
    def expand_from_db(
        self,
        location: str,
        all_localities: list,
        radius_km: Optional[float] = None
    ) -> list:
        with_dist = self.expand_from_db_with_distances(location, all_localities, radius_km)
        return [r["area"] for r in with_dist]

    # =========================================================================
    # warm_cache — call at app startup
    # =========================================================================
    def warm_cache(self, localities: list):
        skipped = fetched = failed = 0
        for loc in localities:
            loc_clean = loc.strip()
            if self._cache.get(loc_clean) is not None:
                skipped += 1
                continue
            if self.get_coords(loc_clean):
                fetched += 1
            else:
                failed += 1
        logger.info(
            f"[GeoExpander] warm_cache — {fetched} geocoded, {skipped} cached, {failed} failed."
        )

    # =========================================================================
    # cache_stats
    # =========================================================================
    def cache_stats(self) -> dict:
        return {
            "total_cached": len(self._cache.all_cached()),
            "cache_path":   GEO_CACHE_PATH,
        }


# =============================================================================
# .env additions needed:
# =============================================================================
# GEO_CITY_HINT=Chennai
# GEO_STATE_HINT=Tamil Nadu
# GEO_COUNTRY_HINT=India
# GEO_USER_AGENT=tolet-ai-geocoder/2.0 (contact@tolet.city)
# GEO_EXPAND_RADIUS_KM=4.0
# GEO_TIMEOUT_SEC=10
# GEO_RATE_LIMIT_SEC=1.1
# GEO_CACHE_PATH=/app/geo_cache.db