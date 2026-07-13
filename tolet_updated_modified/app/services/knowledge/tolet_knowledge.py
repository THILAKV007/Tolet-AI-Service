import os


class ToletKnowledge:

    def __init__(self):

        # ===================================
        # Knowledge File Path
        # ===================================
        self.file_path = (
            "data/tolet_knowledge.txt"
        )

        # ===================================
        # Cached Content
        # ===================================
        self.cached_content = None

    # ===================================
    # Load Knowledge File
    # ===================================
    def load_knowledge(self):

        try:

            # ===================================
            # File Exists Check
            # ===================================
            if not os.path.exists(
                self.file_path
            ):

                return (
                    "Tolet AI is an intelligent "
                    "real-estate rental assistant."
                )

            # ===================================
            # Read File
            # ===================================
            with open(

                self.file_path,

                "r",

                encoding="utf-8"
            ) as file:

                content = file.read().strip()

            # ===================================
            # Cache
            # ===================================
            self.cached_content = content

            return content

        except Exception as error:

            print(
                "Knowledge Load Error:",
                error
            )

            return (
                "Tolet AI helps users search "
                "rental properties intelligently."
            )

        # ===================================
    # Get Knowledge
    # ===================================
    def get_knowledge(self):

        if self.cached_content:

            return self.cached_content

        return self.load_knowledge()

    # ===================================
    # Get Context
    # ===================================
    def get_context(

        self,

        query: str = ""
    ):

        return self.get_knowledge()

    # ===================================
    # Detect Tolet AI Query
    # ===================================
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
            "who created",
            "goal",
            "purpose",
            "startup",
            "company"
        ]

        for keyword in keywords:

            if keyword in query:

                return True

        return False