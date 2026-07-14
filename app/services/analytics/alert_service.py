import os
import json
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

# ===================================
# Alert Service
# Wires up demand_logger data to
# notify users when a matching
# property becomes available.
#
# Flow:
#   1. User searches → no results found
#   2. demand_logger logs the search
#   3. User opts in → alert_service
#      saves their alert preference
#   4. When new property is added to DB
#      → check_and_notify() fires
#   5. User gets notified (email/webhook)
#
# Storage: Redis
# Notification: webhook or email
# ===================================

try:
    import redis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False


class AlertService:

    ALERT_TTL = 60 * 60 * 24 * 7  # 7 days

    def __init__(self):
        self.client    = None
        self._fallback = {}

        if REDIS_AVAILABLE:
            self._connect()

    # ===================================
    # Connect to Redis
    # ===================================
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
            print(f"[AlertService] Redis connection failed: {e}")
            self.client = None

    def _key(self, session_id: str) -> str:
        return f"tolet:alert:{session_id}"

    def _all_alerts_key(self) -> str:
        return "tolet:alerts:all"

    # ===================================
    # Register Alert
    # Called when user says
    # "notify me when available" or
    # "alert me when something comes up"
    # ===================================
    def register(
        self,
        session_id: str,
        filters: dict,
        contact: str = None
    ) -> bool:

        alert = {
            "session_id":  session_id,
            "filters":     filters,
            "contact":     contact,
            "created_at":  datetime.utcnow().isoformat(),
            "notified":    False
        }

        try:
            if self.client:
                # Save individual alert
                self.client.setex(
                    self._key(session_id),
                    self.ALERT_TTL,
                    json.dumps(alert)
                )
                # Add to global index
                self.client.sadd(self._all_alerts_key(), session_id)

            else:
                self._fallback[session_id] = alert

            print(f"[AlertService] Alert registered for session {session_id}: {filters}")
            return True

        except Exception as e:
            print(f"[AlertService] register error: {e}")
            return False

    # ===================================
    # Check and Notify
    # Call this when a new property is
    # added to the database.
    # Returns list of matched session_ids.
    # ===================================
    def check_and_notify(self, new_property: dict) -> list:

        matched = []

        try:
            alert_ids = self._get_all_alert_ids()

            for session_id in alert_ids:
                alert = self._get_alert(session_id)
                if not alert or alert.get("notified"):
                    continue

                if self._matches(new_property, alert["filters"]):
                    self._notify(session_id, alert, new_property)
                    matched.append(session_id)

        except Exception as e:
            print(f"[AlertService] check_and_notify error: {e}")

        return matched

    # ===================================
    # Match Property to Alert Filters
    # ===================================
    def _matches(self, property: dict, filters: dict) -> bool:

        if filters.get("location"):
            if filters["location"].lower() not in property.get("location", "").lower():
                return False

        if filters.get("bhk"):
            if property.get("bhk") != filters["bhk"]:
                return False

        if filters.get("max_price"):
            if property.get("price", 0) > filters["max_price"]:
                return False

        if filters.get("min_price"):
            if property.get("price", 0) < filters["min_price"]:
                return False

        if filters.get("furnished"):
            if property.get("furnished") != filters["furnished"]:
                return False

        if filters.get("near_metro"):
            if not property.get("near_metro"):
                return False

        tenant = filters.get("tenant_type")
        if tenant == "bachelor" and not property.get("bachelor_friendly"):
            return False
        if tenant == "family" and not property.get("family_friendly"):
            return False

        return True

    # ===================================
    # Send Notification
    # Extend this to send email/SMS/push
    # ===================================
    def _notify(self, session_id: str, alert: dict, property: dict):

        print(
            f"[AlertService] MATCH for session {session_id}: "
            f"{property.get('title')} in {property.get('location')} "
            f"at ₹{property.get('price')}"
        )

        # ===================================
        # Webhook Notification
        # Set ALERT_WEBHOOK_URL in .env
        # ===================================
        webhook_url = os.getenv("ALERT_WEBHOOK_URL")
        if webhook_url:
            try:
                import urllib.request
                payload = json.dumps({
                    "session_id": session_id,
                    "property":   property,
                    "filters":    alert["filters"],
                    "contact":    alert.get("contact")
                }).encode()

                req = urllib.request.Request(
                    webhook_url,
                    data=payload,
                    headers={"Content-Type": "application/json"},
                    method="POST"
                )
                urllib.request.urlopen(req, timeout=5)

            except Exception as e:
                print(f"[AlertService] Webhook failed: {e}")

        # Mark as notified
        alert["notified"] = True
        if self.client:
            self.client.setex(
                self._key(session_id),
                self.ALERT_TTL,
                json.dumps(alert)
            )

    # ===================================
    # Cancel Alert
    # ===================================
    def cancel(self, session_id: str):
        try:
            if self.client:
                self.client.delete(self._key(session_id))
                self.client.srem(self._all_alerts_key(), session_id)
            else:
                self._fallback.pop(session_id, None)
        except Exception as e:
            print(f"[AlertService] cancel error: {e}")

    # ===================================
    # Check if alert exists
    # ===================================
    def has_alert(self, session_id: str) -> bool:
        try:
            if self.client:
                return self.client.exists(self._key(session_id)) > 0
            return session_id in self._fallback
        except Exception:
            return False

    def _get_all_alert_ids(self) -> list:
        if self.client:
            return list(self.client.smembers(self._all_alerts_key()))
        return list(self._fallback.keys())

    def _get_alert(self, session_id: str) -> dict:
        if self.client:
            raw = self.client.get(self._key(session_id))
            return json.loads(raw) if raw else None
        return self._fallback.get(session_id)