# syntax=docker/dockerfile:1.7

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

WORKDIR /app/data

# Download a pinned DDInter SQLite DB from the project's release source.
ARG INTERACTION_DB_REPO
ARG INTERACTION_DB_TAG
ARG INTERACTION_DB_SHA256
COPY scripts/download_interaction_db.py /tmp/download_interaction_db.py
RUN --mount=type=secret,id=github_token,required=false \
    test -n "${INTERACTION_DB_REPO}" || { echo "INTERACTION_DB_REPO build arg is required"; exit 1; }; \
    test -n "${INTERACTION_DB_TAG}" || { echo "INTERACTION_DB_TAG build arg is required"; exit 1; }; \
    if [ -f /run/secrets/github_token ]; then export GITHUB_TOKEN="$(cat /run/secrets/github_token)"; fi; \
    if [ -n "${INTERACTION_DB_SHA256}" ]; then export INTERACTION_DB_SHA256="${INTERACTION_DB_SHA256}"; fi; \
    python /tmp/download_interaction_db.py \
      --repo "${INTERACTION_DB_REPO}" \
      --tag "${INTERACTION_DB_TAG}" \
      --asset ddinter.db \
      --output ddinter.db

# --- Application base stage ---
FROM python:3.12-slim AS app-base

WORKDIR /app

# Copy built virtualenv from builder
COPY --from=builder /app/.venv /app/.venv

# Copy DDInter SQLite DB from downloader stage
COPY --from=db-downloader /app/data /app/data

ENV PATH="/app/.venv/bin:$PATH"
ENV HF_HOME=/app/models
ENV TRANSFORMERS_CACHE=/app/models
ENV INTERACTION_DB_PATH=/app/data/ddinter.db

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

# --- Benchmark runner stage ---
FROM app-base AS benchmark-runner

USER root

COPY eval/ /app/eval/

RUN chown -R pillchecker:pillchecker /app/eval

USER pillchecker

ENTRYPOINT ["python", "-m", "eval.run_benchmark"]
CMD []

# --- Runtime stage ---
FROM app-base AS runtime

EXPOSE 8000

ENTRYPOINT ["/app/scripts/prod-startup.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
