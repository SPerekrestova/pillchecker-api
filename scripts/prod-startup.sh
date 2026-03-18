#!/bin/bash
set -e

# Production Startup Script
# BioMCP sidecar handles drug interaction data — no local DB needed.

echo "[PROD] Starting PillChecker API..."

# Execute the CMD
exec "$@"
