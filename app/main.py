import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.health import router as health_router
from app.data import ddinter_store
from app.nlp import ner_model

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Loading NER model...")
    ner_model.load_model()
    logger.info("NER model loaded.")
    logger.info("Loading interaction data...")
    ddinter_store.load()
    logger.info("Loaded %d interaction pairs.", ddinter_store.interaction_count())
    yield


app = FastAPI(
    title="PillChecker API",
    description="Medication interaction checker",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(health_router)
