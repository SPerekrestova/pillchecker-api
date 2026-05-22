import json
from pathlib import Path

import pytest

from eval.io import bucket, dataset


def test_load_benchmark_records_from_local_json(tmp_path: Path):
    source = tmp_path / "benchmark.json"
    source.write_text(
        json.dumps([
            {
                "id": "case-1",
                "category": "single_ingredient",
                "ocr_text": "Ibuprofen 200 mg",
                "expected_names": ["ibuprofen"],
                "source_composition": "Ibuprofen",
            }
        ]),
        encoding="utf-8",
    )

    records, meta = dataset.load_benchmark_records(local_path=source)

    assert records[0]["id"] == "case-1"
    assert meta.repo_id is None
    assert meta.path == str(source)
    assert meta.revision is None


def test_load_benchmark_records_downloads_hf_revision(monkeypatch, tmp_path: Path):
    downloaded = tmp_path / "downloaded.json"
    downloaded.write_text(
        json.dumps([
            {
                "id": "case-2",
                "category": "dual_ingredient",
                "ocr_text": "Warfarin and ibuprofen",
                "expected_names": ["warfarin", "ibuprofen"],
                "source_composition": "Warfarin + Ibuprofen",
            }
        ]),
        encoding="utf-8",
    )
    calls = {}

    def fake_download(**kwargs):
        calls.update(kwargs)
        return str(downloaded)

    monkeypatch.setattr(dataset, "hf_hub_download", fake_download)
    monkeypatch.setenv("HF_TOKEN", "hf_test_token")

    records, meta = dataset.load_benchmark_records(revision="abc123")

    assert records[0]["id"] == "case-2"
    assert calls == {
        "repo_id": "SPerva/pillchecker-ner-benchmark",
        "repo_type": "dataset",
        "filename": "data/benchmark.json",
        "revision": "abc123",
        "token": "hf_test_token",
    }
    assert meta.revision == "abc123"


def test_load_benchmark_records_rejects_invalid_record(tmp_path: Path):
    source = tmp_path / "benchmark.json"
    source.write_text(
        json.dumps([
            {
                "id": "missing-fields",
                "category": "single_ingredient",
            }
        ]),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="ocr_text"):
        dataset.load_benchmark_records(local_path=source)


def test_write_run_artifacts_uses_immutable_files(tmp_path: Path):
    output_dir = tmp_path / "run"

    written = bucket.write_run_artifacts(
        output_dir=output_dir,
        results={"ner": {}, "linking": {}, "interactions": {}, "fp_taxonomy": {}},
        manifest={"run_id": "run-1"},
        summary_markdown="# Summary\n",
    )

    assert written == {
        "results": output_dir / "results.json",
        "manifest": output_dir / "manifest.json",
        "summary": output_dir / "summary.md",
    }
    assert json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))["run_id"] == "run-1"


def test_bucket_prefix_validation_rejects_root_results():
    with pytest.raises(ValueError, match="benchmark-results"):
        bucket.validate_output_prefix("results.json")


def test_upload_run_artifacts_writes_under_bucket_prefix(tmp_path: Path):
    output_dir = tmp_path / "run"
    written = bucket.write_run_artifacts(
        output_dir=output_dir,
        results={"ok": True},
        manifest={"run_id": "run-1"},
    )
    fs = FakeFilesystem()

    remote_paths = bucket.upload_run_artifacts(
        artifacts=written,
        output_prefix="benchmark-results/2026-05-19/run-1/",
        filesystem=fs,
    )

    assert remote_paths == [
        "hf://buckets/SPerva/pillchecker-experiments/benchmark-results/2026-05-19/run-1/results.json",
        "hf://buckets/SPerva/pillchecker-experiments/benchmark-results/2026-05-19/run-1/manifest.json",
    ]
    assert json.loads(fs.files[remote_paths[0]].decode("utf-8")) == {"ok": True}


class FakeFilesystem:
    def __init__(self):
        self.files = {}

    def exists(self, path):
        return path in self.files

    def open(self, path, mode):
        assert mode == "wb"
        return FakeWriter(self.files, path)


class FakeWriter:
    def __init__(self, files, path):
        self.files = files
        self.path = path
        self.data = bytearray()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc_type is None:
            self.files[self.path] = bytes(self.data)

    def write(self, data):
        self.data.extend(data)
