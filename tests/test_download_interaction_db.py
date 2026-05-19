from pathlib import Path

import pytest

from scripts import download_interaction_db


def test_verify_sha256_accepts_matching_file(tmp_path: Path):
    db = tmp_path / "ddinter.db"
    db.write_bytes(b"ddinter")

    download_interaction_db._verify_sha256(
        db,
        "ac1bec8404c800c19b1bd812c3d4aa821b0211231b98f37dc8f081df488612bb",
    )


def test_verify_sha256_rejects_mismatch(tmp_path: Path):
    db = tmp_path / "ddinter.db"
    db.write_bytes(b"ddinter")

    with pytest.raises(RuntimeError, match="Checksum mismatch"):
        download_interaction_db._verify_sha256(db, "0" * 64)
