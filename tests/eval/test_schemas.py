import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _load_schema(name: str) -> dict:
    return json.loads((ROOT / "eval" / name).read_text())


def test_interaction_label_candidates_schema_accepts_minimal_candidate():
    schema = _load_schema("interaction_label_candidates.schema.json")
    candidate = {
        "run_id": "run-1",
        "dataset_revision": "abc123",
        "timestamp_utc": "2026-05-19T12:00:00Z",
        "candidates": [
            {
                "record_id": "case-1",
                "drug_a": "warfarin",
                "drug_b": "ibuprofen",
                "candidate_status": "source_hit",
                "review_status": "unreviewed",
                "is_ground_truth": False,
            }
        ],
        "errors": [],
    }

    required = set(schema["required"])
    assert required <= candidate.keys()
    candidate_schema = schema["properties"]["candidates"]["items"]
    assert set(candidate_schema["required"]) <= candidate["candidates"][0].keys()
    assert candidate_schema["properties"]["is_ground_truth"]["const"] is False
    assert candidate["candidates"][0]["candidate_status"] in candidate_schema["properties"]["candidate_status"]["enum"]
    assert candidate["candidates"][0]["review_status"] in candidate_schema["properties"]["review_status"]["enum"]


def test_interaction_label_candidates_schema_rejects_ground_truth_true():
    schema = _load_schema("interaction_label_candidates.schema.json")
    candidate_schema = schema["properties"]["candidates"]["items"]

    assert candidate_schema["properties"]["is_ground_truth"]["const"] is False


def test_benchmark_results_schema_contains_required_metric_blocks():
    schema = _load_schema("benchmark_results.schema.json")
    result = {
        "overall": {
            "records_total": 1,
            "records_completed": 1,
            "records_errored": 0,
            "error_rate": 0.0,
            "timeout_count": 0,
            "concurrency": 1,
            "wall_time_seconds": 0.1,
            "records_per_second": 10.0,
        },
        "timing": {
            "components": {
                "total": {"p50_ms": 1.0, "p95_ms": 1.0, "p99_ms": 1.0, "max_ms": 1.0, "mean_ms": 1.0}
            },
            "slowest_component": "total",
            "slowest_component_counts": {"total": 1},
        },
        "ner": {
            "strict": {"precision": 1.0, "recall": 1.0, "f1": 1.0},
            "lenient": {"precision": 1.0, "recall": 1.0, "f1": 1.0},
            "per_category": {},
            "per_noise_level": None,
            "confidence_sweep": {},
            "score_distribution": {},
            "n_records_scored": 1,
        },
        "linking": {
            "coverage": 1.0,
            "fallback_rate": 0.0,
            "nil_rate": None,
            "n_link_attempts": 0,
            "n_drugs_total": 1,
            "acc_at_1": None,
            "incorrect_link_rate": None,
        },
        "rxnorm": {
            "coverage": 1.0,
            "fallback_rate": 0.0,
            "nil_rate": None,
            "n_link_attempts": 0,
            "n_drugs_total": 1,
            "acc_at_1": None,
            "incorrect_link_rate": None,
            "n_rxnorm_attempts": 0,
            "rxnorm_by_method": {},
            "unresolved_queries": [],
            "canonicalization_collisions": [],
        },
        "interactions": {
            "descriptive": {
                "total_pairs_checked": 0,
                "ddinter_hit_rate": 0.0,
                "openfda_hit_rate": 0.0,
                "unknown_rate": 0.0,
                "severity_distribution": {"minor": 0, "moderate": 0, "major": 0, "unknown": 0},
                "uncertain_rate": 0.0,
                "records_with_any_interaction": 0,
                "ddinter_rxcui_hit_rate": 0.0,
                "ddinter_fts_rescue_rate": 0.0,
                "openfda_rescue_rate": 0.0,
                "source_counts": {"ddinter": 0, "openfda": 0, "unknown": 0},
                "top_unknown_pairs": [],
            },
            "accuracy": None,
            "seed_smoke": {
                "recall": 0.0,
                "false_alarm_rate": 0.0,
                "severity_accuracy": 0.0,
                "missed_pairs": [],
            },
        },
        "errors": {
            "total": 0,
            "by_stage": {},
            "by_class": {},
            "records": [],
        },
        "fp_taxonomy": {
            "brand": {"count": 0, "examples": []},
            "salt": {"count": 0, "examples": []},
            "form": {"count": 0, "examples": []},
            "mfg": {"count": 0, "examples": []},
            "numeric": {"count": 0, "examples": []},
            "excipient": {"count": 0, "examples": []},
            "other": {"count": 0, "examples": []},
            "total_fp": 0,
            "n_records_scored": 1,
        },
    }

    assert set(schema["required"]) <= result.keys()
    for block_name in schema["required"]:
        assert set(schema["properties"][block_name]["required"]) <= result[block_name].keys()
