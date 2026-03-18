import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.analyze import router as analyze_router
from app.api.health import router as health_router
from app.api.interactions import router as interactions_router
from app.clients import drugbank_client
from app.middleware.api_key import APIKeyMiddleware
from app.nlp import ner_model, severity_classifier

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Loading NER model...")
    ner_model.load_model()
    logger.info("NER model loaded.")
    logger.info("Loading severity classifier...")
    severity_classifier.load_model()
    logger.info("Severity classifier loaded: %s", severity_classifier.is_loaded())
    logger.info("Connecting to DrugBank MCP server...")
    await drugbank_client.connect()
    logger.info("DrugBank MCP connected: %s", await drugbank_client.health_check())
    yield
    await drugbank_client.close()


app = FastAPI(
    title="PillChecker API",
    description="Medication interaction checker",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS: only needed for local development (different ports).
# In production, nginx serves both frontend and API on the same origin.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:8080",
        "http://localhost:5173",
        "http://localhost:3000",
    ],
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "X-API-Key"],
)

app.add_middleware(APIKeyMiddleware)

app.include_router(health_router)
app.include_router(analyze_router)
app.include_router(interactions_router)