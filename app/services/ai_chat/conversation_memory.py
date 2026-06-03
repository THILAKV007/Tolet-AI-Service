class ConversationMemory:

    def __init__(self):
        self.memory_store = {}


    def save_memory(self, session_id: str, data: dict):

        if session_id not in self.memory_store:
            self.memory_store[session_id] = {
                "filters": {},
                "properties": [],
                "history": []
            }

        self.memory_store[session_id]["filters"] = data.get("filters", {})


        new_properties = data.get("properties", [])
        if new_properties:
            self.memory_store[session_id]["properties"] = new_properties

        self.memory_store[session_id]["history"].append({
            "query":      data.get("query", ""),
            "filters":    data.get("filters", {}),
            "properties": data.get("properties", []),
            "intent":     data.get("intent", "")
        })

    def get_memory(self, session_id: str):

        return self.memory_store.get(session_id, {
            "filters": {},
            "properties": [],
            "history": []
        })


    def add_message(self, session_id: str, role: str, message: str):

        if session_id not in self.memory_store:
            self.memory_store[session_id] = {
                "filters": {},
                "properties": [],
                "history": []
            }

        self.memory_store[session_id]["history"].append({
            "role":    role,
            "message": message
        })


    def get_latest(self, session_id: str):

        history = self.memory_store.get(session_id, {}).get("history", [])

        if not history:
            return None

        # Walk backwards: prefer a turn with properties
        for turn in reversed(history):
            if turn.get("properties"):
                return turn

        # Fallback: return the most recent turn even if empty
        return history[-1]

    def get_recent(self, session_id: str, limit: int = 5):

        history = self.memory_store.get(session_id, {}).get("history", []  )

        return history[-limit:]

    def is_refilter_query(self, query: str) -> bool:

        refilter_keywords = [
            "which one", "which ones",
            "located on", "located in",
            "only", "show me", "filter",
            "below", "under", "above",
            "based on above", "from above",
            "from those", "of those",
            "in avadi", "in velachery",
            "in ambattur", "in chennai",
        ]

        return any(
            kw in query.lower()
            for kw in refilter_keywords
        )

 
    def merge_filters(
        self,
        old_filters: dict,
        new_filters: dict
    ) -> dict:

        merged = old_filters.copy()

        for key, value in new_filters.items():
            if value is not None:
                merged[key] = value

        return merged