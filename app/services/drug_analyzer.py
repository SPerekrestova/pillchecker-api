"""Drug analyzer — the two-pass identification pipeline.

Pass 1: NER extracts chemical entities from OCR text.
Pass 2 (fallback): If NER finds 0 drugs, try RxNorm /approximateTerm
         on the largest text blocks.

Both passes enrich results with dosage regex and RxNorm normalization.
"""

import logging

from app.clients import rxnorm_client
from app.nlp import ner_model
from app.nlp.dosage_parser import extract_dosages

logger = logging.getLogger(__name__)


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

    # Pass 1: NER
    entities = ner_model.predict(text)
    drug_entities = [
        e for e in entities
        if e.label in ("CHEM", "Chemical", "CHEMICAL") and not e.text.isdigit()
    ]

    if drug_entities:
        logger.info("NER found %d drug entities", len(drug_entities))
        return await _enrich_ner_results(drug_entities, dosage_str)

    # Pass 2: Fallback — try RxNorm approximate matching on text blocks
    logger.info("NER found 0 drugs, trying RxNorm fallback")
    return await _rxnorm_fallback(text, dosage_str)


async def _enrich_ner_results(
    entities: list[ner_model.Entity],
    dosage_str: str | None,
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

        results.append({
            "rxcui": rxcui,
            "name": name,
            "dosage": dosage_str,
            "form": None,
            "source": "ner",
            "confidence": entity.score,
        })

    return results


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
        if candidates:
            best = candidates[0]
            # Look up details to get the proper drug name
            details = await rxnorm_client.get_drug_details(best.rxcui)
            name = details.get("name", best.name) if details else best.name

            results.append({
                "rxcui": best.rxcui,
                "name": name,
                "dosage": dosage_str,
                "form": None,
                "source": "rxnorm_fallback",
                "confidence": 0.5,  # Lower confidence for fallback
            })
            # Only return the first match in fallback mode
            break

    return results
