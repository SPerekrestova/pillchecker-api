"""Admin endpoints for cache management."""

import logging

from fastapi import APIRouter

from app.clients import openfda_client, rxnorm_client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])


@router.post("/cache/clear")
async def clear_cache():
    """Clear all in-memory caches. Requires API key authentication."""
    rxnorm_client._cache.clear()
    openfda_client._cache.clear()
    logger.info("All caches cleared via admin endpoint")
    return {"status": "ok", "message": "All caches cleared"}
