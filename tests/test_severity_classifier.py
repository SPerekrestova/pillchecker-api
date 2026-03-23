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
        severity, uncertain = severity_classifier.classify("contraindicated combination")
        assert severity == "major"

    def test_moderate_severity(self, mock_pipeline):
        mock_pipeline.return_value = {
            "labels": [
                "moderate interaction requiring monitoring",
                "critical dangerous interaction",
                "minor interaction with low risk",
            ],
            "scores": [0.70, 0.20, 0.10],
        }
        severity, uncertain = severity_classifier.classify("monitor blood pressure")
        assert severity == "moderate"

    def test_minor_severity(self, mock_pipeline):
        mock_pipeline.return_value = {
            "labels": [
                "minor interaction with low risk",
                "moderate interaction requiring monitoring",
                "critical dangerous interaction",
            ],
            "scores": [0.75, 0.15, 0.10],
        }
        severity, uncertain = severity_classifier.classify("minimal clinical significance")
        assert severity == "minor"

    def test_returns_tuple_with_uncertain_flag(self, mock_pipeline):
        mock_pipeline.return_value = {
            "labels": [
                "critical dangerous interaction",
                "moderate interaction requiring monitoring",
                "minor interaction with low risk",
            ],
            "scores": [0.85, 0.10, 0.05],
        }
        severity, uncertain = severity_classifier.classify("contraindicated combination")
        assert severity == "major"
        assert uncertain is False

    def test_low_confidence_returns_major_uncertain(self, mock_pipeline):
        """Below threshold (0.7), classifier should return major+uncertain."""
        mock_pipeline.return_value = {
            "labels": [
                "minor interaction with low risk",
                "moderate interaction requiring monitoring",
                "critical dangerous interaction",
            ],
            "scores": [0.45, 0.35, 0.20],
        }
        severity, uncertain = severity_classifier.classify("some vague description")
        assert severity == "major"
        assert uncertain is True

    def test_empty_description(self, mock_pipeline):
        severity, uncertain = severity_classifier.classify("")
        assert severity == "unknown"
        assert uncertain is True
        mock_pipeline.assert_not_called()

    def test_none_description(self, mock_pipeline):
        severity, uncertain = severity_classifier.classify(None)
        assert severity == "unknown"
        assert uncertain is True
        mock_pipeline.assert_not_called()

    def test_inference_failure_falls_back_to_regex(self, mock_pipeline):
        mock_pipeline.side_effect = RuntimeError("OOM")
        severity, uncertain = severity_classifier.classify("contraindicated")
        assert severity == "major"
        assert uncertain is True


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

    def test_fallback_unknown_for_neutral_text(self):
        """Unrecognized text now defaults to 'major' for safety."""
        result = severity_classifier._regex_fallback("No significant interaction.")
        assert result == "major"

    def test_classify_uses_fallback_when_unloaded(self):
        severity, uncertain = severity_classifier.classify("contraindicated")
        assert severity == "major"


class TestLoadModel:
    def test_is_loaded_false_initially(self):
        severity_classifier._classifier = None
        assert severity_classifier.is_loaded() is False
