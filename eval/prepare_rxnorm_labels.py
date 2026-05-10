#!/usr/bin/env python3
"""Prepare reviewable RxNorm labels for the HF benchmark dataset."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from collections import Counter
from pathlib import Path, PurePosixPath

from huggingface_hub import HfApi, hf_hub_download

from app.clients import rxnorm_client

DEFAULT_REPO_ID = "SPerva/pillchecker-ner-benchmark"
DEFAULT_DATASET_PATH = "data/benchmark.json"
DEFAULT_SOURCE_DATASET = "MattBastar/Medicine_Details"
DEFAULT_OUTPUT = "eval/benchmark.rxnorm_candidates.json"


def _load_records(repo_id: str, dataset_path: str) -> tuple[list[dict[str, object]], str]:
    downloaded = hf_hub_download(
        repo_id=repo_id,
        repo_type="dataset",
        filename=dataset_path,
    )
    with open(downloaded, encoding="utf-8") as handle:
        records = json.load(handle)
    if not isinstance(records, list):
        raise ValueError(f"Expected a JSON list in {repo_id}/{dataset_path}")
    return records, downloaded


def _string_list(value: object, field_name: str) -> list[str]:
    if not isinstance(value, list):
        raise ValueError(f"{field_name} must be a list")
    strings: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise ValueError(f"{field_name} must contain non-empty strings")
        strings.append(item)
    return strings


async def _resolve_name(name: str) -> dict[str, object]:
    exact_rxcui = await rxnorm_client.get_rxcui(name)
    if exact_rxcui:
        return {
            "name": name,
            "status": "exact",
            "rxcui": exact_rxcui,
            "candidates": [],
        }

    candidates = await rxnorm_client.approximate_term(name)
    return {
        "name": name,
        "status": "needs_review",
        "rxcui": None,
        "candidates": [
            {
                "rxcui": candidate.rxcui,
                "name": candidate.name,
                "score": candidate.score,
            }
            for candidate in candidates[:5]
        ],
    }


async def _build_resolutions(names: list[str]) -> dict[str, dict[str, object]]:
    resolutions: dict[str, dict[str, object]] = {}
    for index, name in enumerate(names, 1):
        resolutions[name] = await _resolve_name(name)
        if index % 25 == 0:
            print(f"Resolved {index}/{len(names)} ingredient names")
    return resolutions


def _generated_exact_rxcuis(resolutions: list[dict[str, object]]) -> list[str]:
    return [
        str(resolution["rxcui"])
        for resolution in resolutions
        if resolution.get("status") == "exact" and resolution.get("rxcui")
    ]


def _merge_expected_rxcuis(record: dict[str, object], generated: list[str]) -> list[str]:
    existing_value = record.get("expected_rxcuis")
    if existing_value is None:
        return generated

    existing = _string_list(existing_value, "expected_rxcuis")
    merged = list(dict.fromkeys([*existing, *generated]))
    if set(merged) != set(existing):
        record_id = record.get("id", "<unknown>")
        added = sorted(set(merged) - set(existing))
        print(
            f"Preserved existing expected_rxcuis for {record_id}; "
            f"appended generated exact matches: {added}"
        )
    return merged


def _enrich_records(
    records: list[dict[str, object]],
    resolutions: dict[str, dict[str, object]],
    source_dataset: str,
) -> list[dict[str, object]]:
    enriched: list[dict[str, object]] = []
    for record in records:
        expected_names = _string_list(record.get("expected_names"), "expected_names")
        row = dict(record)
        row.setdefault("source_dataset", source_dataset)
        rxnorm_resolution = [resolutions[name] for name in expected_names]
        row["rxnorm_resolution"] = rxnorm_resolution
        row["expected_rxcuis"] = _merge_expected_rxcuis(record, _generated_exact_rxcuis(rxnorm_resolution))
        enriched.append(row)
    return enriched


def _write_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def _summarize(enriched: list[dict[str, object]]) -> dict[str, object]:
    status_counts: Counter[str] = Counter()
    unresolved_names: set[str] = set()
    total_labels = 0
    for record in enriched:
        resolutions = record.get("rxnorm_resolution")
        if not isinstance(resolutions, list):
            continue
        for resolution in resolutions:
            if not isinstance(resolution, dict):
                continue
            status = str(resolution.get("status"))
            status_counts[status] += 1
            total_labels += 1
            if status != "exact":
                name = resolution.get("name")
                if isinstance(name, str):
                    unresolved_names.add(name)
    return {
        "records": len(enriched),
        "ingredient_labels": total_labels,
        "status_counts": dict(sorted(status_counts.items())),
        "unresolved_names": sorted(unresolved_names),
    }


def _upload_if_requested(repo_id: str, output: Path, upload_path: str | None, source_path: str) -> None:
    if upload_path is None:
        return
    if PurePosixPath(upload_path) == PurePosixPath(source_path):
        raise SystemExit(
            f"Refusing to overwrite canonical benchmark data at {source_path}; "
            "upload candidates to a review path"
        )
    token = os.environ.get("HF_TOKEN")
    if not token:
        raise SystemExit("HF_TOKEN is required when --upload-path is set")
    HfApi(token=token).upload_file(
        repo_id=repo_id,
        repo_type="dataset",
        path_or_fileobj=str(output),
        path_in_repo=upload_path,
        commit_message="Add reviewable RxNorm label candidates",
    )


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-id", default=DEFAULT_REPO_ID)
    parser.add_argument("--dataset-path", default=DEFAULT_DATASET_PATH)
    parser.add_argument("--source-dataset", default=DEFAULT_SOURCE_DATASET)
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--upload-path",
        default=None,
        help=(
            "Optional HF dataset path for the generated candidate file. "
            "Uploading over the source benchmark path is refused."
        ),
    )
    args = parser.parse_args()

    records, downloaded = _load_records(args.repo_id, args.dataset_path)
    print(f"Loaded {len(records)} records from {downloaded}")
    names = sorted({name for record in records for name in _string_list(record.get("expected_names"), "expected_names")})
    resolutions = await _build_resolutions(names)
    enriched = _enrich_records(records, resolutions, args.source_dataset)
    output = Path(args.output)
    _write_json(output, enriched)
    summary = _summarize(enriched)
    _write_json(output.with_suffix(".summary.json"), summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    _upload_if_requested(args.repo_id, output, args.upload_path, args.dataset_path)


if __name__ == "__main__":
    asyncio.run(main())
