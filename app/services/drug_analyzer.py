"""Drug analyzer — the two-pass identification pipeline.

Pass 1: NER extracts chemical entities from OCR text.
Pass 2 (fallback): If NER finds 0 drugs, try RxNorm /approximateTerm
         on the largest text blocks.

Both passes enrich results with dosage regex and RxNorm normalization.
"""

import logging

from app.clients import rxnorm_client
from app.middleware.audit_log import get_audit_context
from app.nlp import ner_model
from app.nlp.dosage_parser import extract_dosages
from app.nlp.ocr_cleaner import clean as ocr_clean

logger = logging.getLogger(__name__)

_MAX_DOSAGE_DISTANCE = 50  # max chars between drug entity end and dosage start


def _nearest_dosage(entity_end: int, dosages: list) -> str | None:
    """Find the dosage closest to a drug entity by character offset."""
    if not dosages:
        return None
    nearest = min(dosages, key=lambda d: abs(d.start - entity_end))
    if abs(nearest.start - entity_end) <= _MAX_DOSAGE_DISTANCE:
        return nearest.raw
    return None


async def analyze(text: str) -> list[dict]:
    """Analyze OCR text and return enriched drug profiles.

    Returns a list of dicts, each with:
      - rxcui: str | None
      - name: str
      - dosage: str | None
      - form: str | None
      - source: "ner" | "rxnorm_fallback"
      - confidence: float
    """
    # Extract dosages from the full text (used for both passes)
    dosages = extract_dosages(text)
    dosage_str = dosages[0].raw if dosages else None

    # Clean OCR artifacts before NER
    cleaned_text = ocr_clean(text)

    # Pass 1: NER (on cleaned text)
    entities = ner_model.predict(cleaned_text)

    ctx = get_audit_context()
    if ctx:
        ctx.add("ner", {
            "entities": [{"text": e.text, "label": e.label, "score": round(e.score, 4)} for e in entities],
            "model": ner_model.MODEL_ID,
        })

    drug_entities = [
        e for e in entities
        if e.label in ("CHEM", "Chemical", "CHEMICAL") and not e.text.isdigit()
    ]

    if drug_entities:
        logger.info("NER found %d drug entities", len(drug_entities))
        enriched = await _enrich_ner_results(drug_entities, dosages)
        if enriched:
            return enriched
        logger.info("All NER entities filtered out, trying RxNorm fallback")

    # Pass 2: Fallback — try RxNorm approximate matching on text blocks
    logger.info("Falling through to RxNorm fallback")
    return await _rxnorm_fallback(text, dosage_str)


async def _enrich_ner_results(
    entities: list[ner_model.Entity],
    dosages: list,
) -> list[dict]:
    """Enrich NER entities with RxNorm data."""
    results = []
    seen_names = set()

    for entity in entities:
        name = entity.text.strip()
        if name.lower() in seen_names:
            continue
        seen_names.add(name.lower())

        rxcui = await rxnorm_client.get_rxcui(name)

        if rxcui is None:
            logger.info("Skipping NER entity '%s' — not found in RxNorm", name)
            continue

        results.append({
            "rxcui": rxcui,
            "name": name,
            "dosage": _nearest_dosage(entity.end, dosages),
            "form": None,
            "source": "ner",
            "confidence": entity.score,
            "needs_confirmation": entity.score < 0.85,
        })

    results.sort(key=lambda r: r["confidence"], reverse=True)
    return results



# Minimum approximate-term score to accept a fallback match.
# Real drug names score ~10+; false positives (common English words
# matched to brand names like "Hello Bello") score <4.
_MIN_APPROX_SCORE = 6.0


async def _rxnorm_fallback(text: str, dosage_str: str | None) -> list[dict]:
    """Try to identify drugs by sending text blocks to RxNorm approximate search."""
    # Split into words, try the longest blocks first
    words = text.split()
    results = []
    tried = set()

    for word in words:
        clean = word.strip(",.;:()[]")
        if len(clean) < 3 or clean.lower() in tried:
            continue
        tried.add(clean.lower())

        candidates = await rxnorm_client.approximate_term(clean)
        if not candidates:
            continue

        best = candidates[0]

        # Reject weak matches — common English words can match brand names
        # (e.g. "hello" → "Hello Bello" at score 3.98).
        if best.score < _MIN_APPROX_SCORE:
            continue

        # Look up details to get the proper drug name
        details = await rxnorm_client.get_drug_details(best.rxcui)
        name = details.get("name", best.name) if details else best.name

        # Skip results where we couldn't resolve a non-empty drug name
        if not name:
            continue

        results.append({
            "rxcui": best.rxcui,
            "name": name,
            "dosage": dosage_str,
            "form": None,
            "source": "rxnorm_fallback",
            "confidence": best.score / 20.0,  # normalize approx score to 0-1 range
            "needs_confirmation": True,
        })
        # Only return the first match in fallback mode
        break

    return results
