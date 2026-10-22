RULES = {
    "Water Problem": (
        ["water", "pipe", "drinking", "tap", "supply", "leakage", "no water", "water shortage"],
        "Water Supply",
    ),
    "Road": (
        ["road", "pothole", "street", "traffic", "bridge"],
        "Engineering",
    ),
    "Social Problem": (
        ["garbage", "waste", "trash", "dump", "dirty", "sanitation", "social", "public nuisance"],
        "Sanitation",
    ),
    "Streetlight": (
        ["street light", "streetlight", "lamp", "light not working", "dark"],
        "Electrical",
    ),
    "Drainage Problem": (
        ["drain", "drainage", "sewage", "overflow", "gutter", "waterlogging"],
        "Sanitation",
    ),
    "PWD": (
        ["pwd", "disability", "accessible", "wheelchair", "handicap"],
        "PWD Department",
    ),
    "Transportation Problem": (
        ["transport", "transportation", "bus", "bus stop", "vehicle", "public transit"],
        "Transportation",
    ),
    "Milk Dairy Problem": (
        ["milk", "dairy", "cattle", "cow", "buffalo", "milk collection"],
        "Dairy Department",
    ),
    "Electricity Problem": (
        ["electricity", "power cut", "power outage", "voltage", "transformer", "electric"],
        "Electrical",
    ),
    "Other Problems": ([], "Panchayat Office"),
}

CATEGORY_OPTIONS = list(RULES.keys()) + ["Water", "Garbage", "Drainage", "General"]


def classify_complaint(text):
    text = text.lower()
    scores = {
        category: sum(keyword in text for keyword in keywords)
        for category, (keywords, _) in RULES.items()
    }
    maximum = max(scores.values())
    category = "Other Problems" if maximum == 0 else max(scores, key=scores.get)
    department = RULES[category][1]

    emergency_words = ["danger", "accident", "fire", "contaminated", "school", "hospital", "urgent"]
    if any(word in text for word in emergency_words):
        priority = "High"
    elif category in ["Water Problem", "Road", "Drainage Problem", "Streetlight", "PWD", "Transportation Problem", "Electricity Problem"]:
        priority = "Medium"
    else:
        priority = "Low"

    return category, priority, department
