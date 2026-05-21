import argparse
from pathlib import Path

import pytest

from app.nlp import ner_model
from eval import run_benchmark


@pytest.mark.asyncio
async def test_run_benchmark_captures_trace_metrics_and_artifacts(monkeypatch, tmp_path: Path):
    records = [
        {
            "id": "case-1",
            "category": "dual_ingredient",
            "ocr_text": "Warfarin 5 mg and ibuprofen 200 mg",
            "expected_names": ["warfarin", "ibuprofen"],
            "source_composition": "Warfarin + Ibuprofen",
        }
    ]
    rxcuis = {"warfarin": "11289", "ibuprofen": "5640"}

    def fake_ocr(text):
        return text

    def fake_predict(_text):
        return [
            ner_model.Entity(text="warfarin", label="CHEM", score=0.96, start=0, end=8),
            ner_model.Entity(text="ibuprofen", label="CHEM", score=0.94, start=18, end=27),
        ]

    async def fake_get_rxcui(name):
        return rxcuis.get(name.casefold())

    async def fake_ddinter(rxcui_a, rxcui_b):
        if {rxcui_a, rxcui_b} == {"11289", "5640"}:
            return {
                "drug_a_id": "DDI00001",
                "drug_b_id": "DDI00002",
                "drug_a_name": "warfarin",
                "drug_b_name": "ibuprofen",
                "severity": "major",
                "atc_category": "B01 + M01",
            }
        return None

    async def no_fts(_name_a, _name_b):
        return None

    async def no_openfda(_drug_a, _drug_b):
        return None

    monkeypatch.setattr(run_benchmark.drug_analyzer, "ocr_clean", fake_ocr)
    monkeypatch.setattr(run_benchmark.drug_analyzer.ner_model, "predict", fake_predict)
    monkeypatch.setattr(run_benchmark.rxnorm_client, "get_rxcui", fake_get_rxcui)
    monkeypatch.setattr(run_benchmark.ddinter_db.client, "lookup_by_rxcui", fake_ddinter)
    monkeypatch.setattr(run_benchmark.ddinter_db.client, "lookup_by_name_fts", no_fts)
    monkeypatch.setattr(run_benchmark.openfda_client, "check_pair", no_openfda)

    output = await run_benchmark.run_benchmark(records, concurrency=1, seed_cases=None)

    prediction = output["predictions"][0]
    assert prediction["ocr_noise_level"] is None
    assert [drug["name"] for drug in prediction["drugs"]] == ["warfarin", "ibuprofen"]
    assert prediction["interactions"]["interactions"][0]["source"] == "ddinter"
    assert prediction["ner_entities"][0]["text"] == "warfarin"
    assert len(prediction["link_attempts"]) >= 2
    assert set(prediction["elapsed_ms"]) == {
        "ocr_clean",
        "ner",
        "rxnorm",
        "ddinter_rxcui",
        "ddinter_fts",
        "openfda",
        "severity",
        "analyze",
        "interactions",
        "total",
    }
    assert output["results"]["ner"]["strict"]["f1"] == 1.0
    assert output["results"]["interactions"]["accuracy"] is None

    artifacts = run_benchmark.write_local_outputs(
        output_dir=tmp_path,
        predictions=output["predictions"],
        results=output["results"],
        manifest={"run_id": "run-1"},
        errors=output["errors"],
    )
    assert (tmp_path / "predictions.jsonl").read_text(encoding="utf-8").count("\n") == 1
    assert (tmp_path / "errors.jsonl").read_text(encoding="utf-8") == ""
    assert artifacts["results"].name == "results.json"


def test_manifest_summary_contains_top_line_metric_scalars():
    results = {
        "ner": {"strict": {"f1": 0.8}, "lenient": {"f1": 0.9}},
        "linking": {"coverage": 0.75, "nil_rate": 0.1},
        "interactions": {
            "descriptive": {"total_pairs_checked": 4, "ddinter_hit_rate": 0.5},
            "seed_smoke": {"recall": 1.0, "false_alarm_rate": 0.0},
        },
        "fp_taxonomy": {"total_fp": 3},
    }

    scalars = run_benchmark.summary_metrics(results)

    assert scalars == {
        "ner_strict_f1": 0.8,
        "ner_lenient_f1": 0.9,
        "linking_coverage": 0.75,
        "linking_nil_rate": 0.1,
        "interactions_total_pairs_checked": 4,
        "interactions_ddinter_hit_rate": 0.5,
        "interactions_openfda_hit_rate": None,
        "interactions_unknown_rate": None,
        "seed_smoke_recall": 1.0,
        "seed_smoke_false_alarm_rate": 0.0,
        "fp_total": 3,
    }


@pytest.mark.asyncio
async def test_run_benchmark_records_per_record_errors(monkeypatch):
    async def broken_analyze(_text):
        raise RuntimeError("bad OCR")

    monkeypatch.setattr(run_benchmark.drug_analyzer, "analyze", broken_analyze)

    output = await run_benchmark.run_benchmark(
        [{
            "id": "case-error",
            "category": "single_ingredient",
            "ocr_text": "unreadable",
            "expected_names": ["ibuprofen"],
            "source_composition": "Ibuprofen",
        }],
        concurrency=1,
        seed_cases=None,
    )

    assert output["predictions"][0]["record_id"] == "case-error"
    assert output["predictions"][0]["drugs"] == []
    assert output["errors"] == [{
        "record_id": "case-error",
        "stage": "analyze",
        "error_class": "RuntimeError",
        "message": "bad OCR",
    }]


@pytest.mark.asyncio
async def test_run_benchmark_records_timeout_error(monkeypatch):
    async def hanging_analyze(_text):
        await run_benchmark.asyncio.sleep(0.05)
        return [{"name": "ibuprofen", "rxcui": "5640"}]

    monkeypatch.setattr(run_benchmark.drug_analyzer, "analyze", hanging_analyze)

    output = await run_benchmark.run_benchmark(
        [{
            "id": "case-timeout",
            "category": "single_ingredient",
            "ocr_text": "ibuprofen",
            "expected_names": ["ibuprofen"],
            "source_composition": "Ibuprofen",
        }],
        concurrency=1,
        seed_cases=None,
        record_timeout_seconds=0.01,
    )

    assert output["predictions"][0]["record_id"] == "case-timeout"
    assert output["predictions"][0]["drugs"] == []
    assert output["errors"] == [{
        "record_id": "case-timeout",
        "stage": "record_timeout",
        "error_class": "TimeoutError",
        "message": "record exceeded 0.01s timeout",
    }]


def test_manifest_includes_ddinter_release_metadata():
    manifest = run_benchmark.build_manifest(
        run_id="tier1-test",
        dataset_revision="abc123",
        dataset_path="data/benchmark.json",
        command="python -m eval.run_benchmark",
        sample_size=1,
        output_prefix="benchmark-results/2026-05-21/tier1-test/",
        results={"ner": {}, "linking": {}, "interactions": {}, "fp_taxonomy": {}},
        random_seed=None,
        ddinter_db={
            "repo": "SPerekrestova/pillchecker-api",
            "tag": "ddinter-2026-05-16",
            "asset": "ddinter.db",
            "sha256": "abc123",
        },
    )

    assert manifest["ddinter_db"] == {
        "repo": "SPerekrestova/pillchecker-api",
        "tag": "ddinter-2026-05-16",
        "asset": "ddinter.db",
        "sha256": "abc123",
    }


@pytest.mark.asyncio
async def test_ensure_ddinter_db_downloads_from_github_release(monkeypatch, tmp_path: Path):
    checks = iter([False, True])
    downloads = []

    async def fake_health_check():
        return next(checks)

    def fake_download_release_asset(**kwargs):
        downloads.append(kwargs)
        kwargs["output"].write_bytes(b"sqlite")

    monkeypatch.setattr(run_benchmark.ddinter_db.client, "health_check", fake_health_check)
    monkeypatch.setattr(run_benchmark.download_interaction_db, "download_release_asset", fake_download_release_asset)

    db_path = tmp_path / "ddinter.db"
    args = argparse.Namespace(
        ddinter_db_output=str(db_path),
        ddinter_db_repo="SPerva/ddinter-release",
        ddinter_db_tag="v1",
        ddinter_db_asset="ddinter.db",
        ddinter_db_sha256="abc123",
        no_ddinter_db_download=False,
    )

    assert await run_benchmark.ensure_ddinter_db(args) is True
    assert downloads == [{
        "repo": "SPerva/ddinter-release",
        "tag": "v1",
        "output": db_path,
        "asset": "ddinter.db",
        "token": None,
        "sha256": "abc123",
    }]
    assert run_benchmark.ddinter_db.client.db_path == str(db_path)


@pytest.mark.asyncio
async def test_ensure_ddinter_db_fails_without_release_source(monkeypatch):
    async def fake_health_check():
        return False

    monkeypatch.setattr(run_benchmark.ddinter_db.client, "health_check", fake_health_check)
    monkeypatch.delenv("INTERACTION_DB_REPO", raising=False)
    monkeypatch.delenv("INTERACTION_DB_TAG", raising=False)
    args = argparse.Namespace(
        ddinter_db_output=None,
        ddinter_db_repo=None,
        ddinter_db_tag=None,
        ddinter_db_asset="ddinter.db",
        ddinter_db_sha256=None,
        no_ddinter_db_download=False,
    )

    assert await run_benchmark.ensure_ddinter_db(args) is False
