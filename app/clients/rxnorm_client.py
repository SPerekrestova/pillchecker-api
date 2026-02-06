"""Async client for the NLM RxNorm REST API.

Free, no API key required. Rate limit: 20 req/sec.
Docs: https://lhncbc.nlm.nih.gov/RxNav/APIs/RxNormAPIs.html
"""

import time
from dataclasses import dataclass

import httpx

RXNORM_BASE = "https://rxnav.nlm.nih.gov/REST"

# Simple TTL cache: {key: (value, expiry_timestamp)}
_cache: dict[str, tuple[object, float]] = {}
_CACHE_TTL = 86400  # 24 hours


def _cache_get(key: str) -> object | None:
    if key in _cache:
        value, expiry = _cache[key]
        if time.time() < expiry:
            return value
        del _cache[key]
    return None


def _cache_set(key: str, value: object) -> None:
    _cache[key] = (value, time.time() + _CACHE_TTL)


@dataclass
class DrugInfo:
    rxcui: str
    name: str
    synonym: str | None = None
    tty: str | None = None  # Term type (IN=ingredient, BN=brand name, etc.)


async def get_rxcui(name: str) -> str | None:
    """Get the RxCUI for an exact drug name.

    Returns the RxCUI string or None if not found.
    """
    cache_key = f"rxcui:{name.lower()}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{RXNORM_BASE}/rxcui.json",
            params={"name": name, "search": 2},
        )
        resp.raise_for_status()
        data = resp.json()

    group = data.get("idGroup", {})
    rxcui_list = group.get("rxnormId")
    result = rxcui_list[0] if rxcui_list else None
    _cache_set(cache_key, result)
    return result


async def approximate_term(term: str) -> list[DrugInfo]:
    """Fuzzy search for a drug name. Good for brand names and typos.

    Returns a list of DrugInfo candidates, best match first.
    """
    cache_key = f"approx:{term.lower()}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{RXNORM_BASE}/approximateTerm.json",
            params={"term": term, "maxEntries": 5},
        )
        resp.raise_for_status()
        data = resp.json()

    candidates = data.get("approximateGroup", {}).get("candidate", [])
    results = []
    for c in candidates:
        results.append(DrugInfo(
            rxcui=c.get("rxcui", ""),
            name=c.get("name", ""),
        ))
    _cache_set(cache_key, results)
    return results


async def search_by_name(name: str) -> list[DrugInfo]:
    """Search RxNorm drugs by name. Returns matching concepts."""
    cache_key = f"search:{name.lower()}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{RXNORM_BASE}/drugs.json",
            params={"name": name},
        )
        resp.raise_for_status()
        data = resp.json()

    groups = data.get("drugGroup", {}).get("conceptGroup", [])
    results = []
    for group in groups:
        for prop in group.get("conceptProperties", []):
            results.append(DrugInfo(
                rxcui=prop.get("rxcui", ""),
                name=prop.get("name", ""),
                synonym=prop.get("synonym", None),
                tty=prop.get("tty", None),
            ))
    _cache_set(cache_key, results)
    return results


async def get_drug_details(rxcui: str) -> dict | None:
    """Get full details for a drug by its RxCUI.

    Returns the raw properties dict from RxNorm.
    """
    cache_key = f"details:{rxcui}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{RXNORM_BASE}/rxcui/{rxcui}/properties.json",
        )
        resp.raise_for_status()
        data = resp.json()

    props = data.get("properties", None)
    _cache_set(cache_key, props)
    return props
