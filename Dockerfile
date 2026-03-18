FROM ghcr.io/astral-sh/uv:0.9-python3.12-bookworm-slim AS builder

WORKDIR /app

# Copy dependency files first for layer caching
COPY pyproject.toml uv.lock .python-version ./

# Install dependencies only (locked, no project code yet)
RUN uv sync --frozen --no-install-project --no-dev

# Copy application code and install the project
COPY app/ app/
RUN uv sync --frozen --no-dev

# --- Node.js build stage ---
FROM node:20-bookworm AS node-builder

WORKDIR /app/drugbank-mcp-server

COPY drugbank-mcp-server/package.json drugbank-mcp-server/package-lock.json ./
RUN npm ci

COPY drugbank-mcp-server/scripts/ scripts/
COPY drugbank-mcp-server/src/ src/
RUN npm run download:db && npm run build:code

# --- Runtime stage ---
FROM python:3.12-slim

WORKDIR /app

# Copy Node.js binary (needed at runtime to run the MCP server)
COPY --from=node:20-slim /usr/local/bin/node /usr/local/bin/node

# Copy built drugbank-mcp-server (includes node_modules with native addons, DB, and build/)
COPY --from=node-builder /app/drugbank-mcp-server /app/drugbank-mcp-server

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
