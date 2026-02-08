#!/bin/bash
set -e

# CI Startup Script
# Used for integration tests to quickly bootstrap a functional environment.

DB_PATH="/app/data/fda_interactions.db"
CI_LIMIT="5000"

echo "[CI] Starting in CI mode."
echo "[CI] Checking database at $DB_PATH..."

# In CI, we expect to start fresh or just want to ensure we have *some* data.
# We don't care about preserving data across runs usually (no volumes), 
# but if a file exists (e.g. from a build layer?), we might check it.
# Given CI usually has no volume or an empty one, we just sync.

if [ ! -f "$DB_PATH" ]; then
    echo "[CI] Database not found. Bootstrapping with $CI_LIMIT records..."
    python scripts/sync_fda_data.py "$CI_LIMIT"
else
    echo "[CI] Database found. Skipping sync."
fi

# Execute the CMD (e.g. uvicorn ...)
exec "$@"
