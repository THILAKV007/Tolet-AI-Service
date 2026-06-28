class KnowledgeDetector:

    def is_tolet_query(

        self,

        query: str
    ):

        query = query.lower()

        keywords = [

            "what is tolet ai",
            "about tolet ai",
            "tolet ai",
            "vision",
            "mission",
            "who built tolet ai",
            "features of tolet ai",
            "why tolet ai",
            "what does tolet ai do",
            "how tolet ai works"
        ]

        for keyword in keywords:

            if keyword in query:

                return True

        return False