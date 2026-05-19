#!/usr/bin/env python3
"""Prepare review-only interaction label candidates from source lookups."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime
from itertools import combinations
from pathlib import Path
from uuid import uuid4

from app.clients import ddinter_db, openfda_client, rxnorm_client
from eval.io.dataset import load_benchmark_records

_CATEGORY_ALIASES = {
    "dual": "dual_ingredient",
    "multi": "multi_ingredient",
    "single": "single_ingredient",
}


async def build_candidates(
    records: list[dict],
    *,
    concurrency: int,
    dataset_revision: str = "local",
) -> dict:
    """Build a human-review queue for interaction labels."""
    if concurrency < 1:
        raise ValueError("concurrency must be at least 1")
    semaphore = asyncio.Semaphore(concurrency)
    tasks = []
    for record in records:
        names = _expected_names(record)
        if len(names) < 2:
            continue
        for drug_a, drug_b in combinations(names, 2):
            tasks.append(_run_pair(record, drug_a, drug_b, semaphore))

    pair_results = await asyncio.gather(*tasks)
    candidates = [result[0] for result in pair_results]
    errors = [result[1] for result in pair_results if result[1] is not None]
    return {
        "run_id": _run_id(),
        "dataset_revision": dataset_revision,
        "timestamp_utc": _timestamp(),
        "candidates": candidates,
        "errors": errors,
    }


async def _run_pair(
    record: dict,
    drug_a: str,
    drug_b: str,
    semaphore: asyncio.Semaphore,
) -> tuple[dict, dict | None]:
    async with semaphore:
        try:
            return await _build_pair_candidate(record, drug_a, drug_b), None
        except Exception as exc:
            candidate = _base_candidate(record, drug_a, drug_b, None, None)
            candidate.update({
                "candidate_status": "error",
                "suggested_interacts": None,
                "suggested_severity": None,
                "notes": str(exc),
            })
            error = {
                "record_id": str(record.get("id", "")),
                "drug_a": drug_a,
                "drug_b": drug_b,
                "error_class": exc.__class__.__name__,
                "message": str(exc),
            }
            return candidate, error


async def _build_pair_candidate(record: dict, drug_a: str, drug_b: str) -> dict:
    rxcui_a, rxcui_b = await asyncio.gather(
        rxnorm_client.get_rxcui(drug_a),
        rxnorm_client.get_rxcui(drug_b),
    )
    candidate = _base_candidate(record, drug_a, drug_b, rxcui_a, rxcui_b)

    ddinter_hit = await _lookup_ddinter(drug_a, drug_b, rxcui_a, rxcui_b)
    openfda_hit = await _lookup_openfda(drug_a, drug_b)
    evidence = []

    if ddinter_hit is not None:
        candidate["ddinter"] = _format_ddinter(ddinter_hit)
        evidence.append({
            "source": "ddinter",
            "source_version": "2.0",
            "url_or_id": _ddinter_url_or_id(ddinter_hit),
            "description": "Interaction reported in DDInter 2.0.",
        })

    if openfda_hit is not None:
        candidate["openfda"] = _format_openfda(openfda_hit)
        evidence.append({
            "source": "openfda",
            "source_version": None,
            "url_or_id": None,
            "description": openfda_hit.get("description"),
        })

    candidate["evidence"] = evidence
    if evidence:
        candidate["candidate_status"] = "source_hit"
        candidate["suggested_interacts"] = True
        candidate["suggested_severity"] = _suggested_severity(ddinter_hit)
    else:
        candidate["candidate_status"] = "no_source_hit"
        candidate["suggested_interacts"] = None
        candidate["suggested_severity"] = None
    return candidate


async def _lookup_ddinter(
    drug_a: str,
    drug_b: str,
    rxcui_a: str | None,
    rxcui_b: str | None,
) -> dict | None:
    if rxcui_a and rxcui_b:
        hit = await ddinter_db.client.lookup_by_rxcui(rxcui_a, rxcui_b)
        if hit is not None:
            return hit
    return await ddinter_db.client.lookup_by_name_fts(drug_a, drug_b)


async def _lookup_openfda(drug_a: str, drug_b: str) -> dict | None:
    hit = await openfda_client.check_pair(drug_a, drug_b)
    if hit is None:
        hit = await openfda_client.check_pair(drug_b, drug_a)
    return hit


def _base_candidate(
    record: dict,
    drug_a: str,
    drug_b: str,
    rxcui_a: str | None,
    rxcui_b: str | None,
) -> dict:
    return {
        "record_id": str(record.get("id", "")),
        "drug_a": drug_a,
        "drug_b": drug_b,
        "rxcui_a": rxcui_a,
        "rxcui_b": rxcui_b,
        "ddinter": None,
        "openfda": None,
        "evidence": [],
        "candidate_status": "error",
        "suggested_interacts": None,
        "suggested_severity": None,
        "review_status": "unreviewed",
        "is_ground_truth": False,
        "notes": "",
    }


def _format_ddinter(hit: dict) -> dict:
    return {
        "hit": True,
        "severity": hit.get("severity"),
        "drug_a_id": hit.get("drug_a_id"),
        "drug_b_id": hit.get("drug_b_id"),
        "atc_category": hit.get("atc_category"),
    }


def _format_openfda(hit: dict) -> dict:
    return {
        "hit": True,
        "description": hit.get("description"),
    }


def _ddinter_url_or_id(hit: dict) -> str | None:
    drug_a_id = hit.get("drug_a_id")
    drug_b_id = hit.get("drug_b_id")
    if drug_a_id and drug_b_id:
        return f"{drug_a_id}+{drug_b_id}"
    return None


def _suggested_severity(ddinter_hit: dict | None) -> str | None:
    if ddinter_hit is None:
        return "unknown"
    severity = ddinter_hit.get("severity")
    return str(severity).lower() if severity else "unknown"


def _expected_names(record: dict) -> list[str]:
    value = record.get("expected_names", [])
    if not isinstance(value, list):
        return []
    names = []
    seen = set()
    for item in value:
        if not isinstance(item, str) or not item.strip():
            continue
        key = item.casefold()
        if key in seen:
            continue
        seen.add(key)
        names.append(item)
    return names


def _run_id() -> str:
    return f"interaction-candidates-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-{uuid4().hex[:8]}"


def _timestamp() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _category_filter(value: str) -> set[str]:
    categories = set()
    for raw in value.split(","):
        key = raw.strip()
        if not key:
            continue
        categories.add(_CATEGORY_ALIASES.get(key, key))
    return categories


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")


async def _main_async(args: argparse.Namespace) -> int:
    try:
        records, _meta = load_benchmark_records(revision=args.revision)
    except Exception as exc:
        print(f"Failed to load HF benchmark dataset: {exc}", file=sys.stderr)
        return 2

    if not await ddinter_db.client.health_check():
        print("DDInter DB is missing or unreadable", file=sys.stderr)
        return 3

    categories = _category_filter(args.categories)
    filtered = [record for record in records if record.get("category") in categories]
    if args.limit is not None:
        filtered = filtered[:args.limit]
    output = await build_candidates(
        filtered,
        concurrency=args.concurrency,
        dataset_revision=args.revision,
    )
    _write_json(Path(args.out), output)
    print(
        f"Wrote {len(output['candidates'])} interaction candidates "
        f"and {len(output['errors'])} errors to {args.out}"
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--revision", required=True, help="Pinned HF dataset revision.")
    parser.add_argument("--out", required=True, help="Local candidate JSON output path.")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--categories", default="dual,multi")
    parser.add_argument("--concurrency", type=int, default=8)
    args = parser.parse_args()
    return asyncio.run(_main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
