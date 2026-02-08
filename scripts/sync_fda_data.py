#!/usr/bin/env python3
"""
Sync FDA drug label data into a local SQLite database.
Fetches Public Domain data from OpenFDA.
"""
import json
import sqlite3
import zipfile
import io
import logging
import re
import sys
import asyncio
import tempfile
from pathlib import Path
import httpx
import ijson

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

# Use absolute path to ensure consistency regardless of where the script is run from.
PROJECT_ROOT = Path(__file__).parent.parent
DB_PATH = PROJECT_ROOT / "data" / "fda_interactions.db"

DOWNLOAD_JSON_URL = "https://api.fda.gov/download.json"

# Regex for basic severity inference
RX_CRITICAL = re.compile(r"\b(contraindicated|fatal|do not use|death)\b", re.IGNORECASE)
RX_WARNING = re.compile(r"\b(caution|monitor|warning|risk|avoid)\b", re.IGNORECASE)

def setup_db(conn: sqlite3.Connection):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS labels (
            id TEXT PRIMARY KEY,
            rxcui TEXT,
            generic_name TEXT,
            brand_name TEXT,
            interactions TEXT,
            contraindications TEXT,
            warnings TEXT,
            last_updated TEXT
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_generic ON labels(generic_name)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_brand ON labels(brand_name)")

def infer_severity(text: str) -> str:
    if not text:
        return "unknown"
    if RX_CRITICAL.search(text):
        return "major"
    if RX_WARNING.search(text):
        return "moderate"
    return "minor"

def parse_record(record: dict):
    openfda = record.get("openfda", {})
    
    # Use the FDA's unique record ID instead of RxCUI as the primary key
    label_id = record.get("id")
    if not label_id:
        return None

    generic_names = openfda.get("generic_name", [])
    brand_names = openfda.get("brand_name", [])
    
    # If we don't have a name, we can't search for it later
    if not generic_names and not brand_names:
        return None

    rxcuis = openfda.get("rxcui", [])
    
    return {
        "id": label_id,
        "rxcui": rxcuis[0] if rxcuis else None,
        "generic_name": generic_names[0] if generic_names else None,
        "brand_name": brand_names[0] if brand_names else None,
        "interactions": " ".join(record.get("drug_interactions", []) or []),
        "contraindications": " ".join(record.get("contraindications", []) or []),
        "warnings": " ".join(record.get("warnings", []) or record.get("warnings_and_precautions", []) or []),
        "last_updated": record.get("effective_time")
    }

async def get_partition_urls():
    """Fetch the list of all drug label partition URLs."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(DOWNLOAD_JSON_URL)
        resp.raise_for_status()
        data = resp.json()
    
    label_data = data['results']['drug']['label']
    return [p['file'] for p in label_data['partitions']]

async def sync_data(limit: int | None = 1000):
    """Download partitions and sync records."""
    urls = await get_partition_urls()
    logger.info(f"Found {len(urls)} partitions.")

    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        setup_db(conn)
        total_synced = 0
        
        # Optimize SQLite for bulk inserts
        conn.execute("PRAGMA synchronous = OFF")
        conn.execute("PRAGMA journal_mode = WAL")

        for url in urls:
            if limit and total_synced >= limit:
                break

            logger.info(f"Downloading {url}...")
            
            # Download to a temporary file to save RAM
            with tempfile.NamedTemporaryFile(suffix=".zip") as tmp_file:
                async with httpx.AsyncClient(timeout=120.0) as client:
                    async with client.stream("GET", url) as resp:
                        resp.raise_for_status()
                        async for chunk in resp.aiter_bytes():
                            tmp_file.write(chunk)
                tmp_file.flush()
                
                logger.info(f"Processing records from partition...")
                
                try:
                    with zipfile.ZipFile(tmp_file.name) as z:
                        json_filename = z.namelist()[0]
                        with z.open(json_filename) as f:
                            # Use ijson for memory-efficient streaming parsing
                            # 'results.item' iterates over items in the "results" array
                            for record in ijson.items(f, 'results.item'):
                                parsed = parse_record(record)
                                if not parsed:
                                    continue
                                    
                                conn.execute("""
                                    INSERT OR REPLACE INTO labels 
                                    (id, rxcui, generic_name, brand_name, interactions, contraindications, warnings, last_updated)
                                    VALUES (:id, :rxcui, :generic_name, :brand_name, :interactions, :contraindications, :warnings, :last_updated)
                                """, parsed)
                                
                                total_synced += 1
                                
                                # Commit in batches to keep transaction size manageable
                                if total_synced % 1000 == 0:
                                    conn.commit()
                                    logger.info(f"Synced {total_synced} records...")

                                if limit and total_synced >= limit:
                                    break
                except zipfile.BadZipFile:
                    logger.error(f"Failed to unzip {url}. Skipping.")
                    continue
            
            conn.commit() # Commit after each partition

    logger.info(f"Successfully synced {total_synced} records to {DB_PATH}")

if __name__ == "__main__":
    arg_limit = sys.argv[1] if len(sys.argv) > 1 else "1000"
    limit = int(arg_limit) if arg_limit.lower() != "all" else None
    asyncio.run(sync_data(limit))
