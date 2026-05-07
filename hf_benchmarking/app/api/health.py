"""Health check endpoints."""

from fastapi import APIRouter
from app.clients import drugbank_client
from app.nlp import ner_model

router = APIRouter()


@router.get("/health")
async def health_check():
    """Basic health check to verify the API is running."""
    return {
        "status": "ok",
        "version": "0.1.0",
        "ner_model_loaded": ner_model.is_loaded(),
    }


@router.get("/health/data")
async def data_health_check():
    """Check the status of the drug interaction data source."""
    connected = await drugbank_client.health_check()
    return {
        "status": "ready" if connected else "degraded",
        "drugbank": "connected" if connected else "unreachable",
    }
