# ===================================
# setup_db.py
# Seeds sample properties into MongoDB
# based on the actual Property schema.
# Run once: python setup_db.py
# ===================================

import os
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()

try:
    from pymongo import MongoClient
    from bson import ObjectId
except ImportError:
    print("pymongo not installed. Run: pip install pymongo")
    exit()


# ===================================
# Connect
# ===================================
uri     = os.getenv("MONGODB_URI", "mongodb://localhost:27017")
db_name = os.getenv("MONGODB_DB", "tolet_db")

try:
    client     = MongoClient(uri, serverSelectionTimeoutMS=5000)
    db         = client[db_name]
    collection = db["properties"]
    client.admin.command("ping")
    print(f"Connected to MongoDB Atlas — database: {db_name}")
except Exception as e:
    print(f"Connection failed: {e}")
    exit()


# ===================================
# Sample Properties
# Matches actual Property schema
# ===================================
sample_properties = [
    {
        "user":               ObjectId(),
        "propertyType":       "Apartment",
        "locality":           "Anna Nagar",
        "apartmentType":      "2BHK",
        "city":               "Chennai",
        "bedRoomCount":       2,
        "bathroomCount":      2,
        "balconyCount":       1,
        "floorNumber":        3,
        "totalNumberOfFloor": 6,
        "propertyFacing":     "East",
        "state":              "Tamil Nadu",
        "sqFt":               "1100",
        "availableFrom":      "Immediate",
        "furnishedType":      "Semi-Furnished",
        "preferredTenant":    "Family",
        "gender":             "Any",
        "propertyAge":        "2 years",
        "waterResource":      "Corporation",
        "availableAmenities": [
            {"title": "Lift"},
            {"title": "Power Backup"},
            {"title": "Security"},
        ],
        "monthlyRent":        22000,
        "maintenance":        500,
        "securityDeposit":    "2 months",
        "electricityBill":    "Tenant",
        "noticePeriod":       "1 month",
        "isBrokerExcuse":     True,
        "petsAllowed":        "No",
        "ownerAtPlace":       "No",
        "paidRentalVia":      "Online",
        "photos":             [{"url": ""}],
        "additionalDetails":  "Well-maintained apartment in prime location.",
        "preferredTimeToTalk":["Morning", "Evening"],
        "createdAt":          datetime.now(timezone.utc),
        "updatedAt":          datetime.now(timezone.utc),
    },
    {
        "user":               ObjectId(),
        "propertyType":       "House",
        "locality":           "Tambaram",
        "apartmentType":      "3BHK",
        "city":               "Chennai",
        "bedRoomCount":       3,
        "bathroomCount":      2,
        "balconyCount":       2,
        "floorNumber":        0,
        "totalNumberOfFloor": 2,
        "propertyFacing":     "North",
        "state":              "Tamil Nadu",
        "sqFt":               "1500",
        "availableFrom":      "Immediate",
        "furnishedType":      "Fully-Furnished",
        "preferredTenant":    "Family",
        "gender":             "Any",
        "propertyAge":        "5 years",
        "waterResource":      "Borewell",
        "availableAmenities": [
            {"title": "Car Parking"},
            {"title": "Garden"},
        ],
        "monthlyRent":        25000,
        "maintenance":        1000,
        "securityDeposit":    "3 months",
        "electricityBill":    "Tenant",
        "noticePeriod":       "2 months",
        "isBrokerExcuse":     False,
        "petsAllowed":        "Yes",
        "ownerAtPlace":       "No",
        "paidRentalVia":      "Online",
        "photos":             [{"url": ""}],
        "additionalDetails":  "Independent house with garden and covered parking.",
        "preferredTimeToTalk":["Evening"],
        "createdAt":          datetime.now(timezone.utc),
        "updatedAt":          datetime.now(timezone.utc),
    },
    {
        "user":               ObjectId(),
        "propertyType":       "PG",
        "locality":           "Velachery",
        "apartmentType":      "1BHK",
        "city":               "Chennai",
        "bedRoomCount":       1,
        "bathroomCount":      1,
        "balconyCount":       0,
        "floorNumber":        1,
        "totalNumberOfFloor": 3,
        "propertyFacing":     "West",
        "state":              "Tamil Nadu",
        "sqFt":               "450",
        "availableFrom":      "Immediate",
        "furnishedType":      "Fully-Furnished",
        "preferredTenant":    "Bachelor",
        "gender":             "Male",
        "occupancy":          "Single",
        "propertyAge":        "3 years",
        "waterResource":      "Corporation",
        "availableAmenities": [
            {"title": "WiFi"},
            {"title": "Laundry"},
            {"title": "Mess"},
        ],
        "monthlyRent":        8000,
        "maintenance":        0,
        "securityDeposit":    "1 month",
        "electricityBill":    "Included",
        "noticePeriod":       "15 days",
        "isBrokerExcuse":     True,
        "petsAllowed":        "No",
        "ownerAtPlace":       "Yes",
        "paidRentalVia":      "Online",
        "photos":             [{"url": ""}],
        "additionalDetails":  "PG near Velachery metro, meals included.",
        "preferredTimeToTalk":["Morning"],
        "createdAt":          datetime.now(timezone.utc),
        "updatedAt":          datetime.now(timezone.utc),
    },
    {
        "user":               ObjectId(),
        "propertyType":       "Flat",
        "locality":           "Ambattur",
        "apartmentType":      "2BHK",
        "city":               "Chennai",
        "bedRoomCount":       2,
        "bathroomCount":      1,
        "balconyCount":       1,
        "floorNumber":        2,
        "totalNumberOfFloor": 4,
        "propertyFacing":     "South",
        "state":              "Tamil Nadu",
        "sqFt":               "950",
        "availableFrom":      "15 days",
        "furnishedType":      "Semi-Furnished",
        "preferredTenant":    "Any",
        "gender":             "Any",
        "propertyAge":        "4 years",
        "waterResource":      "Corporation",
        "availableAmenities": [
            {"title": "Lift"},
            {"title": "Car Parking"},
            {"title": "Power Backup"},
        ],
        "monthlyRent":        15000,
        "maintenance":        500,
        "securityDeposit":    "2 months",
        "electricityBill":    "Tenant",
        "noticePeriod":       "1 month",
        "isBrokerExcuse":     True,
        "petsAllowed":        "No",
        "ownerAtPlace":       "No",
        "paidRentalVia":      "Online",
        "photos":             [{"url": ""}],
        "additionalDetails":  "Affordable flat near Ambattur industrial estate.",
        "preferredTimeToTalk":["Evening", "Night"],
        "createdAt":          datetime.now(timezone.utc),
        "updatedAt":          datetime.now(timezone.utc),
    },
    {
        "user":               ObjectId(),
        "propertyType":       "Apartment",
        "locality":           "Avadi",
        "apartmentType":      "2BHK",
        "city":               "Chennai",
        "bedRoomCount":       2,
        "bathroomCount":      2,
        "balconyCount":       1,
        "floorNumber":        1,
        "totalNumberOfFloor": 5,
        "propertyFacing":     "East",
        "state":              "Tamil Nadu",
        "sqFt":               "1050",
        "availableFrom":      "Immediate",
        "furnishedType":      "Semi-Furnished",
        "preferredTenant":    "Bachelor",
        "gender":             "Any",
        "propertyAge":        "1 year",
        "waterResource":      "Corporation",
        "availableAmenities": [
            {"title": "Metro Nearby"},
            {"title": "Power Backup"},
            {"title": "Security"},
        ],
        "monthlyRent":        18000,
        "maintenance":        500,
        "securityDeposit":    "2 months",
        "electricityBill":    "Tenant",
        "noticePeriod":       "1 month",
        "isBrokerExcuse":     True,
        "petsAllowed":        "No",
        "ownerAtPlace":       "No",
        "paidRentalVia":      "Online",
        "photos":             [{"url": ""}],
        "additionalDetails":  "Modern apartment close to Avadi metro station.",
        "preferredTimeToTalk":["Morning", "Evening"],
        "createdAt":          datetime.now(timezone.utc),
        "updatedAt":          datetime.now(timezone.utc),
    },
]


# ===================================
# Insert (skip if already seeded)
# ===================================
existing = collection.count_documents({})

if existing > 0:
    print(f"Collection already has {existing} documents. Skipping insert.")
    print("To re-seed, drop the collection first.")
else:
    result = collection.insert_many(sample_properties)
    print(f"Inserted {len(result.inserted_ids)} properties.")


# ===================================
# Verify
# ===================================
rows = list(collection.find(
    {},
    {"_id": 1, "apartmentType": 1, "locality": 1, "city": 1, "monthlyRent": 1, "bedRoomCount": 1}
))
print(f"\nTotal properties in MongoDB: {len(rows)}")
print("\n--- Properties ---")
for row in rows:
    print(
        f"  ID:{row['_id']} | "
        f"{row.get('apartmentType','?')} | "
        f"{row.get('locality','?')}, {row.get('city','?')} | "
        f"₹{row.get('monthlyRent','?')} | "
        f"{row.get('bedRoomCount','?')}BHK"
    )

client.close()
print("\nDone! Your MongoDB is ready.")