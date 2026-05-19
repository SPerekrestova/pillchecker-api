import pytest

from eval import prepare_interaction_labels as labels


@pytest.mark.asyncio
async def test_build_candidates_marks_source_hits_as_review_only(monkeypatch):
    records = [
        {
            "id": "dual-1",
            "category": "dual_ingredient",
            "expected_names": ["warfarin", "ibuprofen"],
        },
        {
            "id": "multi-1",
            "category": "multi_ingredient",
            "expected_names": ["acetaminophen", "atorvastatin", "caffeine"],
        },
    ]
    rxcuis = {
        "warfarin": "11289",
        "ibuprofen": "5640",
        "acetaminophen": "161",
        "atorvastatin": "83367",
        "caffeine": "1886",
    }

    async def fake_get_rxcui(name):
        return rxcuis[name]

    async def fake_ddinter(rxcui_a, rxcui_b):
        if {rxcui_a, rxcui_b} == {"11289", "5640"}:
            return {
                "drug_a_id": "DDI00001",
                "drug_b_id": "DDI00002",
                "severity": "major",
                "atc_category": "B01 + M01",
            }
        return None

    async def no_fts(_name_a, _name_b):
        return None

    async def no_openfda(_drug_a, _drug_b):
        return None

    monkeypatch.setattr(labels.rxnorm_client, "get_rxcui", fake_get_rxcui)
    monkeypatch.setattr(labels.ddinter_db.client, "lookup_by_rxcui", fake_ddinter)
    monkeypatch.setattr(labels.ddinter_db.client, "lookup_by_name_fts", no_fts)
    monkeypatch.setattr(labels.openfda_client, "check_pair", no_openfda)

    output = await labels.build_candidates(records, concurrency=2, dataset_revision="rev-a")

    assert output["dataset_revision"] == "rev-a"
    assert output["errors"] == []
    assert len(output["candidates"]) == 4
    for candidate in output["candidates"]:
        assert candidate["is_ground_truth"] is False
        assert candidate["review_status"] == "unreviewed"
        assert "known_safe" not in candidate

    source_hit = next(c for c in output["candidates"] if c["record_id"] == "dual-1")
    assert source_hit["candidate_status"] == "source_hit"
    assert source_hit["suggested_interacts"] is True
    assert source_hit["suggested_severity"] == "major"
    assert source_hit["ddinter"]["hit"] is True

    no_hit = next(
        c for c in output["candidates"]
        if c["drug_a"] == "acetaminophen" and c["drug_b"] == "atorvastatin"
    )
    assert no_hit["candidate_status"] == "no_source_hit"
    assert no_hit["suggested_interacts"] is None
    assert no_hit["suggested_severity"] is None


@pytest.mark.asyncio
async def test_build_candidates_uses_openfda_reversed_order(monkeypatch):
    records = [
        {
            "id": "dual-2",
            "category": "dual_ingredient",
            "expected_names": ["drug a", "drug b"],
        }
    ]

    async def no_rxcui(_name):
        return None

    async def no_ddinter(*_args):
        return None

    async def fake_openfda(drug_a, drug_b):
        if (drug_a, drug_b) == ("drug b", "drug a"):
            return {"description": "Label text mentions interaction."}
        return None

    monkeypatch.setattr(labels.rxnorm_client, "get_rxcui", no_rxcui)
    monkeypatch.setattr(labels.ddinter_db.client, "lookup_by_rxcui", no_ddinter)
    monkeypatch.setattr(labels.ddinter_db.client, "lookup_by_name_fts", no_ddinter)
    monkeypatch.setattr(labels.openfda_client, "check_pair", fake_openfda)

    output = await labels.build_candidates(records, concurrency=1, dataset_revision="rev-b")

    candidate = output["candidates"][0]
    assert candidate["candidate_status"] == "source_hit"
    assert candidate["suggested_interacts"] is True
    assert candidate["openfda"] == {"hit": True, "description": "Label text mentions interaction."}
    assert candidate["evidence"][0]["source"] == "openfda"


@pytest.mark.asyncio
async def test_build_candidates_records_pair_errors(monkeypatch):
    records = [
        {
            "id": "dual-3",
            "category": "dual_ingredient",
            "expected_names": ["drug a", "drug b"],
        }
    ]

    async def broken_rxcui(_name):
        raise RuntimeError("rxnorm unavailable")

    monkeypatch.setattr(labels.rxnorm_client, "get_rxcui", broken_rxcui)

    output = await labels.build_candidates(records, concurrency=1, dataset_revision="rev-c")

    assert output["candidates"][0]["candidate_status"] == "error"
    assert output["candidates"][0]["is_ground_truth"] is False
    assert output["errors"][0]["error_class"] == "RuntimeError"
