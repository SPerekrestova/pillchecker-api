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

# Install Node.js and build tools for drugbank-mcp-server
# (python3 already present in base image; build-essential needed for better-sqlite3 native addon)
RUN apt-get update && apt-get install -y --no-install-recommends \
    nodejs npm build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install and build drugbank-mcp-server
COPY drugbank-mcp-server/package.json drugbank-mcp-server/package-lock.json /app/drugbank-mcp-server/
RUN cd /app/drugbank-mcp-server && npm ci
COPY drugbank-mcp-server/scripts/ /app/drugbank-mcp-server/scripts/
COPY drugbank-mcp-server/src/ /app/drugbank-mcp-server/src/
RUN cd /app/drugbank-mcp-server && npm run download:db && npm run build:code

COPY --from=builder /app/.venv /app/.venv

ENV PATH="/app/.venv/bin:$PATH"
ENV HF_HOME=/app/models
ENV TRANSFORMERS_CACHE=/app/models

# Pre-download NER model so the image is self-contained.
# Layer is cached until venv or model ID changes.
# In local dev, docker-compose mounts a volume over /app/models.
RUN python -c "from transformers import pipeline; \
    pipeline('ner', model='OpenMed/OpenMed-NER-PharmaDetect-ModernClinical-149M', aggregation_strategy='none'); \
    pipeline('zero-shot-classification', model='MoritzLaurer/DeBERTa-v3-base-mnli-fever-anli')"

# App code comes last — most frequently changing layer
COPY --from=builder /app/app /app/app
COPY scripts/ /app/scripts/

RUN chmod +x /app/scripts/prod-startup.sh /app/scripts/ci-startup.sh

EXPOSE 8000

ENTRYPOINT ["/app/scripts/prod-startup.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
