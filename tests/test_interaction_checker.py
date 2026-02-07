"""Tests for the interaction checker service."""

import pytest
import sqlite3
from app.data import fda_store
from app.services import interaction_checker

@pytest.fixture(scope="module")
def mock_db_path(tmp_path_factory):
    # Create a shared temp db
    db_dir = tmp_path_factory.mktemp("data_checker")
    db_path = db_dir / "test_fda_checker.db"
    
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE labels (
            rxcui TEXT PRIMARY KEY, generic_name TEXT, brand_name TEXT, interactions TEXT, contraindications TEXT, warnings TEXT, last_updated TEXT
        )
    """)
    conn.execute("CREATE INDEX idx_generic ON labels(generic_name)")
    
    conn.execute("""
        INSERT INTO labels (rxcui, generic_name, interactions, contraindications, warnings) VALUES 
        ('1', 'IBUPROFEN', 'Warfarin interaction.', 'Do not use with aspirin.', ''),
        ('2', 'WARFARIN', '', 'Do not use with ibuprofen.', 'Avoid aspirin.'),
        ('3', 'ASPIRIN', 'Interacts with warfarin.', 'Contraindicated with ibuprofen.', '')
    """)
    conn.commit()
    conn.close()
    return db_path

@pytest.fixture(autouse=True)
def setup_store(mock_db_path):
    fda_store.DB_PATH = mock_db_path
    fda_store.load()

class TestInteractionChecker:
    def test_two_interacting_drugs(self):
        result = interaction_checker.check(["ibuprofen", "warfarin"])
        assert result["safe"] is False
        assert len(result["interactions"]) == 1
        # Should be major (Warfarin label says "Do not use with ibuprofen") or moderate
        assert result["interactions"][0]["severity"] in ["major", "moderate"]

    def test_two_safe_drugs(self):
        result = interaction_checker.check(["ibuprofen", "amoxicillin"])
        assert result["safe"] is True
        assert result["interactions"] == []

    def test_three_drugs_multiple_interactions(self):
        result = interaction_checker.check(["ibuprofen", "warfarin", "aspirin"])
        # Expecting multiple interactions
        assert result["safe"] is False
        assert len(result["interactions"]) >= 2

    def test_single_drug(self):
        result = interaction_checker.check(["ibuprofen"])
        assert result["safe"] is True

    def test_empty_list(self):
        result = interaction_checker.check([])
        assert result["safe"] is True