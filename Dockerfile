FROM python:3.12-slim AS base

WORKDIR /app

# System deps for torch
RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc && \
    rm -rf /var/lib/apt/lists/*

COPY pyproject.toml .
RUN pip install --no-cache-dir .

COPY app/ app/

# HuggingFace model cache — mount as Docker volume for persistence
ENV HF_HOME=/app/models
ENV TRANSFORMERS_CACHE=/app/models

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
