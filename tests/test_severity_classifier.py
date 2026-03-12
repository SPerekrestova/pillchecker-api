"""Tests for the zero-shot severity classifier."""

import pytest
from unittest.mock import patch, MagicMock
from app.nlp import severity_classifier


class TestClassify:
    """Test classify() with a mocked pipeline so tests run without the model."""

    @pytest.fixture(autouse=True)
    def mock_pipeline(self):
        """Mock the classifier pipeline for all tests in this class."""
        mock = MagicMock()
        severity_classifier._classifier = mock
        yield mock
        severity_classifier._classifier = None

    def test_major_severity(self, mock_pipeline):
        mock_pipeline.return_value = {
            "labels": [
                "critical dangerous interaction",
                "moderate interaction requiring monitoring",
                "minor interaction with low risk",
            ],
            "scores": [0.85, 0.10, 0.05],
        }
        assert severity_classifier.classify("contraindicated combination") == "major"

    def test_moderate_severity(self, mock_pipeline):
        mock_pipeline.return_value = {
            "labels": [
                "moderate interaction requiring monitoring",
                "critical dangerous interaction",
                "minor interaction with low risk",
            ],
            "scores": [0.70, 0.20, 0.10],
        }
        assert severity_classifier.classify("monitor blood pressure") == "moderate"

    def test_minor_severity(self, mock_pipeline):
        mock_pipeline.return_value = {
            "labels": [
                "minor interaction with low risk",
                "moderate interaction requiring monitoring",
                "critical dangerous interaction",
            ],
            "scores": [0.60, 0.25, 0.15],
        }
        assert severity_classifier.classify("minimal clinical significance") == "minor"

    def test_empty_description(self, mock_pipeline):
        assert severity_classifier.classify("") == "unknown"
        mock_pipeline.assert_not_called()

    def test_none_description(self, mock_pipeline):
        assert severity_classifier.classify(None) == "unknown"
        mock_pipeline.assert_not_called()

    def test_inference_failure_falls_back_to_regex(self, mock_pipeline):
        mock_pipeline.side_effect = RuntimeError("OOM")
        assert severity_classifier.classify("contraindicated") == "major"


class TestRegexFallback:
    """Test the regex fallback when the model is not loaded."""

    @pytest.fixture(autouse=True)
    def unload_model(self):
        severity_classifier._classifier = None
        yield
        severity_classifier._classifier = None

    def test_fallback_major(self):
        result = severity_classifier._regex_fallback("Do not use, contraindicated.")
        assert result == "major"

    def test_fallback_moderate(self):
        result = severity_classifier._regex_fallback("Use caution, monitor closely.")
        assert result == "moderate"

    def test_fallback_minor(self):
        result = severity_classifier._regex_fallback("No significant interaction.")
        assert result == "minor"

    def test_classify_uses_fallback_when_unloaded(self):
        assert severity_classifier.classify("contraindicated") == "major"


class TestLoadModel:
    def test_is_loaded_false_initially(self):
        severity_classifier._classifier = None
        assert severity_classifier.is_loaded() is False
