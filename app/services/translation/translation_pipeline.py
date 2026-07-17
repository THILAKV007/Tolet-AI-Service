import re

from services.translation.sarvam_translator import (
    SarvamTranslator
)


class TranslationPipeline:

    def __init__(self):

        self.translator = (
            SarvamTranslator()
        )

        self.normalization_map = {

            # Want
            "venum": "want",
            "venam": "want",
            "veanum": "want",
            "venaum": "want",

            # Need
            "theva": "need",
            "thevai": "need",

            # Location
            "la": "in",
            "ku": "for",
            "kitta": "near",

            # House
            "veedu": "house",
            "flatu": "flat",

            # Near
            "pakathula": "near",

            # Budget
            "kammi": "low",
            "cheap": "budget",

            # Misc
            "iruka": "available",
            "iruku": "available"
        }

    def normalize_text(self, query: str):

        query = query.lower()

        # Strip punctuation/symbols but PRESERVE Tamil Unicode script
        # (U+0B80–U+0BFF) as well as ASCII letters/digits. Previously this
        # stripped ALL non a-zA-Z0-9 characters, which silently blanked out
        # any Tamil-script text that reached here (e.g. if the translator
        # API call failed/timed out and the raw query was passed through
        # unchanged) instead of leaving it intact for a later fallback.
        query = re.sub(
            r"[^a-zA-Z0-9\u0B80-\u0BFF\s]",
            " ",
            query
        )

        words = query.split()

        normalized_words = []

        for word in words:

            normalized_words.append(
                self.normalization_map.get(
                    word,
                    word
                )
            )

        cleaned_query = " ".join(
            normalized_words
        )

        return cleaned_query

    def process(self, query: str):

        # Translate FIRST, on the RAW original query. This must happen
        # before normalize_text runs, because normalize_text's regex strips
        # every non-ASCII character (including all Tamil Unicode script) —
        # previously translation ran on the ALREADY-STRIPPED text, so a
        # message in Tamil script (e.g. "வணக்கம்") was blanked out before
        # the translator ever got a chance to see it, and the Sarvam API
        # was never actually called.
        translated_query = (
            self.translator
            .translate_tanglish_to_english(
                query
            )
        )

        # Safety guard: translator can return None if the API response has a
        # null translated_text field. Fall back to the raw query in that case.
        translated_query = (translated_query or query).strip()

        # normalize_text now runs on the TRANSLATED (already-English, or
        # unchanged-if-plain-English) text — safe to ASCII-strip at this
        # point, and this is also where the Tanglish word-substitution map
        # (venum -> want, etc.) still catches anything Sarvam left alone.
        cleaned_query = self.normalize_text(translated_query)

        return {
            "original_query":   query,
            "cleaned_query":    cleaned_query,
            "translated_query": translated_query.lower()
        }