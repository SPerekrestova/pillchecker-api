"""API endpoint tests.

Tests /interactions and /health endpoints directly.
/analyze requires the NER model loaded — tested via Docker or manual run.
"""

import pytest
from fastapi.testclient import TestClient

from app.data import ddinter_store


@pytest.fixture(scope="module", autouse=True)
def load_data():
    ddinter_store.load()


@pytest.fixture
def client():
    # Import app without triggering lifespan (which loads the NER model)
    from app.api.interactions import router as interactions_router
    from app.api.health import router as health_router
    from fastapi import FastAPI

    test_app = FastAPI()
    test_app.include_router(health_router)
    test_app.include_router(interactions_router)
    return TestClient(test_app)


class TestInteractionsEndpoint:
    def test_known_interaction(self, client):
        resp = client.post("/interactions", json={"drugs": ["ibuprofen", "warfarin"]})
        assert resp.status_code == 200
        data = resp.json()
        assert data["safe"] is False
        assert len(data["interactions"]) == 1
        assert data["interactions"][0]["severity"] == "major"

    def test_no_interaction(self, client):
        resp = client.post("/interactions", json={"drugs": ["ibuprofen", "amoxicillin"]})
        assert resp.status_code == 200
        data = resp.json()
        assert data["safe"] is True

    def test_three_drugs(self, client):
        resp = client.post("/interactions", json={"drugs": ["ibuprofen", "warfarin", "aspirin"]})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["interactions"]) == 3

    def test_validation_requires_two_drugs(self, client):
        resp = client.post("/interactions", json={"drugs": ["ibuprofen"]})
        assert resp.status_code == 422  # Validation error

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
        assert data["interaction_pairs"] == 20
