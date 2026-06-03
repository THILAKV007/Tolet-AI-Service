import random

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

    # ===================================
    # Location Match Validator
    #
    # If the user asked for a specific city/area,
    # check that every returned property actually
    # belongs to that location.
    # If none match → return empty list so that
    # no cards are shown and the AI says "no results".
    # ===================================
    def _filter_by_location_match(self, properties: list, filters: dict) -> list:

        requested_location = (filters.get("location") or "").strip().lower()
        location_expand    = filters.get("location_expand") or []

        # No location filter requested → nothing to validate
        if not requested_location and not location_expand:
            return properties

        # Build the full set of accepted location keywords
        accepted_keywords = set()
        if requested_location:
            accepted_keywords.add(requested_location)
        if location_expand and isinstance(location_expand, list):
            for loc in location_expand:
                accepted_keywords.add(loc.strip().lower())

        if not accepted_keywords:
            return properties

        matched = []
        for prop in properties:
            # Check locality, city, AND state fields for a match
            prop_location = " ".join(filter(None, [
                (prop.get("location") or "").lower(),
                (prop.get("city") or "").lower(),
                (prop.get("state") or "").lower(),
                (prop.get("locality") or "").lower(),
            ]))
            # Accept if ANY accepted keyword appears in any of the property's location fields
            if any(keyword in prop_location for keyword in accepted_keywords):
                matched.append(prop)

        return matched

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


        ranked_properties = []

        search_intents = {
            "property_search",
            "refilter",
            "recommendation"
        }

        if intent in search_intents:

            properties = self.property_service.search(filters)

            properties = self._filter_by_location_match(properties, filters)

            if not properties:
                if filters.get("location"):
                    self.demand_logger.log_unavailable_location(
                        query=query,
                        location=filters["location"]
                    )
                elif filters.get("location_expand"):
                    log_loc = ", ".join(filters["location_expand"][:3]) + "..."
                    self.demand_logger.log_unavailable_location(
                        query=query,
                        location=log_loc
                    )

            all_ranked = self.ranking_engine.rank(
                filters=filters,
                properties=properties
            )

            if intent == "recommendation":
                ranked_properties = all_ranked[:1]
            else:
                if len(all_ranked) > 0:
                    max_show = min(3, len(all_ranked))
                    count    = random.randint(1, max_show)  # guaranteed >= 1
                    ranked_properties = all_ranked[:count]
                else:
                    ranked_properties = []



        new_location_requested = bool(
            filters.get("location") or filters.get("location_expand")
        )


        if intent == "contact_request" and current_props:
            response_properties = current_props
            response_filters    = current_filters if current_filters else {}
        elif intent == "property_discussion" and not ranked_properties and current_props and not new_location_requested:
            response_properties = current_props
            response_filters    = current_filters if current_filters else {}
        else:
            response_properties = ranked_properties
            response_filters    = filters if ranked_properties else {}

        ai_response = self.response_ai.generate(
            query=cleaned_query,
            filters=response_filters,
            properties=response_properties,
            intent=intent,
            session_messages=session_messages
        )

        self._save_turn(
            session_id=session_id,
            user_query=query,
            assistant_response=ai_response,
            filters=filters,
            properties=ranked_properties,
            intent=intent
        )

        return {
            "success":          True,
            "query":            query,
            "intent":           intent,
            "translated_query": translation_result["translated_query"],
            "cleaned_query":    cleaned_query,
            "filters":          filters,
            "properties":       ranked_properties,
            "response":         ai_response
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