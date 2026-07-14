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

            # min_price is the other end of the same budget range — a
            # property cheaper than the user's stated minimum is just as
            # much a mismatch as one above their max (e.g. someone with a
            # ₹5,000–₹10,000 PG budget likely wants that price band, not
            # the cheapest possible option), so score it symmetrically.
            if (

                filters.get("min_price")

                and

                property_item.get("price")
            ):

                if (

                    property_item["price"]

                    >=

                    filters["min_price"]
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


        # Sort by score DESC, then distance_km ASC (closer = better tiebreaker).
        # Properties without distance_km (non-geo searches) get 0 distance → no effect.
        ranked_properties.sort(
            key=lambda item: (
                -item["score"],
                item.get("distance_km", 0)
            )
        )

        return ranked_properties