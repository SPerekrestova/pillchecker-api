"""RxNorm linking metrics."""

from __future__ import annotations

from collections import defaultdict


def _rate(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def compute(predictions: list[dict], dataset: list[dict]) -> dict:
    drugs = [drug for pred in predictions for drug in pred.get("drugs", [])]
    attempts = [attempt for pred in predictions for attempt in pred.get("link_attempts", [])]
    rxnorm_attempts = [attempt for pred in predictions for attempt in pred.get("rxnorm_attempts", [])]
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

    diagnostics = _rxnorm_diagnostics(rxnorm_attempts)
    return {
        "coverage": _rate(resolved, len(drugs)),
        "fallback_rate": _rate(fallback, len(drugs)),
        "nil_rate": _rate(nil_count, len(attempts)) if attempts else None,
        "n_link_attempts": len(attempts),
        "n_drugs_total": len(drugs),
        "acc_at_1": acc_at_1,
        "incorrect_link_rate": incorrect_link_rate,
        **diagnostics,
    }


def _rxnorm_diagnostics(attempts: list[dict]) -> dict:
    by_method: dict[str, dict[str, int]] = defaultdict(lambda: {"hit": 0, "miss": 0, "error": 0})
    unresolved = []
    queries_by_rxcui: dict[str, set[str]] = defaultdict(set)

    for attempt in attempts:
        method = str(attempt.get("method") or "unknown")
        status = str(attempt.get("status") or "unknown")
        if status not in {"hit", "miss", "error"}:
            status = "miss" if attempt.get("rxcui") is None else "hit"
        by_method[method][status] += 1

        query = str(attempt.get("query") or attempt.get("name") or "")
        rxcui = attempt.get("rxcui")
        if rxcui:
            queries_by_rxcui[str(rxcui)].add(query)
        elif status in {"miss", "error"}:
            unresolved.append({
                "query": query,
                "stage": attempt.get("stage"),
                "method": method,
            })

    collisions = [
        {"rxcui": rxcui, "queries": sorted(query for query in queries if query)}
        for rxcui, queries in sorted(queries_by_rxcui.items())
        if len({query.casefold() for query in queries if query}) > 1
    ]
    return {
        "n_rxnorm_attempts": len(attempts),
        "rxnorm_by_method": {
            method: counts
            for method, counts in sorted(by_method.items())
        },
        "unresolved_queries": unresolved[:20],
        "canonicalization_collisions": collisions[:20],
    }
