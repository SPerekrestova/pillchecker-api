"""Tests for DDInter coverage audit input parsing."""

from __future__ import annotations

import json
from pathlib import Path

from eval import coverage_audit


def test_collect_names_from_interaction_seed_file(tmp_path: Path):
    path = tmp_path / "interaction_seed_cases.json"
    path.write_text(json.dumps({
        "positive_pairs": [{"drug_a": "warfarin", "drug_b": "ibuprofen"}],
        "known_safe_pairs": [{"drug_a": "acetaminophen", "drug_b": "amoxicillin"}],
    }))
    assert coverage_audit.collect_names(path) == {
        "acetaminophen",
        "amoxicillin",
        "ibuprofen",
        "warfarin",
    }


def test_collect_names_from_jsonl_benchmark_records(tmp_path: Path):
    path = tmp_path / "benchmark.jsonl"
    path.write_text(
        json.dumps({"expected_names": ["Warfarin", "Ibuprofen"]}) + "\n" +
        json.dumps({"drugs": ["Aspirin"]}) + "\n"
    )
    assert coverage_audit.collect_names(path) == {"Warfarin", "Ibuprofen", "Aspirin"}
