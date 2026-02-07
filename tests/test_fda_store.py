"""Tests for the FDA interaction store."""

import pytest
import sqlite3
from app.data import fda_store

@pytest.fixture
def mock_db(tmp_path):
    db_path = tmp_path / "test_fda_store.db"
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE labels (
            rxcui TEXT PRIMARY KEY, 
            generic_name TEXT, 
            brand_name TEXT, 
            interactions TEXT, 
            contraindications TEXT, 
            warnings TEXT,
            last_updated TEXT
        )
    """)
    # Add test data
    conn.execute("""
        INSERT INTO labels (rxcui, generic_name, brand_name, interactions, contraindications, warnings) VALUES 
        ('1', 'IBUPROFEN', 'ADVIL', 'May interact with warfarin.', 'Do not use with aspirin.', 'Caution with naproxen.')
    """)
    conn.commit()
    conn.close()
    
    # Patch the store to use this DB
    fda_store.DB_PATH = db_path
    fda_store.load()
    return db_path

def test_check_interaction_found_in_interactions(mock_db):
    result = fda_store.check_interaction("ibuprofen", "warfarin")
    assert result is not None
    assert result.severity == "moderate"
    assert "warfarin" in result.description.lower()

def test_check_interaction_found_in_contraindications(mock_db):
    result = fda_store.check_interaction("ibuprofen", "aspirin")
    assert result is not None
    assert result.severity == "major"

def test_case_insensitivity(mock_db):
    # Search by brand name (caps) and target (lowercase)
    result = fda_store.check_interaction("ASPIRIN", "ADVIL")
    assert result is not None
    assert result.severity == "major"

def test_order_independence(mock_db):
    res1 = fda_store.check_interaction("ibuprofen", "warfarin")
    res2 = fda_store.check_interaction("warfarin", "ibuprofen")
    assert res1.description == res2.description

def test_no_interaction_found(mock_db):
    result = fda_store.check_interaction("ibuprofen", "vitamin c")
    assert result is None

def test_interaction_count(mock_db):
    assert fda_store.interaction_count() == 1
