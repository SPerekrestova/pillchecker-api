"""Drug-drug interaction benchmark metrics."""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any, Awaitable, Callable


SEVERITIES = ("minor", "moderate", "major", "unknown")


def _pair_key(drug_a: str, drug_b: str) -> tuple[str, str]:
    return tuple(sorted((drug_a.casefold().strip(), drug_b.casefold().strip())))


def _rate(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def _empty_seed_smoke() -> dict:
    return {
        "recall": 0.0,
        "false_alarm_rate": 0.0,
        "severity_accuracy": 0.0,
        "missed_pairs": [],
    }


def _seed_result_for(seed_results: dict, drug_a: str, drug_b: str) -> dict:
    return seed_results.get((drug_a, drug_b)) or seed_results.get(_pair_key(drug_a, drug_b)) or {}


def compute_seed_smoke(seed_cases: dict | None, seed_results: dict | None) -> dict:
    if not seed_cases or seed_results is None:
        return _empty_seed_smoke()
    positives = seed_cases.get("positive_pairs", [])
    negatives = seed_cases.get("known_safe_pairs", [])

    hits = 0
    severity_hits = 0
    severity_total = 0
    missed = []
    for case in positives:
        result = _seed_result_for(seed_results, case["drug_a"], case["drug_b"])
        interactions = result.get("interactions", [])
        if interactions and not result.get("safe", False):
            hits += 1
            expected_severity = case.get("severity")
            if expected_severity:
                severity_total += 1
                if interactions[0].get("severity") == expected_severity:
                    severity_hits += 1
        else:
            missed.append([case["drug_a"], case["drug_b"]])

    false_alarms = 0
    for case in negatives:
        result = _seed_result_for(seed_results, case["drug_a"], case["drug_b"])
        if result.get("interactions") or result.get("safe") is False:
            false_alarms += 1

    return {
        "recall": _rate(hits, len(positives)),
        "false_alarm_rate": _rate(false_alarms, len(negatives)),
        "severity_accuracy": _rate(severity_hits, severity_total),
        "missed_pairs": missed,
    }


async def run_seed_smoke(
    seed_cases: dict,
    check_func: Callable[[list[str]], Awaitable[dict[str, Any]]],
) -> dict[tuple[str, str], dict]:
    results = {}
    for case in seed_cases.get("positive_pairs", []) + seed_cases.get("known_safe_pairs", []):
        results[_pair_key(case["drug_a"], case["drug_b"])] = await check_func([case["drug_a"], case["drug_b"]])
    return results


def _accuracy(predictions: list[dict], dataset: list[dict]) -> dict | None:
    records = [record for record in dataset if record.get("expected_interactions")]
    if not records:
        return None
    predictions_by_id = {str(pred.get("record_id")): pred for pred in predictions}
    recalls = []
    severity_hits = 0
    severity_total = 0
    false_alarms = 0
    false_alarm_total = 0
    confusion = {expected: {predicted: 0 for predicted in SEVERITIES} for expected in SEVERITIES}

    for record in records:
        expected_pairs = {
            _pair_key(item["drug_a"], item["drug_b"]): item
            for item in record.get("expected_interactions", [])
            if item.get("interacts", True)
        }
        known_safe = {
            _pair_key(item["drug_a"], item["drug_b"])
            for item in record.get("known_safe_pairs", [])
        }
        pred = predictions_by_id.get(str(record.get("id")), {})
        predicted_pairs = {
            _pair_key(item["drug_a"], item["drug_b"]): item
            for item in (pred.get("interactions") or {}).get("interactions", [])
        }
        recalls.append(_rate(len(expected_pairs.keys() & predicted_pairs.keys()), len(expected_pairs)))
        false_alarm_total += len(predicted_pairs)
        false_alarms += len(known_safe & predicted_pairs.keys())
        for pair, expected in expected_pairs.items():
            if pair not in predicted_pairs:
                continue
            expected_severity = expected.get("severity", "unknown")
            predicted_severity = predicted_pairs[pair].get("severity", "unknown")
            if expected_severity not in SEVERITIES:
                expected_severity = "unknown"
            if predicted_severity not in SEVERITIES:
                predicted_severity = "unknown"
            confusion[expected_severity][predicted_severity] += 1
            severity_total += 1
            if expected_severity == predicted_severity:
                severity_hits += 1

    return {
        "recall": sum(recalls) / len(recalls),
        "false_alarm_rate": _rate(false_alarms, false_alarm_total),
        "severity_accuracy": _rate(severity_hits, severity_total),
        "severity_confusion": confusion,
    }


def compute(
    predictions: list[dict],
    dataset: list[dict],
    seed_cases: dict | None = None,
    seed_results: dict | None = None,
) -> dict:
    coverage = {"ddinter": 0, "openfda": 0, "unknown": 0}
    severity_distribution = {severity: 0 for severity in SEVERITIES}
    uncertain = 0
    returned = 0
    records_with_any = 0
    attempts = [attempt for prediction in predictions for attempt in prediction.get("interaction_attempts", [])]

    for prediction in predictions:
        interactions_response = prediction.get("interactions") or {}
        summary = interactions_response.get("coverage_summary", {})
        for key in coverage:
            coverage[key] += int(summary.get(key, 0))
        returned_interactions = interactions_response.get("interactions", [])
        if returned_interactions:
            records_with_any += 1
        for item in returned_interactions:
            severity = item.get("severity", "unknown")
            if severity not in severity_distribution:
                severity = "unknown"
            severity_distribution[severity] += 1
            returned += 1
            if item.get("uncertain"):
                uncertain += 1

    total_pairs = sum(coverage.values())
    attempt_diagnostics = _attempt_diagnostics(attempts)
    return {
        "descriptive": {
            "total_pairs_checked": total_pairs,
            "ddinter_hit_rate": _rate(coverage["ddinter"], total_pairs),
            "openfda_hit_rate": _rate(coverage["openfda"], total_pairs),
            "unknown_rate": _rate(coverage["unknown"], total_pairs),
            "severity_distribution": severity_distribution,
            "uncertain_rate": _rate(uncertain, returned),
            "records_with_any_interaction": records_with_any,
            **attempt_diagnostics,
        },
        "accuracy": _accuracy(predictions, dataset),
        "seed_smoke": compute_seed_smoke(seed_cases, seed_results),
    }


def _status(attempt: dict, component: str) -> str:
    block = attempt.get(component) or {}
    return str(block.get("status") or "skipped")


def _attempt_diagnostics(attempts: list[dict]) -> dict:
    total = len(attempts)
    source_counts = Counter(str(attempt.get("final_source") or "unknown") for attempt in attempts)
    ddinter_rxcui_hits = sum(1 for attempt in attempts if _status(attempt, "ddinter_rxcui") == "hit")
    ddinter_fts_hits = sum(1 for attempt in attempts if _status(attempt, "ddinter_fts") == "hit")
    openfda_hits = sum(1 for attempt in attempts if _status(attempt, "openfda") == "hit")
    unknown_pairs = Counter(
        _pair_key(str(attempt.get("drug_a", "")), str(attempt.get("drug_b", "")))
        for attempt in attempts
        if attempt.get("final_source") == "unknown"
    )
    return {
        "ddinter_rxcui_hit_rate": _rate(ddinter_rxcui_hits, total),
        "ddinter_fts_rescue_rate": _rate(ddinter_fts_hits, total),
        "openfda_rescue_rate": _rate(openfda_hits, total),
        "source_counts": {
            "ddinter": int(source_counts.get("ddinter", 0)),
            "openfda": int(source_counts.get("openfda", 0)),
            "unknown": int(source_counts.get("unknown", 0)),
        },
        "top_unknown_pairs": [
            {"drug_a": drug_a, "drug_b": drug_b, "count": count}
            for (drug_a, drug_b), count in unknown_pairs.most_common(10)
        ],
    }
