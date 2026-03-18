"""Tests for the BioMCP MCP client."""

import time
import pytest
from unittest.mock import AsyncMock, patch, MagicMock, call
from app.clients import biomcp_client


class TestGetInteractions:
    @pytest.fixture(autouse=True)
    def reset_cache(self):
        biomcp_client._cache.clear()
        yield
        biomcp_client._cache.clear()

    @pytest.fixture
    def mock_session(self):
        """Mock the MCP session's call_tool method."""
        session = AsyncMock()
        biomcp_client._session = session
        yield session
        biomcp_client._session = None

    @pytest.mark.asyncio
    async def test_returns_interactions(self, mock_session):
        mock_session.call_tool.return_value = MagicMock(
            content=[MagicMock(text='{"interactions":[{"drug":"Warfarin","description":"Increases bleeding risk."}]}')],
            isError=False,
        )
        result = await biomcp_client.get_interactions("ibuprofen")
        assert len(result) == 1
        assert result[0]["drug"] == "Warfarin"
        assert result[0]["description"] == "Increases bleeding risk."

    @pytest.mark.asyncio
    async def test_call_tool_uses_biomcp_command_schema(self, mock_session):
        """call_tool must use tool name 'biomcp' with {'command': '--json get drug <name> interactions'}."""
        mock_session.call_tool.return_value = MagicMock(
            content=[MagicMock(text='{"name":"ibuprofen","interactions":[{"drug":"Aspirin","description":"May increase bleeding risk."}],"_meta":{}}')],
            isError=False,
        )
        result = await biomcp_client.get_interactions("ibuprofen")
        mock_session.call_tool.assert_called_once_with(
            "biomcp",
            {"command": "get drug ibuprofen interactions --json"},
        )
        assert result == [{"drug": "Aspirin", "description": "May increase bleeding risk."}]

    @pytest.mark.asyncio
    async def test_returns_empty_for_no_interactions(self, mock_session):
        mock_session.call_tool.return_value = MagicMock(
            content=[MagicMock(text='{"interactions":[]}')],
            isError=False,
        )
        result = await biomcp_client.get_interactions("acetaminophen")
        assert result == []

    @pytest.mark.asyncio
    async def test_caches_results(self, mock_session):
        mock_session.call_tool.return_value = MagicMock(
            content=[MagicMock(text='{"interactions":[{"drug":"Aspirin","description":"test"}]}')],
            isError=False,
        )
        await biomcp_client.get_interactions("ibuprofen")
        await biomcp_client.get_interactions("ibuprofen")
        assert mock_session.call_tool.call_count == 1

    @pytest.mark.asyncio
    async def test_cache_expires(self, mock_session):
        mock_session.call_tool.return_value = MagicMock(
            content=[MagicMock(text='{"interactions":[]}')],
            isError=False,
        )
        await biomcp_client.get_interactions("ibuprofen")
        # Expire the cache entry
        for key in biomcp_client._cache:
            biomcp_client._cache[key] = (biomcp_client._cache[key][0], time.time() - 1)
        await biomcp_client.get_interactions("ibuprofen")
        assert mock_session.call_tool.call_count == 2

    @pytest.mark.asyncio
    async def test_raises_on_connection_error(self, mock_session):
        mock_session.call_tool.side_effect = Exception("Connection refused")
        with pytest.raises(biomcp_client.BioMCPUnavailableError):
            await biomcp_client.get_interactions("ibuprofen")

    @pytest.mark.asyncio
    async def test_raises_when_no_session(self):
        biomcp_client._session = None
        with pytest.raises(biomcp_client.BioMCPUnavailableError):
            await biomcp_client.get_interactions("ibuprofen")

    @pytest.mark.asyncio
    async def test_raises_on_error_response(self, mock_session):
        mock_session.call_tool.return_value = MagicMock(
            content=[MagicMock(text='{}')],
            isError=True,
        )
        with pytest.raises(biomcp_client.BioMCPUnavailableError):
            await biomcp_client.get_interactions("ibuprofen")

    @pytest.mark.asyncio
    async def test_drug_name_with_spaces_is_quoted(self, mock_session):
        """Drug names containing spaces must be shell-quoted in the command string."""
        mock_session.call_tool.return_value = MagicMock(
            content=[MagicMock(text='{"interactions":[]}')],
            isError=False,
        )
        await biomcp_client.get_interactions("Co-Amoxiclav 500mg")
        mock_session.call_tool.assert_called_once_with(
            "biomcp",
            {"command": "get drug 'Co-Amoxiclav 500mg' interactions --json"},
        )



class TestConnect:
    @pytest.fixture(autouse=True)
    def reset_state(self):
        orig_session = biomcp_client._session
        orig_streams = biomcp_client._streams
        orig_tool = biomcp_client._tool_name
        biomcp_client._session = None
        biomcp_client._streams = None
        biomcp_client._tool_name = "biomcp"
        yield
        biomcp_client._session = orig_session
        biomcp_client._streams = orig_streams
        biomcp_client._tool_name = orig_tool

    def _make_mock_session(self, tool_names: list[str]) -> AsyncMock:
        session = AsyncMock()
        tools_result = MagicMock()
        tool_mocks = []
        for n in tool_names:
            t = MagicMock()
            t.name = n
            tool_mocks.append(t)
        tools_result.tools = tool_mocks
        session.list_tools.return_value = tools_result
        return session

    @pytest.mark.asyncio
    async def test_connect_discovers_biomcp_tool_name(self):
        """connect() calls list_tools() and sets _tool_name to 'biomcp' when present."""
        mock_session = self._make_mock_session(["biomcp"])
        mock_streams = AsyncMock()
        mock_streams.__aenter__.return_value = (AsyncMock(), AsyncMock(), None)
        mock_streams.__aexit__.return_value = None

        with patch("app.clients.biomcp_client.streamable_http_client", return_value=mock_streams), \
             patch("app.clients.biomcp_client.ClientSession", return_value=mock_session):
            await biomcp_client.connect()

        assert biomcp_client._tool_name == "biomcp"
        mock_session.list_tools.assert_called_once()

    @pytest.mark.asyncio
    async def test_connect_discovers_shell_tool_name_pre_0815(self):
        """connect() falls back to 'shell' for pre-0.8.15 BioMCP versions."""
        mock_session = self._make_mock_session(["shell"])
        mock_streams = AsyncMock()
        mock_streams.__aenter__.return_value = (AsyncMock(), AsyncMock(), None)
        mock_streams.__aexit__.return_value = None

        with patch("app.clients.biomcp_client.streamable_http_client", return_value=mock_streams), \
             patch("app.clients.biomcp_client.ClientSession", return_value=mock_session):
            await biomcp_client.connect()

        assert biomcp_client._tool_name == "shell"

    @pytest.mark.asyncio
    async def test_connect_degrades_gracefully_on_failure(self):
        """connect() sets _session=None when the sidecar is unreachable."""
        mock_streams = AsyncMock()
        mock_streams.__aenter__.side_effect = Exception("connection refused")

        with patch("app.clients.biomcp_client.streamable_http_client", return_value=mock_streams):
            await biomcp_client.connect()

        assert biomcp_client._session is None


class TestHealthCheck:
    @pytest.fixture(autouse=True)
    def reset_session(self):
        orig = biomcp_client._session
        yield
        biomcp_client._session = orig

    @pytest.mark.asyncio
    async def test_health_check_success(self):
        biomcp_client._session = AsyncMock()
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_client.get.return_value = mock_resp
            assert await biomcp_client.health_check() is True

    @pytest.mark.asyncio
    async def test_health_check_failure(self):
        biomcp_client._session = AsyncMock()
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_client.get.side_effect = Exception("down")
            assert await biomcp_client.health_check() is False

    @pytest.mark.asyncio
    async def test_health_check_uses_base_url_not_mcp_path(self):
        """health_check() must use BIOMCP_BASE_URL for GET /health, not BIOMCP_URL."""
        biomcp_client._session = AsyncMock()
        with patch("app.clients.biomcp_client.BIOMCP_BASE_URL", "http://testhost:9090"), \
             patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_client.get.return_value = mock_resp
            await biomcp_client.health_check()
            mock_client.get.assert_called_once_with("http://testhost:9090/health")

    @pytest.mark.asyncio
    async def test_health_check_returns_false_when_session_is_none(self):
        """health_check() must return False if MCP session is not established,
        even when the HTTP sidecar would respond 200."""
        biomcp_client._session = None
        try:
            with patch("httpx.AsyncClient") as mock_client_cls:
                mock_client = AsyncMock()
                mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
                mock_resp = MagicMock()
                mock_resp.status_code = 200
                mock_client.get.return_value = mock_resp
                assert await biomcp_client.health_check() is False
        finally:
            biomcp_client._session = None
