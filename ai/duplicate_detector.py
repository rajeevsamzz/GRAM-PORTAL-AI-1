from math import asin, cos, radians, sin, sqrt
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity


def distance_km(lat1, lon1, lat2, lon2):
    if None in (lat1, lon1, lat2, lon2):
        return None
    value = sin(radians(lat2 - lat1) / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(radians(lon2 - lon1) / 2) ** 2
    return round(2 * 6371 * asin(sqrt(value)), 2)


def find_similar(connection, description, category, latitude, longitude, limit=5):
    rows = connection.execute("SELECT id, ticket, description, category, latitude, longitude, status FROM complaints ORDER BY id DESC").fetchall()
    matches = []
    for row in rows:
        if row["category"] != category:
            continue
        distance = distance_km(latitude, longitude, row["latitude"], row["longitude"])
        if distance is not None and distance > 2:
            continue
        score = 0.0
        if row["description"]:
            score = float(cosine_similarity(TfidfVectorizer().fit_transform([description, row["description"]]))[0, 1])
        if score >= 0.35:
            matches.append({"ticket": row["ticket"], "similarity": round(score * 100), "distance": distance, "status": row["status"], "id": row["id"]})
    return sorted(matches, key=lambda item: item["similarity"], reverse=True)[:limit]


def find_duplicate(connection, description, latitude, longitude, user_id):
    exact = connection.execute("SELECT ticket FROM complaints WHERE user_id = ? AND lower(description) = lower(?) ORDER BY id DESC LIMIT 1", (user_id, description)).fetchone()
    return exact["ticket"] if exact else None