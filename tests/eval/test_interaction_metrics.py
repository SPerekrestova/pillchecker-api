from eval.metrics import interactions


def test_interaction_descriptive_counts_all_buckets():
    predictions = [{
        "record_id": "1",
        "interactions": {
            "coverage_summary": {"ddinter": 1, "openfda": 1, "unknown": 1},
            "interactions": [
                {"drug_a": "a", "drug_b": "b", "severity": "major", "uncertain": False},
                {"drug_a": "c", "drug_b": "d", "severity": "unknown", "uncertain": True},
            ],
        },
    }]

    result = interactions.compute(predictions, [{"id": "1"}])

    assert result["descriptive"]["total_pairs_checked"] == 3
    assert result["descriptive"]["ddinter_hit_rate"] == 1 / 3
    assert result["descriptive"]["openfda_hit_rate"] == 1 / 3
    assert result["descriptive"]["unknown_rate"] == 1 / 3
    assert result["descriptive"]["severity_distribution"]["major"] == 1
    assert result["descriptive"]["uncertain_rate"] == 0.5


def test_interaction_accuracy_none_without_reviewed_labels():
    dataset = [{"id": "1", "expected_interactions": []}]

    result = interactions.compute([], dataset)

    assert result["accuracy"] is None


def test_interaction_accuracy_and_known_safe_false_alarm():
    predictions = [{
        "record_id": "1",
        "interactions": {
            "coverage_summary": {"ddinter": 2, "openfda": 0, "unknown": 0},
            "interactions": [
                {"drug_a": "warfarin", "drug_b": "ibuprofen", "severity": "major", "uncertain": False},
                {"drug_a": "acetaminophen", "drug_b": "atorvastatin", "severity": "unknown", "uncertain": False},
            ],
        },
    }]
    dataset = [{
        "id": "1",
        "expected_interactions": [
            {"drug_a": "ibuprofen", "drug_b": "warfarin", "interacts": True, "severity": "major"}
        ],
        "known_safe_pairs": [
            {"drug_a": "acetaminophen", "drug_b": "atorvastatin", "interacts": False}
        ],
    }]

    result = interactions.compute(predictions, dataset)

    assert result["accuracy"]["recall"] == 1.0
    assert result["accuracy"]["false_alarm_rate"] == 0.5
    assert result["accuracy"]["severity_accuracy"] == 1.0


def test_seed_smoke_reads_known_safe_pairs_key():
    seed_cases = {
        "positive_pairs": [{"drug_a": "a", "drug_b": "b", "severity": "major"}],
        "known_safe_pairs": [{"drug_a": "c", "drug_b": "d"}],
    }
    seed_results = {
        ("a", "b"): {"safe": False, "interactions": [{"drug_a": "a", "drug_b": "b", "severity": "major"}]},
        ("c", "d"): {"safe": True, "interactions": []},
    }

    result = interactions.compute([], [], seed_cases=seed_cases, seed_results=seed_results)

    assert result["seed_smoke"]["recall"] == 1.0
    assert result["seed_smoke"]["false_alarm_rate"] == 0.0
    assert result["seed_smoke"]["severity_accuracy"] == 1.0
