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

_SENTENCE_RE = re.compile(r'(?<=[.!?])\s+')
_MAX_DESCRIPTION = 500


def _extract_sentences(text: str, match_start: int, match_end: int) -> str:
    """Return the sentence containing the match plus the next sentence, capped at _MAX_DESCRIPTION chars."""
    # Split text into sentences with their positions
    sentences: list[tuple[int, int]] = []
    prev = 0
    for m in _SENTENCE_RE.finditer(text):
        sentences.append((prev, m.start()))
        prev = m.end()
    sentences.append((prev, len(text)))

    # Find the sentence containing the match
    hit_idx = 0
    for i, (s, e) in enumerate(sentences):
        if s <= match_start < e:
            hit_idx = i
            break

    # Take the hit sentence + one following sentence
    end_idx = min(hit_idx + 2, len(sentences))
    start_pos = sentences[hit_idx][0]
    end_pos = sentences[end_idx - 1][1]
    result = text[start_pos:end_pos].strip()

    if len(result) > _MAX_DESCRIPTION:
        # Truncate at last sentence boundary within limit
        truncated = result[:_MAX_DESCRIPTION]
        last_period = truncated.rfind('.')
        if last_period > 0:
            result = truncated[:last_period + 1]
        else:
            result = truncated[:_MAX_DESCRIPTION - 1].rstrip() + "…"

    return result


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
    """Search for target_drug in label_drug's interaction text.
    Scans ALL available labels for label_drug and returns the most severe match found.
    """
    cursor = _conn.execute(
        "SELECT interactions, contraindications, warnings FROM labels WHERE generic_name = ? OR brand_name = ?",
        (label_drug.upper(), label_drug.upper())
    )
    
    # We iterate through all labels for this drug.
    # Different manufacturers might have more/less detailed text.
    # We want to find the "worst case" interaction.
    
    best_match: Interaction | None = None
    severity_rank = {"minor": 1, "moderate": 2, "major": 3}

    rows = cursor.fetchall()
    if not rows:
        return None

    # Pattern to find the target drug in text
    pattern = re.compile(rf"\b{re.escape(target_drug)}\b", re.IGNORECASE)

    for row in rows:
        # Combine all safety text for this specific label
        full_text = f"{row['interactions']} {row['contraindications']} {row['warnings']}"
        
        if pattern.search(full_text):
            # Infer severity for this specific label
            current_severity = "moderate"
            if row['contraindications'] and pattern.search(row['contraindications']):
                current_severity = "major"
            
            # If we haven't found a match yet, or this one is more severe, keep it.
            if best_match is None or severity_rank[current_severity] > severity_rank[best_match.severity]:
                
                # Extract sentence(s) containing the match
                match = pattern.search(full_text)
                description = _extract_sentences(full_text, match.start(), match.end())

                best_match = Interaction(
                    drug_a=label_drug,
                    drug_b=target_drug,
                    severity=current_severity,
                    description=description,
                    management="See official FDA label for complete prescribing information."
                )
                
                # Optimization: If we found a MAJOR interaction, we can stop looking. 
                # It doesn't get worse than that.
                if current_severity == "major":
                    return best_match

    return best_match

def interaction_count() -> int:
    if _conn is None: return 0
    return _conn.execute("SELECT COUNT(*) FROM labels").fetchone()[0]
