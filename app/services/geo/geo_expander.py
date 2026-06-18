import os
import math
import logging
import time
from typing import Optional

logger = logging.getLogger(__name__)


def _haversine_km(lat1, lon1, lat2, lon2) -> float:
    R = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi       = math.radians(lat2 - lat1)
    dlambda    = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return R * 2 * math.asin(math.sqrt(a))


# ===================================
# Static Coordinate Map — India Localities
# No API needed. Pure offline math.
# Add new areas here as your DB grows.
# Format: "Title Case Name": (lat, lon)
# ===================================
INDIA_LOCALITY_COORDS = {

    # ── Chennai South ───────────────────────────────
    "Pallikaranai":    (12.9487, 80.2120),
    "Velachery":       (12.9815, 80.2180),
    "Medavakkam":      (12.9167, 80.1953),
    "Sholinganallur":  (12.9010, 80.2279),
    "Perungudi":       (12.9551, 80.2432),
    "Keelkattalai":    (12.9570, 80.1952),
    "Madipakkam":      (12.9594, 80.2000),
    "Nanganallur":     (12.9788, 80.1903),
    "Adambakkam":      (12.9776, 80.2031),
    "Selaiyur":        (12.9069, 80.1476),
    "Chromepet":       (12.9516, 80.1462),
    "Pallavaram":      (12.9675, 80.1491),
    "Tambaram":        (12.9229, 80.1273),
    "Perungalathur":   (12.8918, 80.1024),
    "Vandalur":        (12.8909, 80.0818),
    "Mudichur":        (12.9066, 80.0734),

    # ── Chennai West / Central ───────────────────────
    "Vadapalani":      (13.0510, 80.2129),
    "Kk Nagar":        (13.0489, 80.2001),   # your DB uses this
    "K.K. Nagar":      (13.0489, 80.2001),   # alias
    "Kk Nagar West":   (13.0489, 80.1950),
    "Ashok Nagar":     (13.0393, 80.2217),
    "Kodambakkam":     (13.0491, 80.2253),
    "Virugambakkam":   (13.0535, 80.1982),
    "Saligramam":      (13.0544, 80.2074),
    "Valasaravakkam":  (13.0496, 80.1710),
    "Mugalivakkam":    (13.0335, 80.1700),
    "Nesapakkam":      (13.0408, 80.1865),
    "Ramapuram":       (13.0323, 80.1791),
    "Porur":           (13.0359, 80.1567),
    "Alapakkam":       (13.0360, 80.1698),
    "Arumbakkam":      (13.0720, 80.2097),
    "Ekkatuthangal":   (13.0168, 80.2197),
    "Ekkattuthangal":  (13.0168, 80.2197),
    "Guindy":          (13.0067, 80.2206),
    "St Thomas Mount": (13.0017, 80.1955),
    "Alandur":         (13.0019, 80.2082),

    # ── Chennai Central / North ─────────────────────
    "T Nagar":         (13.0418, 80.2341),
    "Nungambakkam":    (13.0569, 80.2425),
    "Anna Nagar":      (13.0850, 80.2101),
    "Anna Nagar West": (13.0899, 80.1971),
    "Kilpauk":         (13.0839, 80.2461),
    "Egmore":          (13.0732, 80.2609),
    "Tondiarpet":      (13.1192, 80.2922),
    "Perambur":        (13.1150, 80.2485),
    "Kolathur":        (13.1197, 80.2129),
    "Villivakkam":     (13.1039, 80.2132),
    "Madhavaram":      (13.1484, 80.2337),
    "Pattabiram":      (13.1404, 80.0554),
    "Mogappair":       (13.0878, 80.1742),
    "Ambattur":        (13.1143, 80.1548),
    "Avadi":           (13.1143, 80.0996),
    "Poonamallee":     (13.0471, 80.0963),
    "Thirumangalam":   (13.0891, 80.2196),
    "Aminjikarai":     (13.0672, 80.2244),
    "Chetpet":         (13.0728, 80.2432),
    "Choolai":         (13.0975, 80.2568),
    "Sowcarpet":       (13.0979, 80.2728),

    # ── Chennai East / OMR ──────────────────────────
    "Adyar":           (13.0012, 80.2565),
    "Mylapore":        (13.0336, 80.2677),
    "Thiruvanmiyur":   (12.9826, 80.2570),
    "Omr":             (12.9010, 80.2279),
    "Thoraipakkam":    (12.9345, 80.2340),
    "Karapakkam":      (12.9063, 80.2321),
    "Navalur":         (12.8431, 80.2243),
    "Siruseri":        (12.8271, 80.2260),
    "Kelambakkam":     (12.7930, 80.2217),
    "Besant Nagar":    (13.0002, 80.2700),
    "Kotturpuram":     (13.0147, 80.2501),
    "Raja Annamalai Puram": (13.0290, 80.2566),
    "Mandaveli":       (13.0246, 80.2659),
    "Foreshore Estate":(13.0165, 80.2769),

    # ── Bangalore ───────────────────────────────────
    "Whitefield":      (12.9698, 77.7500),
    "Koramangala":     (12.9352, 77.6245),
    "Hsr Layout":      (12.9116, 77.6389),
    "Indiranagar":     (12.9719, 77.6412),
    "Marathahalli":    (12.9591, 77.6974),
    "Bellandur":       (12.9256, 77.6762),
    "Electronic City": (12.8399, 77.6770),
    "Jp Nagar":        (12.9102, 77.5930),
    "Bannerghatta":    (12.8632, 77.5986),
    "Btm Layout":      (12.9166, 77.6101),
    "Jayanagar":       (12.9308, 77.5832),
    "Malleshwaram":    (13.0035, 77.5680),
    "Hebbal":          (13.0350, 77.5970),
    "Yelahanka":       (13.1007, 77.5963),
    "Kr Puram":        (13.0013, 77.6963),
    "Sarjapur":        (12.8606, 77.7855),
    "Mahadevapura":    (12.9946, 77.7116),

    # ── Hyderabad ───────────────────────────────────
    "Gachibowli":      (17.4401, 78.3489),
    "Hitech City":     (17.4486, 78.3773),
    "Kondapur":        (17.4600, 78.3615),
    "Madhapur":        (17.4478, 78.3920),
    "Banjara Hills":   (17.4156, 78.4347),
    "Jubilee Hills":   (17.4317, 78.4071),
    "Kukatpally":      (17.4849, 78.3995),
    "Lb Nagar":        (17.3496, 78.5522),
    "Secunderabad":    (17.4399, 78.4983),
    "Ameerpet":        (17.4374, 78.4487),
    "Begumpet":        (17.4433, 78.4670),
    "Miyapur":         (17.4963, 78.3549),
    "Nallagandla":     (17.4580, 78.3264),
    "Manikonda":       (17.3960, 78.3940),
    "Puppalaguda":     (17.3948, 78.3763),
    "Financial District": (17.4156, 78.3498),

    # ── Mumbai ──────────────────────────────────────
    "Andheri":         (19.1136, 72.8697),
    "Bandra":          (19.0596, 72.8295),
    "Powai":           (19.1176, 72.9060),
    "Thane":           (19.2183, 72.9781),
    "Navi Mumbai":     (19.0330, 73.0297),
    "Borivali":        (19.2307, 72.8567),
    "Malad":           (19.1872, 72.8484),
    "Goregaon":        (19.1663, 72.8526),
    "Kurla":           (19.0726, 72.8843),
    "Ghatkopar":       (19.0860, 72.9081),
    "Mulund":          (19.1726, 72.9565),
    "Vikhroli":        (19.1065, 72.9258),
    "Chembur":         (19.0522, 72.8995),
    "Wadala":          (19.0176, 72.8624),

    # ── Pune ────────────────────────────────────────
    "Kothrud":         (18.5074, 73.8077),
    "Hinjewadi":       (18.5913, 73.7389),
    "Wakad":           (18.6012, 73.7609),
    "Baner":           (18.5590, 73.7868),
    "Viman Nagar":     (18.5679, 73.9143),
    "Kalyani Nagar":   (18.5477, 73.9008),
    "Hadapsar":        (18.5018, 73.9260),
    "Kharadi":         (18.5516, 73.9427),
    "Pimple Saudagar": (18.6074, 73.7997),
    "Pimple Nilakh":   (18.5947, 73.7959),
    "Aundh":           (18.5590, 73.8077),
    "Shivajinagar":    (18.5308, 73.8474),
}

# ===================================
# Area Alias Map
#
# Maps alternate spellings / short names
# that users type → canonical Title Case
# name used in INDIA_LOCALITY_COORDS.
#
# Add new aliases whenever your DB uses
# a spelling that differs from what users type.
# ===================================
AREA_ALIASES = {
    # KK Nagar variations
    "kk nagar":          "Kk Nagar",
    "k.k nagar":         "Kk Nagar",
    "k.k. nagar":        "Kk Nagar",
    "kknagar":           "Kk Nagar",
    "kk nagar west":     "Kk Nagar",

    # OMR
    "omr":               "Omr",
    "old mahabalipuram road": "Omr",

    # Common short forms
    "t nagar":           "T Nagar",
    "tnagar":            "T Nagar",
    "anna nagar":        "Anna Nagar",
    "annanagar":         "Anna Nagar",
    "hsr":               "Hsr Layout",
    "hsr layout":        "Hsr Layout",
    "jp nagar":          "Jp Nagar",
    "jpnagar":           "Jp Nagar",
    "btm":               "Btm Layout",
    "btm layout":        "Btm Layout",
    "kr puram":          "Kr Puram",
    "krpuram":           "Kr Puram",
    "e city":            "Electronic City",
    "electronic city":   "Electronic City",
    "hitech city":       "Hitech City",
    "hitec city":        "Hitech City",
    "lb nagar":          "Lb Nagar",
    "lbnagar":           "Lb Nagar",
    "banjara hills":     "Banjara Hills",
    "jubilee hills":     "Jubilee Hills",
    "financial district": "Financial District",
    "navi mumbai":       "Navi Mumbai",
    "viman nagar":       "Viman Nagar",
    "kalyani nagar":     "Kalyani Nagar",
    "pimple saudagar":   "Pimple Saudagar",
    "st thomas mount":   "St Thomas Mount",
    "ekkattuthangal":    "Ekkatuthangal",
    "raja annamalai puram": "Raja Annamalai Puram",
    "foreshore estate":  "Foreshore Estate",
    "anna nagar west":   "Anna Nagar West",
}


def _normalize_location(name: str) -> str:
    """Resolve aliases and return the canonical key for coord lookup."""
    key = name.strip().lower()
    canonical = AREA_ALIASES.get(key)
    if canonical:
        return canonical
    return name.strip().title()


class GeoExpander:

    DEFAULT_RADIUS_KM: float = float(os.getenv("GEO_EXPAND_RADIUS_KM", "4.0"))
    _USER_AGENT = "tolet-ai-geo-expander/1.0"
    _LAST_CALL_TIME: float = 0.0

    def __init__(self):
        self._geocoder = None
        self._ready    = False
        self._init_geocoder()

    def _init_geocoder(self):
        try:
            from geopy.geocoders import Nominatim
            from geopy.exc import GeocoderTimedOut, GeocoderServiceError
            self._geocoder             = Nominatim(user_agent=self._USER_AGENT, timeout=8)
            self._GeocoderTimedOut     = GeocoderTimedOut
            self._GeocoderServiceError = GeocoderServiceError
            self._ready                = True
            logger.info("[GeoExpander] Geopy Nominatim ready.")
        except ImportError:
            logger.warning("[GeoExpander] geopy not installed. Run: pip install geopy")
            self._ready = False

    # ===================================
    # DB-First Geo Expand  ← PRIMARY METHOD
    #
    # Flow:
    # 1. Resolve aliases  ("kk nagar" → "Kk Nagar")
    # 2. Look up origin in static coord map (no API)
    # 3. For each DB locality: resolve alias + lookup
    # 4. Keep those within radius_km
    # 5. Falls back to Nominatim only for unknown areas
    # ===================================
    def expand_from_db(
        self,
        location: str,
        all_localities: list,
        radius_km: Optional[float] = None,
        country_hint: str = "India"
    ) -> list:

        radius_km = radius_km if radius_km is not None else self.DEFAULT_RADIUS_KM
        loc_key   = _normalize_location(location)

        # ── Step 1: get origin coords ──────────────────────────
        origin_coords = INDIA_LOCALITY_COORDS.get(loc_key)

        if origin_coords is None:
            if self._ready:
                logger.info(f"[GeoExpander] '{loc_key}' not in static map, trying Nominatim.")
                geo = self._geocode(f"{location}, {country_hint}")
                if geo:
                    origin_coords = (geo.latitude, geo.longitude)
                else:
                    logger.warning(f"[GeoExpander] Could not locate '{location}'. Returning as-is.")
                    return [loc_key]
            else:
                logger.warning(f"[GeoExpander] '{loc_key}' not in static map and Nominatim unavailable.")
                return [loc_key]

        origin_lat, origin_lon = origin_coords
        logger.info(
            f"[GeoExpander] '{loc_key}' coords: ({origin_lat:.4f}, {origin_lon:.4f}), "
            f"radius={radius_km}km"
        )

        # ── Step 2: check each DB locality ─────────────────────
        result     = [loc_key]
        map_hits   = 0
        map_misses = 0

        for loc in all_localities:
            norm   = _normalize_location(loc)          # resolve alias
            if norm == loc_key:
                continue

            coords = INDIA_LOCALITY_COORDS.get(norm)
            if coords is None:
                map_misses += 1
                logger.debug(f"[GeoExpander] '{norm}' (from '{loc}') not in static map — skipping.")
                continue

            dist = _haversine_km(origin_lat, origin_lon, coords[0], coords[1])
            if dist <= radius_km:
                # Use the original DB name (not the alias key) so DB queries still match
                original_name = loc.strip().title()
                if original_name not in result:
                    result.append(original_name)
                map_hits += 1
                logger.info(f"[GeoExpander] '{loc}' is {dist:.1f}km from '{loc_key}' — included.")
            else:
                logger.debug(f"[GeoExpander] '{loc}' is {dist:.1f}km — too far.")

        logger.info(
            f"[GeoExpander] expand_from_db '{location}' -> {result} "
            f"(map_hits={map_hits}, map_misses={map_misses})"
        )
        return result

    # ===================================
    # Original Nominatim Grid Expand
    # Kept as fallback for unknown areas.
    # ===================================
    def expand_nearby(
        self,
        location: str,
        radius_km: Optional[float] = None,
        country_hint: str = "India"
    ) -> list:
        if not self._ready:
            logger.warning("[GeoExpander] Not ready — geopy unavailable.")
            return []

        radius_km = radius_km if radius_km is not None else self.DEFAULT_RADIUS_KM

        try:
            origin = self._geocode(f"{location}, {country_hint}")
            if origin is None:
                logger.warning(f"[GeoExpander] Could not geocode: {location}")
                return []

            origin_lat, origin_lon = origin.latitude, origin.longitude
            nearby_names = self._sample_grid(origin_lat, origin_lon, radius_km, location)

            result = [location.strip().title()]
            for name in nearby_names:
                norm = name.strip().title()
                if norm and norm not in result:
                    result.append(norm)

            return result

        except Exception as e:
            logger.error(f"[GeoExpander] expand_nearby failed for '{location}': {e}")
            return []

    def _sample_grid(self, center_lat, center_lon, radius_km, location) -> list:
        lat_deg = 1.0 / 111.0
        lon_deg = 1.0 / (111.0 * math.cos(math.radians(center_lat)))
        step    = radius_km * 0.85
        offsets = [
            (0, 0), (step, 0), (-step, 0), (0, step), (0, -step),
            (step*0.7, step*0.7), (-step*0.7, step*0.7),
            (step*0.7, -step*0.7), (-step*0.7, -step*0.7),
        ]
        found = set()
        for (dlat_km, dlon_km) in offsets:
            lat  = center_lat + dlat_km * lat_deg
            lon  = center_lon + dlon_km * lon_deg
            dist = _haversine_km(center_lat, center_lon, lat, lon)
            if dist > radius_km + 0.1:
                continue
            name = self._reverse_geocode_locality(lat, lon)
            if name:
                found.add(name)
        found.discard(location.strip().title())
        return list(found)

    def _reverse_geocode_locality(self, lat, lon) -> Optional[str]:
        try:
            self._rate_limit()
            loc  = self._geocoder.reverse((lat, lon), exactly_one=True, language="en")
            if not loc:
                return None
            addr = loc.raw.get("address", {})
            for key in ("suburb", "neighbourhood", "village", "town", "city_district", "residential"):
                val = addr.get(key, "").strip()
                if val and len(val) > 2:
                    return val.title()
            return None
        except Exception as e:
            logger.debug(f"[GeoExpander] reverse error at ({lat},{lon}): {e}")
            return None

    def _geocode(self, query):
        self._rate_limit()
        try:
            return self._geocoder.geocode(query, exactly_one=True)
        except Exception as e:
            logger.warning(f"[GeoExpander] geocode error: {e}")
            return None

    def _rate_limit(self):
        now     = time.monotonic()
        elapsed = now - GeoExpander._LAST_CALL_TIME
        if elapsed < 1.05:
            time.sleep(1.05 - elapsed)
        GeoExpander._LAST_CALL_TIME = time.monotonic()