import os
import json
import time
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

        # Active search "context" (last filters/properties) is intentionally
        # much shorter-lived than the overall chat history. Without this,
        # filters/properties from several minutes ago could still silently
        # apply to a completely new train of thought — the "AI cache should
        # forget" mismatch. This does NOT wipe the conversation transcript,
        # only the filters/properties used for refilter/discussion logic.
        self.context_ttl = int(os.getenv("SESSION_CONTEXT_TTL_SECONDS", 120))

        self.client   = None
        self._fallback = {}   # ← always initialised — fixes AttributeError when
                              #   redis package is missing and _connect() is never called
        self._context_fallback = {}  # in-memory fallback: {session_id: {"data": {...}, "ts": epoch}}

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

    def _context_key(self, session_id: str) -> str:
        return f"tolet:context:{session_id}"

    # ===================================
    # Short-lived active search context
    # (filters + last properties shown).
    # Expires independently of, and much
    # faster than, the chat history TTL.
    # ===================================
    def get_context(self, session_id: str) -> dict:
        try:
            if self.client:
                raw = self.client.get(self._context_key(session_id))
                if raw:
                    return json.loads(raw)
                return {"filters": {}, "properties": []}

            entry = self._context_fallback.get(session_id)
            if not entry:
                return {"filters": {}, "properties": []}
            if (time.time() - entry["ts"]) > self.context_ttl:
                # Expired — drop it so nothing stale leaks through
                self._context_fallback.pop(session_id, None)
                return {"filters": {}, "properties": []}
            return entry["data"]

        except Exception as e:
            print(f"[SessionStore] get_context error: {e}")
            return {"filters": {}, "properties": []}

    def set_context(self, session_id: str, filters: dict, properties: list):
        try:
            data = {"filters": filters or {}, "properties": properties or []}
            if self.client:
                self.client.setex(
                    self._context_key(session_id),
                    self.context_ttl,
                    json.dumps(data, default=str)
                )
            else:
                self._context_fallback[session_id] = {"data": data, "ts": time.time()}
        except Exception as e:
            print(f"[SessionStore] set_context error: {e}")

    def clear(self, session_id: str):
        """
        Explicit 'forget the above conversation' handler. Wipes both the
        full session (history/messages/filters/properties) and the
        short-lived active-context key, so nothing carries forward.
        """
        try:
            if self.client:
                self.client.delete(self._key(session_id))
                self.client.delete(self._context_key(session_id))
            else:
                self._fallback.pop(session_id, None)
                self._context_fallback.pop(session_id, None)
        except Exception as e:
            print(f"[SessionStore] clear error: {e}")

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

        # Mirror the active filters/properties into the short-TTL context
        # store too, so refilter/discussion logic naturally forgets them
        # after context_ttl seconds even though the full transcript in
        # `session` sticks around for the longer session TTL.
        if turn.get("properties") or turn.get("filters"):
            self.set_context(
                session_id,
                turn.get("filters") or session.get("filters", {}),
                turn.get("properties") or session.get("properties", []),
            )

    def get_latest_with_properties(self, session_id: str) -> dict:
        session = self.get(session_id)
        history = session.get("history", [])

        for turn in reversed(history):
            if turn.get("properties"):
                return turn

        return history[-1] if history else None

    def get_properties(self, session_id: str) -> list:
        return self.get_context(session_id).get("properties", [])

    def get_filters(self, session_id: str) -> dict:
        return self.get_context(session_id).get("filters", {})

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