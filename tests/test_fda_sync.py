import pytest
from scripts.sync_fda_data import parse_record, infer_severity

def test_parse_record_valid():
    record = {
        "id": "spl-uuid-123",
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
    assert parsed["id"] == "spl-uuid-123"
    assert parsed["rxcui"] == "5640"
    assert parsed["generic_name"] == "IBUPROFEN"
    assert "aspirin" in parsed["interactions"].lower()

def test_parse_record_missing_rxcui_but_has_name():
    # RxCUI is now optional as long as we have names
    record = {
        "id": "spl-uuid-456",
        "openfda": {
            "generic_name": ["NEWDRUG"]
        }
    }
    parsed = parse_record(record)
    assert parsed is not None
    assert parsed["id"] == "spl-uuid-456"
    assert parsed["rxcui"] is None
    assert parsed["generic_name"] == "NEWDRUG"

def test_parse_record_invalid_no_id():
    record = {"openfda": {"generic_name": ["DRUG"]}}
    assert parse_record(record) is None

def test_parse_record_invalid_no_names():
    record = {"id": "123", "openfda": {}}
    assert parse_record(record) is None

def test_infer_severity():
    assert infer_severity("This drug is contraindicated with alcohol.") == "major"
    assert infer_severity("Use caution when driving.") == "moderate"
    assert infer_severity("No major side effects.") == "minor"
    assert infer_severity("") == "unknown"
