from datetime import datetime


def calculate_priority(text, category, duplicate_count=0, created_at=None):
    """Return a transparent 0-100 priority score and label."""
    value = 10
    lowered = text.lower()
    for word, points in {"danger": 25, "dangerous": 25, "accident": 22, "injury": 22, "contaminated": 25, "poison": 25, "urgent": 18, "blocked": 12, "school": 14, "hospital": 16, "collapse": 20, "fire": 25}.items():
        if word in lowered:
            value += points
    value += {"Water": 10, "Road": 8, "Drainage": 7, "Garbage": 5, "Streetlight": 4}.get(category, 0)
    value += min(duplicate_count * 5, 20)
    if created_at:
        try:
            age = (datetime.now() - datetime.fromisoformat(created_at)).total_seconds() / 86400
            value += min(max(int(age), 0), 15)
        except ValueError:
            pass
    score = min(value, 100)
    level = "CRITICAL" if score >= 80 else "HIGH" if score >= 60 else "MEDIUM" if score >= 40 else "LOW"
    return score, level