"""Tests for the interaction checker service."""

from app.data import ddinter_store
from app.services import interaction_checker


class TestInteractionChecker:
    @classmethod
    def setup_class(cls):
        ddinter_store.load()

    def test_two_interacting_drugs(self):
        result = interaction_checker.check(["ibuprofen", "warfarin"])
        assert result["safe"] is False
        assert len(result["interactions"]) == 1
        assert result["interactions"][0]["severity"] == "major"

    def test_two_safe_drugs(self):
        result = interaction_checker.check(["ibuprofen", "amoxicillin"])
        assert result["safe"] is True
        assert result["interactions"] == []

    def test_three_drugs_multiple_interactions(self):
        result = interaction_checker.check(["ibuprofen", "warfarin", "aspirin"])
        # ibuprofen+warfarin=major, ibuprofen+aspirin=moderate, warfarin+aspirin=major
        assert result["safe"] is False
        assert len(result["interactions"]) == 3

    def test_single_drug(self):
        result = interaction_checker.check(["ibuprofen"])
        assert result["safe"] is True

    def test_empty_list(self):
        result = interaction_checker.check([])
        assert result["safe"] is True
