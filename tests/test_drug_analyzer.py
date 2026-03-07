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
