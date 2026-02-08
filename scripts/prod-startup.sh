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
    
    # Threshold: 5,000 unique records is a healthy dataset for a single partition.
    # The total dataset across all partitions will be 250k+, but we want to 
    # ensure we have at least *some* real data before continuing.
    if [ "$RECORD_COUNT" -lt 5000 ]; then
        echo "[PROD] Database has only $RECORD_COUNT records. This seems low. Upgrading to FULL dataset..."
        python scripts/sync_fda_data.py all
    else
        echo "[PROD] Database found with $RECORD_COUNT records. Ready."
    fi
fi

# Execute the CMD
exec "$@"
