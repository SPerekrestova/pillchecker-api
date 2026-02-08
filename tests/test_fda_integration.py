import pytest
import sqlite3
from app.data import fda_store
from app.services import interaction_checker

@pytest.fixture
def mock_db(tmp_path):
    db_path = tmp_path / "test_fda.db"
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE labels (
            id TEXT PRIMARY KEY,
            generic_name TEXT, 
            brand_name TEXT, 
            interactions TEXT, 
            contraindications TEXT, 
            warnings TEXT
        )
    """)
    
    # Add some test data
    conn.execute("""
        INSERT INTO labels (id, generic_name, brand_name, interactions, contraindications, warnings) 
        VALUES ('1', 'IBUPROFEN', 'ADVIL', 'May interact with warfarin.', 'Do not use with aspirin.', '')
    """)
    conn.commit()
    
    # Point fda_store to this test db
    fda_store.DB_PATH = db_path
    fda_store.load()
    return conn

def test_interaction_found(mock_db):
    result = interaction_checker.check(["ibuprofen", "warfarin"])
    assert len(result["interactions"]) == 1
    assert result["interactions"][0]["severity"] == "moderate"
    assert "warfarin" in result["interactions"][0]["description"].lower()

def test_critical_interaction(mock_db):
    result = interaction_checker.check(["ibuprofen", "aspirin"])
    assert len(result["interactions"]) == 1
    assert result["interactions"][0]["severity"] == "major"

def test_no_interaction(mock_db):
    result = interaction_checker.check(["ibuprofen", "vitamin c"])
    assert result["safe"] is True
