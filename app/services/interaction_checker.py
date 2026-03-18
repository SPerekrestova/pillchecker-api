"""Interaction checker — looks up drug pairs via BioMCP."""

import asyncio
import logging

from app.clients import biomcp_client
from app.nlp import severity_classifier

logger = logging.getLogger(__name__)

_MANAGEMENT = "Consult a healthcare professional for guidance."


async def check(drug_names: list[str]) -> dict:
    """Check interactions between all pairs of drugs.

    Returns dict with:
      - interactions: list of interaction dicts
      - safe: bool | None (None if data source unavailable)
      - error: str | None

    Note: Per-drug BioMCP errors (malformed response, drug not found) return []
    silently, so safe=True means "no interactions detected" not "guaranteed safe".
    """
    if len(drug_names) < 2:
        return {"interactions": [], "safe": True, "error": None}

    # Fetch interaction lists for each drug (cached per drug)
    unique_names = list(dict.fromkeys(drug_names))  # deduplicate, preserve order
    results = await asyncio.gather(
        *[biomcp_client.get_interactions(name) for name in unique_names],
        return_exceptions=True,
    )

    # Handle per-drug failures gracefully
    all_failed = True
    drug_interactions: dict[str, list[dict]] = {}
    for name, result in zip(unique_names, results):
        if isinstance(result, Exception):
            logger.warning("BioMCP failed for %s: %s", name, result)
            drug_interactions[name] = []
        else:
            all_failed = False
            drug_interactions[name] = result

    if all_failed and len(unique_names) > 0:
        logger.error("BioMCP unavailable — cannot check interactions")
        return {
            "interactions": [],
            "safe": None,
            "error": "Drug interaction data temporarily unavailable",
        }

    # Check all pairs (use deduplicated list to avoid self-pairs)
    interactions = []
    for i, drug_a in enumerate(unique_names):
        for drug_b in unique_names[i + 1:]:
            result = await _find_interaction(drug_a, drug_b, drug_interactions)
            if result:
                logger.info(
                    "Interaction found: %s + %s = %s",
                    drug_a, drug_b, result["severity"],
                )
                interactions.append(result)

    return {
        "interactions": interactions,
        "safe": len(interactions) == 0,
        "error": None,
    }


async def _find_interaction(
    drug_a: str,
    drug_b: str,
    drug_interactions: dict[str, list[dict]],
) -> dict | None:
    """Check if drug_b appears in drug_a's interaction list, or vice versa."""
    # Check A's list for B
    match = _match_in_list(drug_b, drug_interactions.get(drug_a, []))
    if match:
        return await _format(drug_a, drug_b, match)

    # Check B's list for A
    match = _match_in_list(drug_a, drug_interactions.get(drug_b, []))
    if match:
        return await _format(drug_a, drug_b, match)

    return None


def _match_in_list(target: str, interactions: list[dict]) -> dict | None:
    """Find target drug name in a list of interaction entries (case-insensitive)."""
    target_lower = target.lower()
    for entry in interactions:
        if entry.get("drug", "").lower() == target_lower:
            return entry
    return None


async def _format(drug_a: str, drug_b: str, match: dict) -> dict:
    """Format an interaction entry for the API response."""
    description = match.get("description", "")
    loop = asyncio.get_running_loop()
    severity = await loop.run_in_executor(None, severity_classifier.classify, description)
    return {
        "drug_a": drug_a,
        "drug_b": drug_b,
        "severity": severity,
        "description": description or "Interaction reported in DrugBank.",
        "management": _MANAGEMENT,
    }
