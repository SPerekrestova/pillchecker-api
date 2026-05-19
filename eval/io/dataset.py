"""Load and validate benchmark input records."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from huggingface_hub import hf_hub_download

DEFAULT_DATASET_REPO = "SPerva/pillchecker-ner-benchmark"
DEFAULT_DATASET_PATH = "data/benchmark.json"
_REQUIRED_FIELDS = ("id", "category", "ocr_text", "expected_names", "source_composition")
_CATEGORIES = {"single_ingredient", "dual_ingredient", "multi_ingredient"}


@dataclass(frozen=True)
class DatasetMetadata:
    repo_id: str | None
    path: str
    revision: str | None
    local_path: str


def load_benchmark_records(
    *,
    local_path: str | Path | None = None,
    repo_id: str = DEFAULT_DATASET_REPO,
    dataset_path: str = DEFAULT_DATASET_PATH,
    revision: str | None = None,
) -> tuple[list[dict[str, object]], DatasetMetadata]:
    """Load benchmark records from a local JSON file or pinned HF dataset revision."""
    if local_path is not None:
        source = Path(local_path)
        records = _read_json_list(source)
        _validate_records(records)
        return records, DatasetMetadata(
            repo_id=None,
            path=str(source),
            revision=None,
            local_path=str(source),
        )

    downloaded = hf_hub_download(
        repo_id=repo_id,
        repo_type="dataset",
        filename=dataset_path,
        revision=revision,
    )
    records = _read_json_list(Path(downloaded))
    _validate_records(records)
    return records, DatasetMetadata(
        repo_id=repo_id,
        path=dataset_path,
        revision=revision,
        local_path=downloaded,
    )


def _read_json_list(path: Path) -> list[dict[str, object]]:
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, list):
        raise ValueError(f"Expected a JSON list in {path}")
    return data


def _validate_records(records: list[dict[str, object]]) -> None:
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            raise ValueError(f"Record {index} must be an object")
        for field in _REQUIRED_FIELDS:
            if field not in record:
                raise ValueError(f"Record {index} is missing required field {field}")
        if record["category"] not in _CATEGORIES:
            raise ValueError(f"Record {index} has unsupported category {record['category']!r}")
        if not isinstance(record["ocr_text"], str) or not record["ocr_text"].strip():
            raise ValueError(f"Record {index} has invalid ocr_text")
        names = record["expected_names"]
        if not isinstance(names, list) or not names:
            raise ValueError(f"Record {index} has invalid expected_names")
        for name in names:
            if not isinstance(name, str) or not name.strip():
                raise ValueError(f"Record {index} has invalid expected_names item")

