"""Tests for build_ddinter_db CLI subcommands."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import pytest

from scripts import build_ddinter_db


@pytest.fixture
def fake_csv(tmp_path: Path) -> Path:
    content = b"DDInterID_A,Drug_A,DDInterID_B,Drug_B,Level\nDDInter1,Aspirin,DDInter2,Warfarin,Major\n"
    csv = tmp_path / "ddinter_downloads_code_A.csv"
    csv.write_bytes(content)
    return csv


def test_compute_csv_sha256(fake_csv):
    expected = hashlib.sha256(fake_csv.read_bytes()).hexdigest()
    assert build_ddinter_db.compute_csv_sha256(fake_csv) == expected


def test_write_fetch_manifest(tmp_path: Path):
    files = {
        "ddinter_downloads_code_A.csv": "aaa111",
        "ddinter_downloads_code_B.csv": "bbb222",
    }
    manifest_path = tmp_path / "ddinter_manifest.json"
    manifest_sha = build_ddinter_db.write_fetch_manifest(manifest_path, files)
    payload = json.loads(manifest_path.read_text())
    assert payload["csv_sha256"] == files
    assert payload["manifest_sha256"] == manifest_sha
    # manifest_sha256 must be deterministic over the sorted file list
    re_sha = build_ddinter_db.compute_manifest_sha(files)
    assert re_sha == manifest_sha


def test_collect_unique_drug_names(tmp_path: Path):
    (tmp_path / "ddinter_downloads_code_A.csv").write_text(
        "DDInterID_A,Drug_A,DDInterID_B,Drug_B,Level\n"
        "DDInter1,Aspirin,DDInter2,Warfarin,Major\n"
        "DDInter2,Warfarin,DDInter3,Ibuprofen,Moderate\n"
    )
    (tmp_path / "ddinter_downloads_code_B.csv").write_text(
        "DDInterID_A,Drug_A,DDInterID_B,Drug_B,Level\n"
        "DDInter1,Aspirin,DDInter4,Heparin,Minor\n"
    )
    names = build_ddinter_db.collect_unique_drug_names(tmp_path)
    assert names == {
        "DDInter1": "Aspirin",
        "DDInter2": "Warfarin",
        "DDInter3": "Ibuprofen",
        "DDInter4": "Heparin",
    }


def test_crosswalk_reuse_from_previous_release(tmp_path: Path):
    prev = [
        {"rxcui": "1191", "ddinter_id": "DDInter1", "canonical_name": "Aspirin",
         "match_method": "exact", "source_name": "Aspirin"},
        {"rxcui": "11289", "ddinter_id": "DDInter2", "canonical_name": "Warfarin",
         "match_method": "approximate", "source_name": "Warfarin"},
    ]
    current = {"DDInter1": "Aspirin", "DDInter2": "Warfarin", "DDInter3": "Ibuprofen"}
    reused, todo = build_ddinter_db.reuse_crosswalk(prev, current)
    assert {r["ddinter_id"] for r in reused} == {"DDInter1", "DDInter2"}
    assert todo == {"DDInter3": "Ibuprofen"}


import sqlite3


def test_build_emits_valid_sqlite(tmp_path: Path):
    # CSV inputs
    (tmp_path / "ddinter_downloads_code_A.csv").write_text(
        "DDInterID_A,Drug_A,DDInterID_B,Drug_B,Level\n"
        "DDInter1,Aspirin,DDInter2,Warfarin,Major\n"
        "DDInter2,Warfarin,DDInter3,Ibuprofen,Moderate\n"
    )
    crosswalk = tmp_path / "crosswalk.json"
    crosswalk.write_text(json.dumps([
        {"rxcui": "1191", "ddinter_id": "DDInter1", "canonical_name": "Aspirin",
         "match_method": "exact", "source_name": "Aspirin"},
        {"rxcui": "11289", "ddinter_id": "DDInter2", "canonical_name": "Warfarin",
         "match_method": "approximate", "source_name": "Warfarin"},
    ]))
    manifest = tmp_path / "ddinter_manifest.json"
    manifest.write_text(json.dumps({
        "csv_sha256": {"ddinter_downloads_code_A.csv": "deadbeef"},
        "manifest_sha256": "abc123",
    }))

    db_path = tmp_path / "ddinter.db"
    build_ddinter_db.cmd_build(argparse.Namespace(
        csv_dir=str(tmp_path),
        crosswalk=str(crosswalk),
        manifest=str(manifest),
        out_path=str(db_path),
        tag="ddinter-test",
    ))

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = list(conn.execute("SELECT * FROM interactions ORDER BY drug_a_id, drug_b_id"))
        assert len(rows) == 2
        assert rows[0]["drug_a_id"] == "DDInter1"
        assert rows[0]["severity"] == "Major"
        # CHECK constraint on severity
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO interactions VALUES (?,?,?,?,?,?)",
                ("X", "X-Name", "Y", "Y-Name", "Critical", "A"),
            )
        # FTS5 table populated with deduped names
        fts = list(conn.execute("SELECT DISTINCT name FROM drug_names_fts ORDER BY name"))
        names = {r["name"].lower() for r in fts}
        assert {"aspirin", "warfarin", "ibuprofen"} <= names
        # Meta rows
        meta = dict(conn.execute("SELECT key, value FROM meta").fetchall())
        assert meta["source_release"] == "ddinter-test"
        assert "build_timestamp" in meta
        assert meta["csv_sha256_manifest"] == "abc123"


def _build_minimal_db(tmp_path: Path, *, rows: int = 2, severity_for_sentinel: str = "Major") -> Path:
    csv = tmp_path / "ddinter_downloads_code_A.csv"
    lines = ["DDInterID_A,Drug_A,DDInterID_B,Drug_B,Level"]
    # Sentinel
    lines.append(f"DDInter1,Warfarin,DDInter2,Aspirin,{severity_for_sentinel}")
    # Filler rows
    for i in range(rows - 1):
        lines.append(f"DDInter{i+10},Drug{i},DDInter{i+100},Other{i},Moderate")
    csv.write_text("\n".join(lines) + "\n")
    crosswalk = tmp_path / "crosswalk.json"
    crosswalk.write_text("[]")
    manifest = tmp_path / "ddinter_manifest.json"
    manifest.write_text(json.dumps({"csv_sha256": {}, "manifest_sha256": "x"}))
    db_path = tmp_path / "ddinter.db"
    build_ddinter_db.cmd_build(argparse.Namespace(
        csv_dir=str(tmp_path), crosswalk=str(crosswalk),
        manifest=str(manifest), out_path=str(db_path), tag="ddinter-test",
    ))
    return db_path


def test_sanity_check_passes_for_valid_db(tmp_path: Path):
    db = _build_minimal_db(tmp_path)
    # Override thresholds so we don't need 250k rows in a unit test.
    ok = build_ddinter_db.sanity_check(
        db, min_rows=2, sentinel=("Warfarin", "Aspirin"), expected_severity="Major",
        previous_size_bytes=None,
    )
    assert ok is True


def test_sanity_check_fails_if_sentinel_severity_wrong(tmp_path: Path):
    db = _build_minimal_db(tmp_path, severity_for_sentinel="Minor")
    ok = build_ddinter_db.sanity_check(
        db, min_rows=2, sentinel=("Warfarin", "Aspirin"), expected_severity="Major",
        previous_size_bytes=None,
    )
    assert ok is False


def test_sanity_check_fails_if_size_drift_too_large(tmp_path: Path):
    db = _build_minimal_db(tmp_path)
    actual_size = db.stat().st_size
    # Pretend previous release was 10x larger -> drift > 20%
    ok = build_ddinter_db.sanity_check(
        db, min_rows=2, sentinel=("Warfarin", "Aspirin"), expected_severity="Major",
        previous_size_bytes=actual_size * 10,
    )
    assert ok is False
