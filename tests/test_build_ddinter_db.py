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
