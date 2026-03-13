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
