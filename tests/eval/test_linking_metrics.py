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


def test_linking_reports_rxnorm_attempt_diagnostics():
    predictions = [{
        "record_id": "1",
        "drugs": [
            {"name": "Advil", "rxcui": "5640", "source": "rxnorm_fallback"},
            {"name": "unknown", "rxcui": None, "source": "ner"},
        ],
        "rxnorm_attempts": [
            {
                "stage": "analyze",
                "method": "get_rxcui",
                "query": "unknown",
                "rxcui": None,
                "status": "miss",
                "elapsed_ms": 1.0,
            },
            {
                "stage": "analyze",
                "method": "approximate_term",
                "query": "Advil",
                "rxcui": "5640",
                "status": "hit",
                "elapsed_ms": 2.0,
            },
            {
                "stage": "interactions",
                "method": "get_rxcui",
                "query": "Ibuprofen",
                "rxcui": "5640",
                "status": "hit",
                "elapsed_ms": 1.5,
            },
        ],
    }]

    result = linking.compute(predictions, [{"id": "1"}])

    assert result["n_rxnorm_attempts"] == 3
    assert result["rxnorm_by_method"]["get_rxcui"]["hit"] == 1
    assert result["rxnorm_by_method"]["get_rxcui"]["miss"] == 1
    assert result["rxnorm_by_method"]["approximate_term"]["hit"] == 1
    assert result["unresolved_queries"] == [{"query": "unknown", "stage": "analyze", "method": "get_rxcui"}]
    assert result["canonicalization_collisions"] == [{
        "rxcui": "5640",
        "queries": ["Advil", "Ibuprofen"],
    }]


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


def test_incorrect_link_rate_respects_record_boundaries():
    predictions = [
        {
            "record_id": "1",
            "drugs": [{"name": "wrong-for-record-1", "rxcui": "222", "source": "ner"}],
            "link_attempts": [{"name": "wrong-for-record-1", "rxcui": "222"}],
        },
        {
            "record_id": "2",
            "drugs": [{"name": "drug-2", "rxcui": "222", "source": "ner"}],
            "link_attempts": [{"name": "drug-2", "rxcui": "222"}],
        },
    ]
    dataset = [
        {"id": "1", "expected_rxcuis": ["111"]},
        {"id": "2", "expected_rxcuis": ["222"]},
    ]

    result = linking.compute(predictions, dataset)

    assert result["incorrect_link_rate"] == 0.5
