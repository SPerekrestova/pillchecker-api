"""Tests for the DrugBank MCP client."""

import time
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from app.clients import drugbank_client


class TestResolveId:
    """Test the internal name → drugbank_id resolution."""

    @pytest.fixture(autouse=True)
    def reset_cache(self):
        drugbank_client._cache.clear()
        yield
        drugbank_client._cache.clear()

    @pytest.fixture
    def mock_session(self):
        session = AsyncMock()
        drugbank_client._session = session
        yield session
        drugbank_client._session = None

    async def test_resolves_name_to_drugbank_id(self, mock_session):
        mock_session.call_tool.return_value = MagicMock(
            content=[MagicMock(text='{"method":"search_by_name","query":"ibuprofen","count":1,"results":[{"drugbank_id":"DB01050","name":"Ibuprofen"}]}')],
            isError=False,
        )
        result = await drugbank_client._resolve_drugbank_id("ibuprofen")
        assert result == "DB01050"
        mock_session.call_tool.assert_called_once_with(
            "drugbank_info",
            {"method": "search_by_name", "query": "ibuprofen", "limit": 1},
        )

    async def test_returns_none_when_no_results(self, mock_session):
        mock_session.call_tool.return_value = MagicMock(
            content=[MagicMock(text='{"method":"search_by_name","query":"notadrug","count":0,"results":[]}')],
            isError=False,
        )
        result = await drugbank_client._resolve_drugbank_id("notadrug")
        assert result is None

    async def test_caches_resolved_id(self, mock_session):
        mock_session.call_tool.return_value = MagicMock(
            content=[MagicMock(text='{"method":"search_by_name","query":"ibuprofen","count":1,"results":[{"drugbank_id":"DB01050","name":"Ibuprofen"}]}')],
            isError=False,
        )
        await drugbank_client._resolve_drugbank_id("ibuprofen")
        await drugbank_client._resolve_drugbank_id("ibuprofen")
        assert mock_session.call_tool.call_count == 1

    async def test_caches_none_for_unknown_drugs(self, mock_session):
        """Unknown drugs (None result) must also be cached to avoid repeated MCP calls."""
        mock_session.call_tool.return_value = MagicMock(
            content=[MagicMock(text='{"method":"search_by_name","query":"notadrug","count":0,"results":[]}')],
            isError=False,
        )
        await drugbank_client._resolve_drugbank_id("notadrug")
        await drugbank_client._resolve_drugbank_id("notadrug")
        assert mock_session.call_tool.call_count == 1

    async def test_raises_when_no_session(self):
        drugbank_client._session = None
        with pytest.raises(drugbank_client.DrugBankUnavailableError):
            await drugbank_client._resolve_drugbank_id("ibuprofen")


class TestGetInteractions:
    @pytest.fixture(autouse=True)
    def reset_cache(self):
        drugbank_client._cache.clear()
        yield
        drugbank_client._cache.clear()

    @pytest.fixture
    def mock_session(self):
        session = AsyncMock()
        drugbank_client._session = session
        yield session
        drugbank_client._session = None

    async def test_returns_interactions(self, mock_session):
        """Full flow: resolve name → fetch interactions → return [{drug, description}]."""
        mock_session.call_tool.side_effect = [
            # search_by_name
            MagicMock(
                content=[MagicMock(text='{"method":"search_by_name","count":1,"results":[{"drugbank_id":"DB01050","name":"Ibuprofen"}]}')],
                isError=False,
            ),
            # get_drug_interactions
            MagicMock(
                content=[MagicMock(text='{"method":"get_drug_interactions","drugbank_id":"DB01050","drug_name":"Ibuprofen","interaction_count":1,"interactions":[{"drugbank_id":"DB00682","name":"Warfarin","description":"Increases bleeding risk."}]}')],
                isError=False,
            ),
        ]
        result = await drugbank_client.get_interactions("ibuprofen")
        assert len(result) == 1
        assert result[0]["drug"] == "Warfarin"
        assert result[0]["description"] == "Increases bleeding risk."

    async def test_returns_empty_when_drug_not_found(self, mock_session):
        mock_session.call_tool.return_value = MagicMock(
            content=[MagicMock(text='{"method":"search_by_name","count":0,"results":[]}')],
            isError=False,
        )
        result = await drugbank_client.get_interactions("notadrug")
        assert result == []

    async def test_returns_empty_for_no_interactions(self, mock_session):
        mock_session.call_tool.side_effect = [
            MagicMock(
                content=[MagicMock(text='{"method":"search_by_name","count":1,"results":[{"drugbank_id":"DB00001","name":"SomeDrug"}]}')],
                isError=False,
            ),
            MagicMock(
                content=[MagicMock(text='{"method":"get_drug_interactions","drugbank_id":"DB00001","interaction_count":0,"interactions":[]}')],
                isError=False,
            ),
        ]
        result = await drugbank_client.get_interactions("somedrug")
        assert result == []

    async def test_caches_full_interaction_results(self, mock_session):
        mock_session.call_tool.side_effect = [
            MagicMock(
                content=[MagicMock(text='{"method":"search_by_name","count":1,"results":[{"drugbank_id":"DB01050","name":"Ibuprofen"}]}')],
                isError=False,
            ),
            MagicMock(
                content=[MagicMock(text='{"method":"get_drug_interactions","drugbank_id":"DB01050","interaction_count":0,"interactions":[]}')],
                isError=False,
            ),
        ]
        await drugbank_client.get_interactions("ibuprofen")
        await drugbank_client.get_interactions("ibuprofen")
        # Only 2 calls total (resolve + interactions), not 4
        assert mock_session.call_tool.call_count == 2

    async def test_cache_expires(self, mock_session):
        mock_session.call_tool.side_effect = [
            MagicMock(
                content=[MagicMock(text='{"method":"search_by_name","count":1,"results":[{"drugbank_id":"DB01050","name":"Ibuprofen"}]}')],
                isError=False,
            ),
            MagicMock(
                content=[MagicMock(text='{"method":"get_drug_interactions","drugbank_id":"DB01050","interaction_count":0,"interactions":[]}')],
                isError=False,
            ),
            # After cache expires, same calls again
            MagicMock(
                content=[MagicMock(text='{"method":"search_by_name","count":1,"results":[{"drugbank_id":"DB01050","name":"Ibuprofen"}]}')],
                isError=False,
            ),
            MagicMock(
                content=[MagicMock(text='{"method":"get_drug_interactions","drugbank_id":"DB01050","interaction_count":0,"interactions":[]}')],
                isError=False,
            ),
        ]
        await drugbank_client.get_interactions("ibuprofen")
        # Expire all cache entries
        for key in drugbank_client._cache:
            drugbank_client._cache[key] = (drugbank_client._cache[key][0], time.time() - 1)
        await drugbank_client.get_interactions("ibuprofen")
        assert mock_session.call_tool.call_count == 4

    async def test_raises_on_connection_error(self, mock_session):
        mock_session.call_tool.side_effect = Exception("Connection refused")
        with pytest.raises(drugbank_client.DrugBankUnavailableError):
            await drugbank_client.get_interactions("ibuprofen")

    async def test_raises_when_no_session(self):
        drugbank_client._session = None
        with pytest.raises(drugbank_client.DrugBankUnavailableError):
            await drugbank_client.get_interactions("ibuprofen")

    async def test_raises_on_error_response(self, mock_session):
        mock_session.call_tool.return_value = MagicMock(
            content=[MagicMock(text='{}')],
            isError=True,
        )
        with pytest.raises(drugbank_client.DrugBankUnavailableError):
            await drugbank_client.get_interactions("ibuprofen")


class TestConnect:
    @pytest.fixture(autouse=True)
    def reset_state(self):
        orig_session = drugbank_client._session
        orig_streams = drugbank_client._streams
        drugbank_client._session = None
        drugbank_client._streams = None
        yield
        drugbank_client._session = orig_session
        drugbank_client._streams = orig_streams

    async def test_connect_discovers_drugbank_info_tool(self):
        mock_session = AsyncMock()
        tools_result = MagicMock()
        tool_mock = MagicMock()
        tool_mock.name = "drugbank_info"
        tools_result.tools = [tool_mock]
        mock_session.list_tools.return_value = tools_result

        mock_streams = AsyncMock()
        mock_streams.__aenter__.return_value = (AsyncMock(), AsyncMock())
        mock_streams.__aexit__.return_value = None

        with patch("app.clients.drugbank_client.stdio_client", return_value=mock_streams), \
             patch("app.clients.drugbank_client.ClientSession", return_value=mock_session):
            await drugbank_client.connect()

        assert drugbank_client._session is mock_session
        mock_session.initialize.assert_called_once()
        mock_session.list_tools.assert_called_once()

    async def test_connect_degrades_gracefully_on_failure(self):
        mock_streams = AsyncMock()
        mock_streams.__aenter__.side_effect = Exception("node not found")

        with patch("app.clients.drugbank_client.stdio_client", return_value=mock_streams):
            await drugbank_client.connect()

        assert drugbank_client._session is None


class TestHealthCheck:
    @pytest.fixture(autouse=True)
    def reset_session(self):
        orig = drugbank_client._session
        yield
        drugbank_client._session = orig

    async def test_health_check_success(self):
        session = AsyncMock()
        tools_result = MagicMock()
        tools_result.tools = [MagicMock()]
        session.list_tools.return_value = tools_result
        drugbank_client._session = session
        assert await drugbank_client.health_check() is True

    async def test_health_check_returns_false_when_no_session(self):
        drugbank_client._session = None
        assert await drugbank_client.health_check() is False

    async def test_health_check_returns_false_on_error(self):
        session = AsyncMock()
        session.list_tools.side_effect = Exception("broken pipe")
        drugbank_client._session = session
        assert await drugbank_client.health_check() is False
