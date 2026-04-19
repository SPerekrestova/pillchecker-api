FROM ghcr.io/astral-sh/uv:0.9-python3.12-bookworm-slim AS builder

WORKDIR /app

# Copy dependency files first for layer caching
COPY pyproject.toml uv.lock .python-version ./

# Install dependencies only (locked, no project code yet)
RUN uv sync --no-install-project --no-dev

# Copy application code and install the project
COPY app/ app/
RUN uv sync --no-dev

# --- DB downloader stage ---
FROM python:3.12-slim AS db-downloader

WORKDIR /app/drugbank-mcp-server/data

# Use curl to download a pinned version of the pre-built SQLite DB.
# Pinning the tag ensures deterministic builds and allows Docker to cache this layer reliably.
ARG DRUGBANK_DB_REPO=openpharma-org/drugbank-mcp-server
ARG DRUGBANK_DB_TAG=db-2026-04-01
RUN apt-get update && apt-get install -y curl && \
    curl -fL -o drugbank.db "https://github.com/${DRUGBANK_DB_REPO}/releases/download/${DRUGBANK_DB_TAG}/drugbank.db" && \
    apt-get purge -y curl && apt-get autoremove -y && rm -rf /var/lib/apt/lists/*

# --- Runtime stage ---
FROM python:3.12-slim

WORKDIR /app

# Copy built virtualenv from builder
COPY --from=builder /app/.venv /app/.venv

# Copy DrugBank SQLite DB from downloader stage
COPY --from=db-downloader /app/drugbank-mcp-server/data /app/drugbank-mcp-server/data

ENV PATH="/app/.venv/bin:$PATH"
ENV HF_HOME=/app/models
ENV TRANSFORMERS_CACHE=/app/models

# Pre-download NER model so the image is self-contained.
# Layer is cached until venv or model ID changes.
# In local dev, docker-compose mounts a volume over /app/models.
RUN python -c "from transformers import pipeline; \
    pipeline('ner', model='OpenMed/OpenMed-NER-PharmaDetect-BioPatient-108M', aggregation_strategy='none'); \
    pipeline('zero-shot-classification', model='MoritzLaurer/DeBERTa-v3-base-mnli-fever-anli')"

# App code comes last — most frequently changing layer
COPY --from=builder /app/app /app/app
COPY scripts/ /app/scripts/

RUN chmod +x /app/scripts/prod-startup.sh /app/scripts/ci-startup.sh

# Create a non-root user for security
RUN groupadd -r pillchecker && useradd -r -g pillchecker pillchecker && \
    chown -R pillchecker:pillchecker /app

USER pillchecker

EXPOSE 8000

ENTRYPOINT ["/app/scripts/prod-startup.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
