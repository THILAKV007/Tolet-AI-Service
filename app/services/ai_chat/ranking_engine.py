class RankingEngine:

    def rank(

        self,

        filters: dict,

        properties: list
    ):

        ranked_properties = []

        for property_item in properties:

            score = 0

            # ===================================
            # Location Score
            # ===================================
            if (

                filters.get("location")

                and

                property_item.get(
                    "location"
                )
            ):

                if (

                    filters["location"]
                    .lower()

                    ==

                    property_item[
                        "location"
                    ].lower()
                ):

                    score += 50

            # ===================================
            # BHK Score
            # ===================================
            if (

                filters.get("bhk")

                and

                property_item.get("bhk")
            ):

                if (

                    filters["bhk"]

                    ==

                    property_item["bhk"]
                ):

                    score += 30

            # ===================================
            # Budget Score
            # ===================================
            if (

                filters.get("max_price")

                and

                property_item.get("price")
            ):

                if (

                    property_item["price"]

                    <=

                    filters["max_price"]
                ):

                    score += 25

                else:

                    score -= 20

            # ===================================
            # Furnished Score
            # ===================================
            if (

                filters.get("furnished")

                and

                property_item.get(
                    "furnished"
                )
            ):

                if (

                    filters["furnished"]

                    ==

                    property_item[
                        "furnished"
                    ]
                ):

                    score += 20

            # ===================================
            # Metro Score
            # ===================================
            if (

                filters.get("near_metro")
            ):

                if property_item.get(
                    "near_metro"
                ):

                    score += 15

            # ===================================
            # Bachelor Preference
            # ===================================
            if (

                "bachelor"

                in

                str(filters).lower()
            ):

                if property_item.get(
                    "bachelor_friendly"
                ):

                    score += 20

            # ===================================
            # Family Preference
            # ===================================
            if (

                "family"

                in

                str(filters).lower()
            ):

                if property_item.get(
                    "family_friendly"
                ):

                    score += 20

            property_item["score"] = (
                score
            )

            ranked_properties.append(
                property_item
            )


        ranked_properties.sort(

            key=lambda item: item[
                "score"
            ],

            reverse=True
        )

        return ranked_properties