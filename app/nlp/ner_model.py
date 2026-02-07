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
        aggregation_strategy="none",
    )


def is_loaded() -> bool:
    """Check if the NER pipeline is loaded."""
    return _ner_pipeline is not None


def predict(text: str) -> list[Entity]:
    """Extract drug/chemical entities from text.

    Uses aggregation_strategy="none" and merges tokens manually because
    ModernBERT's tokenizer lacks ## sub-word markers, causing the pipeline
    to mislabel continuation tokens as B- (begin) instead of I- (inside).
    """
    if _ner_pipeline is None:
        raise RuntimeError("NER model not loaded — call load_model() first")

    raw = _ner_pipeline(text)
    if not raw:
        return []

    # Strip B-/I- prefix to get base label, then merge adjacent same-label
    # tokens that form alphabetic words (no spaces/digits between them).
    for item in raw:
        item["base_label"] = item["entity"].split("-", 1)[-1]

    merged: list[dict] = [raw[0]]
    for item in raw[1:]:
        prev = merged[-1]
        new_chars = text[prev["end"]:item["end"]]
        if (
            item["base_label"] == prev["base_label"]
            and item["start"] == prev["end"]
            and new_chars.isalpha()
        ):
            prev["end"] = item["end"]
            prev["score"] = min(prev["score"], item["score"])
        else:
            merged.append(item)

    return [
        Entity(
            text=text[item["start"]:item["end"]].strip(),
            label=item["base_label"],
            score=round(float(item["score"]), 4),
            start=item["start"],
            end=item["end"],
        )
        for item in merged
        if item["base_label"] != "O"
    ]
