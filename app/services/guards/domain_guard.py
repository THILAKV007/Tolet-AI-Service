import re

from services.llm.llm_client import LLMClient


class DomainGuard:

    def __init__(self):

        # ===================================
        # Allowed Keywords
        # Generic intent words (need, want,
        # find, show, search, about, etc.) are
        # intentionally excluded — they are too
        # broad and cause false positives on
        # off-topic queries like "please explain"
        # or "i need a salary raise".
        # Whole-word matching is used in
        # is_allowed() to prevent substring hits
        # like "lease" inside "please".
        # ===================================
        self.allowed_keywords = [
            # --- Greetings --- always allowed
            "hi", "hello", "hey", "howdy", "hiya", "greetings",
            "good morning", "good evening", "good afternoon",
            "how are you", "how r u", "whats up", "what's up",
            "sup", "yo", "gm", "gn", "thanks"

            # --- Tolet brand ---
            "tolet ai", "tolet",

            # --- Property types ---
            "house", "home", "property", "flat", "apartment", "villa", "pg",
            "bhk", "1bhk", "2bhk", "3bhk", "4bhk",
            "rk", "1rk", "2rk", "room kitchen", "single room", "studio",

            # --- Rental & real estate terms ---
            "rent", "rental", "lease", "tenant", "landlord", "real estate",
            "furnished", "unfurnished", "deposit", "advance", "eviction",
            "broker", "listing", "agreement", "rental agreement",
            "rental price", "rental market", "average rent", "avg rent",
            "rental tips", "rental advice", "renting", "rented",
            "property management", "property tax",

            # --- Major cities ---
            "chennai", "bangalore", "bengaluru", "delhi", "mumbai", "hyderabad",
            "pune", "kolkata", "ahmedabad", "jaipur", "surat", "coimbatore",
            "madurai", "trichy", "noida", "gurgaon", "gurugram", "navi mumbai",
            "thane", "kochi", "chandigarh", "indore", "bhopal", "nagpur",
            "lucknow", "patna",

            # --- Chennai localities ---
            "avadi", "ambattur", "velachery", "tambaram", "porur", "anna nagar",
            "guindy", "t nagar", "medavakkam", "poonamallee", "ecr", "omr",
            "adyar", "vadapalani",

            # --- Bangalore localities ---
            "whitefield", "hsr layout", "koramangala", "indiranagar",
            "electronic city", "jp nagar", "marathahalli", "btm layout", "hebbal",

            # --- Hyderabad localities ---
            "hitech city", "gachibowli", "madhapur", "banjara hills", "kondapur",

            # --- Preferences ---
            "metro", "bachelor", "bachelors", "family", "family friendly", "parking", "floor",
            "budget", "price", "location", "locality", "nearby",
            "best", "better", "recommend", "suggest", "suitable", "good for",
            "which is", "which one is", "which ones are",

            # --- More cities & regions ---
            "new delhi", "old delhi", "delhi ncr", "ncr",
            "tamil nadu", "karnataka", "maharashtra", "kerala", "telangana",
            "uttar pradesh", "rajasthan", "gujarat", "west bengal",

            # --- Listing & action words ---
            "list", "show", "find", "get", "give", "display", "fetch",
            "available", "any", "all", "current",

            # --- Plural / alternate forms ---
            "properties", "homes", "rooms", "flats", "apartments",

            # --- Price filter words ---
            "below", "under", "above", "less than", "more than",
            "10k", "8k", "15k", "20k", "25k", "30k",
            "cheap", "affordable", "expensive",

            # --- Follow-up / refilter phrases ---
            "which one", "which ones", "based on above", "from above",
            "from those", "of those", "located on", "located in",
            "show only", "only show", "filter",

            # --- Contact / owner queries ---
            "contact", "owner", "contact owner", "phone number", "mobile",
            "whatsapp", "call", "reach", "schedule", "visit", "book visit",
            "how to contact", "owner contact", "owner number", "owner details",

            # --- Conversation continuations ---
            # Short replies like "yes", "no", "sure" have no rental
            # keywords but are follow-ups to the previous AI message.
            # Must be allowed here so they reach intent detection,
            # which correctly classifies them as property_discussion.
            "yes", "no", "sure", "ok", "okay", "yep", "yeah", "nope",
            "alright", "fine", "please", "go ahead", "why not",
            "of course", "definitely", "sounds good", "great",
            "tell me more", "more details", "more detail", "more info",
            "show me", "want more", "need more",
        ]

        # ===================================
        # LLM Client
        # Used to generate natural out-of-
        # domain replies instead of templates.
        # ===================================
        self.llm = LLMClient()

        # ===================================
        # System Prompt for out-of-domain LLM
        # ===================================
        self._system_prompt = (
            "You are Tolet AI, a friendly rental property assistant focused exclusively "
            "on helping users find rental homes across India (apartments, houses, villas, PGs).\n\n"
            "The user just asked something outside your domain. Your job is to:\n"
            "1. Acknowledge their question naturally and warmly — don't be robotic.\n"
            "2. Briefly explain that this is outside what you can help with.\n"
            "3. Let them know you're here for rental property searches in India.\n\n"
            "Keep it SHORT (2–3 sentences max). Sound like a helpful human assistant, "
            "not a bot reciting a policy. Do NOT add CTAs, emojis, or suggest they "
            "look elsewhere in detail — just gently redirect."
        )

        # ===================================
        # Filler words — kept for _extract_topic
        # which is used as fallback topic label.
        # ===================================
        self.topic_filler_words = {
            "please", "explain", "me", "what", "is", "are", "a", "an", "the",
            "about", "tell", "describe", "define", "how", "does", "do", "i",
            "can", "you", "help", "understand", "give", "some", "info", "on",
            "meaning", "of", "why", "when", "where", "who", "which", "could",
            "would", "should", "just", "really", "actually", "basically",
        }

        # ===================================
        # Fallback Templates
        # Used only when the LLM call fails.
        # ===================================
        self._fallback_templates = [
            "That's outside what I can help with — I'm built specifically for rental property searches across India. For anything else, a general assistant would serve you better.",
            "Great question, but it's a bit outside my lane! I'm Tolet AI, focused entirely on helping you find rental homes across India.",
            "Hmm, that one's beyond my area — I'm here purely for rental property queries in India. Happy to help if you're looking for a place to rent!",
            "That's not something I'm able to assist with, unfortunately. My expertise is all about rental properties across Indian cities — feel free to ask me anything on that front!",
        ]

    # ===================================
    # Domain Check
    # Uses whole-word regex matching to
    # prevent substring false positives
    # e.g. "lease" inside "please".
    # ===================================
    def is_allowed(self, query: str) -> bool:
        query_lower = query.lower().strip()
        for kw in self.allowed_keywords:
            pattern = r'\b' + re.escape(kw) + r'\b'
            if re.search(pattern, query_lower):
                return True
        return False

    # ===================================
    # Extract Topic (no LLM)
    # Strips filler words; used as context
    # hint in the LLM user prompt.
    # ===================================
    def _extract_topic(self, query: str) -> str:
        words = re.sub(r'[^\w\s]', '', query.lower()).split()
        meaningful = [w for w in words if w not in self.topic_filler_words]
        topic = " ".join(meaningful[:4]) if meaningful else "that topic"
        return topic

    # ===================================
    # Out-of-Domain Response
    # Tries LLM first; falls back to a
    # static reply if the LLM errors out.
    # ===================================
    def get_response(self, query: str) -> str:

        try:

            user_prompt = (
                f"The user asked: \"{query}\"\n\n"
                f"Respond naturally as Tolet AI, redirecting them "
                f"since this is outside your domain."
            )

            response = self.llm.chat(
                system_prompt=self._system_prompt,
                user_prompt=user_prompt,
                temperature=0.7,   # warmer / more varied tone
                max_tokens=120,    # keep it short
            )

            # Guard: if LLM returns empty/None, fall through to fallback
            if response and response.strip():
                return response.strip()

        except Exception as error:
            print("DomainGuard LLM error:", error)

        # ===================================
        # Fallback — static reply
        # ===================================
        import random
        return random.choice(self._fallback_templates)