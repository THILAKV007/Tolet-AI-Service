import os
import re
from dotenv import load_dotenv

load_dotenv()

try:
    from pymongo import MongoClient
    from bson import ObjectId
    MONGO_AVAILABLE = True
except ImportError:
    MONGO_AVAILABLE = False
    print("[PropertyDBService] pymongo not installed. Run: pip install 'pymongo[srv]'")


class PropertyDBService:

    def __init__(self):
        self.collection = None
        if MONGO_AVAILABLE:
            self._connect()

    def _connect(self):
        try:
            uri     = os.getenv("MONGODB_URI", "mongodb://localhost:27017")
            db_name = os.getenv("MONGODB_DB", "tolet_db")
            client          = MongoClient(uri, serverSelectionTimeoutMS=5000)
            db              = client[db_name]
            self.collection = db["properties"]
            client.admin.command("ping")
            print("[DB] Connected to MongoDB  (db=test)")
        except Exception as e:
            print(f"[PropertyDBService] MongoDB connection failed: {e}")
            self.collection = None

    # =========================================================================
    # Shared location-query builder
    # FIX: this logic previously existed as 3 separate copies (_search_single,
    # _search_expanded, count_by_owner_type), and had already drifted out of
    # sync — the expanded-search copy was missing the "address" field the
    # other two checked. One shared helper means a fix here fixes all callers.
    # =========================================================================
    def _location_or_conditions(self, raw_location: str) -> list:
        loc = raw_location.strip()
        loc_norm    = re.sub(r"\.+", "", loc)              # remove dots (K.K. Nagar → KK Nagar)
        loc_norm    = re.sub(r"\s+", " ", loc_norm).strip()  # collapse spaces
        loc_nospace = re.sub(r"\s+", "", loc_norm)          # "KK Nagar" → "KKNagar"

        # FIX: loc_nospace only strips spaces out of the QUERY. It does nothing
        # for DB values that have EXTRA spaces the query doesn't — e.g. DB
        # stores "k k nagar" (space between the two K's) while the user
        # searches "kk nagar" (no space). Neither "kk nagar" nor "kknagar" is
        # a substring of "k k nagar", so those listings were silently
        # invisible to search. Build a "flexible" pattern that allows any
        # amount of whitespace between every character of the no-space form,
        # so it matches regardless of which side (query or DB) has the extra
        # spacing.
        loc_flex = None
        if loc_nospace:
            loc_flex = r"\s*".join(re.escape(ch) for ch in loc_nospace)

        patterns = {loc, loc_norm, loc_nospace}
        or_conditions = []
        for p in patterns:
            if p:
                pat = re.compile(re.escape(p), re.IGNORECASE)
                or_conditions += [
                    {"locality": pat},
                    {"city":     pat},
                    {"state":    pat},
                    {"address":  pat},
                ]

        if loc_flex:
            flex_pat = re.compile(loc_flex, re.IGNORECASE)
            or_conditions += [
                {"locality": flex_pat},
                {"city":     flex_pat},
                {"state":    flex_pat},
                {"address":  flex_pat},
            ]

        return or_conditions

    def _build_location_query(self, location: str) -> dict:
        return {"$or": self._location_or_conditions(location)}

    def _build_expanded_location_query(self, areas: list) -> dict:
        or_conditions = []
        for area in areas:
            or_conditions += self._location_or_conditions(area.strip())
        return {"$or": or_conditions}

    # =========================================================================
    # Square-footage filter
    # FIX: min_sqft/max_sqft were extracted by the filter extractor but never
    # applied anywhere in the DB query, so a size constraint like "above 500
    # square feet" had zero effect — a 300 sqft listing would still come back.
    #
    # sqFt is stored in Mongo as a STRING (e.g. "450", and in some records
    # possibly with a unit suffix like "300 sqft"), not a number. Comparing
    # strings directly (query["sqFt"] = {"$gte": "500"}) is unsafe: string
    # comparison is lexicographic, so "1500" < "500" as strings even though
    # 1500 > 500 numerically. Instead, build a $expr that pulls the first
    # run of digits out of the field with $regexFind and compares that as a
    # number. Documents where sqFt is missing/blank/non-numeric are excluded
    # from a sqft-filtered search rather than guessed at.
    # =========================================================================
    def _build_sqft_expr(self, min_sqft, max_sqft) -> dict:
        digits_expr = {
            "$let": {
                "vars": {
                    "match": {
                        "$regexFind": {
                            "input": {"$ifNull": [{"$toString": "$sqFt"}, ""]},
                            "regex": r"\d+"
                        }
                    }
                },
                "in": {
                    "$cond": [
                        {"$eq": ["$$match", None]},
                        None,
                        {"$toInt": "$$match.match"}
                    ]
                }
            }
        }

        conditions = [{"$ne": [digits_expr, None]}]
        if min_sqft is not None:
            conditions.append({"$gte": [digits_expr, min_sqft]})
        if max_sqft is not None:
            conditions.append({"$lte": [digits_expr, max_sqft]})

        return {"$expr": {"$and": conditions}}

    # =========================================================================
    # Main Search
    # =========================================================================
    def search(self, filters: dict) -> list:
        if self.collection is None:
            return []

        # Strip internal-only keys
        filters = {k: v for k, v in filters.items() if not k.startswith("_")}

        try:
            location_expand = filters.get("location_expand")
            if location_expand and isinstance(location_expand, list) and location_expand:
                return self._search_expanded(filters, location_expand)
            return self._search_single(filters)
        except Exception as e:
            print(f"[PropertyDBService] Search error: {e}")
            return []

    # =========================================================================
    # Expanded Location Search (OR across multiple areas)
    # =========================================================================
    def _search_expanded(self, filters: dict, areas: list) -> list:
        """
        Search area-by-area in distance order (areas list is already sorted
        nearest-first by GeoExpander). Properties from the closest area appear
        first, then the next area, and so on — giving the user nearest results
        at the top.
        """
        try:
            seen    = set()
            results = []
            per_area_limit = filters.get("limit_per_area", 5)

            for area in areas:
                query = self._build_location_query(area)
                query = self._apply_common_filters(query, filters)

                rows = list(self.collection.find(query).sort("createdAt", -1).limit(per_area_limit))
                for row in rows:
                    key = str(row["_id"])
                    if key not in seen:
                        seen.add(key)
                        results.append(self._serialize(row))

            print(
                f"[PropertyDBService] _search_expanded: {len(areas)} areas searched"
                f" → {len(results)} total results (distance-ordered)"
            )
            return results
        except Exception as e:
            print(f"[PropertyDBService] _search_expanded error: {e}")
            return []

    # =========================================================================
    # Single Location Search
    # FIX: Use partial word-boundary regex so "velachery" matches "VELACHERY"
    # and "kk nagar" matches "kk nagar, CHENNAI" etc.
    # =========================================================================
    def _search_single(self, filters: dict) -> list:
        try:
            query = {}

            if filters.get("location"):
                query.update(self._build_location_query(filters["location"]))

            query = self._apply_common_filters(query, filters)
            limit = filters.get("limit", 20)

            print(f"[PropertyDBService] Mongo query: {query}")
            rows = list(self.collection.find(query).sort("createdAt", -1).limit(limit))
            results = [self._serialize(row) for row in rows]
            print(f"[PropertyDBService] _search_single '{filters.get('location')}' → {len(results)} results")
            return results

        except Exception as e:
            print(f"[PropertyDBService] _search_single error: {e}")
            return []

    # =========================================================================
    # Common Filters
    # FIX: bedRoomCount in DB is stored as "1 BHK" string, not integer.
    # We match it with a regex instead of exact int equality.
    # =========================================================================
    def _apply_common_filters(self, query: dict, filters: dict) -> dict:

        # Only approved properties
        query["status"] = {"$regex": "^approved$", "$options": "i"}

        # BHK is stored as a plain integer in MongoDB (e.g. 2, 3, 1)
        if filters.get("bhk"):
            query["bedRoomCount"] = int(filters["bhk"])

        # FIX: only max_price ("$lte") was ever applied here — a min_price
        # ("$gte") had no effect at all, so a range like "between 5k and
        # 10k" (min_price=5000, max_price=10000) silently behaved as
        # "under 10k", letting cheaper-than-requested listings slip through
        # and (combined with the extractor bug this was paired with) could
        # also wrongly exclude valid mid-range listings depending on which
        # end got captured. Build one $lte/$gte dict from whichever bounds
        # are present.
        min_price = filters.get("min_price")
        max_price = filters.get("max_price")
        if min_price is not None or max_price is not None:
            rent_range = {}
            if min_price is not None:
                rent_range["$gte"] = min_price
            if max_price is not None:
                rent_range["$lte"] = max_price
            query["monthlyRent"] = rent_range

        min_sqft = filters.get("min_sqft")
        max_sqft = filters.get("max_sqft")
        if min_sqft is not None or max_sqft is not None:
            query["$expr"] = self._build_sqft_expr(min_sqft, max_sqft)

        if filters.get("furnished"):
            query["furnishedType"] = {
                "$regex":   filters["furnished"],
                "$options": "i"
            }

        if filters.get("near_metro") is True:
            query["availableAmenities.title"] = {
                "$regex":   "metro",
                "$options": "i"
            }

        # ── Lease-specific filters ───────────────────────────────────────────
        # rentType: "monthly" (default recurring rent) vs "lease" (fixed-term,
        # usually paid upfront for the whole leaseMonths period). A user
        # asking "I want lease property" should only see rentType="lease"
        # listings, optionally narrowed further by leaseMonths.
        rent_type = filters.get("rent_type")
        if rent_type:
            query["rentType"] = {"$regex": f"^{re.escape(rent_type)}$", "$options": "i"}

        lease_months = filters.get("lease_months")
        if lease_months:
            query["leaseMonths"] = int(lease_months)

        tenant_type = filters.get("tenant_type")
        if tenant_type == "bachelor":
            query["preferredTenant"] = {"$regex": "bachelor", "$options": "i"}
        elif tenant_type == "family":
            query["preferredTenant"] = {"$regex": "family", "$options": "i"}

        owner_type = filters.get("owner_type")
        if owner_type == "owner":
            # DB stores this as either "direct owner"/"direct_owner" OR just
            # plain "owner" — match both, consistent with the normalization
            # already used in history_builder.py's display logic.
            # FALLBACK: some documents may have "type" missing/blank while
            # still carrying a valid isBrokerExcuse=True boolean (this was
            # true of the local seed data before it was fixed to match
            # production schema) — treat that as a direct-owner signal too,
            # so a document doesn't become invisible to owner-type search
            # just because one of the two redundant fields wasn't set.
            query["$and"] = query.get("$and", []) + [{
                "$or": [
                    {"type": {"$regex": "^(direct[_\\s]?owner|owner)$", "$options": "i"}},
                    {"$and": [
                        {"$or": [{"type": {"$exists": False}}, {"type": ""}]},
                        {"isBrokerExcuse": True},
                    ]},
                ]
            }]
        elif owner_type == "broker":
            query["type"] = {"$regex": "^broker", "$options": "i"}

        # ── Property type isolation ──────────────────────────────────────────
        # DB stores propertyType as "residential", "commercial", or "paid_guest".
        # If the user's intent is clearly one of these (shop/office/workspace →
        # commercial, pg/hostel/student-stay → paid_guest, flat/bhk/house →
        # residential), NEVER let another type leak into the results.
        property_type = filters.get("property_type")
        if property_type in ("residential", "commercial", "paid_guest"):
            query["propertyType"] = {
                "$regex":   f"^{re.escape(property_type)}$",
                "$options": "i"
            }

        # ── Commercial sub-type isolation ────────────────────────────────────
        # apartmentType stores the specific kind of commercial space (e.g.
        # "retail", "office", "warehouse"). Only ever applied alongside
        # property_type="commercial" (enforced upstream in SearchFilters), so
        # a user asking for "office space" doesn't get shown retail/warehouse
        # listings and vice versa. Regex substring match (not anchored) since
        # the DB may store richer strings like "Retail Space".
        apartment_type = filters.get("apartment_type")
        if apartment_type:
            query["apartmentType"] = {
                "$regex":   re.escape(apartment_type),
                "$options": "i"
            }

        return query

    def get_by_id(self, property_id: str) -> dict:
        if self.collection is None:
            return {}
        try:
            row = self.collection.find_one({"_id": ObjectId(property_id)})
            return self._serialize(row) if row else {}
        except Exception as e:
            print(f"[PropertyDBService] get_by_id error: {e}")
            return {}

    def _serialize(self, doc: dict) -> dict:
        if not doc:
            return {}

        amenities  = doc.get("availableAmenities", []) or []

        # near_metro: check amenities list AND waterResource field
        near_metro = any(
            "metro" in (a.get("title") or "").lower()
            for a in amenities
        ) or "metro" in (doc.get("waterResource") or "").lower()

        preferred         = (doc.get("preferredTenant") or "").lower()
        bachelor_friendly = "bachelor" in preferred or "any" in preferred
        family_friendly   = "family"   in preferred or "any" in preferred

        photos = doc.get("photos", []) or []
        image  = photos[0].get("url", "") if photos else ""

        # bedRoomCount is stored as plain integer in MongoDB
        bhk_raw = doc.get("bedRoomCount")
        bhk_num = int(bhk_raw) if isinstance(bhk_raw, (int, float)) else None

        # ── Smart title builder ────────────────────────────────────────────────
        # DB stores propertyType ("residential", "paid_guest", "commercial") and
        # optionally apartmentType ("2BHK Apartment", etc.).
        # For paid_guest: show unitConfig + occupancy for a meaningful title.
        # For residential/commercial: prefer apartmentType, fall back to propertyType.
        prop_type    = (doc.get("propertyType") or "").strip()
        apt_type     = (doc.get("apartmentType") or "").strip()
        unit_config  = (doc.get("unitConfig") or "").strip()       # e.g. "ac", "non-ac"
        occupancy    = (doc.get("occupancy") or "").strip()         # e.g. "single", "double"

        if prop_type.lower() == "paid_guest":
            # Build a readable PG title from available fields
            parts = [p for p in [unit_config.upper() if unit_config else "",
                                  occupancy.title() if occupancy else "",
                                  "PG"] if p]
            title = " ".join(parts)
        elif apt_type:
            title = apt_type
        else:
            title = prop_type.replace("_", " ").title()
        # ──────────────────────────────────────────────────────────────────────

        return {
            "id":                 str(doc["_id"]),
            "title":              title,
            "location":           doc.get("locality") or doc.get("city") or "",
            "city":               doc.get("city", ""),
            "locality":           doc.get("locality", ""),
            "state":              doc.get("state", ""),
            "price":              doc.get("monthlyRent", 0),
            "bhk":                bhk_num,
            "furnished":          doc.get("furnishedType", ""),
            "property_type":      prop_type,
            "apartment_type":     apt_type,
            "near_metro":         near_metro,
            "bachelor_friendly":  bachelor_friendly,
            "family_friendly":    family_friendly,
            "bathroom_count":     doc.get("bathroomCount", 0),
            "balcony_count":      doc.get("balconyCount", 0),
            "sq_ft":              doc.get("sqFt", ""),
            "floor":              doc.get("floorNumber", 0),
            "total_floors":       doc.get("totalNumberOfFloor", 0),
            "available_from":     doc.get("availableFrom", ""),
            "security_deposit":   doc.get("securityDeposit", ""),
            "maintenance":        doc.get("maintenance", 0),
            "notice_period":      doc.get("noticePeriod", ""),
            "pets_allowed":       doc.get("petsAllowed", ""),
            "no_broker":          doc.get("isBrokerExcuse", False),
            "posted_by":          doc.get("type", ""),
            "amenities":          [a.get("title", "") for a in amenities],
            "image":              image,
            "additional_details": doc.get("additionalDetails", ""),
            "owner_name":         doc.get("ownerName", ""),
            "owner_phone":        doc.get("ownerPhone", ""),
            "owner_whatsapp":     doc.get("ownerWhatsapp", ""),
            "preferred_time":     doc.get("preferredTimeToTalk", []),
            "status":             doc.get("status", ""),
            # ── PG-specific fields ─────────────────────────────────────────────
            "unit_config":        unit_config,   # "ac" / "non-ac"
            "occupancy":          occupancy,     # "single" / "double" / "triple"
            "gender":             (doc.get("gender") or "").strip(),  # "male" / "female" / "any"
            "water_resource":     (doc.get("waterResource") or "").strip(),
            "property_age":       (doc.get("propertyAge") or "").strip(),
            "payment_via":        (doc.get("paidRentalVia") or "").strip(),
            # ── Lease-specific fields ───────────────────────────────────────────
            # e.g. rentType: "monthly" / "lease"; leaseMonths: 11, 24, etc.
            "rent_type":          (doc.get("rentType") or "").strip(),
            "lease_months":       doc.get("leaseMonths"),
        }

    # =========================================================================
    # Get All Localities (for geo expander)
    # FIX: Return raw values (not .title()) so case matches DB exactly.
    # GeoExpander does its own normalisation.
    # =========================================================================
    # =========================================================================
    # Owner Type Counts for a Location
    # Returns how many direct owner & broker listings exist in the matched area
    # =========================================================================
    def count_by_owner_type(self, filters: dict) -> dict:
        """
        Returns {"direct_owner": N, "broker": N} for the given location/filter combo.
        Uses the same location matching logic as search() but ignores owner_type filter
        so counts always reflect total availability, not a pre-filtered slice.
        """
        if self.collection is None:
            return {"direct_owner": 0, "broker": 0}

        try:
            # Build base location query (same helper as search())
            location_expand = filters.get("location_expand")
            if location_expand and isinstance(location_expand, list) and location_expand:
                location_query = self._build_expanded_location_query(location_expand)
            elif filters.get("location"):
                location_query = self._build_location_query(filters["location"])
            else:
                return {"direct_owner": 0, "broker": 0}

            # Apply shared filters (bhk, price, etc.) but NOT owner_type
            count_filters = {k: v for k, v in filters.items()
                             if k not in ("owner_type", "location_expand", "location", "_geo_dist_lookup")}
            base_query = dict(location_query)
            base_query = self._apply_common_filters(base_query, count_filters)

            # Direct owner count (same fallback logic as _apply_common_filters,
            # kept in sync so counts and actual search results never disagree)
            #
            # FIX: base_query already carries the LOCATION match under the
            # "$or" key (see _build_location_query / _build_expanded_location_query).
            # The old code did `owner_query["$or"] = [...]` to add the owner-type
            # condition — but a dict can only have one "$or" key, so this
            # OVERWROTE the location clause entirely instead of combining with
            # it. The direct-owner count silently became "how many approved
            # properties of this type exist ANYWHERE in the DB" instead of
            # "...in this location" — e.g. it returned a global count of 14
            # commercial direct-owner listings across every city, while the
            # broker count right below (which uses a different key, "type",
            # and never collides) stayed correctly scoped to the searched
            # location. Fix: preserve the existing "$or" as its own clause and
            # AND it together with the new owner-type "$or".
            owner_query = dict(base_query)
            existing_or = owner_query.pop("$or", None)
            owner_type_or = {
                "$or": [
                    {"type": {"$regex": "^(direct[_\\s]?owner|owner)$", "$options": "i"}},
                    {"$and": [
                        {"$or": [{"type": {"$exists": False}}, {"type": ""}]},
                        {"isBrokerExcuse": True},
                    ]},
                ]
            }
            owner_query["$and"] = owner_query.get("$and", []) + (
                [{"$or": existing_or}] if existing_or else []
            ) + [owner_type_or]
            direct_count = self.collection.count_documents(owner_query)

            # Broker count
            broker_query = dict(base_query)
            broker_query["type"] = {"$regex": "^broker", "$options": "i"}
            broker_count = self.collection.count_documents(broker_query)

            print(f"[PropertyDBService] count_by_owner_type → direct_owner={direct_count}, broker={broker_count}")
            return {"direct_owner": direct_count, "broker": broker_count}

        except Exception as e:
            print(f"[PropertyDBService] count_by_owner_type error: {e}")
            return {"direct_owner": 0, "broker": 0}

    def get_all_localities(self) -> list:
        if self.collection is None:
            return []
        try:
            localities = self.collection.distinct("locality")
            result = sorted({
                val.strip()
                for val in localities
                if val and isinstance(val, str) and val.strip()
            })
            print(f"[PropertyDBService] get_all_localities: {len(result)} unique localities found.")
            return result
        except Exception as e:
            print(f"[PropertyDBService] get_all_localities error: {e}")
            return []

    # =========================================================================
    # Get All Localities WITH their city/state (for geo expander)
    # FIX: plain get_all_localities() above strips city/state entirely, so
    # GeoExpander.expand_from_db_with_distances had no way to tell a Chennai
    # "Anna Nagar" apart from any other city's "Anna Nagar" — its built-in
    # "skip candidates from a different city" check silently never engaged
    # because every candidate arrived as a bare string with no city on it.
    # This returns the richer {"locality","city","state"} shape GeoExpander
    # is actually built to consume.
    # =========================================================================
    def get_all_localities_with_city(self) -> list:
        if self.collection is None:
            return []
        try:
            docs = self.collection.find(
                {}, {"locality": 1, "city": 1, "state": 1, "_id": 0}
            )
            seen   = set()
            result = []
            for doc in docs:
                loc   = (doc.get("locality") or "").strip()
                city  = (doc.get("city") or "").strip()
                state = (doc.get("state") or "").strip()
                if not loc:
                    continue
                key = (loc.lower(), city.lower())
                if key in seen:
                    continue
                seen.add(key)
                result.append({"locality": loc, "city": city, "state": state})
            print(f"[PropertyDBService] get_all_localities_with_city: {len(result)} unique (locality, city) pairs found.")
            return result
        except Exception as e:
            print(f"[PropertyDBService] get_all_localities_with_city error: {e}")
            return []

    # =========================================================================
    # Resolve the actual city/state a location string belongs to
    # FIX: needed so GeoExpander gets a real city_hint/state_hint instead of
    # running blind — without it, expanding from a location matched every
    # locality in the ENTIRE database regardless of city (a search for a
    # Mumbai address could geocode-match, and get labelled "near", a
    # completely unrelated Chennai street 1,300+ km away), because the
    # sanity-radius check inside GeoExpander is a no-op when there's no
    # city_hint to validate against.
    # =========================================================================
    def get_city_state_for_location(self, location: str) -> tuple:
        """Returns (city, state) for the first approved property matching
        `location` (by locality/city/state/address), or ("", "") if none
        found — in which case the caller has no reliable city context and
        geo expansion should be skipped rather than guessed at."""
        if self.collection is None or not location:
            return ("", "")
        try:
            query = self._build_location_query(location)
            query["status"] = {"$regex": "^approved$", "$options": "i"}
            doc = self.collection.find_one(query, {"city": 1, "state": 1, "_id": 0})
            if not doc:
                return ("", "")
            return ((doc.get("city") or "").strip(), (doc.get("state") or "").strip())
        except Exception as e:
            print(f"[PropertyDBService] get_city_state_for_location error: {e}")
            return ("", "")

    def get_all_cities(self) -> list:
        if self.collection is None:
            return []
        try:
            cities = self.collection.distinct("city")
            result = sorted({
                val.strip()
                for val in cities
                if val and isinstance(val, str) and val.strip()
            })
            print(f"[PropertyDBService] get_all_cities: {len(result)} unique cities found.")
            return result
        except Exception as e:
            print(f"[PropertyDBService] get_all_cities error: {e}")
            return []

    def close(self):
        pass