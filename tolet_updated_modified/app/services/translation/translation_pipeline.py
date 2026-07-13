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

        query = re.sub(
            r"[^a-zA-Z0-9\s]",
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

        cleaned_query = self.normalize_text(query)

        translated_query = (
            self.translator
            .translate_tanglish_to_english(
                cleaned_query
            )
        )

        # Safety guard: translator can return None if the API response has a
        # null translated_text field. Fall back to cleaned_query in that case.
        translated_query = (translated_query or cleaned_query).lower().strip()

        return {
            "original_query":   query,
            "cleaned_query":    cleaned_query,
            "translated_query": translated_query
        }