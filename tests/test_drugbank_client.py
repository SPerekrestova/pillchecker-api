"""Tests for the DrugBank client (direct SQLite version)."""

import time
import pytest
from unittest.mock import AsyncMock, patch
from app.clients import drugbank_client


class TestResolveId:
    """Test the internal name → drugbank_id resolution."""

    @pytest.fixture(autouse=True)
    def reset_cache(self):
        drugbank_client._cache.clear()
        yield
        drugbank_client._cache.clear()

    @pytest.fixture
    def mock_db(self):
        with patch("app.clients.drugbank_client.db", new_callable=AsyncMock) as mock:
            yield mock

    async def test_resolves_name_to_drugbank_id(self, mock_db):
        mock_db.search_by_name.return_value = [{"drugbank_id": "DB01050", "name": "Ibuprofen"}]
        result = await drugbank_client._resolve_drugbank_id("ibuprofen")
        assert result == "DB01050"
        mock_db.search_by_name.assert_called_once_with("ibuprofen", limit=1)

    async def test_returns_none_when_no_results(self, mock_db):
        mock_db.search_by_name.return_value = []
        result = await drugbank_client._resolve_drugbank_id("notadrug")
        assert result is None

    async def test_caches_resolved_id(self, mock_db):
        mock_db.search_by_name.return_value = [{"drugbank_id": "DB01050", "name": "Ibuprofen"}]
        await drugbank_client._resolve_drugbank_id("ibuprofen")
        await drugbank_client._resolve_drugbank_id("ibuprofen")
        assert mock_db.search_by_name.call_count == 1

    async def test_caches_none_for_unknown_drugs(self, mock_db):
        """Unknown drugs (None result) must also be cached."""
        mock_db.search_by_name.return_value = []
        await drugbank_client._resolve_drugbank_id("notadrug")
        await drugbank_client._resolve_drugbank_id("notadrug")
        assert mock_db.search_by_name.call_count == 1


class TestGetInteractions:
    @pytest.fixture(autouse=True)
    def reset_cache(self):
        drugbank_client._cache.clear()
        yield
        drugbank_client._cache.clear()

    @pytest.fixture
    def mock_db(self):
        with patch("app.clients.drugbank_client.db", new_callable=AsyncMock) as mock:
            yield mock

    async def test_returns_interactions(self, mock_db):
        """Full flow: resolve name → fetch interactions → return [{drug, description}]."""
        mock_db.search_by_name.return_value = [{"drugbank_id": "DB01050", "name": "Ibuprofen"}]
        mock_db.get_drug_interactions.return_value = [
            {"name": "Warfarin", "description": "Increases bleeding risk.", "severity": "major"}
        ]
        
        result = await drugbank_client.get_interactions("ibuprofen")
        assert len(result) == 1
        assert result[0]["drug"] == "Warfarin"
        assert result[0]["description"] == "Increases bleeding risk."
        assert result[0]["severity"] == "major"

    async def test_returns_empty_when_drug_not_found(self, mock_db):
        mock_db.search_by_name.return_value = []
        result = await drugbank_client.get_interactions("notadrug")
        assert result == []

    async def test_returns_empty_for_no_interactions(self, mock_db):
        mock_db.search_by_name.return_value = [{"drugbank_id": "DB00001", "name": "SomeDrug"}]
        mock_db.get_drug_interactions.return_value = []
        result = await drugbank_client.get_interactions("somedrug")
        assert result == []

    async def test_caches_full_interaction_results(self, mock_db):
        mock_db.search_by_name.return_value = [{"drugbank_id": "DB01050", "name": "Ibuprofen"}]
        mock_db.get_drug_interactions.return_value = []
        
        await drugbank_client.get_interactions("ibuprofen")
        await drugbank_client.get_interactions("ibuprofen")
        # Only 2 calls total (resolve + interactions), not 4
        assert mock_db.search_by_name.call_count == 1
        assert mock_db.get_drug_interactions.call_count == 1

    async def test_cache_expires(self, mock_db):
        mock_db.search_by_name.return_value = [{"drugbank_id": "DB01050", "name": "Ibuprofen"}]
        mock_db.get_drug_interactions.return_value = []
        
        await drugbank_client.get_interactions("ibuprofen")
        # Expire all cache entries
        for key in drugbank_client._cache:
            drugbank_client._cache[key] = (drugbank_client._cache[key][0], time.time() - 1)
        
        await drugbank_client.get_interactions("ibuprofen")
        assert mock_db.search_by_name.call_count == 2
        assert mock_db.get_drug_interactions.call_count == 2


class TestConnect:
    async def test_connect_calls_db_connect(self):
        with patch("app.clients.drugbank_client.db", new_callable=AsyncMock) as mock_db:
            await drugbank_client.connect()
            mock_db.connect.assert_called_once()

    async def test_connect_handles_failure(self):
        with patch("app.clients.drugbank_client.db", new_callable=AsyncMock) as mock_db:
            mock_db.connect.side_effect = Exception("DB error")
            # Should not raise
            await drugbank_client.connect()


class TestHealthCheck:
    async def test_health_check_delegates_to_db(self):
        with patch("app.clients.drugbank_client.db", new_callable=AsyncMock) as mock_db:
            mock_db.health_check.return_value = True
            assert await drugbank_client.health_check() is True
            mock_db.health_check.assert_called_once()

    async def test_health_check_returns_false_when_db_unhealthy(self):
        with patch("app.clients.drugbank_client.db", new_callable=AsyncMock) as mock_db:
            mock_db.health_check.return_value = False
            assert await drugbank_client.health_check() is False


class TestErrorPropagation:
    """Database errors must propagate so transient failures are not cached."""

    @pytest.fixture(autouse=True)
    def reset_cache(self):
        drugbank_client._cache.clear()
        yield
        drugbank_client._cache.clear()

    @pytest.fixture
    def mock_db(self):
        with patch("app.clients.drugbank_client.db", new_callable=AsyncMock) as mock:
            yield mock

    async def test_resolve_raises_on_db_error(self, mock_db):
        mock_db.search_by_name.side_effect = RuntimeError("disk I/O error")
        with pytest.raises(drugbank_client.DrugBankUnavailableError):
            await drugbank_client._resolve_drugbank_id("ibuprofen")

    async def test_resolve_does_not_cache_db_error(self, mock_db):
        """A transient DB error must not be cached as 'not found'."""
        mock_db.search_by_name.side_effect = [
            RuntimeError("disk I/O error"),
            [{"drugbank_id": "DB01050", "name": "Ibuprofen"}],
        ]
        with pytest.raises(drugbank_client.DrugBankUnavailableError):
            await drugbank_client._resolve_drugbank_id("ibuprofen")
        # Next call after DB recovers must hit the DB again and succeed
        result = await drugbank_client._resolve_drugbank_id("ibuprofen")
        assert result == "DB01050"
        assert mock_db.search_by_name.call_count == 2

    async def test_get_interactions_raises_on_resolve_error(self, mock_db):
        mock_db.search_by_name.side_effect = RuntimeError("disk I/O error")
        with pytest.raises(drugbank_client.DrugBankUnavailableError):
            await drugbank_client.get_interactions("ibuprofen")

    async def test_get_interactions_raises_on_lookup_error(self, mock_db):
        mock_db.search_by_name.return_value = [
            {"drugbank_id": "DB01050", "name": "Ibuprofen"}
        ]
        mock_db.get_drug_interactions.side_effect = RuntimeError("disk I/O error")
        with pytest.raises(drugbank_client.DrugBankUnavailableError):
            await drugbank_client.get_interactions("ibuprofen")

    async def test_get_interactions_does_not_cache_db_error(self, mock_db):
        mock_db.search_by_name.return_value = [
            {"drugbank_id": "DB01050", "name": "Ibuprofen"}
        ]
        mock_db.get_drug_interactions.side_effect = [
            RuntimeError("disk I/O error"),
            [{"name": "Warfarin", "description": "x", "severity": "major"}],
        ]
        with pytest.raises(drugbank_client.DrugBankUnavailableError):
            await drugbank_client.get_interactions("ibuprofen")
        # After recovery, the next call must hit the DB again and succeed
        result = await drugbank_client.get_interactions("ibuprofen")
        assert len(result) == 1
        assert result[0]["drug"] == "Warfarin"
