"""OpenFDA fallback client for drug interaction checking.

Used when DrugBank returns an empty interaction list for a drug.
Fetches the FDA drug label and searches its drug_interactions text
for a mention of the target drug.

No API key required. Rate limit: 240 req/min.
Docs: https://open.fda.gov/apis/drug/label/
"""

import logging
import re
import time
from urllib.parse import quote

import httpx

logger = logging.getLogger(__name__)

OPENFDA_BASE = "https://api.fda.gov/drug/label.json"

# Sentinel to distinguish cache miss from cached empty string
_CACHE_MISS = object()

# Simple TTL cache: {key: (value, expiry_timestamp)}
_cache: dict[str, tuple[object, float]] = {}
_CACHE_TTL = 86400  # 24 hours


def _cache_get(key: str) -> object:
    """Return cached value or _CACHE_MISS sentinel."""
    if key in _cache:
        value, expiry = _cache[key]
        if time.time() < expiry:
            return value
        del _cache[key]
    return _CACHE_MISS


def _cache_set(key: str, value: object) -> None:
    _cache[key] = (value, time.time() + _CACHE_TTL)


async def _fetch_label_text(drug_name: str) -> str | None:
    """Fetch and cache the drug_interactions text from an FDA label.

    Returns:
        Joined drug_interactions text (may be empty string if field absent),
        or None if the drug has no FDA label or a network error occurred.
    """
    cache_key = f"openfda:label:{drug_name.lower()}"
    cached = _cache_get(cache_key)
    if cached is not _CACHE_MISS:
        return cached  # type: ignore[return-value]

    # Phrase-quote the name for OpenFDA's Elasticsearch syntax
    quoted_name = f'"{quote(drug_name)}"'
    url = f"{OPENFDA_BASE}?search=openfda.generic_name:{quoted_name}&limit=1"

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, timeout=10.0)
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:
        logger.warning("OpenFDA request failed for %s: %s", drug_name, exc)
        return None

    results = data.get("results", [])
    if not results:
        _cache_set(cache_key, None)
        return None

    paragraphs = results[0].get("drug_interactions", [])
    text = " ".join(paragraphs)  # array of strings → single searchable string
    _cache_set(cache_key, text)
    return text


async def check_pair(drug_a: str, drug_b: str) -> dict | None:
    """Check if drug_b is mentioned in drug_a's FDA label interactions section.

    Returns:
        {"drug": drug_b, "description": <extracted context>} if found,
        None if not found or label unavailable.
        description is always non-empty when a dict is returned.
    """
    text = await _fetch_label_text(drug_a)
    if not text:
        return None

    pattern = re.compile(rf'\b{re.escape(drug_b)}\b', re.IGNORECASE)
    if not pattern.search(text):
        return None

    # Extract up to 2 sentences containing the match
    sentences = re.split(r'\. (?=[A-Z])', text)
    matching = [s.strip() for s in sentences if pattern.search(s)]
    extracted = ". ".join(matching[:2])
    description = extracted or f"Interaction with {drug_b} reported in FDA labeling."

    return {"drug": drug_b, "description": description}
