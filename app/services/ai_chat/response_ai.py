from services.llm.llm_client import LLMClient
from services.llm.prompts import RESPONSE_SYSTEM_PROMPT
from services.ai_chat.history_builder import HistoryBuilder

import re


DETAIL_REQUEST_SIGNALS = [
    "yeah", "yes", "sure", "of course",
    "ofcourse", "okay", "ok", "go ahead",
    "tell me more", "more details", "details",
    "explain", "describe", "what else",
    "sounds good", "interesting", "nice",
    "cool", "great", "please", "yep", "yup"
]

# ── Grounding-check regexes ───────────────────────────────────────────────────
# Prices the model mentions, e.g. "₹22,000", "Rs 10000", "22,000/month"
_PRICE_PATTERN = re.compile(r'(?:₹|rs\.?\s?)\s?([\d][\d,]*)', re.IGNORECASE)

# Stray meta-commentary the model sometimes leaks about its own instructions —
# e.g. "(Note: I'm not actually showing you results for X as per the rule...)"
_META_NOTE_PATTERN = re.compile(
    r'\(\s*note\s*:.*?\)|\[\s*note\s*:.*?\]|^\s*note\s*:.*$',
    re.IGNORECASE | re.DOTALL | re.MULTILINE
)


class ResponseAI:

    def __init__(self):
        self.llm     = LLMClient()
        self.builder = HistoryBuilder()

    # =========================================================================
    # Meta-note stripper — safety net in case the LLM leaks internal
    # reasoning/instructions into the user-facing reply despite the prompt
    # telling it not to.
    # =========================================================================
    def _strip_meta_notes(self, text: str) -> str:
        if not text:
            return text
        cleaned = _META_NOTE_PATTERN.sub("", text)
        cleaned = re.sub(r'\n{3,}', '\n\n', cleaned).strip()
        return cleaned or text  # never return empty — fall back to original

    # =========================================================================
    # Grounding check — makes sure any price the model quotes in its reply
    # actually belongs to one of the real properties it was given. Catches
    # hallucinated listings (e.g. inventing a ₹22,000 PG when the only real
    # match was ₹10,000).
    # =========================================================================
    def _is_grounded(self, text: str, properties: list) -> bool:
        mentioned_prices = {
            int(m.replace(",", "")) for m in _PRICE_PATTERN.findall(text or "")
        }
        if not mentioned_prices:
            return True  # nothing to check against

        valid_prices = {
            p.get("price") for p in (properties or [])
            if isinstance(p.get("price"), (int, float)) and p.get("price")
        }
        # If the model quoted at least one price and NONE of them match a
        # real property's price, the reply is ungrounded (hallucinated).
        return any(price in valid_prices for price in mentioned_prices)

    # =========================================================================
    # Deterministic fallback — used only when the LLM's reply fails the
    # grounding check. Built directly from real property data so it can
    # never contain a hallucinated price or location.
    # =========================================================================
    def _build_fallback_response(self, properties: list) -> str:
        if not properties:
            return (
                "I couldn't find any listings matching that search right now. "
                "Feel free to try a different area, budget, or property type — "
                "I'm happy to take another look."
            )

        lines = ["Here's what I found for you, straight from our listings:"]
        for p in properties[:3]:
            loc     = p.get("location") or p.get("locality") or p.get("city") or "an area nearby"
            price   = p.get("price")
            ptype   = (p.get("property_type") or "").replace("_", " ")
            posted  = "direct owner" if p.get("posted_by") == "direct_owner" else "broker-listed"
            price_str = f"₹{price:,}/month" if price else "price on request"
            lines.append(f"- {ptype.title() or 'Property'} in {loc} — {price_str} ({posted})")
        lines.append("Want more details on any of these, or should I narrow it down further?")
        return "\n".join(lines)


    def generate(
        self,
        query: str,
        filters: dict,
        properties: list,
        intent: str,
        session_messages: list = None,
        geo_original_location: str = None,
        geo_expanded_areas: list = None,
        owner_type_counts: dict = None
    ) -> str:

        try:

            query_lower   = query.strip().lower()
            is_detail_ask = (
                intent == "property_discussion" and
                any(signal in query_lower for signal in DETAIL_REQUEST_SIGNALS)
            )
            max_tokens = 800 if is_detail_ask else 600

            current_user_message = self.builder.build_user_message_with_context(
                query=query,
                filters=filters,
                properties=properties,
                intent=intent,
                geo_original_location=geo_original_location,
                geo_expanded_areas=geo_expanded_areas,
                owner_type_counts=owner_type_counts
            )

            messages = self.builder.build(
                session_messages=session_messages or [],
                system_prompt=RESPONSE_SYSTEM_PROMPT
            )

            messages.append({
                "role": "user",
                "content": current_user_message
            })


            messages = self.builder.trim_to_budget(messages, max_messages=22)


            ai_response = self.llm.chat_with_history(
                messages=messages,
                temperature=0.5,   # was 0.9 — high temperature was making the
                                    # model "get creative" with property details
                                    # instead of sticking to the real data.
                max_tokens=max_tokens
            )

            ai_response = self._strip_meta_notes(ai_response)

            if not self._is_grounded(ai_response, properties):
                print(
                    "[ResponseAI] Ungrounded response detected "
                    f"(quoted price not in real property list) — "
                    f"falling back to deterministic template. Raw: {ai_response!r}"
                )
                ai_response = self._build_fallback_response(properties)

            return ai_response

        except Exception as e:
            print(f"[ResponseAI] generate error: {e}")
            return (
                "Something tripped up on my end — "
                "mind rephrasing that?"
            )


    def generate_clarification(
        self,
        query: str,
        filters: dict,
        session_messages: list = None
    ) -> str:

        try:
            system_prompt = """
You are Tolet AI. The user gave only a partial rental search (e.g. just a
BHK, a property type like PG/commercial, or a preference) with no location
and no budget yet.

Ask ONE short, warm, natural follow-up question to narrow the search down.
Ask for the location first. If a location is already known in the filters
but the budget is not, ask for the budget instead.

Rules:
- 2-3 lines maximum, conversational, like a helpful human agent.
- Do NOT list, invent, or reference any property details — none have been
  fetched yet.
- Do NOT expose filter names or JSON.
- Vary your phrasing every time — never robotic or repetitive.
"""
            messages = [{"role": "system", "content": system_prompt}]

            if session_messages:
                for msg in session_messages[-6:]:
                    if msg.get("role") in ("user", "assistant"):
                        messages.append(msg)

            known = ", ".join(
                f"{k}: {v}" for k, v in filters.items()
                if v and not str(k).startswith("_")
            ) or "nothing specific yet"

            messages.append({
                "role": "user",
                "content": (
                    f'User said: "{query}"\n'
                    f"What we know so far: {known}\n\n"
                    f"Ask a natural clarifying question to get their location "
                    f"(and budget if location is already known)."
                )
            })

            return self.llm.chat_with_history(
                messages=messages,
                temperature=0.9,
                max_tokens=150
            )

        except Exception as e:
            print(f"[ResponseAI] generate_clarification error: {e}")
            return (
                "Got it! Which area are you looking in, and do you have "
                "a budget in mind?"
            )


    def generate_knowledge_response(
        self,
        query: str,
        knowledge: str,
        session_messages: list = None
    ) -> str:

        try:
            system_prompt = """
You are Tolet AI — a conversational rental property assistant for India.
Answer ONLY using the provided Tolet AI knowledge context.
Be warm, natural, and vary your phrasing every time.
Minimum 3 lines. Never robotic or repetitive.
"""
            messages = [{"role": "system", "content": system_prompt}]

            if session_messages:
                for msg in session_messages[-6:]:
                    if msg.get("role") in ("user", "assistant"):
                        messages.append(msg)

            messages.append({
                "role": "user",
                "content": (
                    f"User Question: {query}\n"
                    f"Tolet AI Knowledge Context: {knowledge}\n\n"
                    f"Answer conversationally using only the knowledge above."
                )
            })

            return self.llm.chat_with_history(
                messages=messages,
                temperature=0.9,
                max_tokens=500
            )

        except Exception:
            return (
                "Tolet AI helps you find rental homes across India — "
                "just tell me what you're looking for!"
            )