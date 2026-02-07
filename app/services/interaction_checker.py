"""Interaction checker — looks up drug pairs in the FDA Open Data store."""

import logging

from app.data.fda_store import Interaction, check_interaction

logger = logging.getLogger(__name__)


def check(drug_names: list[str]) -> dict:
    """Check interactions between all pairs of drugs.

    Args:
        drug_names: List of drug names (generic, lowercase preferred).

    Returns:
        Dict with:
          - interactions: list of interaction dicts
          - safe: bool (True if no interactions found)
    """
    interactions = []

    for i, drug_a in enumerate(drug_names):
        for drug_b in drug_names[i + 1:]:
            result = check_interaction(drug_a, drug_b)
            if result:
                logger.info(
                    "Interaction found: %s + %s = %s",
                    drug_a, drug_b, result.severity,
                )
                interactions.append(_format_interaction(result))

    return {
        "interactions": interactions,
        "safe": len(interactions) == 0,
    }


def _format_interaction(interaction: Interaction) -> dict:
    return {
        "drug_a": interaction.drug_a,
        "drug_b": interaction.drug_b,
        "severity": interaction.severity,
        "description": interaction.description,
        "management": interaction.management,
    }