import psycopg2
from dotenv import load_dotenv
import os

load_dotenv()

conn = psycopg2.connect(
    host=os.getenv("DB_HOST"),
    port=os.getenv("DB_PORT"),
    dbname=os.getenv("DB_NAME"),
    user=os.getenv("DB_USER"),
    password=os.getenv("DB_PASSWORD")
)
conn.autocommit = True
cursor = conn.cursor()

updates = [
    (1, "https://images.unsplash.com/photo-1502672260266-1c1ef2d93688?w=400"),
    (2, "https://images.unsplash.com/photo-1568605114967-8130f3a36994?w=400"),
    (3, "https://images.unsplash.com/photo-1522708323590-d24dbb6b0267?w=400"),
    (4, "https://images.unsplash.com/photo-1600585154526-990dced4db0d?w=400"),
    (5, "https://images.unsplash.com/photo-1494526585095-c41746248156?w=400"),
    (6, "https://images.unsplash.com/photo-1484154218962-a197022b5858?w=400"),
    (7, "https://images.unsplash.com/photo-1560448204-e02f11c3d0e2?w=400"),
    (8, "https://images.unsplash.com/photo-1512917774080-9991f1c4c750?w=400"),
    (9, "https://images.unsplash.com/photo-1493809842364-78817add7ffb?w=400"),
    (10,"https://images.unsplash.com/photo-1554995207-c18c203602cb?w=400"),
]

for prop_id, image_url in updates:
    cursor.execute(
        "UPDATE properties SET image = %s WHERE id = %s",
        (image_url, prop_id)
    )
    print(f"Updated image for property ID {prop_id}")

cursor.close()
conn.close()
print("\nAll images updated!")