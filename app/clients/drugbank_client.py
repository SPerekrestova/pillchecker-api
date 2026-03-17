"""Async client for DrugBank MCP server.

Spawns drugbank-mcp-server as a stdio child process and queries
drug interaction data from a pre-built DrugBank SQLite database.
"""

import json
import logging
import os
import time
from contextlib import AbstractAsyncContextManager

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

logger = logging.getLogger(__name__)

DRUGBANK_SERVER_CMD = os.environ.get("DRUGBANK_SERVER_CMD", "node")
DRUGBANK_SERVER_ARGS = os.environ.get(
    "DRUGBANK_SERVER_ARGS",
    os.path.join(os.path.dirname(__file__), "..", "..", "drugbank-mcp-server", "build", "index.js"),
)

_session: ClientSession | None = None
_streams: AbstractAsyncContextManager | None = None

# Simple TTL cache: {key: (value, expiry_timestamp)}
_cache: dict[str, tuple[object, float]] = {}
_CACHE_TTL = 86400  # 24 hours
_CACHE_MISS = object()  # sentinel to distinguish cache miss from cached None


class DrugBankUnavailableError(Exception):
    """Raised when the DrugBank MCP server is unreachable or returns an error."""


def _cache_get(key: str) -> object:
    """Return cached value or _CACHE_MISS sentinel."""
    if key in _cache:
        value, expiry = _cache[key]
        if time.time() < expiry:
            return value
        del _cache[key]
    return _CACHE_MISS


def _cache_set(key: str, value: object) -> None:
    _cache[key] = (value, time.time() + _CACHE_TTL)


async def connect() -> None:
    """Spawn the DrugBank MCP server and establish a stdio session.

    Silently degrades to _session=None on failure (graceful degradation).
    """
    global _session, _streams
    try:
        server_params = StdioServerParameters(
            command=DRUGBANK_SERVER_CMD,
            args=[DRUGBANK_SERVER_ARGS],
        )
        _streams = stdio_client(server_params)
        read_stream, write_stream = await _streams.__aenter__()
        try:
            _session = ClientSession(read_stream, write_stream)
            await _session.__aenter__()
            await _session.initialize()
            tools = await _session.list_tools()
            names = {t.name for t in tools.tools}
            if "drugbank_info" not in names:
                logger.warning("DrugBank MCP server tools: %s — expected 'drugbank_info'", names)
            logger.info("Connected to DrugBank MCP server (tools=%s)", names)
        except Exception:
            await _streams.__aexit__(None, None, None)
            raise
    except Exception:
        logger.warning("Failed to connect to DrugBank MCP server", exc_info=True)
        _session = None
        _streams = None


async def close() -> None:
    """Close the MCP session and kill the child process."""
    global _session, _streams
    try:
        if _session is not None:
            try:
                await _session.__aexit__(None, None, None)
            except Exception:
                pass
            _session = None
    finally:
        if _streams is not None:
            try:
                await _streams.__aexit__(None, None, None)
            except Exception:
                pass
            _streams = None


async def health_check() -> bool:
    """Check if the MCP session is alive by calling list_tools."""
    if _session is None:
        return False
    try:
        await _session.list_tools()
        return True
    except Exception:
        return False


async def _resolve_drugbank_id(drug_name: str) -> str | None:
    """Resolve a drug name to a DrugBank ID via search_by_name.

    Returns the drugbank_id of the first result, or None if not found.
    Raises DrugBankUnavailableError if the session is down.
    """
    cache_key = f"dbid:{drug_name.lower()}"
    cached = _cache_get(cache_key)
    if cached is not _CACHE_MISS:
        return cached

    if _session is None:
        raise DrugBankUnavailableError("DrugBank MCP session not established")

    try:
        result = await _session.call_tool(
            "drugbank_info",
            {"method": "search_by_name", "query": drug_name, "limit": 1},
        )
    except Exception as exc:
        raise DrugBankUnavailableError(f"DrugBank call failed: {exc}") from exc

    if result.isError:
        raise DrugBankUnavailableError(f"DrugBank returned error for {drug_name}")

    try:
        data = json.loads(result.content[0].text)
        results = data.get("results", [])
        drugbank_id = results[0]["drugbank_id"] if results else None
    except (json.JSONDecodeError, IndexError, KeyError):
        logger.warning("Failed to parse search_by_name response for %s", drug_name)
        drugbank_id = None

    _cache_set(cache_key, drugbank_id)
    return drugbank_id


async def get_interactions(drug_name: str) -> list[dict]:
    """Get drug-drug interactions for a given drug name.

    Returns list of {"drug": str, "description": str | None}.
    Raises DrugBankUnavailableError if the server is unreachable.
    """
    cache_key = f"interactions:{drug_name.lower()}"
    cached = _cache_get(cache_key)
    if cached is not _CACHE_MISS:
        return cached

    # Step 1: resolve name → drugbank_id
    drugbank_id = await _resolve_drugbank_id(drug_name)
    if drugbank_id is None:
        logger.info("Drug not found in DrugBank: %s", drug_name)
        _cache_set(cache_key, [])
        return []

    # Step 2: fetch interactions
    if _session is None:
        raise DrugBankUnavailableError("DrugBank MCP session not established")

    try:
        result = await _session.call_tool(
            "drugbank_info",
            {"method": "get_drug_interactions", "drugbank_id": drugbank_id},
        )
    except Exception as exc:
        raise DrugBankUnavailableError(f"DrugBank call failed: {exc}") from exc

    if result.isError:
        raise DrugBankUnavailableError(f"DrugBank returned error for {drugbank_id}")

    try:
        data = json.loads(result.content[0].text)
        raw_interactions = data.get("interactions", [])
        # Map to same format as biomcp_client: {drug, description}
        interactions = [
            {"drug": entry.get("name", ""), "description": entry.get("description")}
            for entry in raw_interactions
        ]
    except (json.JSONDecodeError, IndexError):
        logger.warning("Failed to parse interactions response for %s", drug_name)
        interactions = []

    _cache_set(cache_key, interactions)
    return interactions
