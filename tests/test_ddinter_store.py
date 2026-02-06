"""Tests for the DDInter interaction store."""

from app.data import ddinter_store


class TestDDInterStore:
    @classmethod
    def setup_class(cls):
        ddinter_store.load()

    def test_ibuprofen_warfarin_major(self):
        result = ddinter_store.check_interaction("Ibuprofen", "Warfarin")
        assert result is not None
        assert result.severity == "major"
        assert "bleeding" in result.description.lower()

    def test_case_insensitive(self):
        result = ddinter_store.check_interaction("IBUPROFEN", "warfarin")
        assert result is not None

    def test_order_independent(self):
        a = ddinter_store.check_interaction("warfarin", "ibuprofen")
        b = ddinter_store.check_interaction("ibuprofen", "warfarin")
        assert a == b

    def test_no_interaction(self):
        result = ddinter_store.check_interaction("ibuprofen", "amoxicillin")
        assert result is None

    def test_sildenafil_nitroglycerin(self):
        result = ddinter_store.check_interaction("sildenafil", "nitroglycerin")
        assert result is not None
        assert result.severity == "major"

    def test_moderate_interaction(self):
        result = ddinter_store.check_interaction("omeprazole", "clopidogrel")
        assert result is not None
        assert result.severity == "moderate"

    def test_management_present(self):
        result = ddinter_store.check_interaction("warfarin", "ibuprofen")
        assert len(result.management) > 0

    def test_store_has_data(self):
        assert ddinter_store.interaction_count() == 20
        assert ddinter_store.drug_count() > 10
