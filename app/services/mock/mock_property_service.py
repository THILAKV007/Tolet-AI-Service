class MockPropertyService:

    def __init__(self):

        self.properties = [

            {
                "id": 1,
                "title": "Modern 2BHK Apartment",
                "location": "Avadi",
                "price": 18000,
                "bhk": 2,
                "property_type": "apartment",
                "furnished": "semi",
                "near_metro": True,
                "bachelor_friendly": True,
                "family_friendly": False,
                "image": (
                    "https://images.unsplash.com/"
                    "photo-1502672260266-1c1ef2d93688"
                )
            },

            {
                "id": 2,
                "title": "Family 3BHK House",
                "location": "Tambaram",
                "price": 25000,
                "bhk": 3,
                "property_type": "house",
                "furnished": "fully",
                "near_metro": False,
                "bachelor_friendly": False,
                "family_friendly": True,
                "image": (
                    "https://images.unsplash.com/"
                    "photo-1568605114967-8130f3a36994"
                )
            },

            {
                "id": 3,
                "title": "Budget Bachelor PG",
                "location": "Velachery",
                "price": 8000,
                "bhk": 1,
                "property_type": "pg",
                "furnished": "fully",
                "near_metro": True,
                "bachelor_friendly": True,
                "family_friendly": False,
                "image": (
                    "https://images.unsplash.com/"
                    "photo-1522708323590-d24dbb6b0267"
                )
            },

            {
                "id": 4,
                "title": "Luxury Villa",
                "location": "Porur",
                "price": 45000,
                "bhk": 4,
                "property_type": "villa",
                "furnished": "fully",
                "near_metro": False,
                "bachelor_friendly": False,
                "family_friendly": True,
                "image": (
                    "https://images.unsplash.com/"
                    "photo-1600585154526-990dced4db0d"
                )
            },

            {
                "id": 5,
                "title": "Affordable 2BHK Flat",
                "location": "Ambattur",
                "price": 15000,
                "bhk": 2,
                "property_type": "flat",
                "furnished": "semi",
                "near_metro": True,
                "bachelor_friendly": True,
                "family_friendly": True,
                "image": (
                    "https://images.unsplash.com/"
                    "photo-1494526585095-c41746248156"
                )
            },

            {
                "id": 6,
                "title": "Premium Apartment",
                "location": "Anna Nagar",
                "price": 30000,
                "bhk": 3,
                "property_type": "apartment",
                "furnished": "fully",
                "near_metro": True,
                "bachelor_friendly": False,
                "family_friendly": True,
                "image": (
                    "https://images.unsplash.com/"
                    "photo-1484154218962-a197022b5858"
                )
            }
        ]

    def search(

        self,

        filters: dict
    ):

        results = []

        for property_item in self.properties:


            if (

                filters.get("bhk")

                and

                property_item["bhk"]

                !=

                filters["bhk"]
            ):

                continue


            if (

                filters.get("max_price")

                and

                property_item["price"]

                >

                filters["max_price"]
            ):

                continue


            if (

                filters.get("min_price")

                and

                property_item["price"]

                <

                filters["min_price"]
            ):

                continue


            if (

                filters.get("location")

                and

                property_item[
                    "location"
                ].lower()

                !=

                filters[
                    "location"
                ].lower()
            ):

                continue


            if (

                filters.get("furnished")

                and

                property_item[
                    "furnished"
                ]

                !=

                filters[
                    "furnished"
                ]
            ):

                continue

            # ===================================
            # Metro Filter
            # ===================================
            if (

                filters.get("near_metro")
            ):

                if not property_item[
                    "near_metro"
                ]:

                    continue

            tenant_type = filters.get("tenant_type")
            if tenant_type == "bachelor":
                if not property_item.get("bachelor_friendly"):
                    continue
            elif tenant_type == "family":
                if not property_item.get("family_friendly"):
                    continue

            results.append(
                property_item
            )

        return results