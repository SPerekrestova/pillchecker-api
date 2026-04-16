"""Client for DrugBank database.

Refactored to use direct SQLite access via app/clients/drugbank_db.py,
eliminating the need for the Node.js MCP server child process.
"""

import logging
import time
from app.clients.drugbank_db import db

logger = logging.getLogger(__name__)

# Simple TTL cache: {key: (value, expiry_timestamp)}
_cache: dict[str, tuple[object, float]] = {}
_CACHE_TTL = 14400  # 4 hours
_CACHE_MISS = object()  # sentinel to distinguish cache miss from cached None


class DrugBankUnavailableError(Exception):
    """Raised when the DrugBank database is unreachable or returns an error."""


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
    """Connect to the DrugBank SQLite database."""
    try:
        await db.connect()
    except Exception as e:
        logger.warning("Failed to connect to DrugBank SQLite database: %s", e)


async def close() -> None:
    """Close the database connection."""
    await db.close()


async def health_check() -> bool:
    """Check if the database connection is alive."""
    # A simple way to check is to try a dummy query or check connection status
    if db._conn is None:
        try:
            await db.connect()
            return True
        except Exception:
            return False
    return True


async def _resolve_drugbank_id(drug_name: str) -> str | None:
    """Resolve a drug name to a DrugBank ID via search_by_name.

    Returns the drugbank_id of the first result, or None if not found.
    """
    cache_key = f"dbid:{drug_name.lower()}"
    cached = _cache_get(cache_key)
    if cached is not _CACHE_MISS:
        return cached

    try:
        results = await db.search_by_name(drug_name, limit=1)
        drugbank_id = results[0]["drugbank_id"] if results else None
    except Exception as exc:
        logger.error("DrugBank resolution failed for %s: %s", drug_name, exc)
        drugbank_id = None

    _cache_set(cache_key, drugbank_id)
    return drugbank_id


async def get_interactions(drug_name: str) -> list[dict]:
    """Get drug-drug interactions for a given drug name.

    Returns list of {"drug": str, "description": str | None, "severity": str | None}.
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
    try:
        raw_interactions = await db.get_drug_interactions(drugbank_id)
        # Map to format expected by interaction_checker.py: {drug, description, severity}
        interactions = [
            {
                "drug": entry.get("name", ""),
                "description": entry.get("description"),
                "severity": entry.get("severity"),
            }
            for entry in raw_interactions
        ]
    except Exception as exc:
        logger.error("Failed to fetch interactions for %s: %s", drugbank_id, exc)
        interactions = []

    _cache_set(cache_key, interactions)
    return interactions
