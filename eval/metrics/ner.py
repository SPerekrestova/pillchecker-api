"""NER benchmark metrics."""

from __future__ import annotations

import re
import string
from collections import defaultdict
from typing import Callable


_SALT_SUFFIX = re.compile(
    r"\s+(sodium|hydrochloride|hcl|sulfate|calcium|phosphate|maleate|potassium|tartrate|fumarate|citrate)$",
    re.IGNORECASE,
)


def normalize_name(value: str) -> str:
    value = value.lower().strip(string.punctuation + string.whitespace)
    value = re.sub(r"\s+", " ", value)
    return _SALT_SUFFIX.sub("", value).strip()


def _token_jaccard(left: str, right: str) -> float:
    left_tokens = set(normalize_name(left).split())
    right_tokens = set(normalize_name(right).split())
    if not left_tokens and not right_tokens:
        return 1.0
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


def _strict_match(left: str, right: str) -> bool:
    return normalize_name(left) == normalize_name(right)


def _lenient_match(left: str, right: str) -> bool:
    return _strict_match(left, right) or _token_jaccard(left, right) >= 0.5


def _prf(tp: int, fp: int, fn: int) -> dict[str, float]:
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {"precision": precision, "recall": recall, "f1": f1}


def _record_metrics(predicted: list[str], expected: list[str], matcher: Callable[[str, str], bool]) -> dict[str, float]:
    counts = _record_counts(predicted, expected, matcher)
    return _prf(counts["tp"], counts["fp"], counts["fn"])


def _record_counts(predicted: list[str], expected: list[str], matcher: Callable[[str, str], bool]) -> dict[str, int]:
    matched_expected: set[int] = set()
    tp = 0
    for pred in predicted:
        match_index = next(
            (idx for idx, exp in enumerate(expected) if idx not in matched_expected and matcher(pred, exp)),
            None,
        )
        if match_index is not None:
            matched_expected.add(match_index)
            tp += 1
    fp = len(predicted) - tp
    fn = len(expected) - tp
    return {"tp": tp, "fp": fp, "fn": fn}


def diagnostics_for_entities(entities: list[dict], expected_names: list[str]) -> dict:
    predicted = [str(entity.get("text", "")) for entity in entities]
    expected = [str(name) for name in expected_names]
    strict = _record_counts(predicted, expected, _strict_match)
    lenient = _record_counts(predicted, expected, _lenient_match)
    return {
        "entities": entities,
        "strict": strict,
        "lenient": lenient,
        "expected_count": len(expected),
        "predicted_count": len(predicted),
        "low_confidence_count": sum(1 for entity in entities if float(entity.get("score", 1.0)) < 0.85),
    }


def _average(blocks: list[dict[str, float]]) -> dict[str, float]:
    if not blocks:
        return {"precision": 0.0, "recall": 0.0, "f1": 0.0}
    return {
        key: sum(block[key] for block in blocks) / len(blocks)
        for key in ("precision", "recall", "f1")
    }


def _entities_for_threshold(prediction: dict, threshold: float) -> list[str]:
    return [
        str(entity.get("text", ""))
        for entity in prediction.get("ner_entities", [])
        if float(entity.get("score", 1.0)) >= threshold
    ]


def _compute_blocks(predictions: list[dict], dataset: list[dict], threshold: float = 0.0) -> dict:
    predictions_by_id = {str(pred.get("record_id")): pred for pred in predictions}
    strict_blocks = []
    lenient_blocks = []
    per_category: dict[str, dict[str, list[dict[str, float]]]] = defaultdict(lambda: {"strict": [], "lenient": []})
    per_noise: dict[str, dict[str, list[dict[str, float]]]] = defaultdict(lambda: {"strict": [], "lenient": []})
    saw_noise = False

    for record in dataset:
        prediction = predictions_by_id.get(str(record.get("id")), {})
        predicted = _entities_for_threshold(prediction, threshold)
        expected = [str(name) for name in record.get("expected_names", [])]
        strict = _record_metrics(predicted, expected, _strict_match)
        lenient = _record_metrics(predicted, expected, _lenient_match)
        strict_blocks.append(strict)
        lenient_blocks.append(lenient)
        category = str(record.get("category", "unknown"))
        per_category[category]["strict"].append(strict)
        per_category[category]["lenient"].append(lenient)
        if record.get("ocr_noise_level") is not None:
            saw_noise = True
            noise = str(record.get("ocr_noise_level", "unknown"))
            per_noise[noise]["strict"].append(strict)
            per_noise[noise]["lenient"].append(lenient)

    return {
        "strict": _average(strict_blocks),
        "lenient": _average(lenient_blocks),
        "per_category": {
            category: {
                "strict": _average(values["strict"]),
                "lenient": _average(values["lenient"]),
            }
            for category, values in per_category.items()
        },
        "per_noise_level": {
            noise: {
                "strict": _average(values["strict"]),
                "lenient": _average(values["lenient"]),
            }
            for noise, values in per_noise.items()
        } if saw_noise else None,
    }


def _score_distribution(predictions: list[dict]) -> dict[str, int]:
    bins = {f"{idx / 10:.1f}": 0 for idx in range(10)}
    for prediction in predictions:
        for entity in prediction.get("ner_entities", []):
            score = max(0.0, min(float(entity.get("score", 0.0)), 0.9999))
            lower = int(score * 10) / 10
            bins[f"{lower:.1f}"] += 1
    return bins


def compute(predictions: list[dict], dataset: list[dict], thresholds: list[float] | None = None) -> dict:
    thresholds = thresholds or [round(0.5 + idx * 0.05, 2) for idx in range(11)]
    base = _compute_blocks(predictions, dataset)
    confidence_sweep = {}
    for threshold in thresholds:
        threshold_block = _compute_blocks(predictions, dataset, threshold)
        kept = sum(len(_entities_for_threshold(pred, threshold)) for pred in predictions)
        confidence_sweep[f"{threshold:.2f}"] = {
            "strict": threshold_block["strict"],
            "lenient": threshold_block["lenient"],
            "kept_entity_count": kept,
        }
    return {
        **base,
        "confidence_sweep": confidence_sweep,
        "score_distribution": _score_distribution(predictions),
        "n_records_scored": len(dataset),
    }
