import pytest

from eval.metrics import fp_taxonomy


@pytest.mark.asyncio
async def test_fp_taxonomy_classifies_core_categories_and_caches_brand_lookup():
    calls = []

    async def resolver(rxcui):
        calls.append(rxcui)
        return {"tty": "BN"} if rxcui == "brand-rxcui" else {"tty": "IN"}

    predictions = [{
        "record_id": "1",
        "drugs": [
            {"name": "200 mg"},
            {"name": "tablet"},
            {"name": "Acme Pharma"},
            {"name": "sodium"},
            {"name": "glycine"},
            {"name": "Advil", "rxcui": "brand-rxcui"},
            {"name": "Advil", "rxcui": "brand-rxcui"},
            {"name": "mystery"},
        ],
    }]
    dataset = [{"id": "1", "expected_names": ["ibuprofen"]}]

    result = await fp_taxonomy.compute(predictions, dataset, details_resolver=resolver)

    assert result["numeric"]["count"] == 1
    assert result["form"]["count"] == 1
    assert result["mfg"]["count"] == 1
    assert result["salt"]["count"] == 1
    assert result["excipient"]["count"] == 1
    assert result["brand"]["count"] == 2
    assert result["other"]["count"] == 1
    assert calls == ["brand-rxcui"]


@pytest.mark.asyncio
async def test_fp_taxonomy_ignores_lenient_expected_match():
    predictions = [{"record_id": "1", "drugs": [{"name": "amoxicillin trihydrate"}]}]
    dataset = [{"id": "1", "expected_names": ["amoxicillin"]}]

    result = await fp_taxonomy.compute(predictions, dataset)

    assert result["total_fp"] == 0
