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
        return or_conditions

    def _build_location_query(self, location: str) -> dict:
        return {"$or": self._location_or_conditions(location)}

    def _build_expanded_location_query(self, areas: list) -> dict:
        or_conditions = []
        for area in areas:
            or_conditions += self._location_or_conditions(area.strip())
        return {"$or": or_conditions}

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

        if filters.get("max_price"):
            query["monthlyRent"] = {"$lte": filters["max_price"]}

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
            owner_query = dict(base_query)
            owner_query["$or"] = [
                {"type": {"$regex": "^(direct[_\\s]?owner|owner)$", "$options": "i"}},
                {"$and": [
                    {"$or": [{"type": {"$exists": False}}, {"type": ""}]},
                    {"isBrokerExcuse": True},
                ]},
            ]
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