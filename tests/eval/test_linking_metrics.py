from eval.metrics import linking


def test_linking_nil_rate_from_explicit_attempts():
    predictions = [{
        "record_id": "1",
        "drugs": [
            {"name": "ibuprofen", "rxcui": "5640", "source": "ner"},
            {"name": "unknown", "rxcui": None, "source": "ner"},
        ],
        "link_attempts": [
            {"name": "ibuprofen", "rxcui": "5640"},
            {"name": "warfarin", "rxcui": "11289"},
            {"name": "unknown", "rxcui": None},
        ],
    }]

    result = linking.compute(predictions, [{"id": "1", "expected_names": ["ibuprofen"]}])

    assert result["coverage"] == 0.5
    assert result["nil_rate"] == 1 / 3
    assert result["n_link_attempts"] == 3


def test_linking_nil_rate_none_without_attempts():
    result = linking.compute([{"record_id": "1", "drugs": [], "link_attempts": []}], [{"id": "1"}])

    assert result["nil_rate"] is None
    assert result["n_link_attempts"] == 0


def test_linking_gt_metrics_when_expected_rxcuis_present():
    predictions = [{
        "record_id": "1",
        "drugs": [
            {"name": "ibuprofen", "rxcui": "5640", "source": "ner"},
            {"name": "wrong", "rxcui": "1", "source": "rxnorm_fallback"},
        ],
        "link_attempts": [{"name": "ibuprofen", "rxcui": "5640"}],
    }]
    dataset = [{"id": "1", "expected_rxcuis": ["5640"]}]

    result = linking.compute(predictions, dataset)

    assert result["acc_at_1"] == 1.0
    assert result["fallback_rate"] == 0.5
    assert result["incorrect_link_rate"] == 0.5
