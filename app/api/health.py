"""Health check endpoints."""

from fastapi import APIRouter
from app.data import fda_store
from app.nlp import ner_model

router = APIRouter()


@router.get("/health")
async def health_check():
    """Basic health check to verify the API is running."""
    return {
        "status": "ok", 
        "version": "0.1.0",
        "ner_model_loaded": ner_model.is_loaded()
    }

@router.get("/health/data")
async def data_health_check():
    """Check the status of the medication interaction database."""
    count = fda_store.interaction_count()
    return {
        "status": "ready" if count > 0 else "empty",
        "record_count": count,
        "database": str(fda_store.DB_PATH)
    }
