"""Admin endpoints for cache management."""

import logging

from fastapi import APIRouter

from app.clients import drugbank_client, openfda_client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])


@router.post("/cache/clear")
async def clear_cache():
    """Clear all in-memory caches. Requires API key authentication."""
    drugbank_client._cache.clear()
    openfda_client._cache.clear()
    logger.info("All caches cleared via admin endpoint")
    return {"status": "ok", "message": "All caches cleared"}
