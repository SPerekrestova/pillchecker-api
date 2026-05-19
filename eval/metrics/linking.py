"""RxNorm linking metrics."""

from __future__ import annotations


def _rate(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def compute(predictions: list[dict], dataset: list[dict]) -> dict:
    drugs = [drug for pred in predictions for drug in pred.get("drugs", [])]
    attempts = [attempt for pred in predictions for attempt in pred.get("link_attempts", [])]
    resolved = sum(1 for drug in drugs if drug.get("rxcui"))
    fallback = sum(1 for drug in drugs if drug.get("source") == "rxnorm_fallback")
    nil_count = sum(1 for attempt in attempts if attempt.get("rxcui") is None)

    records_with_gt = [record for record in dataset if record.get("expected_rxcuis")]
    predictions_by_id = {str(pred.get("record_id")): pred for pred in predictions}
    acc_at_1 = None
    incorrect_link_rate = None
    if records_with_gt:
        acc_values = []
        incorrect = 0
        predicted_with_rxcui_total = 0
        for record in records_with_gt:
            expected = {str(value) for value in record.get("expected_rxcuis", [])}
            pred = predictions_by_id.get(str(record.get("id")), {})
            predicted = set()
            for drug in pred.get("drugs", []):
                rxcui = drug.get("rxcui")
                if not rxcui:
                    continue
                predicted_with_rxcui_total += 1
                rxcui_str = str(rxcui)
                predicted.add(rxcui_str)
                if rxcui_str not in expected:
                    incorrect += 1
            acc_values.append(len(expected & predicted) / len(expected) if expected else 0.0)
        acc_at_1 = sum(acc_values) / len(acc_values)
        incorrect_link_rate = _rate(incorrect, predicted_with_rxcui_total)

    return {
        "coverage": _rate(resolved, len(drugs)),
        "fallback_rate": _rate(fallback, len(drugs)),
        "nil_rate": _rate(nil_count, len(attempts)) if attempts else None,
        "n_link_attempts": len(attempts),
        "n_drugs_total": len(drugs),
        "acc_at_1": acc_at_1,
        "incorrect_link_rate": incorrect_link_rate,
    }
