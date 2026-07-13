import random
import re
import concurrent.futures

from services.translation.translation_pipeline import TranslationPipeline
from services.extractors.hybrid_extractor import HybridExtractor
from services.ai_chat.response_ai import ResponseAI
from services.ai_chat.intent_detector import IntentDetector
from services.ai_chat.ranking_engine import RankingEngine
from services.guards.domain_guard import DomainGuard
from services.analytics.demand_logger import DemandLogger
from services.knowledge.tolet_knowledge import ToletKnowledge
from services.knowledge.knowledge_detector import KnowledgeDetector
from services.mock.property_db_service import PropertyDBService
from services.session.session_store import SessionStore
from services.geo.geo_expander import GeoExpander
from services.geo.spell_corrector import LocationSpellCorrector


# ── How many properties to show after geo expansion ───────────────────────────
# After a geo-expansion search (nearby areas), we want to surface MORE options
# so the user has real choices. Normal search = up to 3; geo = up to 5.
GEO_EXPANSION_MAX_PROPS = int(5)
NORMAL_MAX_PROPS        = int(3)


class ChatService:

    def __init__(self):

        self.translation_pipeline = TranslationPipeline()
        self.extractor            = HybridExtractor()
        self.property_service     = PropertyDBService()
        self.ranking_engine       = RankingEngine()
        self.response_ai          = ResponseAI()
        self.intent_detector      = IntentDetector()
        self.domain_guard         = DomainGuard()
        self.demand_logger        = DemandLogger()
        self.tolet_knowledge      = ToletKnowledge()
        self.knowledge_detector   = KnowledgeDetector()
        self.session_store        = SessionStore()
        self.geo_expander         = GeoExpander()
        self.spell_corrector      = LocationSpellCorrector()

        # Pre-warm the geocode cache with all localities currently in the DB.
        all_localities = []
        try:
            all_localities = self.property_service.get_all_localities()
            if all_localities:
                print(f"[ChatService] Warming geo cache for {len(all_localities)} DB localities...")
                self.geo_expander.warm_cache(all_localities)
                print(f"[ChatService] Geo cache ready. Stats: {self.geo_expander.cache_stats()}")
        except Exception as e:
            print(f"[ChatService] Geo warm_cache skipped: {e}")

        # Teach DomainGuard about every real locality/city in the DB so a
        # first-turn message naming an approved area (e.g. "Ramapuram") is
        # never wrongly rejected as off-topic just because it's missing
        # from DomainGuard's small hardcoded keyword shortlist.
        self._known_locations = []
        try:
            all_cities = self.property_service.get_all_cities()
            known_locations = (all_localities or []) + (all_cities or [])
            if known_locations:
                self.domain_guard.add_known_locations(known_locations)
                self._known_locations = known_locations
                print(f"[ChatService] DomainGuard learned {len(known_locations)} live DB locations.")
        except Exception as e:
            print(f"[ChatService] DomainGuard location warm-up skipped: {e}")

    # =========================================================================
    # Deterministic Location-Mention Check
    # Backstop for IntentDetector's own documented rule: "If the user mentions
    # a LOCATION or AREA explicitly → ALWAYS property_search, even if there is
    # prior context." The LLM classifier doesn't always follow that rule
    # reliably — when it doesn't, a message like "kk nagar pg property" gets
    # treated as a carry-forward turn, silently reusing stale filters
    # (e.g. a leftover tenant_type from an earlier message) that the user
    # never mentioned this time, causing real listings to be filtered out
    # and misreported as "no properties available".
    # =========================================================================
    def _mentions_known_location(self, query: str) -> bool:
        if not query or not self._known_locations:
            return False
        query_lower = query.lower()
        for loc in self._known_locations:
            loc_clean = (loc or "").strip().lower()
            if len(loc_clean) > 2 and loc_clean in query_lower:
                return True
            # Also check individual tokens for messy multi-word DB addresses
            for tok in loc_clean.replace(",", " ").split():
                if len(tok) > 2 and re.search(r'\b' + re.escape(tok) + r'\b', query_lower):
                    return True
        return False

    # =========================================================================
    # Location Match Validator
    # =========================================================================
    def _filter_by_location_match(self, properties: list, filters: dict, geo_expanded: bool = False) -> list:

        requested_location = (filters.get("location") or "").strip().lower()
        location_expand    = filters.get("location_expand") or []

        if not requested_location and not location_expand:
            return properties

        if geo_expanded:
            return properties

        def _add_kw(loc: str, kw_set: set):
            norm = loc.strip().lower()
            if norm:
                kw_set.add(norm)
                for word in norm.split():
                    if len(word) > 2:
                        kw_set.add(word)

        accepted_keywords = set()
        if requested_location:
            _add_kw(requested_location, accepted_keywords)
        if location_expand and isinstance(location_expand, list):
            for loc in location_expand:
                _add_kw(loc, accepted_keywords)

        if not accepted_keywords:
            return properties

        matched = []
        for prop in properties:
            prop_location = " ".join(filter(None, [
                (prop.get("location") or "").lower(),
                (prop.get("city")     or "").lower(),
                (prop.get("state")    or "").lower(),
                (prop.get("locality") or "").lower(),
            ]))
            if any(kw in prop_location for kw in accepted_keywords):
                matched.append(prop)

        return matched

    def _correct_location_spelling(self, location: str, db_localities: list) -> tuple:
        """
        Returns (corrected_location, was_corrected, original_location).
        Logs the correction so it's visible in server logs.
        """
        corrected, changed = self.spell_corrector.correct(location, db_localities)
        if changed:
            print(
                f"[ChatService] Spell-corrected location: "
                f"'{location}' → '{corrected}'"
            )
        return corrected, changed, location

    # =========================================================================
    # Run geo expansion & direct-DB-search in parallel to cut latency
    # =========================================================================
    def _geo_expand_parallel(
        self,
        location: str,
        all_localities: list,
        hard_type_filters: dict = None,
        city_hint: str = None,
        state_hint: str = None,
    ) -> dict:
        """
        Runs two tasks in parallel:
          Task A — direct property search for the exact location
          Task B — geo expansion to find nearby localities

        hard_type_filters (e.g. {"property_type": "paid_guest"}) is applied to
        the direct search too — otherwise "does this location have listings?"
        would say yes just because SOME other property type exists there,
        even when the type the user actually asked for (PG/commercial/
        residential) has zero listings — wrongly skipping geo-expansion.

        city_hint/state_hint: the city/state the origin `location` belongs to.
        Forwarded straight through to expand_from_db_with_distances(), whose
        own docstring flags these as required — without them, a locality name
        that exists in more than one city (e.g. "Anna Nagar" in both Chennai
        and Madurai) can't be disambiguated, and the per-candidate city
        filter silently becomes a no-op.

        Returns a dict with keys:
          direct_results      : list of properties from exact-match search
          expanded_with_dist  : list of {area, distance_km} dicts
        """
        direct_search_filters = {"location": location}
        if hard_type_filters:
            direct_search_filters.update(hard_type_filters)

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            future_direct = pool.submit(
                self.property_service.search, direct_search_filters
            )
            future_geo = pool.submit(
                self.geo_expander.expand_from_db_with_distances,
                location, all_localities, None, city_hint, state_hint
            )
            direct_results     = future_direct.result()
            expanded_with_dist = future_geo.result()

        return {
            "direct_results":     direct_results,
            "expanded_with_dist": expanded_with_dist,
        }

    # =========================================================================
    # Main Query Processor
    # =========================================================================
    def process_query(self, session_id: str, query: str) -> dict:

        translation_result = self.translation_pipeline.process(query)
        cleaned_query      = translation_result["cleaned_query"]

        session_messages = self.session_store.get_messages(session_id)
        current_filters  = self.session_store.get_filters(session_id)
        current_props    = self.session_store.get_properties(session_id)

        if not self.domain_guard.is_allowed(cleaned_query):
            if not current_props:
                return {
                    "success":    False,
                    "query":      query,
                    "response":   self.domain_guard.get_response(query),
                    "properties": []
                }

        if self.knowledge_detector.is_tolet_query(cleaned_query):
            knowledge   = self.tolet_knowledge.get_knowledge()
            ai_response = self.response_ai.generate_knowledge_response(
                query=cleaned_query,
                knowledge=knowledge,
                session_messages=session_messages
            )
            self._save_turn(session_id, query, ai_response, {}, [], "knowledge")
            return {
                "success":          True,
                "query":            query,
                "intent":           "knowledge",
                "translated_query": translation_result["translated_query"],
                "cleaned_query":    cleaned_query,
                "filters":          {},
                "properties":       [],
                "response":         ai_response
            }

        intent = self.intent_detector.detect(
            query=cleaned_query,
            conversation_history=session_messages
        )

        # Deterministic backstop: IntentDetector's own prompt says a message
        # naming a location should ALWAYS be property_search, resetting any
        # carried-forward filters. The LLM doesn't always apply that rule
        # reliably — enforce it here so stale filters (e.g. a leftover
        # "bachelor" preference) can't silently zero out a fresh, plain
        # location search like "kk nagar pg property".
        if intent != "property_search" and self._mentions_known_location(cleaned_query):
            print(
                f"[ChatService] Intent override: '{intent}' → 'property_search' "
                f"(query names a known DB location)"
            )
            intent = "property_search"

        # Deterministic backstop: "contact_request" only makes sense when
        # there's an actual property in context to request contact info FOR.
        # A phrase like "direct owner" can be misread by the LLM as wanting
        # the owner's contact details, when it's really a search preference
        # (owner-posted, no broker). If there's nothing in current_props to
        # contact, this can never be a genuine contact request — treat it as
        # a fresh search instead so it isn't dropped on the floor.
        if intent == "contact_request" and not current_props:
            print(
                f"[ChatService] Intent override: 'contact_request' → 'property_search' "
                f"(no properties in context to contact)"
            )
            intent = "property_search"

        if intent == "property_search":
            filters_for_extraction = {}
        elif intent == "refilter":
            filters_for_extraction = dict(current_filters) if current_filters else {}
        else:
            filters_for_extraction = dict(current_filters) if current_filters else {}

        filters = self.extractor.extract(
            query=cleaned_query,
            conversation_history=session_messages,
            previous_filters=filters_for_extraction
        )

        # =====================================================================
        # Fresh-search filter sanitizer
        # For "property_search" intent, filters_for_extraction was already
        # reset to {} above — so programmatically nothing should carry
        # forward. BUT the extractor is still handed the raw conversation
        # HISTORY TEXT (for tone/language context), and the LLM can re-surface
        # ANY filter it saw mentioned several turns ago — bachelor/family,
        # direct-owner/broker, near-metro, furnished, bhk, budget — even
        # though the CURRENT message never asked for it and previous_filters
        # was empty. Confirmed live: tenant_type+owner_type leaked on one
        # query, near_metro leaked on the next — same root cause, different
        # field each time. So this checks EVERY filter field generically
        # rather than allowlisting field-by-field as they turn up.
        # =====================================================================
        if intent == "property_search":
            q_lower_sanitize = cleaned_query.lower()

            field_keywords = {
                "tenant_type": ("bachelor", "family"),
                "owner_type":  (
                    "direct owner", "no broker", "without broker", "owner only",
                    "broker", "straight owner", "straight from owner", "one to one",
                    "one-on-one", "no agent", "without agent", "no middleman",
                    "no middle man", "skip the broker", "no commission",
                    "zero brokerage", "brokerage free", "owner directly",
                    "directly from owner", "talk to the owner", "non-broker",
                    "with agent", "brokered", "agent listing",
                ),
                "near_metro":  ("metro",),
                "furnished":   ("furnished",),
            }
            for field, keywords in field_keywords.items():
                if filters.get(field) and not any(kw in q_lower_sanitize for kw in keywords):
                    print(
                        f"[ChatService] Dropping stale {field} '{filters[field]}' "
                        f"— not mentioned in this message."
                    )
                    filters[field] = None if field != "near_metro" else False

            # bhk and max_price are numeric — the current message should
            # contain at least one digit for either to be legitimate this turn.
            has_digit = bool(re.search(r"\d", q_lower_sanitize))
            if filters.get("bhk") and not has_digit:
                print(f"[ChatService] Dropping stale bhk '{filters['bhk']}' — no number in this message.")
                filters["bhk"] = None
            if filters.get("max_price") and not has_digit:
                print(f"[ChatService] Dropping stale max_price '{filters['max_price']}' — no number in this message.")
                filters["max_price"] = None

        # Capture what the user actually typed/meant as the location BEFORE
        # geo-expansion (below) can null out filters["location"] or swap it
        # for a nearby sub-locality. This is the single source of truth for
        # what to call the area in every message shown to the user — the
        # main response and the owner-type summary must always agree on it.
        originally_requested_location = (
            filters.get("location") or
            (filters.get("location_expand") or [None])[0]
        )

        prev_location        = filters_for_extraction.get("location")
        prev_location_expand = filters_for_extraction.get("location_expand")
        new_location_this_turn = bool(
            (filters.get("location") and filters.get("location") != prev_location) or
            (filters.get("location_expand") and filters.get("location_expand") != prev_location_expand)
        )

        # =====================================================================
        # Spell-correct location BEFORE geo expansion
        # =====================================================================
        spell_correction_note = None  # surfaced to AI if correction was made
        if filters.get("location") and not filters.get("location_expand"):
            try:
                # FIX: include known CITIES alongside localities in the spell-
                # correction corpus. Previously only localities (e.g. "Anna
                # Nagar", "Velachery") were passed in, so a correctly-typed
                # CITY like "Chennai" never matched anything in Pass 1 (exact
                # match) and fell through to Pass 2/3 fuzzy matching, which
                # risked silently rewriting it to an unrelated locality before
                # the search ever ran — while the reply text still showed the
                # original, correct city name (since that's captured earlier),
                # masking the mismatch. Including cities lets "Chennai" hit
                # the exact-match pass and never enter fuzzy matching at all.
                all_localities_for_spell = (
                    (self.property_service.get_all_localities() or []) +
                    (self.property_service.get_all_cities() or [])
                )
                corrected_loc, was_corrected, original_loc = self._correct_location_spelling(
                    filters["location"], all_localities_for_spell
                )
                if was_corrected:
                    filters["location"] = corrected_loc
                    spell_correction_note = (
                        f"(auto-corrected '{original_loc}' → '{corrected_loc}')"
                    )
            except Exception as e:
                print(f"[ChatService] Spell-correction skipped: {e}")

        # =====================================================================
        # Geo Expand — DB-First (radius search)
        #   Direct search + geo expansion run in PARALLEL
        #   After geo expansion, show GEO_EXPANSION_MAX_PROPS (5)
        # =====================================================================
        geo_original_location = None
        geo_expanded_areas    = []
        is_geo_expanded       = False

        if (
            intent in {"property_search", "refilter", "recommendation"}
            and filters.get("location")
            and not filters.get("location_expand")
        ):
            # Dict-form {"locality","city","state"} triples — needed so geo
            # expansion can tell apart same-named localities in different
            # cities, instead of the flat locality-string list which loses
            # that information entirely.
            all_localities = self.property_service.get_all_localities_with_city() or []

            # Look up the searched location's own city/state so it can be
            # passed as the origin's city_hint/state_hint.
            geo_city_hint  = None
            geo_state_hint = None
            location_lower = filters["location"].strip().lower()
            for entry in all_localities:
                if entry.get("locality", "").strip().lower() == location_lower:
                    geo_city_hint  = entry.get("city") or None
                    geo_state_hint = entry.get("state") or None
                    break
            if geo_city_hint is None:
                # Location might itself be a city name rather than a locality
                for entry in all_localities:
                    if entry.get("city", "").strip().lower() == location_lower:
                        geo_city_hint  = entry.get("city") or None
                        geo_state_hint = entry.get("state") or None
                        break

            # Parallel: direct search + geo expansion at the same time
            parallel = self._geo_expand_parallel(
                filters["location"],
                all_localities,
                hard_type_filters={"property_type": filters["property_type"]}
                if filters.get("property_type") else None,
                city_hint=geo_city_hint,
                state_hint=geo_state_hint,
            )
            direct_results     = parallel["direct_results"]
            expanded_with_dist = parallel["expanded_with_dist"]

            # Validate direct results against strict location match
            direct_results = self._filter_by_location_match(
                direct_results,
                {"location": filters["location"]},
                geo_expanded=False
            )

            if not direct_results:
                # No direct listings → use nearby areas from parallel geo result
                if len(expanded_with_dist) > 1:
                    geo_original_location = filters["location"]
                    nearby_areas = expanded_with_dist[1:]  # exclude origin (index 0)

                    dist_lookup = {
                        entry["area"].strip().lower(): entry["distance_km"]
                        for entry in nearby_areas
                    }
                    filters["_geo_dist_lookup"] = dist_lookup

                    geo_expanded_areas = [
                        f"{entry['area']} ({entry['distance_km']} km away)"
                        for entry in nearby_areas
                    ]
                    filters["location_expand"] = [entry["area"] for entry in nearby_areas]
                    filters["location"]        = None
                    is_geo_expanded            = True
                    print(
                        f"[ChatService] Geo expanded '{geo_original_location}'"
                        f" → nearby: {geo_expanded_areas}"
                    )
                else:
                    print(
                        f"[ChatService] No nearby areas found for '{filters['location']}' within radius."
                    )
            else:
                print(
                    f"[ChatService] Direct listings found in '{filters['location']}'"
                    " — skipping geo expand."
                )

        # =====================================================================
        # Clarification Gate
        # If the user gave only a thin signal (e.g. just "2bhk" or "pg") with
        # NO location and NO budget, don't blindly dump every matching listing.
        # ~40% of the time, ask a quick clarifying question (location, then
        # budget) instead — like a real agent narrowing down the search.
        # This never fires if a location is already known, the user gave a
        # budget, or they explicitly asked to see everything/all/list.
        # =====================================================================
        needs_clarification = False
        if intent in {"property_search", "refilter"}:
            has_location = bool(filters.get("location") or filters.get("location_expand"))
            has_budget   = bool(filters.get("max_price"))
            # NOTE: property_type now defaults to "residential" even when the
            # user gave no type signal at all (see hybrid_extractor.py), so it
            # can no longer be used as a proxy for "the user said something
            # specific". Only count it here when it's an explicit non-default
            # signal (commercial / paid_guest) that the user actually stated.
            has_signal   = bool(
                filters.get("bhk") or
                filters.get("property_type") in ("commercial", "paid_guest") or
                filters.get("furnished") or filters.get("tenant_type")
            )
            query_lower_check = cleaned_query.lower()
            explicit_listing_request = any(
                sig in query_lower_check for sig in (
                    "list", "show all", "show me all", "all properties",
                    "everything", "any location", "anything available"
                )
            )
            if has_signal and not has_location and not has_budget and not explicit_listing_request:
                needs_clarification = random.random() < 0.4

        if needs_clarification:
            ai_response = self.response_ai.generate_clarification(
                query=cleaned_query,
                filters=filters,
                session_messages=session_messages
            )
            self._save_turn(
                session_id=session_id,
                user_query=query,
                assistant_response=ai_response,
                filters=filters,
                properties=[],
                intent="clarification"
            )
            return {
                "success":          True,
                "query":            query,
                "intent":           "clarification",
                "translated_query": translation_result["translated_query"],
                "cleaned_query":    cleaned_query,
                "filters":          filters,
                "properties":       [],
                "response":         ai_response,
            }

        # =====================================================================
        # Property Search + Ranking
        # =====================================================================
        ranked_properties = []

        search_intents = {"property_search", "refilter", "recommendation"}

        if intent in search_intents:

            properties = self.property_service.search(filters)
            properties = self._filter_by_location_match(
                properties, filters, geo_expanded=is_geo_expanded
            )

            if not properties:
                if filters.get("location"):
                    self.demand_logger.log_unavailable_location(
                        query=query, location=filters["location"]
                    )
                elif filters.get("location_expand"):
                    log_loc = ", ".join(filters["location_expand"][:3]) + "..."
                    self.demand_logger.log_unavailable_location(
                        query=query, location=log_loc
                    )

            # Inject distance_km into each property so the ranking engine can
            # use proximity as a tiebreaker for geo-expanded results.
            if is_geo_expanded and filters.get("_geo_dist_lookup"):
                dist_lookup = filters["_geo_dist_lookup"]
                for prop in properties:
                    prop_loc = (prop.get("locality") or prop.get("location") or "").strip().lower()
                    prop["distance_km"] = dist_lookup.get(prop_loc, 999)

            all_ranked = self.ranking_engine.rank(filters=filters, properties=properties)

            if intent == "recommendation":
                ranked_properties = all_ranked[:1]

            elif is_geo_expanded:
                # Geo expansion → show up to GEO_EXPANSION_MAX_PROPS
                # so user sees multiple nearby options, not just 1
                ranked_properties = all_ranked[:GEO_EXPANSION_MAX_PROPS]

                # If geo expanded but fewer than 3 results, retry with
                # relaxed filters (drop bhk / price / furnished constraints)
                # so the user always sees at least 3 nearby properties when they exist.
                # NOTE: property_type is NEVER relaxed — a PG search must never
                # get padded with residential/commercial listings, and vice versa.
                GEO_MIN_PROPS = 3
                if len(ranked_properties) < GEO_MIN_PROPS:
                    relaxed_filters = {
                        k: v for k, v in filters.items()
                        if k in ("location_expand", "_geo_dist_lookup", "property_type")
                    }
                    relaxed_props = self.property_service.search(relaxed_filters)
                    relaxed_props = self._filter_by_location_match(
                        relaxed_props, relaxed_filters, geo_expanded=True
                    )
                    relaxed_ranked = self.ranking_engine.rank(
                        filters=relaxed_filters, properties=relaxed_props
                    )
                    # Merge: keep original results first, then fill with relaxed ones
                    seen_ids = {p["id"] for p in ranked_properties}
                    for prop in relaxed_ranked:
                        if prop["id"] not in seen_ids and len(ranked_properties) < GEO_MIN_PROPS:
                            ranked_properties.append(prop)
                            seen_ids.add(prop["id"])
                    if len(ranked_properties) > len(all_ranked):
                        print(
                            f"[ChatService] Geo relaxed-filter fallback added "
                            f"{len(ranked_properties) - len(all_ranked[:GEO_EXPANSION_MAX_PROPS])} "
                            f"extra properties to meet min={GEO_MIN_PROPS}"
                        )

                print(
                    f"[ChatService] Geo results: {len(ranked_properties)} properties shown "
                    f"(max={GEO_EXPANSION_MAX_PROPS}, min={GEO_MIN_PROPS})"
                )

            else:
                if len(all_ranked) > 0:
                    max_show = min(NORMAL_MAX_PROPS, len(all_ranked))

                    # FIX: always show up to NORMAL_MAX_PROPS (3) when that many
                    # matches exist. Previously this picked a RANDOM count between
                    # 1 and max_show for plain searches, so a user with 6 matching
                    # properties could be shown just 1 — looking like there was
                    # barely any inventory when there wasn't. Listing-intent
                    # queries ("show", "list", "all", etc.) and refilters already
                    # got the full max_show; now every search does.
                    count = max_show

                    ranked_properties = all_ranked[:count]
                else:
                    ranked_properties = []

        # =====================================================================
        # Response Assembly
        # =====================================================================
        new_location_requested = new_location_this_turn

        if intent == "contact_request" and current_props:
            response_properties = current_props
            response_filters    = current_filters if current_filters else {}
        elif intent == "property_discussion" and not ranked_properties and current_props and not new_location_requested:
            response_properties = current_props
            response_filters    = current_filters if current_filters else {}
        else:
            response_properties = ranked_properties
            response_filters    = filters if ranked_properties else {}

        # =====================================================================
        # Owner-Type Counts — how many direct owner vs broker listings exist
        # for the searched location (ignores the owner_type filter itself so
        # totals always reflect full supply, not the already-filtered slice).
        #
        # If the user gave NO location (e.g. "I want commercial property"),
        # there's no location to count against yet — but if properties WERE
        # still found (a location-less DB search can still return matches),
        # fall back to the locality of the first result so the summary stays
        # truthful instead of defaulting to a stale "0 direct owner / 0
        # broker" that contradicts the property just shown.
        # =====================================================================
        owner_type_counts  = {"direct_owner": 0, "broker": 0}
        is_multi_location_summary = False  # true = counts below are a real cross-location aggregate
        counts_location    = (
            filters.get("location") or
            filters.get("location_expand") or
            originally_requested_location
        )

        if not counts_location and ranked_properties:
            # Only fall back to "the first result's locality" when EVERY
            # matched property actually shares that same locality — a
            # genuine "any location" search can legitimately return results
            # spanning several different cities (e.g. PG listings in
            # Annamalai Nagar, Coimbatore, AND Chennai), and naming just the
            # first result's area would misreport a partial count as if it
            # were the total.
            distinct_localities = {
                (p.get("locality") or p.get("location") or p.get("city") or "").strip().lower()
                for p in ranked_properties
            }
            distinct_localities.discard("")
            if len(distinct_localities) == 1:
                fallback_locality = (
                    ranked_properties[0].get("locality") or
                    ranked_properties[0].get("location") or
                    ranked_properties[0].get("city")
                )
                if fallback_locality:
                    counts_location = fallback_locality
            elif len(distinct_localities) > 1:
                # Results genuinely span multiple areas with no location
                # filter — compute a real aggregate directly from the FULL
                # matched set ('properties', before ranking/display
                # truncation) rather than scoping to any single area, so the
                # count reflects true total supply matching this search
                # (property_type, etc.) across every location, not just the
                # locations of the properties shown on screen.
                for prop in properties:
                    posted_by = (prop.get("posted_by") or "").strip().lower()
                    if re.match(r"^(direct[_\s]?owner|owner)$", posted_by):
                        owner_type_counts["direct_owner"] += 1
                    elif posted_by.startswith("broker"):
                        owner_type_counts["broker"] += 1
                is_multi_location_summary = True
                counts_location = "multiple locations"  # truthy sentinel — skips the DB re-query below
                print(
                    f"[ChatService] Multi-location aggregate — "
                    f"direct_owner={owner_type_counts['direct_owner']}, "
                    f"broker={owner_type_counts['broker']} "
                    f"across {len(properties)} matched properties in {len(distinct_localities)} areas."
                )

        if intent in search_intents and counts_location and not is_multi_location_summary:
            try:
                count_filters = dict(filters)
                if not filters.get("location") and not filters.get("location_expand"):
                    count_filters["location"] = counts_location
                owner_type_counts = self.property_service.count_by_owner_type(count_filters)
            except Exception as e:
                print(f"[ChatService] owner_type_counts skipped: {e}")

        # Hoisted above generate() (previously computed after, near the
        # frontend badge) so the LLM prompt and the badge derive from the
        # SAME area name and can never diverge. Only meaningful once
        # counts_location is known, so default to None until then — the
        # badge-only fallback ("this area") is applied further below where
        # counts_location is guaranteed to be truthy.
        area_name = (
            "multiple locations" if is_multi_location_summary else (
                originally_requested_location or
                geo_original_location or
                (filters.get("location_expand") or [None])[0] or
                counts_location or
                None
            )
        )

        ai_response = self.response_ai.generate(
            query=cleaned_query,
            filters=response_filters,
            properties=response_properties,
            intent=intent,
            session_messages=session_messages,
            geo_original_location=geo_original_location,
            geo_expanded_areas=geo_expanded_areas,
            owner_type_counts=owner_type_counts,
            owner_type_area=area_name
        )

        self._save_turn(
            session_id=session_id,
            user_query=query,
            assistant_response=ai_response,
            filters=filters,
            properties=ranked_properties,
            intent=intent
        )

        # ── Natural language summaries for frontend badges ───────────────────
        # Only generate these for property-related intents — not greetings,
        # off-topic, knowledge queries, etc.
        if intent not in search_intents:
            return {
                "success":              True,
                "query":                query,
                "intent":               intent,
                "translated_query":     translation_result["translated_query"],
                "cleaned_query":        cleaned_query,
                "filters":              filters,
                "properties":           ranked_properties,
                "response":             ai_response,
            }

        # No location context at all (no filter, no geo-expansion, no
        # fallback from a returned property) → there's nothing real to
        # summarize. Skip the direct-owner/broker badge instead of showing
        # a made-up "this area has 0 listings" that contradicts the
        # property already shown to the user.
        if not counts_location:
            return {
                "success":              True,
                "query":                query,
                "intent":               intent,
                "translated_query":     translation_result["translated_query"],
                "cleaned_query":        cleaned_query,
                "filters":              filters,
                "properties":           ranked_properties,
                "response":             ai_response,
                "owner_type_counts":    owner_type_counts,
                **( {"spell_correction": spell_correction_note} if spell_correction_note else {})
            }

        # area_name was already computed above (before generate()) and
        # passed to the LLM as owner_type_area — reused here as-is for the
        # badge so the two can never disagree. Only the final "this area"
        # fallback is applied here, since counts_location is now guaranteed
        # truthy at this point (checked earlier above).
        area_name = area_name or "this area"
        d_count = owner_type_counts.get("direct_owner", 0)
        b_count = owner_type_counts.get("broker", 0)

        # ── Direct owner summary templates ───────────────────────────────────
        if d_count > 0:
            p = "property" if d_count == 1 else "properties"
            direct_owner_templates = [
                f"Great news! {area_name} has {d_count} direct owner {p} available.\nNo middlemen, no brokerage fees — you deal straight with the owner!",
                f"We found {d_count} direct owner {p} in {area_name}.\nThis means zero brokerage charges and direct communication with the owner.",
                f"In {area_name}, {d_count} direct owner {p} {'is' if d_count == 1 else 'are'} currently listed.\nPerfect if you want to avoid broker fees and negotiate directly!",
                f"Looking good! There {'is' if d_count == 1 else 'are'} {d_count} direct owner {p} in {area_name} right now.\nSkip the middleman and connect with the owner directly.",
                f"{area_name} currently has {d_count} owner-listed {p}.\nDeal directly, save on brokerage, and move in faster!",
                f"We spotted {d_count} direct owner {p} in {area_name} for you.\nNo broker involved — just you and the owner, keeping it simple.",
            ]
            direct_owner_summary = random.choice(direct_owner_templates)
        else:
            direct_owner_none_templates = [
                f"Hmm, no direct owner properties found in {area_name} right now.\nBut don't worry — broker listings are available and they handle everything for you!",
                f"It looks like {area_name} doesn't have any direct owner listings at the moment.\nConsider the broker options — they can make the whole process smooth and hassle-free.",
                f"No direct owner properties in {area_name} currently.\nBrokers in this area are well-experienced and can help you find the right fit quickly.",
                f"Unfortunately, {area_name} has no direct owner listings available today.\nThe broker properties here are a great alternative — they manage all paperwork and visits for you.",
                f"We couldn't find any direct owner listings in {area_name} at this time.\nNot to worry — broker-managed properties in this area are reliable and well-maintained!",
            ]
            direct_owner_summary = random.choice(direct_owner_none_templates)

        # ── Broker summary templates ──────────────────────────────────────────
        if b_count > 0:
            p = "property" if b_count == 1 else "properties"
            broker_templates = [
                f"{area_name} has {b_count} broker {p} listed.\nBrokers handle everything — visits, paperwork, and negotiation — so you can move in stress-free!",
                f"We found {b_count} broker-managed {p} in {area_name}.\nThey take care of the entire process from shortlisting to signing the agreement.",
                f"There {'is' if b_count == 1 else 'are'} {b_count} broker {p} available in {area_name}.\nBrokers here are experienced and can guide you through every step of the rental process.",
                f"In {area_name}, {b_count} broker {p} {'is' if b_count == 1 else 'are'} up for grabs.\nLet the broker handle the legwork while you focus on choosing your perfect home!",
                f"{area_name} currently shows {b_count} broker-listed {p}.\nA great option if you want professional assistance with negotiation and documentation.",
                f"We spotted {b_count} broker {p} in {area_name} for you.\nBrokers make the rental journey smoother — they coordinate viewings and handle all the formalities.",
            ]
            broker_summary = random.choice(broker_templates)
        else:
            broker_none_templates = [
                f"No broker listings found in {area_name} at the moment.\nBut the direct owner options here are a fantastic deal — straight from the owner, no extra fees!",
                f"{area_name} has no broker properties listed right now.\nThe good news? Direct owner properties mean zero brokerage and faster decisions!",
                f"Broker listings aren't available in {area_name} currently.\nGo direct with the owners — it's simpler, cheaper, and often faster to close.",
                f"We couldn't find any broker properties in {area_name} today.\nDirect owner listings are your best bet here — no commission, no delays!",
                f"No broker-managed properties in {area_name} for now.\nDirect owner listings are available though — a great way to save on brokerage and connect personally.",
            ]
            broker_summary = random.choice(broker_none_templates)

        return {
            "success":              True,
            "query":                query,
            "intent":               intent,
            "translated_query":     translation_result["translated_query"],
            "cleaned_query":        cleaned_query,
            "filters":              filters,
            "location":             area_name,
            "properties":           ranked_properties,
            "response":             ai_response,
            "owner_type_counts":    owner_type_counts,
            "direct_owner_summary": direct_owner_summary,
            "broker_summary":       broker_summary,
            **( {"spell_correction": spell_correction_note} if spell_correction_note else {})
        }

    def _save_turn(
        self,
        session_id: str,
        user_query: str,
        assistant_response: str,
        filters: dict,
        properties: list,
        intent: str
    ):
        self.session_store.append_message(session_id, "user",      user_query)
        self.session_store.append_message(session_id, "assistant", assistant_response)
        self.session_store.append_history(session_id, {
            "query":      user_query,
            "filters":    filters,
            "properties": properties,
            "intent":     intent
        })
        self.session_store.refresh(session_id)