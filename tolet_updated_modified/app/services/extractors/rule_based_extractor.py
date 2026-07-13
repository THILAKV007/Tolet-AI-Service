import re

# Reuse the same multi-city/state reference lists spell_corrector.py already
# maintains, instead of keeping a third independent (and already stale)
# locality list here. The old hardcoded list below only had 10 Chennai
# localities — the exact same "Chennai-only" gap that was a critical bug in
# spell_corrector.py (see file 3 in this review) and geo_expander.py (file
# 4). Properties in Kochi, Bangalore, Mumbai, etc. could never be matched
# by this extractor's location rule.
from services.geo.spell_corrector import (
    _CHENNAI_REFERENCE_LOCALITIES,
    _CITY_STATE_REFERENCE,
)


class RuleBasedExtractor:

    def extract(

        self,

        query: str
    ):

        query = query.lower()


        filters = {

            "bhk": None,

            "max_price": None,

            "location": None,

            "location_expand": None,

            "property_type": None,

            "furnished": None,

            "near_metro": False,

            "tenant_type": None,

            "owner_type": None,
        }

        bhk_match = re.search(

            r'(\d+)\s*bhk',

            query
        )

        if bhk_match:

            filters["bhk"] = int(

                bhk_match.group(1)
            )

        # FIX: the old pattern `(under|below|max)?\s*₹?\s*(\d+)(k)?` had
        # every meaningful part optional, so it matched ANY bare number in
        # the query — bhk counts, square footage, etc. — as a price the
        # moment it crossed the >=1000 rupee floor (e.g. "1200 sqft 2bhk"
        # would wrongly set max_price=1200). It also used re.search's
        # leftmost-match behavior, so a false match earlier in the
        # sentence could shadow the user's real price mentioned later.
        # Now a price is only recognized when it's marked as one: preceded
        # by a price cue word ("under"/"below"/"max"/"budget"/"rent"/
        # "price"), preceded by ₹, or suffixed with "k" (e.g. "15k").
        price_match = re.search(
            r'(?:under|below|max|budget(?:\s+of)?|rent(?:\s+of)?|price(?:\s+of)?)'
            r'\s*₹?\s*(?P<amt1>\d+)(?P<k1>k)?'
            r'|₹\s*(?P<amt2>\d+)(?P<k2>k)?'
            r'|\b(?P<amt3>\d+)\s*k\b',
            query
        )

        if price_match:

            amount = int(
                price_match.group("amt1")
                or price_match.group("amt2")
                or price_match.group("amt3")
            )

            if price_match.group("k1") or price_match.group("k2"):

                amount *= 1000

            if amount >= 1000:

                filters["max_price"] = amount

        # FIX: "unfurnished" contains "furnished" as a substring, so the old
        # elif chain (fully furnished / semi furnished / furnished) fell
        # through to the generic "furnished" branch for "unfurnished" too —
        # tagging a user who explicitly wants an UNfurnished place as
        # wanting furnished, the opposite of their intent. Also switched
        # values to the canonical "fully"/"semi"/"unfurnished" strings that
        # SearchFilters (hybrid_extractor.py) uses and that actually match
        # the DB's furnishedType format ("Fully-Furnished", "Semi-Furnished")
        # via property_db_service.py's substring regex — the old values
        # ("fully furnished" with a space) never matched that hyphenated DB
        # format and would have silently returned zero results.
        if "unfurnished" in query:

            filters["furnished"] = "unfurnished"

        elif "fully furnished" in query or "full furnished" in query:

            filters["furnished"] = "fully"

        elif "semi furnished" in query or "semi-furnished" in query:

            filters["furnished"] = "semi"

        elif "furnished" in query:

            filters["furnished"] = "fully"

        if "near metro" in query:

            filters["near_metro"] = True

        # NOTE: property_db_service.py only isolates on property_type values
        # "residential", "commercial", "paid_guest" — anything else is
        # silently ignored (no type filter applied at all). Map user-facing
        # synonyms to those exact DB values here.
        property_type_map = {
            "house":    "residential",
            "apartment":"residential",
            "flat":     "residential",
            "villa":    "residential",
            "studio":   "residential",
            "pg":       "paid_guest",
            "hostel":   "paid_guest",
        }

        # FIX: parse 1rk/2rk as bhk=1/bhk=2 + property_type=residential
        rk_match = re.search(r"(\d+)\s*rk", query)
        if rk_match:
            filters["bhk"] = int(rk_match.group(1))
            filters["property_type"] = "residential"

        for keyword, property_type in property_type_map.items():

            if keyword in query:

                filters["property_type"] = (
                    property_type
                )

                break

        if re.search(r"\bbachelors?\b", query):

            filters["tenant_type"] = (
                "bachelor"
            )

        elif "family" in query:

            filters["tenant_type"] = (
                "family"
            )

        # FIX: owner_type is a real, consumed field (property_db_service.py
        # filters on "type"/isBrokerExcuse) that this extractor never set at
        # all — meaning a rule-based-only path could never honor a "direct
        # owner, no broker" request. budget_preference (removed above) was
        # the opposite problem: a field this extractor invented that no
        # downstream code ever reads (confirmed via grep — it's dead
        # weight, not a real filter).
        no_broker_phrases = (
            "direct owner", "no broker", "without broker", "owner only",
            "no agent", "without agent", "no middleman", "zero brokerage",
            "brokerage free", "no commission", "owner directly",
        )
        broker_phrases = (
            "broker", "through agent", "with agent", "agent listing",
        )
        if any(p in query for p in no_broker_phrases):
            filters["owner_type"] = "owner"
        elif any(p in query for p in broker_phrases):
            filters["owner_type"] = "broker"

        for location in _CHENNAI_REFERENCE_LOCALITIES + _CITY_STATE_REFERENCE:

            if location in query:

                filters["location"] = (

                    location.title()
                )

                break

        return filters