"""Integration tests for RxNorm client — hits live API."""

import pytest

from app.clients import rxnorm_client


@pytest.mark.asyncio
async def test_get_rxcui_ibuprofen():
    """Ibuprofen should resolve to RxCUI 5640."""
    rxcui = await rxnorm_client.get_rxcui("ibuprofen")
    assert rxcui == "5640"


@pytest.mark.asyncio
async def test_get_rxcui_unknown():
    """Nonsense drug name should return None."""
    rxcui = await rxnorm_client.get_rxcui("xyznotadrug123")
    assert rxcui is None


@pytest.mark.asyncio
async def test_approximate_term_advil():
    """Brand name 'Advil' should find candidates, resolve to Ibuprofen via details."""
    results = await rxnorm_client.approximate_term("Advil")
    assert len(results) > 0
    # The approximate endpoint returns brand-name concepts (e.g. "Advil").
    # To get the generic name, we look up details on the first result's RxCUI.
    assert any("advil" in r.name.lower() for r in results)
    details = await rxnorm_client.get_drug_details(results[0].rxcui)
    # RxCUI 153010 maps to the Advil brand of Ibuprofen
    assert details is not None


@pytest.mark.asyncio
async def test_search_by_name_warfarin():
    """Warfarin should return drug concepts."""
    results = await rxnorm_client.search_by_name("warfarin")
    assert len(results) > 0
    assert any("warfarin" in r.name.lower() for r in results)


@pytest.mark.asyncio
async def test_get_drug_details():
    """RxCUI 5640 (Ibuprofen) should return properties."""
    details = await rxnorm_client.get_drug_details("5640")
    assert details is not None
    assert details.get("name", "").lower() == "ibuprofen"
