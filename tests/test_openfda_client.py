"""Tests for the OpenFDA fallback client."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from app.clients import openfda_client


@pytest.fixture(autouse=True)
def reset_cache():
    openfda_client._cache.clear()
    yield
    openfda_client._cache.clear()


WARFARIN_LABEL = {
    "results": [{
        "drug_interactions": [
            "Ibuprofen and other NSAIDs may enhance the anticoagulant effect of warfarin.",
            "Patients should be monitored closely when combining these medications."
        ]
    }]
}

WARFARIN_LABEL_NO_INTERACTIONS = {
    "results": [{}]
}

EMPTY_RESULTS = {"results": []}


def make_response(json_data, status_code=200):
    mock = MagicMock()
    mock.status_code = status_code
    mock.json.return_value = json_data
    mock.raise_for_status = MagicMock()
    if status_code >= 400:
        mock.raise_for_status.side_effect = Exception(f"HTTP {status_code}")
    return mock


class TestCheckPair:
    async def test_returns_match_when_drug_mentioned(self):
        with patch("app.clients.openfda_client._fetch_label_text", new=AsyncMock(
            return_value="Ibuprofen and other NSAIDs may enhance the anticoagulant effect of warfarin. Patients should monitor closely."
        )):
            result = await openfda_client.check_pair("warfarin", "ibuprofen")
        assert result is not None
        assert result["drug"] == "ibuprofen"
        assert "ibuprofen" in result["description"].lower()
        assert len(result["description"]) > 0

    async def test_returns_none_when_drug_not_mentioned(self):
        with patch("app.clients.openfda_client._fetch_label_text", new=AsyncMock(
            return_value="This drug interacts with aspirin and heparin."
        )):
            result = await openfda_client.check_pair("warfarin", "ibuprofen")
        assert result is None

    async def test_returns_none_when_label_unavailable(self):
        with patch("app.clients.openfda_client._fetch_label_text", new=AsyncMock(return_value=None)):
            result = await openfda_client.check_pair("unknowndrug", "ibuprofen")
        assert result is None

    async def test_whole_word_match_only(self):
        """'aspirin' inside 'heparin' must NOT match."""
        with patch("app.clients.openfda_client._fetch_label_text", new=AsyncMock(
            return_value="Use with caution in patients on heparin therapy."
        )):
            result = await openfda_client.check_pair("warfarin", "aspirin")
        assert result is None

    async def test_description_is_never_empty_on_match(self):
        """check_pair must guarantee non-empty description when it returns a dict."""
        with patch("app.clients.openfda_client._fetch_label_text", new=AsyncMock(
            return_value="ibuprofen"  # match with no surrounding sentence context
        )):
            result = await openfda_client.check_pair("warfarin", "ibuprofen")
        assert result is not None
        assert result["description"]  # truthy, not empty

    async def test_case_insensitive_match(self):
        with patch("app.clients.openfda_client._fetch_label_text", new=AsyncMock(
            return_value="IBUPROFEN increases bleeding risk when combined with warfarin."
        )):
            result = await openfda_client.check_pair("warfarin", "ibuprofen")
        assert result is not None


class TestFetchLabelText:
    async def test_fetches_and_joins_drug_interactions_array(self):
        """drug_interactions is a JSON array — must be joined into one string."""
        mock_resp = make_response(WARFARIN_LABEL)
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_resp
            mock_client_cls.return_value.__aenter__.return_value = mock_client
            text = await openfda_client._fetch_label_text("warfarin")
        assert "Ibuprofen" in text
        assert "monitored" in text  # from second paragraph

    async def test_returns_empty_string_when_no_drug_interactions_field(self):
        mock_resp = make_response(WARFARIN_LABEL_NO_INTERACTIONS)
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_resp
            mock_client_cls.return_value.__aenter__.return_value = mock_client
            text = await openfda_client._fetch_label_text("warfarin")
        assert text == ""

    async def test_returns_none_on_empty_results(self):
        mock_resp = make_response(EMPTY_RESULTS)
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_resp
            mock_client_cls.return_value.__aenter__.return_value = mock_client
            text = await openfda_client._fetch_label_text("unknowndrug")
        assert text is None

    async def test_returns_none_on_network_error(self):
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get.side_effect = Exception("network error")
            mock_client_cls.return_value.__aenter__.return_value = mock_client
            text = await openfda_client._fetch_label_text("warfarin")
        assert text is None

    async def test_caches_label_text(self):
        mock_resp = make_response(WARFARIN_LABEL)
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_resp
            mock_client_cls.return_value.__aenter__.return_value = mock_client
            await openfda_client._fetch_label_text("warfarin")
            await openfda_client._fetch_label_text("warfarin")
            assert mock_client.get.call_count == 1  # second call hits cache

    async def test_url_uses_phrase_quoting_for_multiword_name(self):
        mock_resp = make_response(EMPTY_RESULTS)
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_resp
            mock_client_cls.return_value.__aenter__.return_value = mock_client
            await openfda_client._fetch_label_text("acetylsalicylic acid")
            call_args = mock_client.get.call_args
            url = call_args[0][0] if call_args[0] else call_args[1].get("url", "")
            # Drug name must be quoted for phrase search
            assert '%22acetylsalicylic' in url or '"acetylsalicylic' in url
