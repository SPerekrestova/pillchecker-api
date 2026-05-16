"""Interaction checker with DDInter SQLite primary and OpenFDA fallback."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.clients import ddinter_db, openfda_client, rxnorm_client
from app.middleware.audit_log import get_audit_context
from app.nlp import severity_classifier

logger = logging.getLogger(__name__)

_MANAGEMENT = "Consult a healthcare professional for guidance."
_EMPTY_COVERAGE = {"ddinter": 0, "openfda": 0, "unknown": 0}


async def check(drug_names: list[str]) -> dict[str, Any]:
    """Check pairwise interactions for the supplied drug names."""
    if len(drug_names) < 2:
        return {
            "interactions": [],
            "safe": True,
            "error": None,
            "coverage_summary": dict(_EMPTY_COVERAGE),
        }

    unique_names = list(dict.fromkeys(drug_names))
    rxcui_results = await asyncio.gather(
        *[rxnorm_client.get_rxcui(name) for name in unique_names],
        return_exceptions=True,
    )
    rxcui_by_name: dict[str, str | None] = {}
    for name, result in zip(unique_names, rxcui_results):
        if isinstance(result, Exception):
            logger.warning("RxNorm failed for %s: %s", name, result)
            rxcui_by_name[name] = None
        else:
            rxcui_by_name[name] = result

    interactions: list[dict[str, Any]] = []
    coverage = dict(_EMPTY_COVERAGE)
    for index, drug_a in enumerate(unique_names):
        for drug_b in unique_names[index + 1:]:
            entry, bucket = await _resolve_pair(drug_a, drug_b, rxcui_by_name)
            coverage[bucket] += 1
            if entry is not None:
                interactions.append(entry)

    return {
        "interactions": interactions,
        "safe": len(interactions) == 0,
        "error": None,
        "coverage_summary": coverage,
    }


async def _resolve_pair(
    drug_a: str,
    drug_b: str,
    rxcui_by_name: dict[str, str | None],
) -> tuple[dict[str, Any] | None, str]:
    rxcui_a = rxcui_by_name.get(drug_a)
    rxcui_b = rxcui_by_name.get(drug_b)

    if rxcui_a and rxcui_b:
        try:
            ddinter_hit = await ddinter_db.client.lookup_by_rxcui(rxcui_a, rxcui_b)
        except Exception:
            logger.warning("DDInter RxCUI lookup failed for %s + %s", drug_a, drug_b, exc_info=True)
        else:
            if ddinter_hit:
                return _format_ddinter(drug_a, drug_b, rxcui_a, rxcui_b, ddinter_hit), "ddinter"

    try:
        ddinter_hit = await ddinter_db.client.lookup_by_name_fts(drug_a, drug_b)
    except Exception:
        logger.warning("DDInter FTS lookup failed for %s + %s", drug_a, drug_b, exc_info=True)
    else:
        if ddinter_hit:
            return _format_ddinter(drug_a, drug_b, rxcui_a, rxcui_b, ddinter_hit), "ddinter"

    fda_hit = await _openfda_pair(drug_a, drug_b)
    if fda_hit:
        return await _format_openfda(drug_a, drug_b, rxcui_a, rxcui_b, fda_hit), "openfda"

    return None, "unknown"


def _format_ddinter(
    drug_a: str,
    drug_b: str,
    rxcui_a: str | None,
    rxcui_b: str | None,
    hit: dict[str, Any],
) -> dict[str, Any]:
    severity = hit.get("severity") or "unknown"
    _audit_severity(drug_a, drug_b, severity, False, "ddinter", "ddinter_sqlite")
    return {
        "drug_a": drug_a,
        "drug_b": drug_b,
        "rxcui_a": rxcui_a,
        "rxcui_b": rxcui_b,
        "severity": severity,
        "source": "ddinter",
        "description": (
            f"Interaction reported in DDInter 2.0 for "
            f"{hit.get('drug_a_name', drug_a)} + {hit.get('drug_b_name', drug_b)}."
        ),
        "management": _MANAGEMENT,
        "uncertain": False,
    }


async def _openfda_pair(drug_a: str, drug_b: str) -> dict[str, Any] | None:
    try:
        fda_hit = await openfda_client.check_pair(drug_a, drug_b)
        if fda_hit is None:
            fda_hit = await openfda_client.check_pair(drug_b, drug_a)
        return fda_hit
    except Exception:
        logger.warning("OpenFDA fallback failed for %s + %s", drug_a, drug_b, exc_info=True)
        return None


async def _format_openfda(
    drug_a: str,
    drug_b: str,
    rxcui_a: str | None,
    rxcui_b: str | None,
    hit: dict[str, Any],
) -> dict[str, Any]:
    description = hit.get("description", "")
    loop = asyncio.get_running_loop()
    severity, uncertain = await loop.run_in_executor(None, severity_classifier.classify, description)
    _audit_severity(drug_a, drug_b, severity, uncertain, "openfda", "zero_shot_classifier")
    return {
        "drug_a": drug_a,
        "drug_b": drug_b,
        "rxcui_a": rxcui_a,
        "rxcui_b": rxcui_b,
        "severity": severity,
        "source": "openfda",
        "description": description or "Interaction reported in FDA labeling.",
        "management": _MANAGEMENT,
        "uncertain": uncertain,
    }


def _audit_severity(
    drug_a: str,
    drug_b: str,
    severity: str,
    uncertain: bool,
    source: str,
    method: str,
) -> None:
    ctx = get_audit_context()
    if ctx:
        ctx.add("severity_classification", {
            "drug_a": drug_a,
            "drug_b": drug_b,
            "severity": severity,
            "uncertain": uncertain,
            "source": source,
            "method": method,
        })
