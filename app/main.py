import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.analyze import router as analyze_router
from app.api.health import router as health_router
from app.api.interactions import router as interactions_router
from app.data import fda_store
from app.nlp import ner_model

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Loading NER model...")
    ner_model.load_model()
    logger.info("NER model loaded.")
    logger.info("Loading interaction data...")
    fda_store.load()
    logger.info("Loaded %d drug labels.", fda_store.interaction_count())
    yield


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
    allow_headers=["Content-Type"],
)

app.include_router(health_router)
app.include_router(analyze_router)
app.include_router(interactions_router)