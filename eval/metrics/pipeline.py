"""Pipeline-level benchmark diagnostics."""

from __future__ import annotations

import math
from collections import Counter


TIMING_COMPONENTS = (
    "ocr_clean",
    "ner",
    "rxnorm",
    "ddinter_rxcui",
    "ddinter_fts",
    "openfda",
    "severity",
    "analyze",
    "interactions",
    "total",
)
def _rate(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def _percentile(values: list[float], percentile: int) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, math.ceil((percentile / 100) * len(ordered)) - 1)
    return round(ordered[index], 3)


def timing(predictions: list[dict]) -> dict:
    components: dict[str, dict] = {}
    for component in TIMING_COMPONENTS:
        values = [
            float(_timing_source(prediction).get(component, 0.0))
            for prediction in predictions
        ]
        components[component] = {
            "p50_ms": _percentile(values, 50),
            "p95_ms": _percentile(values, 95),
            "p99_ms": _percentile(values, 99),
            "max_ms": round(max(values), 3) if values else None,
            "mean_ms": round(sum(values) / len(values), 3) if values else None,
        }

    slowest_counts = Counter(
        prediction.get("slowest_component")
        for prediction in predictions
        if prediction.get("slowest_component")
    )
    return {
        "components": components,
        "slowest_component": slowest_counts.most_common(1)[0][0] if slowest_counts else None,
        "slowest_component_counts": dict(sorted(slowest_counts.items())),
    }


def _timing_source(prediction: dict) -> dict:
    timings = prediction.get("component_timings_ms")
    if timings is None:
        timings = prediction.get("elapsed_ms", {})
    return timings


def overall(
    predictions: list[dict],
    errors: list[dict],
    *,
    concurrency: int,
    wall_time_seconds: float,
) -> dict:
    records_total = len(predictions)
    records_errored = len({str(error.get("record_id")) for error in errors})
    records_completed = records_total - records_errored
    return {
        "records_total": records_total,
        "records_completed": records_completed,
        "records_errored": records_errored,
        "error_rate": _rate(records_errored, records_total),
        "timeout_count": sum(1 for error in errors if error.get("stage") == "record_timeout"),
        "concurrency": concurrency,
        "wall_time_seconds": round(wall_time_seconds, 3),
        "records_per_second": round(records_total / wall_time_seconds, 3) if wall_time_seconds > 0 else None,
    }


def errors(errors_: list[dict]) -> dict:
    by_stage = Counter(str(error.get("stage", "unknown")) for error in errors_)
    by_class = Counter(str(error.get("error_class", "unknown")) for error in errors_)
    return {
        "total": len(errors_),
        "by_stage": dict(sorted(by_stage.items())),
        "by_class": dict(sorted(by_class.items())),
        "records": [
            {
                "record_id": str(error.get("record_id", "")),
                "stage": error.get("stage"),
                "error_class": error.get("error_class"),
                "message": error.get("message"),
            }
            for error in errors_[:20]
        ],
    }
