"""API endpoint tests.

Tests /interactions and /health endpoints directly.
/analyze requires the NER model loaded — tested via Docker or manual run.
"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from fastapi.testclient import TestClient


@pytest.fixture
def mock_drugbank():
    """Mock drugbank_client in every module that imports it."""
    mock = MagicMock()
    mock.get_interactions = AsyncMock()
    mock.health_check = AsyncMock(return_value=True)
    mock.connect = AsyncMock()
    mock.close = AsyncMock()
    mock.BioMCPUnavailableError = Exception
    with patch("app.services.interaction_checker.drugbank_client", mock), \
         patch("app.api.health.drugbank_client", mock), \
         patch("app.main.drugbank_client", mock):
        yield mock


@pytest.fixture
def mock_severity():
    """Mock severity_classifier in every module that imports it."""
    mock = MagicMock()
    mock.classify.return_value = "moderate"
    mock.load_model = MagicMock()
    mock.is_loaded.return_value = True
    with patch("app.services.interaction_checker.severity_classifier", mock), \
         patch("app.main.severity_classifier", mock):
        yield mock


@pytest.fixture
def client(mock_drugbank, mock_severity):
    from app.main import app
    return TestClient(app)


class TestInteractionsEndpoint:
    def test_known_interaction(self, client, mock_drugbank):
        mock_drugbank.get_interactions.side_effect = [
            [{"drug": "Warfarin", "description": "Increases bleeding risk."}],
            [{"drug": "Ibuprofen", "description": "Increases bleeding risk."}],
        ]
        resp = client.post("/interactions", json={"drugs": ["ibuprofen", "warfarin"]})
        assert resp.status_code == 200
        data = resp.json()
        assert data["safe"] is False
        assert len(data["interactions"]) >= 1
        assert data["interactions"][0]["severity"] in ["major", "moderate"]

    def test_no_interaction(self, client, mock_drugbank):
        mock_drugbank.get_interactions.side_effect = [
            [], [],
        ]
        resp = client.post("/interactions", json={"drugs": ["ibuprofen", "amoxicillin"]})
        assert resp.status_code == 200
        data = resp.json()
        assert data["safe"] is True

    def test_three_drugs(self, client, mock_drugbank):
        mock_drugbank.get_interactions.side_effect = [
            [{"drug": "Warfarin", "description": "x"}, {"drug": "Aspirin", "description": "x"}],
            [{"drug": "Ibuprofen", "description": "x"}, {"drug": "Aspirin", "description": "x"}],
            [{"drug": "Ibuprofen", "description": "x"}, {"drug": "Warfarin", "description": "x"}],
        ]
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

    def test_data_health_connected(self, client, mock_drugbank):
        mock_drugbank.health_check.return_value = True
        resp = client.get("/health/data")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ready"
        assert data["drugbank"] == "connected"

    def test_data_health_degraded(self, client, mock_drugbank):
        mock_drugbank.health_check.return_value = False
        resp = client.get("/health/data")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "degraded"
        assert data["drugbank"] == "unreachable"
