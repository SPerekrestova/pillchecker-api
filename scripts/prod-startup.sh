#!/bin/bash
set -e

# Production Startup Script
# DDInter SQLite DB is baked into the image at build time.

echo "[PROD] Starting PillChecker API..."

# Execute the CMD
exec "$@"
