"""Structured audit logging for safety-critical pipeline operations.

Uses contextvars for request-scoped audit context. The middleware
initializes context at request start and logs it at request end.
Service-layer functions append audit entries during processing.
"""

import json
import logging
import time
from contextvars import ContextVar
from dataclasses import dataclass, field

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger("pillchecker.audit")

_audit_context: ContextVar["AuditContext | None"] = ContextVar("audit_context", default=None)


@dataclass
class AuditContext:
    """Request-scoped container for audit entries."""

    entries: list[dict] = field(default_factory=list)
    start_time: float = field(default_factory=time.time)

    def add(self, stage: str, data: dict) -> None:
        """Append an audit entry for a pipeline stage."""
        self.entries.append({"stage": stage, **data})

    def to_dict(self) -> dict:
        """Serialize to a loggable dict."""
        return {
            "timestamp": self.start_time,
            "duration_ms": round((time.time() - self.start_time) * 1000, 1),
            "entries": self.entries,
        }


def init_audit_context() -> AuditContext:
    """Initialize a new audit context for the current request."""
    ctx = AuditContext()
    _audit_context.set(ctx)
    return ctx


def get_audit_context() -> AuditContext | None:
    """Get the current request's audit context, or None if not in a request."""
    return _audit_context.get(None)


class AuditLogMiddleware(BaseHTTPMiddleware):
    """Middleware that initializes audit context and logs it after response."""

    async def dispatch(self, request: Request, call_next):
        # Only audit API endpoints, not health checks
        if request.url.path.startswith("/health"):
            return await call_next(request)

        ctx = init_audit_context()
        ctx.add("request", {
            "method": request.method,
            "path": request.url.path,
        })

        response = await call_next(request)

        ctx.add("response", {"status_code": response.status_code})

        # Log the full audit record as structured JSON
        try:
            logger.info(json.dumps(ctx.to_dict()))
        except Exception:
            logger.warning("Failed to serialize audit log", exc_info=True)

        return response
