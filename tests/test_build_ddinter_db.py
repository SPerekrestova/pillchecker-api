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
