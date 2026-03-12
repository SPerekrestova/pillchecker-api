"""Zero-shot severity classifier for drug interaction descriptions.

Uses DeBERTa-v3-base-mnli for zero-shot classification.
Falls back to regex if the model is not loaded.
"""

import logging
import re

from transformers import pipeline as hf_pipeline

logger = logging.getLogger(__name__)

MODEL_ID = "MoritzLaurer/DeBERTa-v3-base-mnli-fever-anli"

_classifier = None

_CANDIDATE_LABELS = [
    "critical dangerous interaction",
    "moderate interaction requiring monitoring",
    "minor interaction with low risk",
]

_LABEL_MAP = {
    "critical dangerous interaction": "major",
    "moderate interaction requiring monitoring": "moderate",
    "minor interaction with low risk": "minor",
}

_RX_CRITICAL = re.compile(
    r"\b(contraindicated|fatal|do not use|death)\b", re.IGNORECASE
)
_RX_WARNING = re.compile(
    r"\b(caution|monitor|warning|risk|avoid)\b", re.IGNORECASE
)


def load_model() -> None:
    """Load the zero-shot classification pipeline. Call once at app startup."""
    global _classifier
    try:
        _classifier = hf_pipeline(
            "zero-shot-classification",
            model=MODEL_ID,
        )
        logger.info("Severity classifier loaded: %s", MODEL_ID)
    except Exception:
        logger.warning(
            "Failed to load severity classifier — falling back to regex",
            exc_info=True,
        )
        _classifier = None


def is_loaded() -> bool:
    """Check if model is loaded."""
    return _classifier is not None


def classify(description: str | None) -> str:
    """Classify an interaction description into major/moderate/minor.

    Returns 'unknown' if description is empty or None.
    """
    if not description:
        return "unknown"

    if _classifier is None:
        logger.debug("Severity model not loaded, using regex fallback")
        return _regex_fallback(description)

    try:
        result = _classifier(description, _CANDIDATE_LABELS)
        top_label = result["labels"][0]
        return _LABEL_MAP[top_label]
    except Exception:
        logger.warning("Severity classification failed, using regex fallback", exc_info=True)
        return _regex_fallback(description)


def _regex_fallback(text: str) -> str:
    """Simple regex-based severity inference."""
    if _RX_CRITICAL.search(text):
        return "major"
    if _RX_WARNING.search(text):
        return "moderate"
    return "minor"
