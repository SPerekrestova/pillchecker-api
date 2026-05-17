#!/usr/bin/env python3
"""Measure DDInter name coverage for interaction seed or benchmark files."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path


def _record_names(record: dict) -> set[str]:
    names: set[str] = set()
    for key in ("expected_names", "drugs"):
        values = record.get(key)
        if isinstance(values, list):
            names.update(str(v).strip() for v in values if str(v).strip())
    for key in ("positive_pairs", "known_safe_pairs"):
        values = record.get(key)
        if isinstance(values, list):
            for pair in values:
                if not isinstance(pair, dict):
                    continue
                for drug_key in ("drug_a", "drug_b"):
                    value = str(pair.get(drug_key, "")).strip()
                    if value:
                        names.add(value)
    return names


def collect_names(path: Path) -> set[str]:
    """Collect drug names from JSON seed files or JSONL benchmark records."""
    text = path.read_text()
    if path.suffix == ".jsonl":
        names: set[str] = set()
        for line in text.splitlines():
            if line.strip():
                names.update(_record_names(json.loads(line)))
        return names
    payload = json.loads(text)
    if isinstance(payload, list):
        names: set[str] = set()
        for record in payload:
            if isinstance(record, dict):
                names.update(_record_names(record))
        return names
    if isinstance(payload, dict):
        return _record_names(payload)
    raise ValueError(f"Unsupported dataset shape in {path}")


async def _resolve_name(name: str) -> tuple[str, str]:
    from app.clients import ddinter_db, rxnorm_client

    rxcui = await rxnorm_client.get_rxcui(name)
    if rxcui:
        mapping = await ddinter_db.client._ddinter_ids_for_rxcuis([rxcui])  # noqa: SLF001
        if mapping.get(rxcui):
            return "rxcui", f"{rxcui}->{mapping[rxcui]}"
    fts_id = await ddinter_db.client._fts_ddinter_id_for_name(name)  # noqa: SLF001
    if fts_id:
        return "fts", fts_id
    return "unmapped", ""


async def main_async(args: argparse.Namespace) -> int:
    from app.clients import ddinter_db

    if args.db_path:
        await ddinter_db.client.close()
        ddinter_db.client.db_path = args.db_path
    elif os.environ.get("INTERACTION_DB_PATH"):
        await ddinter_db.client.close()
        ddinter_db.client.db_path = os.environ["INTERACTION_DB_PATH"]

    try:
        names = collect_names(Path(args.dataset))
        counts = {"rxcui": 0, "fts": 0, "unmapped": 0}
        unmapped: list[str] = []
        for name in sorted(names, key=str.lower):
            bucket, _evidence = await _resolve_name(name)
            counts[bucket] += 1
            if bucket == "unmapped":
                unmapped.append(name)

        total = sum(counts.values())
        mapped = counts["rxcui"] + counts["fts"]
        coverage = mapped / total if total else 0.0
        print(json.dumps({
            "dataset": args.dataset,
            "total": total,
            "ddinter_via_rxcui": counts["rxcui"],
            "ddinter_via_fts": counts["fts"],
            "unmapped_count": counts["unmapped"],
            "coverage": coverage,
            "threshold": args.threshold,
        }, indent=2, sort_keys=True))
        if unmapped:
            print("UNMAPPED:", file=sys.stderr)
            for name in unmapped:
                print(f"  {name}", file=sys.stderr)
        return 0 if coverage >= args.threshold else 1
    finally:
        await ddinter_db.client.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", default="eval/interaction_seed_cases.json")
    parser.add_argument("--db-path", default=None)
    parser.add_argument("--threshold", type=float, default=0.80)
    return asyncio.run(main_async(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
