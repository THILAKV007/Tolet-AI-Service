import random
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
        try:
            all_localities = self.property_service.get_all_localities()
            if all_localities:
                print(f"[ChatService] Warming geo cache for {len(all_localities)} DB localities...")
                self.geo_expander.warm_cache(all_localities)
                print(f"[ChatService] Geo cache ready. Stats: {self.geo_expander.cache_stats()}")
        except Exception as e:
            print(f"[ChatService] Geo warm_cache skipped: {e}")

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
        all_localities: list
    ) -> dict:
        """
        Runs two tasks in parallel:
          Task A — direct property search for the exact location
          Task B — geo expansion to find nearby localities

        Returns a dict with keys:
          direct_results      : list of properties from exact-match search
          expanded_with_dist  : list of {area, distance_km} dicts
        """
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            future_direct = pool.submit(
                self.property_service.search, {"location": location}
            )
            future_geo = pool.submit(
                self.geo_expander.expand_from_db_with_distances,
                location, all_localities
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
                all_localities_for_spell = self.property_service.get_all_localities() or []
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
            all_localities = self.property_service.get_all_localities() or []

            # Parallel: direct search + geo expansion at the same time
            parallel = self._geo_expand_parallel(filters["location"], all_localities)
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
                GEO_MIN_PROPS = 3
                if len(ranked_properties) < GEO_MIN_PROPS:
                    relaxed_filters = {
                        k: v for k, v in filters.items()
                        if k in ("location_expand", "_geo_dist_lookup")
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

                    # If user explicitly asks to list/see more options, show
                    # the full max instead of a random 1-to-max count.
                    listing_signals = {
                        "list", "show", "other", "more", "all",
                        "any other", "else", "different", "options"
                    }
                    query_lower   = cleaned_query.lower()
                    wants_listing = any(sig in query_lower for sig in listing_signals)

                    if wants_listing or intent == "refilter":
                        count = max_show
                    else:
                        count = random.randint(1, max_show)

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
        # =====================================================================
        owner_type_counts = {"direct_owner": 0, "broker": 0}
        if intent in search_intents and (filters.get("location") or filters.get("location_expand")):
            try:
                owner_type_counts = self.property_service.count_by_owner_type(filters)
            except Exception as e:
                print(f"[ChatService] owner_type_counts skipped: {e}")

        ai_response = self.response_ai.generate(
            query=cleaned_query,
            filters=response_filters,
            properties=response_properties,
            intent=intent,
            session_messages=session_messages,
            geo_original_location=geo_original_location,
            geo_expanded_areas=geo_expanded_areas,
            owner_type_counts=owner_type_counts
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

        area_name = (
            filters.get("location") or
            geo_original_location or
            (filters.get("location_expand") or [None])[0] or
            "this area"
        )
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
