"""Async client for BioMCP MCP server.

Connects to a BioMCP HTTP sidecar and queries drug interaction data
from DrugBank via MyChem.info.
"""

import json
import logging
import os
import time

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

logger = logging.getLogger(__name__)

BIOMCP_URL = os.environ.get("BIOMCP_URL", "http://biomcp:8080/mcp")

_session: ClientSession | None = None
_streams = None  # holds the context manager references for cleanup

# Simple TTL cache: {key: (value, expiry_timestamp)}
_cache: dict[str, tuple[object, float]] = {}
_CACHE_TTL = 86400  # 24 hours


class BioMCPUnavailableError(Exception):
    """Raised when BioMCP sidecar is unreachable or returns an error."""


def _cache_get(key: str) -> object | None:
    if key in _cache:
        value, expiry = _cache[key]
        if time.time() < expiry:
            return value
        del _cache[key]
    return None


def _cache_set(key: str, value: object) -> None:
    _cache[key] = (value, time.time() + _CACHE_TTL)


async def connect() -> None:
    """Establish MCP session with the BioMCP sidecar.

    Silently degrades to _session=None on failure (graceful degradation).
    Callers should handle BioMCPUnavailableError raised by get_interactions().
    """
    global _session, _streams
    try:
        _streams = streamable_http_client(BIOMCP_URL)
        read_stream, write_stream, _ = await _streams.__aenter__()
        try:
            _session = ClientSession(read_stream, write_stream)
            await _session.__aenter__()
            await _session.initialize()
            logger.info("Connected to BioMCP at %s", BIOMCP_URL)
        except Exception:
            # Clean up transport if session init fails
            await _streams.__aexit__(None, None, None)
            raise
    except Exception:
        logger.warning("Failed to connect to BioMCP at %s", BIOMCP_URL, exc_info=True)
        _session = None
        _streams = None


async def close() -> None:
    """Close the MCP session."""
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
    """Check if BioMCP sidecar is reachable via its HTTP health endpoint."""
    base_url = BIOMCP_URL.rsplit("/mcp", 1)[0]
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{base_url}/health")
            return resp.status_code == 200
    except Exception:
        return False


async def get_interactions(drug_name: str) -> list[dict]:
    """Get drug-drug interactions for a given drug name.

    Returns list of {"drug": str, "description": str | None}.
    Raises BioMCPUnavailableError if BioMCP is unreachable.
    """
    cache_key = f"interactions:{drug_name.lower()}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    if _session is None:
        raise BioMCPUnavailableError("BioMCP session not established")

    # NOTE: The exact tool name and argument schema below must be verified
    # after building the sidecar. Run `await _session.list_tools()` during
    # development to confirm the interface. See Task 2 Step 4a.
    try:
        result = await _session.call_tool(
            "get",
            {"entity": "drug", "name": drug_name, "sections": ["interactions"]},
        )
    except Exception as exc:
        raise BioMCPUnavailableError(f"BioMCP call failed: {exc}") from exc

    if result.isError:
        raise BioMCPUnavailableError(f"BioMCP returned error for {drug_name}")

    # Parse the response — BioMCP returns JSON in content[0].text
    try:
        content_block = result.content[0]
        if not hasattr(content_block, "text"):
            logger.warning("BioMCP returned unexpected content type for %s", drug_name)
            interactions = []
        else:
            data = json.loads(content_block.text)
            interactions = data.get("interactions", [])
    except (json.JSONDecodeError, IndexError):
        interactions = []

    _cache_set(cache_key, interactions)
    return interactions
