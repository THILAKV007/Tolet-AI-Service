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

# ── Geocoding context — DEFAULT hints only, used when a caller doesn't pass
#    a per-search city/state (kept for backward-compat with single-city
#    deployments). Prefer passing city_hint/state_hint explicitly per call.
_USER_AGENT   = os.getenv("GEO_USER_AGENT",    "tolet-ai-geocoder/2.0 (contact@tolet.city)")
_TIMEOUT      = int(os.getenv("GEO_TIMEOUT_SEC", "10"))
_RATE_LIMIT   = float(os.getenv("GEO_RATE_LIMIT_SEC", "1.1"))
_CITY_HINT    = os.getenv("GEO_CITY_HINT",    "")
_STATE_HINT   = os.getenv("GEO_STATE_HINT",   "")
_COUNTRY_HINT = os.getenv("GEO_COUNTRY_HINT", "India")

# ── Sanity-radius guard — rejects Nominatim results that land implausibly
#    far from the city being searched (prevents a locality name that also
#    exists in a different state from resolving to the wrong place, and
#    catches Nominatim's generic country/state-level fallback points).
#    FIX: previously this was a single hardcoded lat/lon box tuned only for
#    Chennai, which silently broke geocoding for every other city in a
#    multi-city dataset (Kochi, Mumbai, Kolkata, etc. all fell "outside the
#    box" and were cached as permanent misses). Now the reference point is
#    geocoded dynamically per city hint and cached, so this works for any
#    city without code changes.
_SANITY_RADIUS_KM = float(os.getenv("GEO_SANITY_RADIUS_KM", "60"))
_CITY_CENTRE_TOL   = float(os.getenv("GEO_CITY_CENTRE_TOLERANCE_KM", "0.5"))


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

    def __init__(self, cache: "_GeoCache" = None):
        self._geopy_ready = False
        self._geocoder    = None
        self._cache       = cache  # used to memoize per-city reference points
        self._try_geopy()

    def _try_geopy(self):
        try:
            from geopy.geocoders import Nominatim
            self._geocoder    = Nominatim(user_agent=_USER_AGENT, timeout=_TIMEOUT)
            self._geopy_ready = True
            logger.info("[Geocoder] geopy Nominatim ready.")
        except ImportError:
            logger.warning("[Geocoder] geopy not installed — using urllib fallback.")

    def _reference_point(self, city_hint: str, state_hint: str) -> Optional[Tuple[float, float]]:
        """
        Geocode the CITY itself (not the locality) to get a dynamic
        reference point to sanity-check locality results against. Cached
        under a distinct key so it's only looked up once per city, ever.
        Returns None if no city_hint is available (India-wide search with
        no city context — sanity check is skipped in that case).
        """
        if not city_hint:
            return None
        cache_key = f"__city_ref__:{city_hint.lower()}|{state_hint.lower()}"
        if self._cache:
            cached = self._cache.get(cache_key)
            if cached is not None:
                return cached if cached != () else None

        query = f"{city_hint}, {state_hint}, {_COUNTRY_HINT}" if state_hint else f"{city_hint}, {_COUNTRY_HINT}"
        self._rate_limit()
        result = self._geocode_geopy(query) if self._geopy_ready else self._geocode_urllib(query)
        if self._cache:
            if result:
                self._cache.put(cache_key, result[0], result[1])
            else:
                self._cache.put_miss(cache_key)
        return result

    def _validate(
        self, lat: float, lon: float, ref_point: Optional[Tuple[float, float]]
    ) -> Optional[str]:
        """Returns a rejection reason string, or None if the point looks valid."""
        if ref_point is None:
            return None  # no city context to validate against — accept as-is
        dist = _haversine_km(lat, lon, ref_point[0], ref_point[1])
        if dist > _SANITY_RADIUS_KM:
            return f"{dist:.1f}km from city centre (> {_SANITY_RADIUS_KM}km sanity radius)"
        if _CITY_CENTRE_TOL > 0 and dist < _CITY_CENTRE_TOL:
            return f"landed on city centre itself ({dist:.2f}km) — likely a generic fallback"
        return None

    def geocode(
        self,
        locality: str,
        city_hint: str = None,
        state_hint: str = None,
    ) -> Optional[Tuple[float, float]]:
        # FIX: hints are now per-call (falling back to the global .env values
        # only if the caller doesn't supply them), and validation uses a
        # dynamically-geocoded reference point for THAT city — not a single
        # hardcoded Chennai box. This is what makes multi-city data work.
        city_hint  = city_hint  if city_hint  is not None else _CITY_HINT
        state_hint = state_hint if state_hint is not None else _STATE_HINT
        ref_point  = self._reference_point(city_hint, state_hint)

        layers = []
        if city_hint and state_hint:
            layers.append(f"{locality}, {city_hint}, {state_hint}, {_COUNTRY_HINT}")
        if state_hint:
            layers.append(f"{locality}, {state_hint}, {_COUNTRY_HINT}")
        layers.append(f"{locality}, {_COUNTRY_HINT}")

        for i, query in enumerate(layers, start=1):
            self._rate_limit()
            result = (
                self._geocode_geopy(query)
                if self._geopy_ready
                else self._geocode_urllib(query)
            )
            if result:
                reason = self._validate(result[0], result[1], ref_point)
                if reason:
                    logger.warning(
                        f"[Geocoder] Layer {i} result for '{locality}' via '{query}' "
                        f"rejected: {reason} — treating as miss."
                    )
                else:
                    logger.info(f"[Geocoder] Layer {i} resolved '{locality}' via '{query}'")
                    return result
            logger.debug(f"[Geocoder] Layer {i} miss for '{locality}'")

        # Layer 4 — structured Nominatim params
        self._rate_limit()
        result = self._geocode_structured(locality, city_hint, state_hint)
        if result:
            reason = self._validate(result[0], result[1], ref_point)
            if reason:
                logger.warning(
                    f"[Geocoder] Layer 4 result for '{locality}' rejected: {reason} — treating as miss."
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

    def _geocode_structured(self, locality: str, city_hint: str = None, state_hint: str = None) -> Optional[Tuple[float, float]]:
        import urllib.request, json, urllib.parse
        city_hint  = city_hint  if city_hint  is not None else _CITY_HINT
        state_hint = state_hint if state_hint is not None else _STATE_HINT
        params_dict = {
            "suburb":       locality,
            "state":        state_hint,
            "country":      _COUNTRY_HINT,
            "format":       "json",
            "limit":        1,
            "countrycodes": "in",
        }
        # Only include city if a hint is configured
        if city_hint:
            params_dict["city"] = city_hint
        # Remove blank state hint too
        if not state_hint:
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
        self._geocoder = _Geocoder(cache=self._cache)
        logger.info(f"[GeoExpander] Initialized. Cache: {GEO_CACHE_PATH}")

    # =========================================================================
    # get_coords — cache-first, 4-layer Nominatim fallback
    # =========================================================================
    def get_coords(
        self, location: str, city_hint: str = None, state_hint: str = None
    ) -> Optional[Tuple[float, float]]:
        query = location.strip()
        # FIX: cache key now includes the city hint. Without this, "Anna
        # Nagar" geocoded once under a Chennai context and once under a
        # different city context would collide on the same cache key and
        # silently return the wrong city's coordinates for the second one.
        cache_key = f"{query}|{(city_hint or '').strip()}" if city_hint else query
        cached = self._cache.get(cache_key)

        if cached is None:
            logger.info(f"[GeoExpander] Cache miss — geocoding '{query}' (city_hint={city_hint!r})")
            result = self._geocoder.geocode(query, city_hint=city_hint, state_hint=state_hint)
            if result:
                self._cache.put(cache_key, result[0], result[1])
                return result
            else:
                self._cache.put_miss(cache_key)
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
        radius_km: Optional[float] = None,
        city_hint: str = None,
        state_hint: str = None,
    ) -> list:
        """
        Returns: [{"area": str, "distance_km": float}, ...]
          index 0 = origin (distance 0.0)
          rest    = DB localities within radius, sorted nearest-first

        city_hint/state_hint: the city/state the ORIGIN location belongs to.
        Strongly recommended to pass these — without a city hint, every
        candidate in `all_localities` is geocoded blind, which is unreliable
        for a multi-city dataset (a locality name that exists in more than
        one city can't be disambiguated). Callers should look up the
        origin's city from the DB (e.g. via a matched property's `city`
        field) before calling this.
        """
        radius_km = radius_km if radius_km is not None else self.DEFAULT_RADIUS_KM

        origin = self.get_coords(location, city_hint=city_hint, state_hint=state_hint)
        if origin is None:
            logger.warning(
                f"[GeoExpander] Cannot geocode '{location}'. "
                f"Location will be used as-is without distance expansion."
            )
            return [{"area": location.strip().title(), "distance_km": 0.0}]

        origin_lat, origin_lon = origin
        result = [{"area": location.strip().title(), "distance_km": 0.0}]

        for entry in all_localities:
            # Accept either a plain string (legacy, city-agnostic) or a
            # {"locality": ..., "city": ...} dict (preferred — lets us skip
            # candidates from a different city entirely, and geocode with
            # the RIGHT city hint instead of the origin's hint by mistake).
            if isinstance(entry, dict):
                loc_clean   = (entry.get("locality") or "").strip()
                entry_city  = (entry.get("city") or "").strip()
            else:
                loc_clean  = entry.strip()
                entry_city = city_hint or ""

            if not loc_clean or loc_clean.lower() == location.strip().lower():
                continue

            # Skip candidates known to be in a different city — avoids
            # mixing e.g. a Chennai "Anna Nagar" with an unrelated locality
            # of the same name in another city.
            if city_hint and entry_city and entry_city.lower() != city_hint.lower():
                continue

            coords = self.get_coords(loc_clean, city_hint=entry_city or city_hint, state_hint=state_hint)
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
        radius_km: Optional[float] = None,
        city_hint: str = None,
        state_hint: str = None,
    ) -> list:
        with_dist = self.expand_from_db_with_distances(
            location, all_localities, radius_km, city_hint=city_hint, state_hint=state_hint
        )
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
# GEO_CITY_HINT=Chennai          # fallback only — pass city_hint per call instead
# GEO_STATE_HINT=Tamil Nadu      # fallback only — pass state_hint per call instead
# GEO_COUNTRY_HINT=India
# GEO_USER_AGENT=tolet-ai-geocoder/2.0 (contact@tolet.city)
# GEO_EXPAND_RADIUS_KM=4.0
# GEO_SANITY_RADIUS_KM=60        # replaces the old hardcoded Chennai bbox
# GEO_CITY_CENTRE_TOLERANCE_KM=0.5
# GEO_TIMEOUT_SEC=10
# GEO_RATE_LIMIT_SEC=1.1
# GEO_CACHE_PATH=/app/geo_cache.db