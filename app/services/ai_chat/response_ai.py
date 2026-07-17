from services.llm.llm_client import LLMClient
from services.llm.prompts import RESPONSE_SYSTEM_PROMPT
from services.ai_chat.history_builder import HistoryBuilder
from services.geo.spell_corrector import _CHENNAI_REFERENCE_LOCALITIES, _CITY_STATE_REFERENCE

import re


def _language_instruction(language: str) -> str:
    """
    Turns the LanguageDetector output ("tamil" / "tanglish" / "english")
    into an explicit instruction appended to the system/user prompt.
    Previously LanguageDetector was never actually wired into the
    response pipeline, so the model was never told what language to
    reply in and defaulted to English regardless of the user's query.
    """
    if language == "tamil":
        return (
            "\n\nLANGUAGE: The user wrote in Tamil. Respond ENTIRELY in Tamil "
            "script (தமிழ்). Do not mix in English sentences — property names, "
            "numbers, and area names may stay as-is, but every sentence around "
            "them must be in Tamil."
        )
    if language == "tanglish":
        return (
            "\n\nLANGUAGE: The user wrote in Tanglish (Tamil words typed in "
            "Roman/English script, mixed with English). Respond ENTIRELY in "
            "Tanglish, matching that same casual Roman-script Tamil-English "
            "mix — do not switch to pure English and do not switch to Tamil "
            "script."
        )
    return (
        "\n\nLANGUAGE: The user wrote in English. Respond ENTIRELY in English."
    )


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

# Contradictory "found nothing" hedge sentences that sometimes appear in the
# SAME reply as real, listed properties — e.g. "I couldn't find any listings
# that exactly match your budget and preferences, but here's what I found:"
# followed immediately by 3 real listings. Confirmed in production. Splits
# on sentence boundaries and drops only the offending sentence(s) rather
# than the whole response, since everything else in the reply is grounded.
_NO_MATCH_HEDGE_PATTERN = re.compile(
    r'[^.!?\n]*\b(couldn\'?t find|could not find|no (exact )?match(es)?|'
    r'nothing (exactly )?match(es|ed)?|didn\'?t find any)\b[^.!?\n]*[.!?]',
    re.IGNORECASE
)

# ── Location grounding ────────────────────────────────────────────────────────
# BUG FIX: _is_grounded() previously validated ONLY quoted prices against real
# data — never locations. That's exactly how the original bug slipped through:
# the LLM said "In Ambattur, there are 2 direct owner properties available"
# while the actual results were in Kochi and Chennai, and since no price was
# hallucinated (or none was quoted at all), the grounding check saw nothing
# wrong. We reuse spell_corrector.py's existing pan-India locality/city
# reference lists (rather than maintaining a 4th separate one) to detect any
# *known, real* place name the model mentions, so it can be checked against
# what was actually searched/returned this turn.
_KNOWN_LOCATIONS = sorted(
    set(_CHENNAI_REFERENCE_LOCALITIES) | set(_CITY_STATE_REFERENCE),
    key=len,
    reverse=True,  # longest first, so "anna nagar west" matches before "anna nagar"
)
_LOCATION_PATTERN = re.compile(
    r'\b(' + '|'.join(re.escape(loc) for loc in _KNOWN_LOCATIONS) + r')\b',
    re.IGNORECASE
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
    # No-match-hedge stripper — safety net for the model contradicting
    # itself: claiming "couldn't find any listings that match" in the same
    # reply where it then lists real properties. Only runs when properties
    # actually exist; a true zero-results reply is left untouched.
    # =========================================================================
    def _strip_no_match_hedge(self, text: str, properties: list) -> str:
        if not text or not properties:
            return text
        cleaned = _NO_MATCH_HEDGE_PATTERN.sub("", text)
        cleaned = re.sub(r'[ \t]{2,}', ' ', cleaned)
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
    # Collect every location name that's legitimately allowed to appear in
    # this turn's reply: the actual returned properties' localities/cities,
    # what the user searched for (even with zero results — "no listings in
    # Bangalore" is fine), and any geo-expansion / owner-type-summary area.
    # Synthetic sentinels like "multiple locations"/"this area" are excluded
    # since they're placeholders, not real place names the model could echo.
    # =========================================================================
    def _collect_allowed_locations(
        self,
        properties: list,
        filters: dict,
        geo_original_location: str = None,
        geo_expanded_areas: list = None,
        owner_type_area: str = None
    ) -> set:
        allowed = set()

        for p in (properties or []):
            for key in ("locality", "location", "city"):
                v = p.get(key)
                if v:
                    allowed.add(str(v).strip().lower())

        if filters:
            if filters.get("location"):
                allowed.add(str(filters["location"]).strip().lower())
            for v in (filters.get("location_expand") or []):
                if v:
                    allowed.add(str(v).strip().lower())

        if geo_original_location:
            allowed.add(str(geo_original_location).strip().lower())

        for area in (geo_expanded_areas or []):
            name = area.get("area") if isinstance(area, dict) else area
            if name:
                allowed.add(str(name).strip().lower())

        if owner_type_area and owner_type_area.strip().lower() not in ("multiple locations", "this area"):
            allowed.add(owner_type_area.strip().lower())

        return allowed

    # =========================================================================
    # Location grounding check — flags a reply that names a real, known place
    # (from the pan-India reference list) which isn't backed by anything we
    # actually searched or returned this turn. Uses substring containment
    # both ways so "anna nagar" matches an allowed "anna nagar west" and
    # vice versa. Deliberately permissive (only checks names drawn from the
    # known-locations list) rather than trying to parse arbitrary text, to
    # avoid false positives on ordinary conversational sentences.
    # =========================================================================
    def _is_location_grounded(self, text: str, allowed_locations: set) -> bool:
        mentioned = {m.lower() for m in _LOCATION_PATTERN.findall(text or "")}
        if not mentioned:
            return True  # nothing to check against

        for loc in mentioned:
            if any(loc == a or loc in a or a in loc for a in allowed_locations):
                continue
            return False  # named a real place with no grounding this turn

        return True

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
        owner_type_counts: dict = None,
        owner_type_area: str = None,
        language: str = "english"
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
                owner_type_counts=owner_type_counts,
                owner_type_area=owner_type_area
            )

            messages = self.builder.build(
                session_messages=session_messages or [],
                system_prompt=RESPONSE_SYSTEM_PROMPT + _language_instruction(language)
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
            ai_response = self._strip_no_match_hedge(ai_response, properties)

            allowed_locations = self._collect_allowed_locations(
                properties=properties,
                filters=filters,
                geo_original_location=geo_original_location,
                geo_expanded_areas=geo_expanded_areas,
                owner_type_area=owner_type_area
            )
            price_grounded    = self._is_grounded(ai_response, properties)
            location_grounded = self._is_location_grounded(ai_response, allowed_locations)

            if not price_grounded or not location_grounded:
                print(
                    "[ResponseAI] Ungrounded response detected "
                    f"(price_grounded={price_grounded}, location_grounded={location_grounded}) — "
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
        session_messages: list = None,
        language: str = "english"
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
""" + _language_instruction(language)
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
        session_messages: list = None,
        language: str = "english"
    ) -> str:

        try:
            system_prompt = """
You are Tolet AI — a conversational rental property assistant for India.
Answer ONLY using the provided Tolet AI knowledge context.
Be warm, natural, and vary your phrasing every time.
Minimum 3 lines. Never robotic or repetitive.
""" + _language_instruction(language)
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