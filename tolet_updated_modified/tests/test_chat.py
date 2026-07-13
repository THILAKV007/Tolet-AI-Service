"""
tests/test_chat.py

Was previously an 8-line ad-hoc script that called LLMExtractor.extract()
directly against a live LLM API (needs a real API key, network access, and
a running provider — not runnable in CI, not really a "test"). Replaced with
an actual pytest suite:

  - test_llm_extractor_maps_query_to_filters
        Same scenario the old script exercised (a Tanglish/English mixed
        query with location + bhk + budget + furnished), but with the LLM
        call mocked so it runs offline and deterministically.

  - test_geo_expand_parallel_forwards_city_state_hint
  - test_process_query_owner_type_area_matches_badge_multi_location
        Regression tests for the two fixes made in chat_service.py /
        property_db_service.py: city_hint/state_hint now reach geo_expander
        with dict-form localities, and the LLM-facing owner_type_area and
        the frontend badge's location now derive from the exact same
        hoisted area_name (they structurally cannot diverge anymore).
"""
import json
from unittest.mock import patch

from services.extractors.llm_extractor import LLMExtractor
from services.ai_chat.chat_service import ChatService


# =============================================================================
# LLMExtractor
# =============================================================================
def test_llm_extractor_maps_query_to_filters():
    fake_llm_json = json.dumps({
        "bhk": 3,
        "max_price": 15000,
        "location": "Avadi",
        "property_type": "residential",
        "furnished": "furnished",
        "near_metro": True,
        "tenant_type": None,
        "budget_preference": None,
    })

    with patch("services.llm.llm_client.LLMClient.chat", return_value=fake_llm_json):
        extractor = LLMExtractor()
        result = extractor.extract(
            "Need cheap apartment around 15k near metro in Avadi 3bhk with furnieshed"
        )

    assert result["location"] == "Avadi"
    assert result["bhk"] == 3
    assert result["max_price"] == 15000
    assert result["near_metro"] is True


def test_llm_extractor_returns_empty_dict_on_malformed_json():
    with patch("services.llm.llm_client.LLMClient.chat", return_value="not valid json"):
        extractor = LLMExtractor()
        result = extractor.extract("any query")

    assert result == {}


# =============================================================================
# ChatService — city_hint/state_hint forwarding (file-11 fix, part 1)
# =============================================================================
def test_geo_expand_parallel_forwards_city_state_hint():
    cs = ChatService.__new__(ChatService)
    captured = {}

    class StubPropertyService:
        def search(self, filters):
            return []

    class StubGeoExpander:
        def expand_from_db_with_distances(self, location, all_localities, radius_km, city_hint, state_hint):
            captured["location"] = location
            captured["all_localities"] = all_localities
            captured["city_hint"] = city_hint
            captured["state_hint"] = state_hint
            return [{"area": location, "distance_km": 0.0}]

    cs.property_service = StubPropertyService()
    cs.geo_expander = StubGeoExpander()

    cs._geo_expand_parallel(
        "Anna Nagar",
        [{"locality": "Anna Nagar", "city": "Chennai", "state": "Tamil Nadu"}],
        city_hint="Chennai",
        state_hint="Tamil Nadu",
    )

    assert captured["city_hint"] == "Chennai"
    assert captured["state_hint"] == "Tamil Nadu"
    assert captured["all_localities"] == [
        {"locality": "Anna Nagar", "city": "Chennai", "state": "Tamil Nadu"}
    ]


# =============================================================================
# ChatService — LLM prompt / frontend badge area-name consistency
# (file-11 fix, part 2)
# =============================================================================
def _build_stubbed_chat_service(properties, response_ai):
    cs = ChatService.__new__(ChatService)
    cs._known_locations = []

    class StubTranslation:
        def process(self, q):
            return {"cleaned_query": q, "translated_query": q}

    class StubDomainGuard:
        def is_allowed(self, q):
            return True

        def get_response(self, q):
            return "off topic"

    class StubKnowledgeDetector:
        def is_tolet_query(self, q):
            return False

    class StubIntentDetector:
        def detect(self, query, conversation_history):
            return "property_search"

    class StubExtractor:
        def extract(self, query, conversation_history, previous_filters):
            return {
                "location": None, "location_expand": None, "bhk": None,
                "max_price": None, "furnished": None, "near_metro": None,
                "tenant_type": None, "owner_type": None,
                "property_type": "paid_guest",
            }

    class StubPropertyService:
        def search(self, filters):
            return properties

        def get_all_localities(self):
            return []

        def get_all_localities_with_city(self):
            return []

        def get_all_cities(self):
            return []

        def count_by_owner_type(self, filters):
            return {"direct_owner": 0, "broker": 0}

    class StubRankingEngine:
        def rank(self, filters, properties):
            return properties

    class StubSessionStore:
        def get_messages(self, sid):
            return []

        def get_filters(self, sid):
            return {}

        def get_properties(self, sid):
            return []

        def append_message(self, *a, **k):
            pass

        def append_history(self, *a, **k):
            pass

        def refresh(self, sid):
            pass

    class StubDemandLogger:
        def log_unavailable_location(self, **k):
            pass

    class StubSpellCorrector:
        def correct(self, loc, db):
            return loc, False

    class StubGeoExpander:
        def expand_from_db_with_distances(self, *a, **k):
            return []

        def warm_cache(self, *a, **k):
            pass

        def cache_stats(self):
            return {}

    cs.translation_pipeline = StubTranslation()
    cs.domain_guard = StubDomainGuard()
    cs.knowledge_detector = StubKnowledgeDetector()
    cs.intent_detector = StubIntentDetector()
    cs.extractor = StubExtractor()
    cs.property_service = StubPropertyService()
    cs.ranking_engine = StubRankingEngine()
    cs.session_store = StubSessionStore()
    cs.response_ai = response_ai
    cs.demand_logger = StubDemandLogger()
    cs.spell_corrector = StubSpellCorrector()
    cs.geo_expander = StubGeoExpander()
    return cs


def test_process_query_owner_type_area_matches_badge_multi_location():
    properties = [
        {"id": "1", "title": "PG A", "locality": "Kochi", "location": "Kochi",
         "city": "Kochi", "price": 9000, "posted_by": "direct_owner",
         "property_type": "paid_guest"},
        {"id": "2", "title": "PG B", "locality": "Chennai", "location": "Chennai",
         "city": "Chennai", "price": 11000, "posted_by": "broker",
         "property_type": "paid_guest"},
    ]

    captured = {}

    class StubResponseAI:
        def generate(self, **kwargs):
            captured.update(kwargs)
            return "placeholder LLM reply"

        def generate_clarification(self, **kwargs):
            return "clarify me"

    cs = _build_stubbed_chat_service(properties, StubResponseAI())

    result = cs.process_query(session_id="s1", query="show me all pg listings")

    # The LLM prompt and the frontend badge must derive from the exact same
    # area name — this is the structural fix, not just a coincidental match.
    assert captured.get("owner_type_area") == result.get("location")
    assert captured.get("owner_type_area") == "multiple locations"
