#!/bin/bash
set -e

# CI Startup Script
# BioMCP sidecar handles drug interaction data — no local DB needed.

echo "[CI] Starting in CI mode."

# Execute the CMD (e.g. uvicorn ...)
exec "$@"
