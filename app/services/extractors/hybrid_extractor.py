from services.llm.llm_client import LLMClient
from pydantic import BaseModel, field_validator
from typing import Optional, List
import re as _re


EXTRACTOR_SYSTEM_PROMPT = """
You are a filter extractor for Tolet.ai — a rental property platform in India.

Extract rental search filters from the user's message and conversation context.

Return ONLY a valid JSON object with these exact keys:
{
  "location": "single specific area or locality name as string, or null",
  "location_expand": ["list", "of", "area", "names"] or null,
  "bhk": integer (1, 2, 3, 4) or null,
  "min_price": integer minimum monthly rent in rupees (lower bound) or null,
  "max_price": integer maximum monthly rent in rupees (upper bound) or null,
  "min_sqft": integer minimum square footage (lower bound) or null,
  "max_sqft": integer maximum square footage (upper bound) or null,
  "furnished": "fully" or "semi" or "unfurnished" or null,
  "near_metro": true or false or null,
  "tenant_type": "bachelor" or "family" or null,
  "owner_type": "owner" or "broker" or null,
  "property_type": "residential" or "commercial" or "paid_guest" or "any" or null,
  "rent_type": "monthly" or "lease" or null,
  "lease_months": integer number of months (e.g. 6, 11, 24) or null
}

LEASE RULES:
- If the user says "lease property", "lease", "on lease", "fixed term", "long term lease" →
  rent_type: "lease".
- If the user gives a specific duration ("11 month lease", "2 year lease", "24 months") →
  set lease_months to that number of months (convert years to months, e.g. "2 year" → 24)
  AND set rent_type: "lease".
- If the user says "monthly rent", "month to month", "monthly" → rent_type: "monthly".
- If lease/rent-type isn't mentioned at all, return both as null — do NOT default to
  "monthly", since most listings are monthly and forcing this filter would wrongly
  exclude lease listings from generic searches.

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
- DEFAULT TO RESIDENTIAL: Most users on this platform are searching for a
  home to live in. If the message has NO type signal at all (no shop/office/
  commercial signal, no pg/hostel signal) and no property_type was set in a
  previous turn, return property_type: "residential" — do NOT return null.
  Only return "commercial" or "paid_guest" when the user gives an actual
  positive signal for one of those (see rules above). Carry forward a type
  already established earlier in the conversation if the topic hasn't changed.
- If the user explicitly switches type mid-conversation (e.g. "actually I need
  a shop instead") — override to the new type immediately.
- GENERIC PROPERTY WORDS — don't let a stale type silently hide real matches:
  If the message uses a GENERIC word for what they want — "property",
  "properties", "place", "option", "listing" — with NO specific type signal
  anywhere in that same message (no pg/hostel/shop/office/flat/bhk/house/etc.),
  this means the user is deliberately broadening the search, not continuing
  the narrower one. Return property_type: "any" (do NOT carry forward or
  default to whatever type was established earlier in the conversation).
  Example: earlier turns were about a PG, then the user says "can I get the
  property from Mumbai" — that's a generic word with no PG signal, so
  property_type: "any", even though "paid_guest" was set before.
  Only keep the earlier type when the message has NO property-related word at
  all (e.g. just a location name or a bare filter like "under 10k") — in that
  case the established type context still applies.

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
  Set bhk, min_price, max_price, min_sqft, max_sqft, furnished, near_metro,
  tenant_type all to null, AND property_type: "any" (don't leave a stale type
  from earlier in the conversation scoping an "anything available" request).
  Keep location if mentioned.
- If user says "cheaper" / "less budget" — lower max_price from previous context by 20-30%
- PRICE RANGE RULES — read BOTH numbers when the user gives a range, don't just take one:
  "between X and Y" / "X to Y" / "X-Y" (as a budget/rent/price) → min_price: lower number,
    max_price: higher number (in rupees; "5k" = 5000). Both must be set together — never
    drop one end of a range the user actually gave.
  "under X" / "below X" / "max X" / "budget of X" (single number, no range) → max_price: X,
    min_price: null (unless a min_price was already established earlier and the user isn't
    changing it — see GENERAL RULES on carrying forward filters).
  "above X" / "at least X" / "more than X" / "min budget X" (single number) → min_price: X
- SQUARE FOOTAGE RULES — read the qualifier word, not just the number:
  "above X sqft" / "at least X sqft" / "more than X sqft" / "min X sqft" / "minimum X sqft"
    → min_sqft: X, max_sqft: null
  "under X sqft" / "below X sqft" / "max X sqft" / "maximum X sqft" / "less than X sqft"
    → max_sqft: X, min_sqft: null
  A bare "X sqft" / "X square feet" with NO qualifier word → min_sqft: X (treat a bare
    size mention as "at least this big" — this is the reading that correctly excludes a
    smaller listing, e.g. a 300 sqft space, when the user just said "800 square feet").
  Treat "sqft", "sq ft", "sq.ft", "square feet", and "square foot" as the same unit.
- If user says "furnished only" → furnished: "fully"
- If user says "near metro" → near_metro: true
- If user says "bachelors" / "bachelor friendly" → tenant_type: "bachelor"
- If user says "family" → tenant_type: "family"
- OWNER_TYPE — READ INTENT, NOT JUST FIXED PHRASES:
  Set owner_type: "owner" whenever the user's message means they want to deal
  with the property owner directly, with no middleman — however they phrase
  it. This includes (but is not limited to): "direct owner", "no broker",
  "without broker", "owner only", "straight owner", "straight from owner",
  "one to one", "one-on-one", "no agent", "without agent", "no middleman",
  "skip the broker", "no commission", "zero brokerage", "brokerage free",
  "talk to the owner directly", "owner directly", "non-broker". Recognize
  the INTENT (owner-direct, zero-commission, no-intermediary) even if the
  exact wording is new or unusual — do not require an exact phrase match.
  Set owner_type: "broker" whenever the user's message means they're fine
  with or specifically want a broker/agent involved: "broker", "through
  broker", "broker properties", "agent listings", "with agent", "brokered".
- Understand Indian price expressions: "10k" = 10000, "15k" = 15000, "1 lakh" = 100000
- Understand BHK expressions: "2 bedroom" = 2, "single room" = 1, "studio" = 1, "3 room" = 3
- NEVER carry forward filters the user did not ask for in an open search
- Return null for any field not mentioned or inferable
- Return ONLY the JSON. No explanation. No markdown.
"""


class SearchFilters(BaseModel):
    """
    Canonical schema for extracted rental search filters. Using a real model
    here (instead of a hand-built dict with scattered isinstance() checks)
    means: the shape is documented in one place, invalid values are coerced
    or rejected consistently, and any other service in the pipeline
    (property_db_service.py, response_ai.py, tests) can import this SAME
    model instead of re-implementing its own notion of "what a filter dict
    looks like" — which is exactly the kind of drift that caused the
    Area-field bug in the response layer.
    """
    location:        Optional[str]  = None
    location_expand: Optional[List[str]] = None
    bhk:             Optional[int]  = None
    min_price:       Optional[int]  = None
    max_price:       Optional[int]  = None
    min_sqft:        Optional[int]  = None
    max_sqft:        Optional[int]  = None
    furnished:       Optional[str]  = None
    near_metro:      Optional[bool] = None
    tenant_type:     Optional[str]  = None
    owner_type:      Optional[str]  = None
    property_type:   Optional[str]  = "residential"
    rent_type:       Optional[str]  = None
    lease_months:    Optional[int]  = None

    @field_validator("location", mode="before")
    @classmethod
    def _clean_location(cls, v):
        if not isinstance(v, str) or not v.strip():
            return None
        loc = v.strip()
        # Merge isolated single letters ("K K Nagar" -> "KK Nagar"). Runs
        # repeatedly so 3+ isolated letters ("T K M Nagar") fully collapse,
        # not just the first pair.
        prev = None
        while prev != loc:
            prev = loc
            loc = _re.sub(r"(?<!\w)([A-Za-z])\s+([A-Za-z])(?=\s|$)", r"\1\2", loc)
        loc = _re.sub(r"\.+", "", loc).strip()
        return loc.title() if loc else None

    @field_validator("location_expand", mode="before")
    @classmethod
    def _clean_location_expand(cls, v):
        if not isinstance(v, list):
            return None
        cleaned = [a.strip().title() for a in v if isinstance(a, str) and a.strip()][:12]
        return cleaned or None

    @field_validator("bhk", mode="before")
    @classmethod
    def _clean_bhk(cls, v):
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            return None
        v = int(v)
        return v if 1 <= v <= 10 else None

    @field_validator("min_price", mode="before")
    @classmethod
    def _clean_min_price(cls, v):
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            return None
        v = int(v)
        return v if v > 0 else None

    @field_validator("max_price", mode="before")
    @classmethod
    def _clean_max_price(cls, v):
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            return None
        v = int(v)
        return v if v > 0 else None

    @field_validator("max_price")
    @classmethod
    def _check_price_order(cls, v, info):
        # Guard against the LLM swapping the two ends of a range (e.g.
        # returning min_price=10000, max_price=5000) — swap them back rather
        # than silently producing an impossible "min > max" filter that
        # would match zero properties.
        min_v = info.data.get("min_price")
        if v is not None and min_v is not None and min_v > v:
            info.data["min_price"], v = v, min_v
        return v

    @field_validator("min_sqft", mode="before")
    @classmethod
    def _clean_min_sqft(cls, v):
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            return None
        v = int(v)
        return v if v > 0 else None

    @field_validator("max_sqft", mode="before")
    @classmethod
    def _clean_max_sqft(cls, v):
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            return None
        v = int(v)
        return v if v > 0 else None

    @field_validator("furnished", mode="before")
    @classmethod
    def _clean_furnished(cls, v):
        return v if v in ("fully", "semi", "unfurnished") else None

    @field_validator("tenant_type", mode="before")
    @classmethod
    def _clean_tenant_type(cls, v):
        return v if v in ("bachelor", "family") else None

    @field_validator("owner_type", mode="before")
    @classmethod
    def _clean_owner_type(cls, v):
        return v if v in ("owner", "broker") else None

    @field_validator("rent_type", mode="before")
    @classmethod
    def _clean_rent_type(cls, v):
        if not isinstance(v, str):
            return None
        v = v.strip().lower()
        return v if v in ("monthly", "lease") else None

    @field_validator("lease_months", mode="before")
    @classmethod
    def _clean_lease_months(cls, v):
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            return None
        v = int(v)
        return v if 1 <= v <= 120 else None

    @field_validator("property_type", mode="before")
    @classmethod
    def _clean_property_type(cls, v):
        if not isinstance(v, str):
            return None
        normalized = v.strip().lower().replace(" ", "_")
        synonyms = {
            "residential":  "residential",
            "commercial":   "commercial",
            "paid_guest":   "paid_guest",
            "pg":           "paid_guest",
            "paying_guest": "paid_guest",
            "hostel":       "paid_guest",
            "any":          "any",
            "all":          "any",
            "any_type":     "any",
            "anything":     "any",
        }
        mapped = synonyms.get(normalized)
        if not mapped and normalized:
            print(f"[HybridExtractor] Unrecognized property_type from LLM: '{v}' — filter not applied.")
        return mapped

    def merge_with_previous(self, previous: Optional[dict]) -> "SearchFilters":
        """Carry forward any field this turn didn't set, same precedence
        rules as before: a fresh location_expand clears location and
        vice versa; a fresh min_sqft/max_sqft clears the OTHER sqft bound
        from a previous turn (they're the two ends of one range, not two
        independent filters — a new "above X" narrows the size search,
        it doesn't AND with a leftover "below Y" from a prior turn and
        create an impossible/empty range); the same applies to
        min_price/max_price (a fresh single-ended price like "under 8k"
        clears a previously-set price on the other end, so it doesn't
        silently AND with a stale bound from earlier in the conversation
        and produce an impossible range); property_type always defaults
        to residential."""
        prev = previous or {}
        data = self.model_dump()
        location_just_set   = data["location"] is not None
        expand_just_set      = data["location_expand"] is not None
        min_sqft_just_set    = data["min_sqft"] is not None
        max_sqft_just_set    = data["max_sqft"] is not None
        min_price_just_set   = data["min_price"] is not None
        max_price_just_set   = data["max_price"] is not None

        for key in data:
            if data[key] is None and prev.get(key) is not None:
                if key == "location" and expand_just_set:
                    continue
                if key == "location_expand" and location_just_set:
                    continue
                if key == "min_sqft" and max_sqft_just_set:
                    continue
                if key == "max_sqft" and min_sqft_just_set:
                    continue
                if key == "min_price" and max_price_just_set:
                    continue
                if key == "max_price" and min_price_just_set:
                    continue
                data[key] = prev[key]

        if data["property_type"] is None:
            data["property_type"] = "residential"

        return SearchFilters(**data)


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

    def _validate(self, extracted, previous_filters: dict = None) -> dict:
        # GUARD: chat_json is expected to return a dict, but if the LLM ever
        # returns malformed JSON (e.g. a bare list/string that still parses
        # as valid JSON), extracted.get(...) below would throw an unhandled
        # AttributeError and take the whole request down with it. Treat
        # anything non-dict as "nothing extracted this turn" instead.
        if not isinstance(extracted, dict):
            print(f"[HybridExtractor] LLM returned non-dict JSON ({type(extracted).__name__}) — ignoring this turn's extraction.")
            extracted = {}

        try:
            filters = SearchFilters(**extracted)
        except Exception as e:
            print(f"[HybridExtractor] SearchFilters validation error: {e} — falling back to empty filters.")
            filters = SearchFilters()

        merged = filters.merge_with_previous(previous_filters)
        return merged.model_dump()

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