import re


class RuleBasedExtractor:

    def extract(

        self,

        query: str
    ):

        query = query.lower()


        filters = {

            "bhk": None,

            "max_price": None,

            "location": None,

            "property_type": None,

            "furnished": None,

            "near_metro": False,

            "tenant_type": None,

            "budget_preference": None
        }

        bhk_match = re.search(

            r'(\d+)\s*bhk',

            query
        )

        if bhk_match:

            filters["bhk"] = int(

                bhk_match.group(1)
            )

        price_match = re.search(

            r'(under|below|max)?\s*₹?\s*(\d+)(k)?',

            query
        )

        if price_match:

            amount = int(

                price_match.group(2)
            )

            if price_match.group(3):

                amount *= 1000

            if amount >= 1000:

                filters["max_price"] = amount

        if "fully furnished" in query:

            filters["furnished"] = (
                "fully furnished"
            )

        elif "semi furnished" in query:

            filters["furnished"] = (
                "semi furnished"
            )

        elif "furnished" in query:

            filters["furnished"] = (
                "furnished"
            )

        if "near metro" in query:

            filters["near_metro"] = True

        property_types = [

            "house",
            "apartment",
            "flat",
            "villa",
            "pg",
            "studio",
            "1rk",
            "2rk"
        ]

        # FIX: parse 1rk/2rk as bhk=1/bhk=2 + property_type=rk
        rk_match = re.search(r"(\d+)\s*rk", query)
        if rk_match:
            filters["bhk"] = int(rk_match.group(1))
            filters["property_type"] = "rk"

        for property_type in property_types:

            if property_type in query:

                filters["property_type"] = (
                    property_type
                )

                break

        if re.search(r"\bbachelors?\b", query):

            filters["tenant_type"] = (
                "bachelor"
            )

        elif "family" in query:

            filters["tenant_type"] = (
                "family"
            )

        budget_words = [

            "cheap",
            "affordable",
            "low budget",
            "budget friendly"
        ]

        for word in budget_words:

            if word in query:

                filters[
                    "budget_preference"
                ] = "affordable"

                break

        locations = [

            "avadi",
            "ambattur",
            "velachery",
            "tambaram",
            "porur",
            "anna nagar",
            "t nagar",
            "guindy",
            "medavakkam",
            "poonamallee"
        ]

        for location in locations:

            if location in query:

                filters["location"] = (

                    location.title()
                )

                break

        return filters