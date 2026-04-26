FROM ghcr.io/astral-sh/uv:0.9-python3.12-bookworm-slim AS builder

WORKDIR /home/user/app

# Copy dependency files first for layer caching
COPY pyproject.toml uv.lock .python-version ./

# Install dependencies only (locked, no project code yet)
RUN uv sync --no-install-project --no-dev

# Copy application code and install the project
COPY app/ app/
RUN uv sync --no-dev

# --- DB downloader stage ---
FROM python:3.12-slim AS db-downloader

WORKDIR /home/user/app/drugbank-mcp-server/data

# Use curl to download a pinned version of the pre-built SQLite DB.
ARG DRUGBANK_DB_REPO=openpharma-org/drugbank-mcp-server
ARG DRUGBANK_DB_TAG=db-2026-04-01
RUN apt-get update && apt-get install -y curl && \
    curl -fL -o drugbank.db "https://github.com/${DRUGBANK_DB_REPO}/releases/download/${DRUGBANK_DB_TAG}/drugbank.db" && \
    apt-get purge -y curl && apt-get autoremove -y && rm -rf /var/lib/apt/lists/*

# --- Runtime stage ---
FROM python:3.12-slim

# Set up a new user named "user" with UID 1000 (standard for HF Spaces)
RUN useradd -m -u 1000 user
ENV HOME=/home/user \
    PATH=/home/user/app/.venv/bin:/home/user/.local/bin:$PATH

WORKDIR /home/user/app

# Copy built virtualenv from builder
COPY --from=builder /home/user/app/.venv /home/user/app/.venv

# Copy DrugBank SQLite DB from downloader stage
COPY --from=db-downloader /home/user/app/drugbank-mcp-server/data /home/user/app/drugbank-mcp-server/data

# Ensure paths are correct for the app
ENV HF_HOME=/home/user/app/models
ENV TRANSFORMERS_CACHE=/home/user/app/models

# Pre-download NER model so the image is self-contained.
RUN python -c "from transformers import pipeline; \
    pipeline('ner', model='OpenMed/OpenMed-NER-PharmaDetect-BioPatient-108M', aggregation_strategy='none'); \
    pipeline('zero-shot-classification', model='MoritzLaurer/DeBERTa-v3-base-mnli-fever-anli')"

# App code comes last
COPY --from=builder /home/user/app/app /home/user/app/app
COPY scripts/ /home/user/app/scripts/

RUN chmod +x /home/user/app/scripts/prod-startup.sh /home/user/app/scripts/ci-startup.sh
RUN chown -R user:user /home/user/app

USER user

EXPOSE 7860

ENTRYPOINT ["/home/user/app/scripts/prod-startup.sh"]
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
