import os
import json
from dotenv import load_dotenv

load_dotenv()


try:
    import redis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False
    print("[SessionStore] redis not installed. Run: pip install redis")


class SessionStore:

    def __init__(self):

        self.ttl      = int(os.getenv("SESSION_TTL_SECONDS", 3600))
        self.client   = None
        self._fallback = {}   # ← always initialised — fixes AttributeError when
                              #   redis package is missing and _connect() is never called

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
            print("[SessionStore] Connected to Redis.")

        except Exception as e:
            print(f"[SessionStore] Redis connection failed: {e}")
            print("[SessionStore] Falling back to in-memory store.")
            self.client = None
            # _fallback already initialised in __init__ — no need to reset here

    # ===================================
    # Build Redis Key
    # ===================================
    def _key(self, session_id: str) -> str:
        return f"tolet:session:{session_id}"

    def _default_session(self) -> dict:
        return {
            "filters":    {},
            "properties": [],
            "history":    [],
            "messages":   []
        }

    def get(self, session_id: str) -> dict:
        try:
            if self.client:
                raw = self.client.get(self._key(session_id))
                if raw:
                    return json.loads(raw)
                return self._default_session()

            # Fallback: in-memory
            return self._fallback.get(session_id, self._default_session())

        except Exception as e:
            print(f"[SessionStore] get error: {e}")
            return self._default_session()

    def set(self, session_id: str, data: dict):
        try:
            if self.client:
                self.client.setex(
                    self._key(session_id),
                    self.ttl,
                    json.dumps(data, default=str)
                )
            else:
                self._fallback[session_id] = data

        except Exception as e:
            print(f"[SessionStore] set error: {e}")

    def update(self, session_id: str, key: str, value):
        session      = self.get(session_id)
        session[key] = value
        self.set(session_id, session)

    def append_message(self, session_id: str, role: str, content: str):
        session = self.get(session_id)

        if "messages" not in session:
            session["messages"] = []

        session["messages"].append({
            "role":    role,
            "content": content
        })

        # Keep last 30 messages to avoid token overflow
        if len(session["messages"]) > 30:
            session["messages"] = (
                session["messages"][:1] +
                session["messages"][-29:]
            )

        self.set(session_id, session)

    def get_messages(self, session_id: str) -> list:
        session = self.get(session_id)
        return session.get("messages", [])

    def append_history(self, session_id: str, turn: dict):
        session = self.get(session_id)

        if "history" not in session:
            session["history"] = []

        session["history"].append(turn)

        if len(session["history"]) > 20:
            session["history"] = session["history"][-20:]

        if turn.get("properties"):
            session["properties"] = turn["properties"]

        if turn.get("filters"):
            session["filters"] = turn["filters"]

        self.set(session_id, session)

    def get_latest_with_properties(self, session_id: str) -> dict:
        session = self.get(session_id)
        history = session.get("history", [])

        for turn in reversed(history):
            if turn.get("properties"):
                return turn

        return history[-1] if history else None

    def get_properties(self, session_id: str) -> list:
        session = self.get(session_id)
        return session.get("properties", [])

    def get_filters(self, session_id: str) -> dict:
        session = self.get(session_id)
        return session.get("filters", {})

    def delete(self, session_id: str):
        try:
            if self.client:
                self.client.delete(self._key(session_id))
            else:
                self._fallback.pop(session_id, None)

        except Exception as e:
            print(f"[SessionStore] delete error: {e}")

    def refresh(self, session_id: str):
        try:
            if self.client:
                self.client.expire(self._key(session_id), self.ttl)

        except Exception as e:
            print(f"[SessionStore] refresh error: {e}")
