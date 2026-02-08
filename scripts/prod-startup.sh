#!/bin/bash
set -e

# Production Startup Script
# Used for real deployments. Ensures the full dataset is available.

DB_PATH="/app/data/fda_interactions.db"

echo "[PROD] Checking database at $DB_PATH..."

if [ ! -f "$DB_PATH" ]; then
    echo "[PROD] Database not found. Bootstrapping with FULL dataset (this may take a while)..."
    python scripts/sync_fda_data.py all
else
    # Check if we have a "toy" database (e.g. from a test run or old snapshot)
    # and upgrade it to full if necessary.
    
    # Safely get record count
    RECORD_COUNT=$(python -c "import sqlite3; conn = sqlite3.connect('$DB_PATH'); print(conn.execute('SELECT COUNT(*) FROM labels').fetchone()[0])" 2>/dev/null || echo 0)
    
    # Threshold: If < 10,000 records, assume it's incomplete/test data.
    if [ "$RECORD_COUNT" -lt 10000 ]; then
        echo "[PROD] Database has only $RECORD_COUNT records. Upgrading to FULL dataset..."
        python scripts/sync_fda_data.py all
    else
        echo "[PROD] Database found with $RECORD_COUNT records. Ready."
    fi
fi

# Execute the CMD
exec "$@"
