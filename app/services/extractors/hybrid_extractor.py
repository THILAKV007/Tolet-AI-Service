from services.llm.llm_client import LLMClient


EXTRACTOR_SYSTEM_PROMPT = """
You are a filter extractor for Tolet.ai — a rental property platform in India.

Extract rental search filters from the user's message and conversation context.

Return ONLY a valid JSON object with these exact keys:
{
  "location": "single specific area or locality name as string, or null",
  "location_expand": ["list", "of", "area", "names"] or null,
  "bhk": integer (1, 2, 3, 4) or null,
  "max_price": integer monthly rent in rupees or null,
  "furnished": "fully" or "semi" or "unfurnished" or null,
  "near_metro": true or false or null,
  "tenant_type": "bachelor" or "family" or null,
  "owner_type": "owner" or "broker" or null,
  "property_type": "residential" or "commercial" or "paid_guest" or null
}

PROPERTY TYPE RULES — READ THE USER'S MOTIVE, NOT JUST KEYWORDS:
- Figure out what the property is FOR, from the whole sentence, not a single word.
- COMMERCIAL: user wants a place to run a business, not to live in. Signals:
  "shop", "shop rental", "my new shop", "office", "office space", "workspace",
  "co-working", "coworking", "godown", "warehouse", "showroom", "retail space",
  "commercial space", "for my business/store/clinic".
- PAID_GUEST: user wants a PG/hostel-style stay for themselves. Signals: "pg",
  "hostel", "paying guest", "bachelor room", or the user identifies as a
  "college student" / "school student" and asks about a place to STAY.
  IMPORTANT: if the user says "hostel", still return property_type: "paid_guest"
  (never "residential") — that is the correct DB category for that need.
- RESIDENTIAL: user clearly wants a home to live in: "flat", "apartment", "house",
  "villa", "bhk", "family", or a student who explicitly says "apartment"/"flat"
  WITHOUT mentioning pg/hostel (don't force paid_guest onto every student — only
  when they ask to "stay" generically or mention pg/hostel).
- NEVER mix categories. A commercial request must never carry residential or
  paid_guest signals, and vice versa.
- If the message has NO type signal at all and no property_type was set in a
  previous turn, return property_type: null — do not guess "residential" by
  default. Only infer residential when there IS a positive residential signal
  (bhk, flat, apartment, house, family, villa), OR carry forward a type already
  established earlier in the conversation if the topic hasn't changed.
- If the user explicitly switches type mid-conversation (e.g. "actually I need
  a shop instead") — override to the new type immediately.

LOCATION RULES:
- If user mentions a specific area or locality (Avadi, Velachery, Ambattur etc.)
  → set location: "that area name", location_expand: null
- If user mentions a CITY like Chennai, Bangalore, Hyderabad, Pune, Mumbai, Noida etc.
  → set location: "<the city name as given>", location_expand: null
  Do NOT try to guess or enumerate the city's neighborhoods/localities yourself —
  the app already matches this city name against every property's locality,
  city, AND state fields, so a plain city name safely finds every listing in
  that city regardless of which specific neighborhood it's in. Inventing a
  partial neighborhood list here would hide real listings in neighborhoods you
  didn't think to include.
- If user mentions a STATE like Tamil Nadu, Karnataka, Maharashtra, Uttar Pradesh etc.
  → set location: null, location_expand: [top 12 cities/localities of that state only]
  IMPORTANT: Keep the list to EXACTLY 12 items maximum — never exceed this or the response will be truncated and crash.
- If user asks "what do you have", "list all", "show everything", "current properties"
  with NO location mentioned → set location: null, location_expand: null

GENERAL RULES:
- If user says "show others", "list more", "what else" with NO new location — return previous filters unchanged
- If user explicitly mentions a NEW location or area — ALWAYS override previous location with the new one
- If user says "any", "anything", "all", "whatever is available" — open search.
  Set bhk, max_price, furnished, near_metro, tenant_type all to null. Keep location if mentioned.
- If user says "cheaper" / "less budget" — lower max_price from previous context by 20-30%
- If user says "furnished only" → furnished: "fully"
- If user says "near metro" → near_metro: true
- If user says "bachelors" / "bachelor friendly" → tenant_type: "bachelor"
- If user says "family" → tenant_type: "family"
- If user says "direct owner", "no broker", "without broker", "owner only" → owner_type: "owner"
- If user says "broker", "through broker", "broker properties", "agent listings" → owner_type: "broker"
- Understand Indian price expressions: "10k" = 10000, "15k" = 15000, "1 lakh" = 100000
- Understand BHK expressions: "2 bedroom" = 2, "single room" = 1, "studio" = 1, "3 room" = 3
- NEVER carry forward filters the user did not ask for in an open search
- Return null for any field not mentioned or inferable
- Return ONLY the JSON. No explanation. No markdown.
"""


class HybridExtractor:

    def __init__(self):
        self.llm = LLMClient()

    def extract(
        self,
        query: str,
        conversation_history: list = None,
        previous_filters: dict = None
    ) -> dict:

        history_text = self._format_history(conversation_history)
        prev_text    = self._format_filters(previous_filters)

        user_prompt = f"""
Conversation so far:
{history_text}

Previous filters applied:
{prev_text}

Latest user message: "{query}"

Extract the rental filters as JSON.
"""

        result = self.llm.chat_json(
            system_prompt=EXTRACTOR_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            max_tokens=1200
        )

        return self._validate(result, previous_filters)

    def _validate(self, extracted: dict, previous_filters: dict = None) -> dict:

        clean = {
            "location":        None,
            "location_expand": None,
            "bhk":             None,
            "max_price":       None,
            "furnished":       None,
            "near_metro":      None,
            "tenant_type":     None,
            "owner_type":      None,
            "property_type":   None
        }

        prev = previous_filters or {}

        if isinstance(extracted.get("location"), str):
            loc = extracted["location"].strip()
            # Normalize "K K Nagar" → "KK Nagar", "T Nagar" stays "T Nagar"
            # Rule: if a single letter is isolated between spaces, merge with next word
            import re as _re
            loc = _re.sub(r"(?<!\w)([A-Za-z])\s+([A-Za-z])\s+", r"\1\2 ", loc)
            loc = _re.sub(r"\.+", "", loc).strip()  # remove stray dots
            clean["location"] = loc.title()

        if isinstance(extracted.get("location_expand"), list):
            expanded = [
                a.strip().title()
                for a in extracted["location_expand"]
                if isinstance(a, str) and a.strip()
            ][:12]  # hard cap — prevents token overflow & JSON truncation crash
            if expanded:
                clean["location_expand"] = expanded
                clean["location"]        = None  # never set both

        if isinstance(extracted.get("bhk"), int) and 1 <= extracted["bhk"] <= 10:
            clean["bhk"] = extracted["bhk"]

        if isinstance(extracted.get("max_price"), (int, float)) and extracted["max_price"] > 0:
            clean["max_price"] = int(extracted["max_price"])

        if extracted.get("furnished") in ("fully", "semi", "unfurnished"):
            clean["furnished"] = extracted["furnished"]

        if isinstance(extracted.get("near_metro"), bool):
            clean["near_metro"] = extracted["near_metro"]

        if extracted.get("tenant_type") in ("bachelor", "family"):
            clean["tenant_type"] = extracted["tenant_type"]

        if extracted.get("owner_type") in ("owner", "broker"):
            clean["owner_type"] = extracted["owner_type"]

        # FIX: property_db_service.py only isolates on the exact strings
        # "residential" / "commercial" / "paid_guest" — the old check here
        # required an EXACT match against that tuple, so if the LLM ever
        # returned something semantically correct but not byte-identical
        # (e.g. "PG", "Paid Guest", "paid guest", trailing whitespace,
        # different case), the whole property_type filter silently vanished
        # with no log line, no error, nothing — just a filter that quietly
        # stopped applying. Normalize first, then map common synonyms, and
        # log the rare case where nothing recognizable came back at all.
        raw_property_type = extracted.get("property_type")
        if isinstance(raw_property_type, str):
            normalized_type = raw_property_type.strip().lower().replace(" ", "_")
            property_type_synonyms = {
                "residential":  "residential",
                "commercial":   "commercial",
                "paid_guest":   "paid_guest",
                "pg":           "paid_guest",
                "paying_guest": "paid_guest",
                "hostel":       "paid_guest",
            }
            mapped_type = property_type_synonyms.get(normalized_type)
            if mapped_type:
                clean["property_type"] = mapped_type
            elif normalized_type:
                print(
                    f"[HybridExtractor] Unrecognized property_type from LLM: "
                    f"'{raw_property_type}' — filter not applied."
                )

        location_just_set = clean["location"] is not None
        expand_just_set   = clean["location_expand"] is not None

        for key in clean:
            if clean[key] is None and prev.get(key) is not None:
                if key == "location" and expand_just_set:
                    continue
                if key == "location_expand" and location_just_set:
                    continue
                clean[key] = prev[key]

        return clean

    def _format_history(self, history: list) -> str:

        if not history:
            return "No prior conversation."

        lines = []
        for msg in history[-8:]:
            role    = "User" if msg.get("role") == "user" else "Assistant"
            content = msg.get("content", "")[:250]
            lines.append(f"{role}: {content}")

        return "\n".join(lines)

    def _format_filters(self, filters: dict) -> str:

        if not filters:
            return "None"

        parts = []
        for key, val in filters.items():
            if val is not None:
                parts.append(f"{key}: {val}")

        return ", ".join(parts) if parts else "None"