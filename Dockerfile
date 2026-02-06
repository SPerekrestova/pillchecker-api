FROM ghcr.io/astral-sh/uv:0.9-python3.12-bookworm-slim AS builder

WORKDIR /app

# Copy dependency files first for layer caching
COPY pyproject.toml uv.lock .python-version ./

# Install dependencies only (locked, no project code yet)
RUN uv sync --frozen --no-install-project --no-dev

# Copy application code and install the project
COPY app/ app/
RUN uv sync --frozen --no-dev

# --- Runtime stage ---
FROM python:3.12-slim

WORKDIR /app

COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/app /app/app

ENV PATH="/app/.venv/bin:$PATH"

# HuggingFace model cache — mount as Docker volume for persistence
ENV HF_HOME=/app/models
ENV TRANSFORMERS_CACHE=/app/models

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
