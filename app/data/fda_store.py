"""DDI store backed by SQLite (OpenFDA Public Domain Data)."""
import sqlite3
import logging
import re
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

DB_PATH = Path(__file__).parent.parent.parent / "data" / "fda_interactions.db"
_conn: sqlite3.Connection | None = None

@dataclass
class Interaction:
    drug_a: str
    drug_b: str
    severity: str
    description: str
    management: str

def load():
    """Open DB connection."""
    global _conn
    if not DB_PATH.exists():
        logger.warning(f"FDA database not found at {DB_PATH}. Run sync script first.")
        return
    _conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    _conn.row_factory = sqlite3.Row

def check_interaction(drug_a_name: str, drug_b_name: str) -> Interaction | None:
    """
    Check if drug_a exists in drug_b's label, or vice versa.
    Since labels are unstructured text, we do a keyword search.
    """
    if _conn is None:
        load()
    if _conn is None:
        return None

    # Try both directions
    res = _find_in_label(drug_a_name, drug_b_name)
    if res:
        return res
    
    return _find_in_label(drug_b_name, drug_a_name)

def _find_in_label(target_drug: str, label_drug: str) -> Interaction | None:
    """Search for target_drug in label_drug's interaction text."""
    cursor = _conn.execute(
        "SELECT interactions, contraindications, warnings FROM labels WHERE generic_name = ? OR brand_name = ?",
        (label_drug.upper(), label_drug.upper())
    )
    row = cursor.fetchone()
    if not row:
        return None

    # Combine all safety text
    full_text = f"{row['interactions']} {row['contraindications']} {row['warnings']}"
    
    # Use regex for word-boundary match of the target drug name
    pattern = re.compile(rf"\b{re.escape(target_drug)}\b", re.IGNORECASE)
    
    if pattern.search(full_text):
        # Infer severity from context
        severity = "moderate"
        if row['contraindications'] and pattern.search(row['contraindications']):
            severity = "major"
        
        # Extract a snippet (approx 200 chars around the match)
        match = pattern.search(full_text)
        start = max(0, match.start() - 100)
        end = min(len(full_text), match.end() + 100)
        description = full_text[start:end].strip()
        
        return Interaction(
            drug_a=label_drug,
            drug_b=target_drug,
            severity=severity,
            description=f"...{description}...",
            management="See official FDA label for complete prescribing information."
        )
    
    return None

def interaction_count() -> int:
    if _conn is None: return 0
    return _conn.execute("SELECT COUNT(*) FROM labels").fetchone()[0]
