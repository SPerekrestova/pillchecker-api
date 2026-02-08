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
            id TEXT PRIMARY KEY,
            rxcui TEXT, 
            generic_name TEXT, 
            brand_name TEXT, 
            interactions TEXT, 
            contraindications TEXT, 
            warnings TEXT,
            last_updated TEXT
        )
    """)
    # Add test data: multiple labels for Ibuprofen with different severities
    # Label 1: Moderate interaction with warfarin
    conn.execute("""
        INSERT INTO labels (id, rxcui, generic_name, brand_name, interactions, contraindications, warnings) VALUES 
        ('label_1', '1', 'IBUPROFEN', 'ADVIL', 'May interact with warfarin.', '', '')
    """)
    # Label 2: Major (contraindicated) interaction with aspirin
    conn.execute("""
        INSERT INTO labels (id, rxcui, generic_name, brand_name, interactions, contraindications, warnings) VALUES 
        ('label_2', '1', 'IBUPROFEN', 'MOTRIN', '', 'Do not use with aspirin.', '')
    """)
    conn.commit()
    conn.close()
    
    # Patch the store to use this DB
    fda_store.DB_PATH = db_path
    fda_store.load()
    return db_path

def test_check_interaction_aggregates_severity(mock_db):
    # Should find the moderate interaction from label_1
    res_mod = fda_store.check_interaction("ibuprofen", "warfarin")
    assert res_mod is not None
    assert res_mod.severity == "moderate"

    # Should find the major interaction from label_2
    res_major = fda_store.check_interaction("ibuprofen", "aspirin")
    assert res_major is not None
    assert res_major.severity == "major"

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
    # Search by generic name (caps) and target (lowercase)
    result = fda_store.check_interaction("IBUPROFEN", "aspirin")
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
    assert fda_store.interaction_count() == 2
