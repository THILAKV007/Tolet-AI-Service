from services.llm.llm_client import LLMClient

# ===================================
# Intent Detector (LLM-Based)
# Zero keywords. Zero regex.
# The LLM understands meaning from
# the full conversation context.
#
# Handles naturally:
#   - "can u list others"
#   - "show me cheaper ones"
#   - "அந்த ஒன்னு" (Tamil)
#   - "jo pehle wala tha" (Hindi)
#   - "what else do you have"
#   - Any phrasing, any language
# ===================================

INTENT_SYSTEM_PROMPT = """
You are an intent classifier for Tolet.ai — a rental property platform in India.

Your job: read the conversation history and the latest user message, then return EXACTLY ONE intent word from this list:

property_search     — user wants to find/see rental properties
property_discussion — user is asking about properties already shown (details, more info, which one, that one)
refilter            — user wants to narrow/change results (cheaper, furnished only, near metro, different area)
recommendation      — user wants the best/top suggestion
greeting            — hi, hello, good morning etc.
contact_request     — wants owner contact, phone number, visit, schedule
real_estate_advice  — general rental knowledge (agreements, rights, tips, area advice)
off_topic           — genuinely unrelated to rental properties in India

RULES:
- IMPORTANT DISAMBIGUATION: "direct owner", "no broker", "without broker",
  "owner only", "straight owner", "one to one", "no middleman" etc. are a
  SEARCH PREFERENCE (the user wants listings posted by owners, not brokers)
  → this is property_search (or refilter if there's prior search context),
  NEVER contact_request. Only classify as contact_request when the user is
  asking for a SPECIFIC property's contact details that were already shown —
  phrases like "owner's number", "phone number", "call the owner", "contact
  him/her", "can I visit", "schedule a visit" — AND there is prior
  conversation context with properties already shown. A message like "direct
  owner" with no prior properties in context can never be contact_request.
- If the user mentions a LOCATION or AREA explicitly (e.g. "from kk nagar", "in velachery", "anna nagar property") → ALWAYS property_search, even if there is prior context.
- If the user mentions "want property", "need flat", "looking for", "find me", "show me properties" → ALWAYS property_search.
- If the user has prior conversation context (properties were shown), short vague messages like "others", "more", "next", "list them", "show more" = property_discussion
- "show me cheaper" / "below 10k" / "only furnished" after a search = refilter
- "which is best" / "suggest one" = recommendation
- When in doubt and there is prior context, prefer property_discussion over off_topic
- Short acknowledgements like "yeah", "ok", "alright", "fine", "noted", "sure", "okay"
  AFTER a property discussion = property_discussion, NOT property_search or refilter
- Return ONLY the intent word. No explanation. No punctuation. No quotes.
"""


class IntentDetector:

    def __init__(self):
        self.llm = LLMClient()

    # ===================================
    # Detect Intent
    # conversation_history = list of
    # {"role": "user"/"assistant", "content": "..."}
    # ===================================
    def detect(
        self,
        query: str,
        conversation_history: list = None
    ) -> str:

        history_text = self._format_history(conversation_history)

        user_prompt = f"""
Conversation so far:
{history_text}

Latest user message: "{query}"

What is the intent?
"""

        intent = self.llm.classify(
            system_prompt=INTENT_SYSTEM_PROMPT,
            user_prompt=user_prompt
        )

        # ===================================
        # Validate — fallback to property_search
        # if LLM returns something unexpected
        # ===================================
        valid_intents = {
            "property_search",
            "property_discussion",
            "refilter",
            "recommendation",
            "greeting",
            "contact_request",
            "real_estate_advice",
            "off_topic"
        }

        intent = intent.strip().lower()

        if intent not in valid_intents:
            print(f"[IntentDetector] Unknown intent '{intent}', defaulting to property_search")
            return "property_search"

        return intent

    # ===================================
    # Format history for prompt injection
    # ===================================
    def _format_history(self, history: list) -> str:

        if not history:
            return "No prior conversation."

        lines = []
        for msg in history[-10:]:  # last 10 turns
            role = "User" if msg.get("role") == "user" else "Assistant"
            content = msg.get("content", "")[:300]  # truncate long messages
            lines.append(f"{role}: {content}")

        return "\n".join(lines)