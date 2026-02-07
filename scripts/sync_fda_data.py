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
from pathlib import Path
import httpx

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

DB_PATH = Path("data/fda_interactions.db")
DOWNLOAD_JSON_URL = "https://api.fda.gov/download.json"

# Regex for basic severity inference
RX_CRITICAL = re.compile(r"\b(contraindicated|fatal|do not use|death)\b", re.IGNORECASE)
RX_WARNING = re.compile(r"\b(caution|monitor|warning|risk|avoid)\b", re.IGNORECASE)

def setup_db(conn: sqlite3.Connection):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS labels (
            rxcui TEXT PRIMARY KEY,
            generic_name TEXT,
            brand_name TEXT,
            interactions TEXT,
            contraindications TEXT,
            warnings TEXT,
            last_updated TEXT
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_generic ON labels(generic_name)")

def parse_record(record: dict):
    openfda = record.get("openfda", {})
    rxcuis = openfda.get("rxcui", [])
    if not rxcuis:
        return None
    
    rxcui = rxcuis[0]
    generic_names = openfda.get("generic_name", [])
    brand_names = openfda.get("brand_name", [])
    
    return {
        "rxcui": rxcui,
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

        for url in urls:
            if limit and total_synced >= limit:
                break

            logger.info(f"Downloading {url}...")
            async with httpx.AsyncClient(timeout=120.0) as client:
                resp = await client.get(url)
                resp.raise_for_status()
            
            with zipfile.ZipFile(io.BytesIO(resp.content)) as z:
                json_filename = z.namelist()[0]
                with z.open(json_filename) as f:
                    data = json.load(f)
                    records = data.get("results", [])
            
            logger.info(f"Processing {len(records)} records from partition...")
            for record in records:
                parsed = parse_record(record)
                if not parsed:
                    continue
                    
                conn.execute("""
                    INSERT OR REPLACE INTO labels 
                    (rxcui, generic_name, brand_name, interactions, contraindications, warnings, last_updated)
                    VALUES (:rxcui, :generic_name, :brand_name, :interactions, :contraindications, :warnings, :last_updated)
                """, parsed)
                
                total_synced += 1
                if limit and total_synced >= limit:
                    break
            
            conn.commit()
            logger.info(f"Total synced so far: {total_synced}")

    logger.info(f"Successfully synced {total_synced} records to {DB_PATH}")

if __name__ == "__main__":
    arg_limit = sys.argv[1] if len(sys.argv) > 1 else "1000"
    limit = int(arg_limit) if arg_limit.lower() != "all" else None
    asyncio.run(sync_data(limit))
