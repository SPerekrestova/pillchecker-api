import pytest
from scripts.sync_fda_data import parse_record, infer_severity

def test_parse_record_valid():
    record = {
        "openfda": {
            "rxcui": ["5640"],
            "generic_name": ["IBUPROFEN"],
            "brand_name": ["ADVIL"]
        },
        "drug_interactions": ["May interact with aspirin."],
        "contraindications": ["Do not use if allergic."],
        "effective_time": "20240101"
    }
    parsed = parse_record(record)
    assert parsed["rxcui"] == "5640"
    assert parsed["generic_name"] == "IBUPROFEN"
    assert "aspirin" in parsed["interactions"].lower()

def test_parse_record_missing_rxcui():
    record = {"openfda": {}}
    assert parse_record(record) is None

def test_infer_severity():
    assert infer_severity("This drug is contraindicated with alcohol.") == "major"
    assert infer_severity("Use caution when driving.") == "moderate"
    assert infer_severity("No major side effects.") == "minor"
    assert infer_severity("") == "unknown"
