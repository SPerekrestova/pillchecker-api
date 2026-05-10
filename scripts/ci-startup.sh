#!/bin/bash
set -e

# CI Startup Script
# DrugBank SQLite DB is baked into the image at build time.

echo "[CI] Starting in CI mode."

# Execute the CMD (e.g. uvicorn ...)
exec "$@"
