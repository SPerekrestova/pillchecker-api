"""Unit tests for drug_analyzer — mocks RxNorm client and NER model.

Covers the fallback path quality filters:
  - Low-score approximate matches must be rejected
  - Empty drug names must be filtered out
  - High-confidence matches must still pass through
"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from app.clients.rxnorm_client import DrugInfo
from app.services import drug_analyzer
from app.nlp import ner_model


def _no_ner(text):
    """Stub NER predict that always returns no drug entities."""
    return []


# ─── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def mock_ner():
    """Patch NER so tests don't require the model to be loaded."""
    with patch("app.services.drug_analyzer.ner_model.predict", side_effect=_no_ner):
        yield


# ─── Score threshold tests ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_low_score_candidate_rejected():
    """A candidate with score < threshold must not appear in results."""
    low_score_candidate = DrugInfo(rxcui="2388160", name="Hello Bello", score=3.98)

    with patch(
        "app.services.drug_analyzer.rxnorm_client.approximate_term",
        new=AsyncMock(return_value=[low_score_candidate]),
    ):
        results = await drug_analyzer.analyze("hello world")

    assert results == [], (
        f"Expected no results for low-score match, got: {results}"
    )


@pytest.mark.asyncio
async def test_high_score_candidate_accepted():
    """A candidate with score >= threshold and a valid name must be returned."""
    high_score_candidate = DrugInfo(rxcui="5640", name="Ibuprofen", score=10.55)

    with (
        patch(
            "app.services.drug_analyzer.rxnorm_client.approximate_term",
            new=AsyncMock(return_value=[high_score_candidate]),
        ),
        patch(
            "app.services.drug_analyzer.rxnorm_client.get_drug_details",
            new=AsyncMock(return_value={"name": "ibuprofen"}),
        ),
    ):
        results = await drug_analyzer.analyze("ibuprofen")

    assert len(results) == 1
    assert results[0]["name"] == "ibuprofen"
    assert results[0]["source"] == "rxnorm_fallback"
    assert results[0]["rxcui"] == "5640"


# ─── Empty name filter tests ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_empty_name_candidate_rejected():
    """A candidate with empty name (MMSL source) and empty details must be skipped."""
    nameless_candidate = DrugInfo(rxcui="2388160", name="", score=9.0)

    with (
        patch(
            "app.services.drug_analyzer.rxnorm_client.approximate_term",
            new=AsyncMock(return_value=[nameless_candidate]),
        ),
        patch(
            "app.services.drug_analyzer.rxnorm_client.get_drug_details",
            new=AsyncMock(return_value={}),
        ),
    ):
        results = await drug_analyzer.analyze("some text")

    assert results == [], (
        f"Expected no results when resolved name is empty, got: {results}"
    )


@pytest.mark.asyncio
async def test_empty_best_name_resolved_from_details():
    """When candidate name is empty but details has a name, use the details name."""
    nameless_candidate = DrugInfo(rxcui="5640", name="", score=9.0)

    with (
        patch(
            "app.services.drug_analyzer.rxnorm_client.approximate_term",
            new=AsyncMock(return_value=[nameless_candidate]),
        ),
        patch(
            "app.services.drug_analyzer.rxnorm_client.get_drug_details",
            new=AsyncMock(return_value={"name": "ibuprofen"}),
        ),
    ):
        results = await drug_analyzer.analyze("ibuprofen 400mg")

    assert len(results) == 1
    assert results[0]["name"] == "ibuprofen"


# ─── No candidates ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_no_candidates_returns_empty():
    """When RxNorm returns no candidates for any word, result is empty list."""
    with patch(
        "app.services.drug_analyzer.rxnorm_client.approximate_term",
        new=AsyncMock(return_value=[]),
    ):
        results = await drug_analyzer.analyze("xyzzy nonsense zzz")

    assert results == []


# ─── NER entity filtering tests ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_ner_entity_without_rxcui_filtered_out():
    """NER entities that don't match any RxNorm drug must be excluded."""
    fake_entity = ner_model.Entity(
        text="Pactavis", label="CHEM", score=0.85, start=0, end=8,
    )

    with (
        patch(
            "app.services.drug_analyzer.ner_model.predict",
            return_value=[fake_entity],
        ),
        patch(
            "app.services.drug_analyzer.rxnorm_client.get_rxcui",
            new=AsyncMock(return_value=None),
        ),
        # Fallback should also find nothing
        patch(
            "app.services.drug_analyzer.rxnorm_client.approximate_term",
            new=AsyncMock(return_value=[]),
        ),
    ):
        results = await drug_analyzer.analyze("Pactavis 6 tablets")

    assert results == [], (
        f"Expected no results for NER entity without RxCUI, got: {results}"
    )


@pytest.mark.asyncio
async def test_ner_entity_with_rxcui_returned():
    """NER entities that match a RxNorm drug must be returned."""
    entity = ner_model.Entity(
        text="Paracetamol", label="CHEM", score=0.95, start=0, end=11,
    )

    with (
        patch(
            "app.services.drug_analyzer.ner_model.predict",
            return_value=[entity],
        ),
        patch(
            "app.services.drug_analyzer.rxnorm_client.get_rxcui",
            new=AsyncMock(return_value="161"),
        ),
    ):
        results = await drug_analyzer.analyze("Paracetamol 500mg")

    assert len(results) == 1
    assert results[0]["name"] == "Paracetamol"
    assert results[0]["rxcui"] == "161"
    assert results[0]["source"] == "ner"


@pytest.mark.asyncio
async def test_all_ner_filtered_falls_through_to_fallback():
    """When all NER entities lack rxcui, fallback path should be used."""
    fake_entity = ner_model.Entity(
        text="Pactavis", label="CHEM", score=0.85, start=0, end=8,
    )
    fallback_candidate = DrugInfo(rxcui="10689", name="Trimethoprim", score=10.5)

    with (
        patch(
            "app.services.drug_analyzer.ner_model.predict",
            return_value=[fake_entity],
        ),
        patch(
            "app.services.drug_analyzer.rxnorm_client.get_rxcui",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "app.services.drug_analyzer.rxnorm_client.approximate_term",
            new=AsyncMock(return_value=[fallback_candidate]),
        ),
        patch(
            "app.services.drug_analyzer.rxnorm_client.get_drug_details",
            new=AsyncMock(return_value={"name": "trimethoprim"}),
        ),
    ):
        results = await drug_analyzer.analyze("Pactavis Trimethoprim Tablets")

    assert len(results) == 1
    assert results[0]["name"] == "trimethoprim"
    assert results[0]["source"] == "rxnorm_fallback"


@pytest.mark.asyncio
async def test_ner_results_sorted_by_confidence_descending():
    """Results must be sorted by confidence, highest first."""
    entities = [
        ner_model.Entity(text="Aspirin", label="CHEM", score=0.70, start=0, end=7),
        ner_model.Entity(text="Ibuprofen", label="CHEM", score=0.95, start=20, end=29),
    ]

    async def mock_get_rxcui(name):
        return {"Aspirin": "1191", "Ibuprofen": "5640"}.get(name)

    with (
        patch(
            "app.services.drug_analyzer.ner_model.predict",
            return_value=entities,
        ),
        patch(
            "app.services.drug_analyzer.rxnorm_client.get_rxcui",
            new=AsyncMock(side_effect=mock_get_rxcui),
        ),
    ):
        results = await drug_analyzer.analyze("Aspirin tablets plus Ibuprofen")

    assert len(results) == 2
    assert results[0]["name"] == "Ibuprofen", "Highest confidence drug should be first"
    assert results[1]["name"] == "Aspirin"
