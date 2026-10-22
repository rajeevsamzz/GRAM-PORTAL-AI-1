def analyze_image(path):
    """No domain-trained vision model is bundled; never fabricate a result."""
    return {"available": False, "message": "Image analysis unavailable"}