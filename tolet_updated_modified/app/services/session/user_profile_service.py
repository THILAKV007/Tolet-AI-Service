import os
import json
from dotenv import load_dotenv

load_dotenv()


try:
    import redis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False


class UserProfileService:

    PROFILE_TTL = 60 * 60 * 24 * 30  # 30 days

    def __init__(self):
        self.client   = None
        self._fallback = {}

        if REDIS_AVAILABLE:
            self._connect()


    def _connect(self):
        try:
            self.client = redis.Redis(
                host=os.getenv("REDIS_HOST", "localhost"),
                port=int(os.getenv("REDIS_PORT", 6379)),
                db=int(os.getenv("REDIS_DB", 0)),
                password=os.getenv("REDIS_PASSWORD", None),
                decode_responses=True
            )
            self.client.ping()
        except Exception as e:
            print(f"[UserProfileService] Redis connection failed: {e}")
            self.client = None

    def _key(self, user_id: str) -> str:
        return f"tolet:profile:{user_id}"


    def get(self, user_id: str) -> dict:

        default = {
            "user_id":         user_id,
            "preferred_city":  None,
            "budget_min":      None,
            "budget_max":      None,
            "bhk":             None,
            "tenant_type":     None,
            "furnished":       None,
            "near_metro":      None,
            "search_count":    0,
            "last_seen_city":  None
        }

        try:
            if self.client:
                raw = self.client.get(self._key(user_id))
                return json.loads(raw) if raw else default
            return self._fallback.get(user_id, default)

        except Exception as e:
            print(f"[UserProfileService] get error: {e}")
            return default

    def save(self, user_id: str, profile: dict):
        try:
            if self.client:
                self.client.setex(
                    self._key(user_id),
                    self.PROFILE_TTL,
                    json.dumps(profile, default=str)
                )
            else:
                self._fallback[user_id] = profile

        except Exception as e:
            print(f"[UserProfileService] save error: {e}")

    def update_from_filters(self, user_id: str, filters: dict):

        if not filters:
            return

        profile = self.get(user_id)

        # Learn city preference
        if filters.get("location"):
            profile["last_seen_city"] = filters["location"]

            # After 2+ searches in same city → preferred city
            if profile.get("preferred_city") == filters["location"]:
                pass  # already set
            elif profile["search_count"] >= 2:
                profile["preferred_city"] = filters["location"]

        # Learn BHK preference
        if filters.get("bhk"):
            profile["bhk"] = filters["bhk"]

        # Learn budget
        if filters.get("max_price"):
            profile["budget_max"] = filters["max_price"]

        # Learn tenant type
        if filters.get("tenant_type"):
            profile["tenant_type"] = filters["tenant_type"]

        # Learn furnished preference
        if filters.get("furnished"):
            profile["furnished"] = filters["furnished"]

        # Learn metro preference
        if filters.get("near_metro") is not None:
            profile["near_metro"] = filters["near_metro"]

        profile["search_count"] = profile.get("search_count", 0) + 1

        self.save(user_id, profile)


    def get_default_filters(self, user_id: str) -> dict:

        profile = self.get(user_id)

        return {
            "location":    profile.get("preferred_city"),
            "bhk":         profile.get("bhk"),
            "max_price":   profile.get("budget_max"),
            "furnished":   profile.get("furnished"),
            "near_metro":  profile.get("near_metro"),
            "tenant_type": profile.get("tenant_type")
        }


    def get_profile_summary(self, user_id: str) -> str:

        profile = self.get(user_id)

        if profile.get("search_count", 0) == 0:
            return ""

        parts = []

        if profile.get("preferred_city"):
            parts.append(f"usually searches in {profile['preferred_city']}")
        if profile.get("budget_max"):
            parts.append(f"typical budget up to ₹{profile['budget_max']}")
        if profile.get("bhk"):
            parts.append(f"prefers {profile['bhk']}BHK")
        if profile.get("tenant_type"):
            parts.append(f"{profile['tenant_type']} tenant")
        if profile.get("furnished"):
            parts.append(f"prefers {profile['furnished']} furnished")

        if not parts:
            return ""

        return "User profile: " + ", ".join(parts) + "."