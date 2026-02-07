"""API endpoint tests.

Tests /interactions and /health endpoints directly.
/analyze requires the NER model loaded — tested via Docker or manual run.
"""

import pytest
import sqlite3
from pathlib import Path
from fastapi.testclient import TestClient
from app.data import fda_store

@pytest.fixture(scope="module")
def mock_db_path(tmp_path_factory):
    # Create a shared temp db for the module
    db_dir = tmp_path_factory.mktemp("data")
    db_path = db_dir / "test_fda.db"
    
    # Initialize DB with test data
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
    conn.execute("CREATE INDEX idx_generic ON labels(generic_name)")
    
    # Insert test records
    conn.execute("""
        INSERT INTO labels (rxcui, generic_name, interactions, contraindications, warnings) VALUES 
        ('1', 'IBUPROFEN', 'May interact with warfarin.', 'Do not use with aspirin.', 'Caution with aspirin.'),
        ('2', 'WARFARIN', 'Avoid aspirin.', 'Do not use with ibuprofen.', 'Monitor INR.'),
        ('3', 'ASPIRIN', 'Interacts with warfarin.', 'Contraindicated with ibuprofen.', '')
    """)
    conn.commit()
    conn.close()
    return db_path

@pytest.fixture(scope="module", autouse=True)
def load_data(mock_db_path):
    # Patch the DB_PATH in fda_store to point to our mock DB
    fda_store.DB_PATH = mock_db_path
    fda_store.load()

@pytest.fixture
def client():
    from app.main import app
    return TestClient(app)

class TestInteractionsEndpoint:
    def test_known_interaction(self, client):
        resp = client.post("/interactions", json={"drugs": ["ibuprofen", "warfarin"]})
        assert resp.status_code == 200
        data = resp.json()
        assert data["safe"] is False
        assert len(data["interactions"]) >= 1
        assert data["interactions"][0]["severity"] in ["major", "moderate"]

    def test_no_interaction(self, client):
        resp = client.post("/interactions", json={"drugs": ["ibuprofen", "amoxicillin"]})
        assert resp.status_code == 200
        data = resp.json()
        assert data["safe"] is True

    def test_three_drugs(self, client):
        resp = client.post("/interactions", json={"drugs": ["ibuprofen", "warfarin", "aspirin"]})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["interactions"]) >= 2

    def test_validation_requires_two_drugs(self, client):
        resp = client.post("/interactions", json={"drugs": ["ibuprofen"]})
        assert resp.status_code == 422

    def test_validation_requires_drugs_field(self, client):
        resp = client.post("/interactions", json={})
        assert resp.status_code == 422


class TestHealthEndpoint:
    def test_health_returns_ok(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["version"] == "0.1.0"
    
    def test_data_health(self, client):
        resp = client.get("/health/data")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ready"
        assert data["record_count"] == 3
