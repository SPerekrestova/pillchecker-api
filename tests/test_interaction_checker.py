"""Tests for the interaction checker service."""

import pytest
from unittest.mock import AsyncMock, patch
from app.clients.drugbank_client import DrugBankUnavailableError
from app.services import interaction_checker


@pytest.fixture(autouse=True)
def mock_drugbank():
    """Mock drugbank_client.get_interactions for all tests."""
    with patch("app.services.interaction_checker.drugbank_client") as mock:
        mock.get_interactions = AsyncMock()
        mock.DrugBankUnavailableError = DrugBankUnavailableError
        yield mock


@pytest.fixture(autouse=True)
def mock_severity():
    """Mock severity_classifier.classify for all tests."""
    with patch("app.services.interaction_checker.severity_classifier") as mock:
        mock.classify.return_value = "moderate"
        yield mock


class TestInteractionChecker:
    async def test_two_interacting_drugs(self, mock_drugbank, mock_severity):
        mock_drugbank.get_interactions.side_effect = [
            [{"drug": "Warfarin", "description": "Increases bleeding risk."}],
            [{"drug": "Ibuprofen", "description": "Increases bleeding risk."}],
        ]
        result = await interaction_checker.check(["ibuprofen", "warfarin"])
        assert result["safe"] is False
        assert len(result["interactions"]) == 1
        assert result["interactions"][0]["drug_a"] == "ibuprofen"
        assert result["interactions"][0]["drug_b"] == "warfarin"
        assert result["interactions"][0]["severity"] == "moderate"
        assert result["interactions"][0]["description"] == "Increases bleeding risk."
        assert result["error"] is None

    async def test_two_safe_drugs(self, mock_drugbank):
        mock_drugbank.get_interactions.side_effect = [
            [{"drug": "Metformin", "description": "some interaction"}],
            [{"drug": "Lisinopril", "description": "some interaction"}],
        ]
        result = await interaction_checker.check(["ibuprofen", "amoxicillin"])
        assert result["safe"] is True
        assert result["interactions"] == []

    async def test_three_drugs_multiple_interactions(self, mock_drugbank):
        mock_drugbank.get_interactions.side_effect = [
            [{"drug": "Warfarin", "description": "bleeding"}, {"drug": "Aspirin", "description": "bleeding"}],
            [{"drug": "Ibuprofen", "description": "bleeding"}, {"drug": "Aspirin", "description": "bleeding"}],
            [{"drug": "Ibuprofen", "description": "bleeding"}, {"drug": "Warfarin", "description": "bleeding"}],
        ]
        result = await interaction_checker.check(["ibuprofen", "warfarin", "aspirin"])
        assert result["safe"] is False
        assert len(result["interactions"]) == 3

    async def test_single_drug(self, mock_drugbank):
        result = await interaction_checker.check(["ibuprofen"])
        assert result["safe"] is True

    async def test_empty_list(self, mock_drugbank):
        result = await interaction_checker.check([])
        assert result["safe"] is True

    async def test_drugbank_unavailable(self, mock_drugbank):
        mock_drugbank.get_interactions.side_effect = DrugBankUnavailableError("down")
        result = await interaction_checker.check(["ibuprofen", "warfarin"])
        assert result["safe"] is None
        assert result["error"] == "Drug interaction data temporarily unavailable"
        assert result["interactions"] == []

    async def test_case_insensitive_matching(self, mock_drugbank):
        mock_drugbank.get_interactions.side_effect = [
            [{"drug": "WARFARIN", "description": "bleeding risk"}],
            [{"drug": "ibuprofen", "description": "bleeding risk"}],
        ]
        result = await interaction_checker.check(["Ibuprofen", "warfarin"])
        assert result["safe"] is False
        assert len(result["interactions"]) == 1

    async def test_partial_drugbank_failure_still_checks_available_pairs(self, mock_drugbank, mock_severity):
        """If one drug fails but others succeed, check the available pairs."""
        mock_drugbank.get_interactions.side_effect = [
            DrugBankUnavailableError("timeout"),  # ibuprofen fails
            [{"drug": "Aspirin", "description": "bleeding"}],  # warfarin succeeds
            [{"drug": "Warfarin", "description": "bleeding"}],  # aspirin succeeds
        ]
        result = await interaction_checker.check(["ibuprofen", "warfarin", "aspirin"])
        assert result["safe"] is False
        assert result["error"] is None
        # warfarin-aspirin pair should still be found
        assert len(result["interactions"]) >= 1
        pairs = [(i["drug_a"], i["drug_b"]) for i in result["interactions"]]
        assert ("warfarin", "aspirin") in pairs

    async def test_duplicate_drug_names_no_self_interaction(self, mock_drugbank):
        """Duplicate drug names must not produce self-interaction pairs."""
        mock_drugbank.get_interactions.side_effect = [
            [{"drug": "Ibuprofen", "description": "bleeding"}],  # ibuprofen lists itself
            [{"drug": "Warfarin", "description": "bleeding"}],
        ]
        result = await interaction_checker.check(["ibuprofen", "ibuprofen", "warfarin"])
        # Should check only one pair: ibuprofen-warfarin (no self-pair)
        for interaction in result["interactions"]:
            assert interaction["drug_a"] != interaction["drug_b"]
