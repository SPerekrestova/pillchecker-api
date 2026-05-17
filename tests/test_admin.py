"""Tests for admin cache management endpoint."""

import os
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    mock_ddinter = MagicMock()
    mock_ddinter.connect = AsyncMock()
    mock_ddinter.close = AsyncMock()
    mock_ddinter.health_check = AsyncMock(return_value=True)
    mock_severity = MagicMock()
    mock_severity.load_model = MagicMock()
    mock_severity.is_loaded.return_value = True

    with (
        patch.dict(os.environ, {"API_KEY": "test-key"}),
        patch("app.main.ddinter_db.client", mock_ddinter),
        patch("app.main.severity_classifier", mock_severity),
        patch("app.main.ner_model"),
        patch("app.api.health.ddinter_db.client", mock_ddinter),
        patch("app.services.interaction_checker.ddinter_db.client", mock_ddinter),
        patch("app.services.interaction_checker.severity_classifier", mock_severity),
    ):
        from app.main import app
        yield TestClient(app)


class TestAdminCacheClear:
    def test_clears_cache_with_valid_key(self, client):
        resp = client.post("/admin/cache/clear", headers={"X-API-Key": "test-key"})
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_rejects_without_key(self, client):
        resp = client.post("/admin/cache/clear")
        assert resp.status_code == 401
