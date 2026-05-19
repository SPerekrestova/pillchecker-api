from eval.metrics import ner


def test_strict_match_normalizes_case():
    predictions = [{"record_id": "1", "ner_entities": [{"text": "Ibuprofen", "score": 0.9}]}]
    dataset = [{"id": "1", "expected_names": ["ibuprofen"], "category": "single_ingredient"}]

    result = ner.compute(predictions, dataset)

    assert result["strict"]["f1"] == 1.0
    assert result["lenient"]["f1"] == 1.0


def test_lenient_match_handles_salt_or_hydrate_variant():
    predictions = [{"record_id": "1", "ner_entities": [{"text": "amoxicillin trihydrate", "score": 0.9}]}]
    dataset = [{"id": "1", "expected_names": ["amoxicillin"], "category": "single_ingredient"}]

    result = ner.compute(predictions, dataset)

    assert result["strict"]["f1"] == 0.0
    assert result["lenient"]["f1"] == 1.0


def test_confidence_sweep_recall_is_non_increasing():
    predictions = [{
        "record_id": "1",
        "ner_entities": [
            {"text": "ibuprofen", "score": 0.9},
            {"text": "warfarin", "score": 0.6},
        ],
    }]
    dataset = [{"id": "1", "expected_names": ["ibuprofen", "warfarin"], "category": "dual_ingredient"}]

    result = ner.compute(predictions, dataset, thresholds=[0.5, 0.85])

    assert result["confidence_sweep"]["0.50"]["strict"]["recall"] == 1.0
    assert result["confidence_sweep"]["0.85"]["strict"]["recall"] == 0.5
