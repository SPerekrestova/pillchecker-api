"""API endpoint tests.

Tests /interactions and /health endpoints directly.
/analyze requires the NER model loaded — tested via Docker or manual run.
"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from fastapi.testclient import TestClient


@pytest.fixture
def mock_ddinter():
    """Mock DDInter client in every module that imports it."""
    mock = MagicMock()
    mock.health_check = AsyncMock(return_value=True)
    mock.connect = AsyncMock()
    mock.close = AsyncMock()
    mock.lookup_by_rxcui = AsyncMock(return_value=None)
    mock.lookup_by_name_fts = AsyncMock(return_value=None)
    with patch("app.services.interaction_checker.ddinter_db.client", mock), \
         patch("app.api.health.ddinter_db.client", mock), \
         patch("app.main.ddinter_db.client", mock):
        yield mock


@pytest.fixture
def mock_severity():
    """Mock severity_classifier in every module that imports it."""
    mock = MagicMock()
    mock.classify.return_value = ("moderate", False)
    mock.load_model = MagicMock()
    mock.is_loaded.return_value = True
    with patch("app.services.interaction_checker.severity_classifier", mock), \
         patch("app.main.severity_classifier", mock):
        yield mock


@pytest.fixture
def client(mock_ddinter, mock_severity):
    from app.main import app
    return TestClient(app)


class TestAnalyzeValidation:
    def test_analyze_rejects_oversized_text(self, client):
        """Text over 5000 chars must be rejected with 422."""
        resp = client.post(
            "/analyze",
            json={"text": "Metformin 500mg " * 500},
            headers={"X-API-Key": "test-key"},
        )
        assert resp.status_code == 422

    def test_analyze_strips_html_from_raw_text(self, client):
        """HTML tags must be stripped from raw_text to prevent XSS."""
        with patch("app.services.drug_analyzer.analyze", new=AsyncMock(return_value=[])):
            resp = client.post(
                "/analyze",
                json={"text": '<script>alert(1)</script>Metformin 500mg'},
                headers={"X-API-Key": "test-key"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert "<script>" not in data["raw_text"]
        assert "alert(1)" in data["raw_text"]

    def test_analyze_non_latin_text_returns_note(self, client):
        """Non-Latin text should return empty drugs with explanatory note."""
        resp = client.post(
            "/analyze",
            json={"text": "阿莫西林胶囊 500mg"},
            headers={"X-API-Key": "test-key"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["drugs"] == []
        assert "note" in data
        assert "Latin" in data["note"]

    def test_analyze_mixed_script_processes_normally(self, client):
        """Text with mostly Latin chars should process normally even with some non-Latin."""
        with patch("app.api.analyze.drug_analyzer.analyze", new=AsyncMock(return_value=[])):
            resp = client.post(
                "/analyze",
                json={"text": "Metformin 500mg (メトホルミン)"},
                headers={"X-API-Key": "test-key"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("note") is None or "Non-Latin" not in data.get("note", "")


class TestInteractionsValidation:
    def test_interactions_rejects_empty_string_drug(self, client):
        """Empty strings in drugs list must be rejected with 422."""
        resp = client.post(
            "/interactions",
            json={"drugs": ["metformin", "", "lisinopril"]},
            headers={"X-API-Key": "test-key"},
        )
        assert resp.status_code == 422

    def test_interactions_rejects_whitespace_only_drug(self, client):
        """Whitespace-only strings must be rejected after stripping."""
        resp = client.post(
            "/interactions",
            json={"drugs": ["  ", "metformin"]},
            headers={"X-API-Key": "test-key"},
        )
        assert resp.status_code == 422

    def test_interactions_rejects_long_drug_name(self, client):
        """Drug names over 200 chars must be rejected."""
        resp = client.post(
            "/interactions",
            json={"drugs": ["a" * 201, "metformin"]},
            headers={"X-API-Key": "test-key"},
        )
        assert resp.status_code == 422


def test_interaction_result_accepts_new_fields():
    from app.api.schemas import InteractionResult

    result = InteractionResult(
        drug_a="Warfarin",
        drug_b="Aspirin",
        rxcui_a="11289",
        rxcui_b="1191",
        severity="major",
        source="ddinter",
        description="",
        management="Consult a healthcare professional.",
        uncertain=False,
    )
    assert result.source == "ddinter"
    assert result.rxcui_a == "11289"


def test_interactions_response_includes_coverage_summary():
    from app.api.schemas import DDInterDataSource, InteractionsDataSources, InteractionsResponse

    response = InteractionsResponse(
        interactions=[],
        safe=True,
        error=None,
        data_sources=InteractionsDataSources(
            ddinter=DDInterDataSource(
                version="2.0",
                license="CC BY-NC-SA 4.0",
                attribution_url="https://ddinter2.scbdd.com/",
            ),
            severity_classifier="model-id",
        ),
        coverage_summary={"ddinter": 0, "openfda": 0, "unknown": 0},
    )
    assert response.coverage_summary == {"ddinter": 0, "openfda": 0, "unknown": 0}
    assert response.data_sources.ddinter.version == "2.0"


class TestInteractionsEndpoint:
    def test_known_interaction(self, client):
        with patch("app.api.interactions.interaction_checker.check", new=AsyncMock(return_value={
            "interactions": [{
                "drug_a": "ibuprofen",
                "drug_b": "warfarin",
                "rxcui_a": "5640",
                "rxcui_b": "11289",
                "severity": "major",
                "source": "ddinter",
                "description": "Interaction reported in DDInter 2.0.",
                "management": "Consult a healthcare professional for guidance.",
                "uncertain": False,
            }],
            "safe": False,
            "error": None,
            "coverage_summary": {"ddinter": 1, "openfda": 0, "unknown": 0},
        })):
            resp = client.post("/interactions", json={"drugs": ["ibuprofen", "warfarin"]})
        assert resp.status_code == 200
        data = resp.json()
        assert data["safe"] is False
        assert len(data["interactions"]) >= 1
        assert data["interactions"][0]["severity"] in ["major", "moderate"]
        assert data["interactions"][0]["source"] == "ddinter"
        assert data["coverage_summary"]["ddinter"] == 1
        assert "data_sources" in data
        assert data["data_sources"]["ddinter"]["version"] == "2.0"
        assert "severity_classifier" in data["data_sources"]

    def test_no_interaction(self, client):
        with patch("app.api.interactions.interaction_checker.check", new=AsyncMock(return_value={
            "interactions": [],
            "safe": True,
            "error": None,
            "coverage_summary": {"ddinter": 0, "openfda": 0, "unknown": 1},
        })):
            resp = client.post("/interactions", json={"drugs": ["ibuprofen", "amoxicillin"]})
        assert resp.status_code == 200
        data = resp.json()
        assert data["safe"] is True
        assert data["coverage_summary"]["unknown"] == 1

    def test_three_drugs(self, client):
        with patch("app.api.interactions.interaction_checker.check", new=AsyncMock(return_value={
            "interactions": [
                {"drug_a": "ibuprofen", "drug_b": "warfarin", "severity": "major", "source": "ddinter",
                 "description": "x", "management": "m", "uncertain": False},
                {"drug_a": "warfarin", "drug_b": "aspirin", "severity": "major", "source": "ddinter",
                 "description": "x", "management": "m", "uncertain": False},
            ],
            "safe": False,
            "error": None,
            "coverage_summary": {"ddinter": 2, "openfda": 0, "unknown": 1},
        })):
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

    def test_data_health_connected(self, client, mock_ddinter):
        mock_ddinter.health_check.return_value = True
        resp = client.get("/health/data")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ready"
        assert data["ddinter"] == "connected"

    def test_data_health_degraded(self, client, mock_ddinter):
        mock_ddinter.health_check.return_value = False
        resp = client.get("/health/data")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "degraded"
        assert data["ddinter"] == "unreachable"
