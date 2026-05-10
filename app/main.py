import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded


def _get_real_client_ip(request: Request) -> str:
    """Extract real client IP from X-Forwarded-For (Cloud Run) or fall back to direct IP."""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


limiter = Limiter(key_func=_get_real_client_ip)

from app.api.admin import router as admin_router
from app.api.analyze import router as analyze_router
from app.api.health import router as health_router
from app.api.interactions import router as interactions_router
from app.clients import drugbank_client
from app.middleware.api_key import APIKeyMiddleware
from app.middleware.audit_log import AuditLogMiddleware
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
    logger.info("Connecting to DrugBank SQLite database...")
    await drugbank_client.connect()
    logger.info("DrugBank SQLite connected: %s", await drugbank_client.health_check())
    yield
    await drugbank_client.close()


app = FastAPI(
    title="PillChecker API",
    description="Medication interaction checker",
    version="0.1.0",
    lifespan=lifespan,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS: only needed for local development (different ports).
# In production, Cloud Run handles routing directly.
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
app.add_middleware(AuditLogMiddleware)

app.include_router(health_router)
app.include_router(analyze_router)
app.include_router(interactions_router)
app.include_router(admin_router)
