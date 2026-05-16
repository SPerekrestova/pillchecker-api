"""Tests for the DDInter SQLite client."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from app.clients import ddinter_db as ddc


@pytest.fixture
def populated_db(tmp_path: Path, monkeypatch) -> Path:
    db = tmp_path / "ddinter.db"
    conn = sqlite3.connect(db)
    conn.executescript("""
        CREATE TABLE interactions (
            drug_a_id TEXT, drug_a_name TEXT,
            drug_b_id TEXT, drug_b_name TEXT,
            severity TEXT CHECK (severity IN ('Minor','Moderate','Major','Unknown')),
            atc_category TEXT,
            PRIMARY KEY (drug_a_id, drug_b_id)
        );
        CREATE TABLE rxnorm_to_ddinter (
            rxcui TEXT PRIMARY KEY, ddinter_id TEXT,
            canonical_name TEXT, match_method TEXT
        );
        CREATE VIRTUAL TABLE drug_names_fts USING fts5(ddinter_id UNINDEXED, name);
        CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
    """)
    conn.execute("INSERT INTO interactions VALUES ('DDInter1','Warfarin','DDInter2','Aspirin','Major','B')")
    conn.execute("INSERT INTO rxnorm_to_ddinter VALUES ('11289','DDInter1','Warfarin','exact')")
    conn.execute("INSERT INTO rxnorm_to_ddinter VALUES ('1191','DDInter2','Aspirin','exact')")
    conn.execute("INSERT INTO drug_names_fts (ddinter_id, name) VALUES ('DDInter1','Warfarin')")
    conn.execute("INSERT INTO drug_names_fts (ddinter_id, name) VALUES ('DDInter2','Aspirin')")
    conn.execute("INSERT INTO meta VALUES ('source_release', 'ddinter-test')")
    conn.commit()
    conn.close()
    monkeypatch.setattr(ddc, "DB_PATH", str(db))
    monkeypatch.setattr(ddc.client, "db_path", str(db))
    ddc.client._conn = None
    return db


async def test_lookup_by_rxcui_returns_lowercase_severity(populated_db):
    result = await ddc.client.lookup_by_rxcui("11289", "1191")
    assert result is not None
    assert result["severity"] == "major"
    assert result["source"] == "ddinter"


async def test_lookup_by_rxcui_handles_either_order(populated_db):
    a = await ddc.client.lookup_by_rxcui("11289", "1191")
    b = await ddc.client.lookup_by_rxcui("1191", "11289")
    assert a is not None and b is not None
    assert a["severity"] == b["severity"] == "major"


async def test_lookup_by_rxcui_miss_returns_none(populated_db):
    assert await ddc.client.lookup_by_rxcui("11289", "99999") is None


async def test_lookup_by_name_fts(populated_db):
    result = await ddc.client.lookup_by_name_fts("Warfarin", "Aspirin")
    assert result is not None
    assert result["severity"] == "major"


async def test_lookup_by_name_fts_phrase_escapes_special_chars(populated_db):
    assert await ddc.client.lookup_by_name_fts('War"farin', "Aspirin") is None


async def test_health_check_true_when_db_present(populated_db):
    assert await ddc.client.health_check() is True


async def test_health_check_false_when_db_missing(tmp_path, monkeypatch):
    missing = tmp_path / "missing.db"
    monkeypatch.setattr(ddc, "DB_PATH", str(missing))
    monkeypatch.setattr(ddc.client, "db_path", str(missing))
    ddc.client._conn = None
    assert await ddc.client.health_check() is False
