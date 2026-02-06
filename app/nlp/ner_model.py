"""OpenMed PharmaDetect NER model wrapper.

Loads the model once at startup and exposes a predict() function
that extracts drug/chemical entities from text.
"""

from dataclasses import dataclass

from transformers import pipeline

MODEL_ID = "OpenMed/OpenMed-NER-PharmaDetect-ModernClinical-149M"

_ner_pipeline = None


@dataclass
class Entity:
    text: str
    label: str
    score: float
    start: int
    end: int


def load_model() -> None:
    """Load the NER pipeline into memory. Call once at app startup."""
    global _ner_pipeline
    _ner_pipeline = pipeline(
        "ner",
        model=MODEL_ID,
        aggregation_strategy="simple",
    )


def predict(text: str) -> list[Entity]:
    """Extract drug/chemical entities from text.

    Returns a list of Entity objects with text, label, confidence score,
    and character offsets.
    """
    if _ner_pipeline is None:
        raise RuntimeError("NER model not loaded — call load_model() first")

    raw = _ner_pipeline(text)
    entities = []
    for item in raw:
        entities.append(
            Entity(
                text=item["word"],
                label=item["entity_group"],
                score=round(item["score"], 4),
                start=item["start"],
                end=item["end"],
            )
        )
    return entities
