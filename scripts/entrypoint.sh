#!/bin/bash
set -e

DB_PATH="/app/data/fda_interactions.db"

echo "Checking database at $DB_PATH..."

if [ ! -f "$DB_PATH" ]; then
    echo "Database not found. Bootstrapping with sample data..."
    # Bootstrap with 5000 records so the app is functional immediately.
    # The user can run a full sync later.
    python scripts/sync_fda_data.py 5000
else
    echo "Database found."
fi

# Execute the CMD from Dockerfile
exec "$@"
