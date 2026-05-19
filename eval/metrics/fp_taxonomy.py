"""False-positive taxonomy for predicted drug names."""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable

from eval.metrics.ner import _lenient_match


EXCIPIENTS = {
    "glycine",
    "l-leucine",
    "l-isoleucine",
    "leucine",
    "isoleucine",
    "l-methylfolate",
    "methylfolate",
    "l-ornithine",
    "l-aspartate",
    "methylcobalamin",
    "benfotiamine",
    "lactobacillus",
    "carboxymethylcellulose",
    "hydroxypropylmethylcellulose",
    "camphor",
    "menthol",
}

NUMERIC_RE = re.compile(r"^\d+(\.\d+)?\s*(mg|mcg|ml|g|iu|%)?$", re.IGNORECASE)
FORM_RE = re.compile(r"\b(tablet|capsule|syrup|injection|cream|ointment|gel|spray|drops?|lotion|powder|suspension)\b", re.IGNORECASE)
MFG_RE = re.compile(r"\b(ltd|inc|corp|gmbh|pharma|pharmaceuticals?|laboratories?|labs)\b", re.IGNORECASE)
SALT_RE = re.compile(r"\b(sodium|hydrochloride|hcl|sulfate|calcium|phosphate|maleate|potassium|tartrate|fumarate|citrate)\b", re.IGNORECASE)


async def _default_details_resolver(rxcui: str) -> dict | None:
    from app.clients import rxnorm_client

    return await rxnorm_client.get_drug_details(rxcui)


def _new_bucket() -> dict:
    return {"count": 0, "examples": []}


def _add(bucket: dict, value: str) -> None:
    bucket["count"] += 1
    if len(bucket["examples"]) < 5:
        bucket["examples"].append(value)


async def _is_brand(
    rxcui: str | None,
    cache: dict[str, dict | None],
    details_resolver: Callable[[str], Awaitable[dict | None]],
) -> bool:
    if not rxcui:
        return False
    if rxcui not in cache:
        cache[rxcui] = await details_resolver(rxcui)
    return (cache[rxcui] or {}).get("tty") == "BN"


async def _classify(
    drug: dict,
    cache: dict[str, dict | None],
    details_resolver: Callable[[str], Awaitable[dict | None]],
) -> str:
    name = str(drug.get("name", "")).strip()
    lowered = name.casefold()
    if lowered in EXCIPIENTS:
        return "excipient"
    if NUMERIC_RE.match(lowered) or lowered.isdigit():
        return "numeric"
    if FORM_RE.search(lowered):
        return "form"
    if MFG_RE.search(lowered):
        return "mfg"
    if SALT_RE.search(lowered):
        return "salt"
    if await _is_brand(drug.get("rxcui"), cache, details_resolver):
        return "brand"
    return "other"


async def compute(
    predictions: list[dict],
    dataset: list[dict],
    details_resolver: Callable[[str], Awaitable[dict | None]] | None = None,
) -> dict:
    resolver = details_resolver or _default_details_resolver
    dataset_by_id = {str(record.get("id")): record for record in dataset}
    result = {
        "brand": _new_bucket(),
        "salt": _new_bucket(),
        "form": _new_bucket(),
        "mfg": _new_bucket(),
        "numeric": _new_bucket(),
        "excipient": _new_bucket(),
        "other": _new_bucket(),
        "total_fp": 0,
        "n_records_scored": len(dataset),
    }
    details_cache: dict[str, dict | None] = {}

    for prediction in predictions:
        record = dataset_by_id.get(str(prediction.get("record_id")), {})
        expected = [str(name) for name in record.get("expected_names", [])]
        for drug in prediction.get("drugs", []):
            name = str(drug.get("name", "")).strip()
            if any(_lenient_match(name, expected_name) for expected_name in expected):
                continue
            category = await _classify(drug, details_cache, resolver)
            _add(result[category], name)
            result["total_fp"] += 1

    return result
