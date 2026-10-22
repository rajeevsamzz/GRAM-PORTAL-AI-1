from pathlib import Path
import joblib
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline

DATA = {"Water": ["dirty water pipeline", "no water supply", "water leakage", "contaminated drinking water", "tap is dry", "water overflowing"], "Garbage": ["garbage piled near road", "waste collection missed", "dirty bin", "plastic waste everywhere", "rubbish at bus stop", "unclean garbage"], "Road": ["pothole on road", "road is broken", "street accident due to road", "damaged bridge", "cracked road surface", "road repair needed"], "Drainage": ["drain is blocked", "sewage overflowing", "waterlogging after rain", "open drain near house", "dirty drainage", "clogged gutter"], "Streetlight": ["street light not working", "dark road at night", "broken electric lamp", "lamp post outage", "streetlight flickering", "no light near school"]}


def train():
    texts, labels = [], []
    for label, examples in DATA.items():
        texts.extend(examples)
        labels.extend([label] * len(examples))
    model = Pipeline([("tfidf", TfidfVectorizer(ngram_range=(1, 2), lowercase=True)), ("classifier", LogisticRegression(max_iter=1000))])
    model.fit(texts, labels)
    output = Path(__file__).parent / "ai" / "models" / "complaint_classifier.joblib"
    output.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, output)
    return output


if __name__ == "__main__":
    print(f"Saved model to {train()}")