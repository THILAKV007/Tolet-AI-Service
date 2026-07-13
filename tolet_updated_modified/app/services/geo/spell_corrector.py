"""
spell_corrector.py — Location Spell Corrector
==============================================
Corrects misspelled locality names BEFORE they reach the geocoder.

Strategy (3-pass fuzzy match):
  Pass 1 — Exact match (no correction needed)
  Pass 2 — difflib.get_close_matches against known Chennai localities list
  Pass 3 — Token-level edit-distance against the same list

The known-locality corpus is built from two sources (merged, deduplicated):
  A) The DB localities list passed in at call time (live, always current)
  B) A bundled Chennai-area reference list (fallback for unknown DB localities)

Usage:
    corrector = LocationSpellCorrector()
    corrected, was_corrected = corrector.correct("thirumulaivoyel", db_localities)
    # → ("Thirumullaivoyal", True)
"""

import re
import logging
from typing import Tuple, List, Optional

logger = logging.getLogger(__name__)

# rapidfuzz is a C++-backed fuzzy matcher — faster and more accurate than
# stdlib difflib (real Levenshtein-family scoring vs difflib's
# Ratcliff/Obershelp heuristic, and no O(n^2) Python-level comparison loop).
# Falls back to difflib if it's not installed yet, same pattern used
# elsewhere in this codebase (see property_db_service.py's pymongo check).
try:
    from rapidfuzz import fuzz, process as rf_process
    RAPIDFUZZ_AVAILABLE = True
except ImportError:
    RAPIDFUZZ_AVAILABLE = False
    import difflib
    print("[SpellCorrector] rapidfuzz not installed — falling back to difflib "
          "(slower, less accurate). Run: pip install rapidfuzz")

# ── Bundled reference list (common Chennai localities) ────────────────────────
# This covers names that may not yet be in the DB but are well-known.
# Add more as needed — lowercase only, the corrector handles casing.
_CHENNAI_REFERENCE_LOCALITIES = [
    "adyar", "adambakkam", "alandur", "ambattur", "aminjikarai",
    "anna nagar", "anna nagar west", "anna nagar east",
    "arumbakkam", "ashok nagar", "avadi", "ayapakkam",
    "besant nagar", "chromepet", "chinmaya nagar", "gerugambakkam", "guindy",
    "iyappanthangal", "injambakkam", "jafarkhanpet",
    "kk nagar", "k.k. nagar", "kkr nagar",
    "kodambakkam", "korattur", "kovilambakkam", "koyambedu",
    "kilpauk", "kolathur", "korukkupet",
    "madipakkam", "maduravoyal", "manali", "mangadu",
    "medavakkam", "mogappair", "mogappair east", "mogappair west",
    "mugalivakkam", "mylapore",
    "nanganallur", "nandanam", "nerkundram", "nolambur",
    "padi", "pallavaram", "pallikaranai", "pammal",
    "pattaravakkam", "perambur", "perungalathur", "perungudi", "porur",
    "poonamallee", "purasaiwakkam",
    "ramapuram", "royapettah", "royapuram",
    "saidapet", "sekaran", "sholinganallur",
    "tambaram", "teynampet", "thiruvanmiyur", "thirumullaivoyal",
    "thirumulaivoyal", "thirumangalam", "thiruverkadu",
    "t nagar", "t.nagar", "tnagar", "tondiarpet",
    "urapakkam", "valasaravakkam", "vanagaram",
    "vadapalani", "velachery", "virugambakkam",
    "west mambalam", "periyar nagar", "nungambakkam",
    "egmore", "fort", "park town", "vepery",
    "madhavaram", "manambakkam", "selaiyur", "chitlapakkam",
    "chrompet", "pallikkaranai", "jalladianpet",
    "peerkankaranai", "ottiyambakkam", "mudichur",
    "kundrathur", "manapakkam", "zamin pallavaram",
    "meenambakkam", "tirusulam", "singaperumalkoil",
    "pozhichalur", "anakaputhur", "ayanambakkam",
    "senneerkuppam", "alwal", "sembakkam",
    "madambakkam", "thoraipakkam", "perungalathur",
    "velappanchavadi", "pattabiram",
]

# ── City / State reference list ────────────────────────────────────────────
# The locality list above only helps within Chennai. Your actual property
# data spans many cities (Kochi, Bangalore, Kolkata, Mumbai, Puducherry,
# Bhubaneshwar, Port Blair, Coimbatore, Mangaluru, Mysuru, even Colombo) —
# without this, a typo like "banglore" or "mumbay" gets no correction at all,
# even though "ambatur" → "ambattur" works fine. Include common alternate
# spellings so both the old and new official names resolve correctly.
_CITY_STATE_REFERENCE = [
    "chennai", "bangalore", "bengaluru", "kochi", "cochin", "coimbatore",
    "mumbai", "kolkata", "puducherry", "pondicherry", "bhubaneshwar",
    "bhubaneswar", "port blair", "mangaluru", "mangalore", "mysuru",
    "mysore", "colombo", "hyderabad", "delhi", "new delhi", "pune",
    "ahmedabad", "surat", "jaipur", "lucknow", "kanpur", "nagpur",
    "indore", "thane", "visakhapatnam", "vadodara", "madurai",
    "tiruchirappalli", "trichy", "salem", "vellore", "erode", "tirunelveli",
    "tamil nadu", "tamilnadu", "kerala", "karnataka", "maharashtra",
    "west bengal", "odisha", "andaman & nicobar islands",
    "andaman and nicobar islands", "sri lanka",
]


class LocationSpellCorrector:
    """
    Fuzzy spell-corrector for Indian locality names.
    Handles:
     - Missing/extra vowels  (thirumulaivoyal → Thirumullaivoyal)
     - Transpositions        (velacery → Velachery)
     - Common phonetic subs  (kk nagar vs K.K. Nagar)
     - Missing spaces        (tnagarr → T Nagar)
    """

    # Similarity threshold — strings below this score are not substituted.
    # 0.75 is strict enough to block false positives like
    # "pattaravakkam" → "valasaravakkam" (shared "-avakkam" suffix, score 0.74)
    # while still catching genuine typos (ambatur→ambattur scores 0.93, etc).
    CUTOFF = 0.75

    # Never try to correct very short strings — too noisy.
    MIN_LENGTH = 4

    def __init__(self):
        self._ref_set: set = set(_CHENNAI_REFERENCE_LOCALITIES) | set(_CITY_STATE_REFERENCE)

    # ── Public API ─────────────────────────────────────────────────────────────

    def correct(
        self,
        raw_location: str,
        db_localities: Optional[List[str]] = None
    ) -> Tuple[str, bool]:
        """
        Correct a potentially misspelled location name.

        Args:
            raw_location:   The string the user typed (e.g. "thirumulaivoyal")
            db_localities:  Live list of locality names from the property DB

        Returns:
            (corrected_name, was_corrected)
            - corrected_name  — best match if confidence is high, else raw_location
            - was_corrected   — True if a substitution was made
        """
        if not raw_location or len(raw_location.strip()) < self.MIN_LENGTH:
            return raw_location, False

        query = raw_location.strip()
        query_norm = self._normalise(query)

        # Build corpus: DB localities + reference list (lowercase, normalised)
        corpus = self._build_corpus(db_localities)

        # Pass 1 — Exact normalised match (no correction needed)
        for canonical, norm in corpus:
            if norm == query_norm:
                logger.debug(f"[SpellCorrector] Exact match: '{query}' → '{canonical}'")
                return canonical, False

        # Pass 2 — fuzzy close match on normalised strings
        norm_list   = [n for _, n in corpus]
        canon_list  = [c for c, _ in corpus]
        match = self._best_match(query_norm, norm_list, cutoff=self.CUTOFF)
        if match:
            close_str, score = match
            idx       = norm_list.index(close_str)
            canonical = canon_list[idx]
            logger.info(
                f"[SpellCorrector] '{query}' → '{canonical}' "
                f"(score={score:.2f}, pass=2-fuzzy)"
            )
            return canonical, canonical.lower() != query.lower()

        # Pass 3 — Token-level: split multi-word query and match each token
        tokens      = query_norm.split()
        if len(tokens) > 1:
            corrected_tokens = []
            changed          = False
            for tok in tokens:
                if len(tok) < self.MIN_LENGTH:
                    corrected_tokens.append(tok)
                    continue
                tok_match = self._best_match(tok, norm_list, cutoff=self.CUTOFF)
                if tok_match:
                    tok_close = tok_match[0]
                    corrected_tokens.append(tok_close)
                    if tok_close != tok:
                        changed = True
                else:
                    corrected_tokens.append(tok)
            if changed:
                reconstructed = " ".join(corrected_tokens)
                # Find closest full canonical for the reconstructed string
                full_match = self._best_match(reconstructed, norm_list, cutoff=0.55)
                if full_match:
                    idx       = norm_list.index(full_match[0])
                    canonical = canon_list[idx]
                    logger.info(
                        f"[SpellCorrector] '{query}' → '{canonical}' (pass=3-token)"
                    )
                    return canonical, canonical.lower() != query.lower()

        logger.debug(f"[SpellCorrector] No correction found for '{query}'")
        return query, False

    # ── Fuzzy matching backend ────────────────────────────────────────────────

    def _best_match(
        self, query: str, candidates: List[str], cutoff: float
    ) -> Optional[Tuple[str, float]]:
        """
        Returns (best_candidate, score 0-1) or None if nothing clears cutoff.
        Uses rapidfuzz (token_sort_ratio — robust to word order and length
        differences, e.g. "nagar anna" vs "anna nagar") when available,
        else falls back to difflib's SequenceMatcher.
        """
        if not candidates:
            return None
        if RAPIDFUZZ_AVAILABLE:
            result = rf_process.extractOne(
                query, candidates, scorer=fuzz.token_sort_ratio,
                score_cutoff=cutoff * 100
            )
            if result:
                match_str, score, _ = result
                return match_str, score / 100
            return None
        else:
            close = difflib.get_close_matches(query, candidates, n=1, cutoff=cutoff)
            if close:
                score = difflib.SequenceMatcher(None, query, close[0]).ratio()
                return close[0], score
            return None

    # ── Helpers ────────────────────────────────────────────────────────────────

    def _normalise(self, text: str) -> str:
        """Lowercase, remove punctuation, collapse whitespace."""
        t = text.lower()
        t = re.sub(r"[.\-_,']", " ", t)   # dots, hyphens → spaces
        t = re.sub(r"\s+", " ", t).strip()
        return t

    def _build_corpus(
        self, db_localities: Optional[List[str]]
    ) -> List[Tuple[str, str]]:
        """
        Return [(canonical_str, normalised_str), ...] corpus.
        DB localities take priority; reference list fills gaps.
        """
        seen_norms = set()
        corpus     = []

        # DB localities first (most authoritative)
        if db_localities:
            for loc in db_localities:
                loc_clean = loc.strip()
                norm      = self._normalise(loc_clean)
                if norm not in seen_norms:
                    seen_norms.add(norm)
                    corpus.append((loc_clean.title(), norm))

        # Reference list (supplemental) — Chennai localities + major
        # cities/states so typos outside Chennai get corrected too.
        for loc in _CHENNAI_REFERENCE_LOCALITIES + _CITY_STATE_REFERENCE:
            norm = self._normalise(loc)
            if norm not in seen_norms:
                seen_norms.add(norm)
                corpus.append((loc.title(), norm))

        return corpus