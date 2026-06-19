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

    # ===================================
    # Connect to MongoDB Atlas
    # ===================================
    def _connect(self):
        try:
            uri     = os.getenv("MONGODB_URI", "mongodb://localhost:27017")
            db_name = os.getenv("MONGODB_DB", "tolet_db")

            client          = MongoClient(uri, serverSelectionTimeoutMS=5000)
            db              = client[db_name]
            self.collection = db["properties"]

            client.admin.command("ping")
            print("[PropertyDBService] Connected to MongoDB Atlas.")

        except Exception as e:
            print(f"[PropertyDBService] MongoDB connection failed: {e}")
            self.collection = None

    # ===================================
    # Main Search Entry Point
    # Always returns a list — never raises.
    # ===================================
    def search(self, filters: dict) -> list:

        if self.collection is None:
            print("[PropertyDBService] No DB connection. Returning empty.")
            return []

        try:
            location_expand = filters.get("location_expand")

            if location_expand and isinstance(location_expand, list) and len(location_expand) > 0:
                return self._search_expanded(filters, location_expand)

            return self._search_single(filters)

        except Exception as e:
            print(f"[PropertyDBService] Search error: {e}")
            return []

    # ===================================
    # Expanded Location Search
    # Searches locality OR city across
    # multiple areas (OR logic).
    # Used when user says a city/state name
    # so the extractor expands it into
    # a list of localities.
    # ===================================
    def _search_expanded(self, filters: dict, areas: list) -> list:

        try:
            location_conditions = []
            for area in areas:
                # Escape special regex chars in area names
                safe_area = re.escape(area)
                pattern   = re.compile(safe_area, re.IGNORECASE)
                location_conditions.append({"locality": pattern})
                location_conditions.append({"city":     pattern})
                location_conditions.append({"state":    pattern})   # also match state field

            query = {"$or": location_conditions}
            query = self._apply_common_filters(query, filters)

            rows = list(
                self.collection.find(query).sort("createdAt", -1).limit(20)
            )

            # Deduplicate by _id
            seen    = set()
            results = []
            for row in rows:
                key = str(row["_id"])
                if key not in seen:
                    seen.add(key)
                    results.append(self._serialize(row))

            return results

        except Exception as e:
            print(f"[PropertyDBService] _search_expanded error: {e}")
            return []

    # ===================================
    # Single Location Search
    # Matches against locality, city,
    # or state field.
    # ===================================
    def _search_single(self, filters: dict) -> list:

        try:
            query = {}

            if filters.get("location"):
                safe_loc = re.escape(filters["location"])
                pattern  = re.compile(safe_loc, re.IGNORECASE)
                query["$or"] = [
                    {"locality": pattern},
                    {"city":     pattern},
                    {"state":    pattern},   # also match state field
                ]

            query = self._apply_common_filters(query, filters)

            rows = list(
                self.collection.find(query).sort("createdAt", -1).limit(20)
            )

            return [self._serialize(row) for row in rows]

        except Exception as e:
            print(f"[PropertyDBService] _search_single error: {e}")
            return []

    # ===================================
    # Common Filters
    # Maps AI filter keys → schema fields
    #
    # AI filter key   → Schema field
    # ─────────────────────────────────
    # bhk             → bedRoomCount
    # max_price       → monthlyRent
    # furnished       → furnishedType
    # near_metro      → availableAmenities.title
    # tenant_type     → preferredTenant
    # status          → status (always filtered to "presenting")
    # ===================================
    def _apply_common_filters(self, query: dict, filters: dict) -> dict:

        # Always restrict to properties that are actively listed ("approved").
        # Properties missing the status field entirely are also excluded —
        # absence of status means not yet approved.
        query["status"] = {"$eq": "approved"}

        if filters.get("bhk"):
            query["bedRoomCount"] = filters["bhk"]

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
        near_metro = any(
            "metro" in (a.get("title") or "").lower()
            for a in amenities
        )

        preferred         = (doc.get("preferredTenant") or "").lower()
        bachelor_friendly = "bachelor" in preferred or "any" in preferred
        family_friendly   = "family"   in preferred or "any" in preferred

        photos = doc.get("photos", []) or []
        image  = photos[0].get("url", "") if photos else ""

        return {
            "id":                 str(doc["_id"]),
            "title":              f"{doc.get('apartmentType', '')} {doc.get('propertyType', '')}".strip(),
            "location":           doc.get("locality") or doc.get("city") or "",
            "city":               doc.get("city", ""),
            "locality":           doc.get("locality", ""),
            "state":              doc.get("state", ""),
            "price":              doc.get("monthlyRent", 0),
            "bhk":                doc.get("bedRoomCount", 0),
            "furnished":          doc.get("furnishedType", ""),
            "property_type":      doc.get("propertyType", ""),
            "apartment_type":     doc.get("apartmentType", ""),
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
            "amenities":          [a.get("title", "") for a in amenities],
            "image":              image,
            "additional_details": doc.get("additionalDetails", ""),

            "owner_name":         doc.get("ownerName", ""),
            "owner_phone":        doc.get("ownerPhone", ""),
            "owner_whatsapp":     doc.get("ownerWhatsapp", ""),
            "preferred_time":     doc.get("preferredTimeToTalk", []),

            "status":             doc.get("status", ""),
        }

    # ===================================
    # Get All Distinct Localities from DB
    # Used by GeoExpander to check nearby
    # areas that actually have listings,
    # instead of blind Nominatim grid scan.
    # ===================================
    def get_all_localities(self) -> list:
        if self.collection is None:
            return []
        try:
            localities = self.collection.distinct("locality")
            cities     = self.collection.distinct("city")

            combined = set()
            for val in localities + cities:
                if val and isinstance(val, str) and val.strip():
                    combined.add(val.strip().title())

            result = sorted(combined)
            print(f"[PropertyDBService] get_all_localities: {len(result)} unique areas found.")
            return result

        except Exception as e:
            print(f"[PropertyDBService] get_all_localities error: {e}")
            return []

    # ===================================
    # Close (MongoDB manages its own pool)
    # ===================================
    def close(self):
        pass