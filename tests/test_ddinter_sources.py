"""Tests for the DDInter source URL + filename catalogue."""

from scripts import ddinter_sources


def test_csv_filenames_match_atc_categories():
    # DDInter publishes one CSV per ATC top-level category.
    expected = {
        "ddinter_downloads_code_A.csv",
        "ddinter_downloads_code_B.csv",
        "ddinter_downloads_code_D.csv",
        "ddinter_downloads_code_H.csv",
        "ddinter_downloads_code_L.csv",
        "ddinter_downloads_code_P.csv",
        "ddinter_downloads_code_R.csv",
        "ddinter_downloads_code_V.csv",
    }
    assert set(ddinter_sources.CSV_FILENAMES) == expected


def test_csv_url_for_filename():
    url = ddinter_sources.csv_url("ddinter_downloads_code_A.csv")
    assert url.startswith("https://ddinter2.scbdd.com/")
    assert url.endswith("ddinter_downloads_code_A.csv")


def test_atc_category_from_filename():
    assert ddinter_sources.atc_category("ddinter_downloads_code_A.csv") == "A"
    assert ddinter_sources.atc_category("ddinter_downloads_code_V.csv") == "V"


def test_atc_category_rejects_unknown_filename():
    import pytest
    with pytest.raises(ValueError):
        ddinter_sources.atc_category("garbage.csv")
