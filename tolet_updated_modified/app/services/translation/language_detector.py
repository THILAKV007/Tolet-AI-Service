class LanguageDetector:

    def detect(

        self,

        query: str
    ):

        query = query.lower()


        tamil_unicode_range = any(

            '\u0b80' <= char <= '\u0bff'

            for char in query
        )

        if tamil_unicode_range:

            return "tamil"

        tanglish_words = [

            "venum",
            "venam",
            "iruka",
            "ennaku",
            "veedu",
            "sapadu",
            "pakkanum",
            "inga",
            "near ah",
            "la",
            "ku"
        ]

        for word in tanglish_words:

            if word in query:

                return "tanglish"

        return "english"