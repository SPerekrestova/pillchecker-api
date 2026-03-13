"""Tests for the BioMCP MCP client."""

import time
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
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
            {"command": "--json get drug ibuprofen interactions"},
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
        with patch("app.clients.biomcp_client.connect", new_callable=AsyncMock) as mock_connect:
            # connect() leaves _session as the same mock (which still raises)
            mock_connect.return_value = None
            with pytest.raises(biomcp_client.BioMCPUnavailableError):
                await biomcp_client.get_interactions("ibuprofen")
            mock_connect.assert_called_once()

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
            {"command": "--json get drug 'Co-Amoxiclav 500mg' interactions"},
        )


    @pytest.mark.asyncio
    async def test_reconnects_on_first_call_tool_failure(self, mock_session):
        """If call_tool raises on first attempt, connect() is called and the second attempt succeeds."""
        good_response = MagicMock(
            content=[MagicMock(text='{"interactions":[{"drug":"Warfarin","description":"Risk."}]}')],
            isError=False,
        )
        mock_session.call_tool.side_effect = [Exception("stale connection"), good_response]

        async def fake_connect():
            # Simulate reconnect restoring the same mock session
            biomcp_client._session = mock_session
            mock_session.call_tool.side_effect = None
            mock_session.call_tool.return_value = good_response

        with patch("app.clients.biomcp_client.connect", side_effect=fake_connect):
            result = await biomcp_client.get_interactions("ibuprofen")

        assert result == [{"drug": "Warfarin", "description": "Risk."}]
        assert mock_session.call_tool.call_count == 2


class TestHealthCheck:
    @pytest.mark.asyncio
    async def test_health_check_success(self):
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
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_client.get.side_effect = Exception("down")
            assert await biomcp_client.health_check() is False

    @pytest.mark.asyncio
    async def test_health_check_uses_base_url_not_mcp_path(self):
        """health_check() must use BIOMCP_BASE_URL for GET /health, not BIOMCP_URL."""
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
