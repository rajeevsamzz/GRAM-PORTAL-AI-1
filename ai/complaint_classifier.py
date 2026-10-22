from pathlib import Path
import joblib

CATEGORY_OPTIONS = ["Water", "Garbage", "Road", "Drainage", "Streetlight"]
MODEL_PATH = Path(__file__).parent / "models" / "complaint_classifier.joblib"


def _load_model():
    if not MODEL_PATH.exists():
        from train_model import train
        train()
    return joblib.load(MODEL_PATH)


def classify_complaint(text):
    model = _load_model()
    prediction = model.predict([text])[0]
    confidence = float(max(model.predict_proba([text])[0]))
    departments = {"Water": "Water Supply Department", "Garbage": "Sanitation Department", "Road": "Engineering Department", "Drainage": "Engineering/Drainage Department", "Streetlight": "Electrical Department"}
    return prediction, confidence, departments[prediction]