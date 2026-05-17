"""Tests for interaction_checker DDInter -> OpenFDA -> unknown routing."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.services import interaction_checker


@pytest.fixture(autouse=True)
def patch_clients(monkeypatch):
    rx = AsyncMock(return_value=None)
    monkeypatch.setattr(interaction_checker.rxnorm_client, "get_rxcui", rx)

    ddc = AsyncMock(return_value=None)
    ddn = AsyncMock(return_value=None)
    monkeypatch.setattr(interaction_checker.ddinter_db.client, "lookup_by_rxcui", ddc)
    monkeypatch.setattr(interaction_checker.ddinter_db.client, "lookup_by_name_fts", ddn)

    fda = AsyncMock(return_value=None)
    monkeypatch.setattr(interaction_checker.openfda_client, "check_pair", fda)
    return {"rxnorm": rx, "ddinter_rxcui": ddc, "ddinter_fts": ddn, "openfda": fda}


async def test_ddinter_hit_via_rxcui(patch_clients):
    patch_clients["rxnorm"].side_effect = ["11289", "1191"]
    patch_clients["ddinter_rxcui"].return_value = {
        "drug_a_id": "DDInter1",
        "drug_b_id": "DDInter2",
        "drug_a_name": "Warfarin",
        "drug_b_name": "Aspirin",
        "severity": "major",
        "source": "ddinter",
        "atc_category": "B",
    }
    result = await interaction_checker.check(["Warfarin", "Aspirin"])
    assert result["coverage_summary"]["ddinter"] == 1
    assert result["interactions"][0]["source"] == "ddinter"
    assert result["interactions"][0]["severity"] == "major"
    assert result["interactions"][0]["rxcui_a"] == "11289"
    patch_clients["openfda"].assert_not_called()


async def test_falls_back_to_fts_when_rxcui_misses(patch_clients):
    patch_clients["rxnorm"].side_effect = [None, None]
    patch_clients["ddinter_fts"].return_value = {
        "drug_a_id": "DDInter1",
        "drug_b_id": "DDInter2",
        "drug_a_name": "Warfarin",
        "drug_b_name": "Aspirin",
        "severity": "major",
        "source": "ddinter",
        "atc_category": "B",
    }
    result = await interaction_checker.check(["Warfarin", "Aspirin"])
    assert result["interactions"][0]["source"] == "ddinter"
    patch_clients["openfda"].assert_not_called()


async def test_openfda_fallback_when_ddinter_misses(patch_clients):
    patch_clients["rxnorm"].side_effect = ["11289", "1191"]
    patch_clients["openfda"].return_value = {"drug": "Aspirin", "description": "Some FDA label sentence."}
    with patch.object(interaction_checker.severity_classifier, "classify", return_value=("moderate", False)):
        result = await interaction_checker.check(["Warfarin", "Aspirin"])
    assert result["interactions"][0]["source"] == "openfda"
    assert result["interactions"][0]["severity"] == "moderate"
    assert result["coverage_summary"]["openfda"] == 1


async def test_unknown_when_all_paths_miss(patch_clients):
    patch_clients["rxnorm"].side_effect = ["1", "2"]
    result = await interaction_checker.check(["A", "B"])
    assert result["coverage_summary"] == {"ddinter": 0, "openfda": 0, "unknown": 1}
    assert result["interactions"] == []


async def test_openfda_low_confidence_keeps_safety_default(patch_clients):
    patch_clients["rxnorm"].side_effect = ["1", "2"]
    patch_clients["openfda"].return_value = {"drug": "B", "description": "vague text"}
    with patch.object(interaction_checker.severity_classifier, "classify", return_value=("major", True)):
        result = await interaction_checker.check(["A", "B"])
    assert result["interactions"][0]["severity"] == "major"
    assert result["interactions"][0]["uncertain"] is True
