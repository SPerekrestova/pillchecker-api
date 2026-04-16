"""Tests for the DrugBank client (direct SQLite version)."""

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
    async def test_health_check_success(self):
        with patch("app.clients.drugbank_client.db") as mock_db:
            mock_db._conn = MagicMock()
            assert await drugbank_client.health_check() is True

    async def test_health_check_connects_if_none(self):
        with patch("app.clients.drugbank_client.db", new_callable=AsyncMock) as mock_db:
            mock_db._conn = None
            assert await drugbank_client.health_check() is True
            mock_db.connect.assert_called_once()
