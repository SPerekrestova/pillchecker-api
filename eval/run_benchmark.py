#!/usr/bin/env python3
"""Run the Tier 1 benchmark and write manifest-backed artifacts.

This benchmark monkey-patches imported runtime call sites in-process to collect
timings and traces. Run it as a single-purpose script, not inside a production
server process.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import os
import subprocess
import sys
import time
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from functools import wraps
from pathlib import Path
from uuid import uuid4

from app.clients import ddinter_db, openfda_client, rxnorm_client
from app.nlp import ner_model, severity_classifier
from app.services import drug_analyzer, interaction_checker
from eval.io.bucket import upload_run_artifacts, validate_output_prefix, write_run_artifacts
from eval.io.dataset import DEFAULT_DATASET_REPO, load_benchmark_records
from eval.metrics import fp_taxonomy
from eval.metrics import interactions as interaction_metrics
from eval.metrics import linking as linking_metrics
from eval.metrics import ner as ner_metrics
from scripts import download_interaction_db

ELAPSED_KEYS = (
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
)
DEFAULT_SEED_CASES = Path(__file__).with_name("interaction_seed_cases.json")

active_benchmark_trace: ContextVar["BenchmarkTrace | None"] = ContextVar(
    "active_benchmark_trace",
    default=None,
)


@dataclass
class BenchmarkTrace:
    elapsed_ms: dict[str, float] = field(default_factory=lambda: {key: 0.0 for key in ELAPSED_KEYS})
    link_attempts: list[dict] = field(default_factory=list)
    ner_entities: list[dict] = field(default_factory=list)

    def add_elapsed(self, key: str, seconds: float) -> None:
        self.elapsed_ms[key] = round(self.elapsed_ms.get(key, 0.0) + seconds * 1000, 3)


@contextlib.contextmanager
def install_benchmark_instrumentation():
    """Wrap runtime dependencies and restore them when the benchmark exits."""
    originals = []

    def patch(target, attr, value) -> None:
        originals.append((target, attr, getattr(target, attr)))
        setattr(target, attr, value)

    patch(drug_analyzer, "ocr_clean", _sync_wrapper(drug_analyzer.ocr_clean, "ocr_clean"))
    patch(drug_analyzer.ner_model, "predict", _sync_wrapper(
        drug_analyzer.ner_model.predict,
        "ner",
        _record_ner_entities,
    ))
    patch(rxnorm_client, "get_rxcui", _async_wrapper(
        rxnorm_client.get_rxcui,
        "rxnorm",
        _record_link_attempt,
    ))
    patch(ddinter_db.client, "lookup_by_rxcui", _async_wrapper(
        ddinter_db.client.lookup_by_rxcui,
        "ddinter_rxcui",
    ))
    patch(ddinter_db.client, "lookup_by_name_fts", _async_wrapper(
        ddinter_db.client.lookup_by_name_fts,
        "ddinter_fts",
    ))
    patch(openfda_client, "check_pair", _async_wrapper(openfda_client.check_pair, "openfda"))
    patch(severity_classifier, "classify", _sync_wrapper(severity_classifier.classify, "severity"))
    patch(interaction_checker, "_format_openfda", _async_wrapper(interaction_checker._format_openfda, "severity"))

    try:
        yield
    finally:
        for target, attr, original in reversed(originals):
            setattr(target, attr, original)


def _sync_wrapper(original, key: str, recorder=None):
    @wraps(original)
    def wrapper(*args, **kwargs):
        trace = active_benchmark_trace.get()
        start = time.perf_counter()
        result = None
        try:
            result = original(*args, **kwargs)
            return result
        finally:
            if trace is not None:
                trace.add_elapsed(key, time.perf_counter() - start)
                if recorder is not None and result is not None:
                    recorder(trace, args, result)

    return wrapper


def _async_wrapper(original, key: str, recorder=None):
    @wraps(original)
    async def wrapper(*args, **kwargs):
        trace = active_benchmark_trace.get()
        start = time.perf_counter()
        result = None
        try:
            result = await original(*args, **kwargs)
            return result
        finally:
            if trace is not None:
                trace.add_elapsed(key, time.perf_counter() - start)
                if recorder is not None:
                    recorder(trace, args, result)

    return wrapper


def _record_ner_entities(trace: BenchmarkTrace, _args: tuple, entities: list) -> None:
    trace.ner_entities = [
        {
            "text": entity.text,
            "label": entity.label,
            "score": float(entity.score),
            "start": int(entity.start),
            "end": int(entity.end),
        }
        for entity in entities
    ]


def _record_link_attempt(trace: BenchmarkTrace, args: tuple, rxcui: str | None) -> None:
    trace.link_attempts.append({
        "name": args[0] if args else None,
        "rxcui": rxcui,
        "method": "rxnorm_exact",
    })


async def run_benchmark(
    records: list[dict],
    *,
    concurrency: int,
    seed_cases: dict | None,
) -> dict:
    """Run the benchmark over already-loaded records."""
    if concurrency < 1:
        raise ValueError("concurrency must be at least 1")
    semaphore = asyncio.Semaphore(concurrency)
    with install_benchmark_instrumentation():
        record_results = await asyncio.gather(*[
            _run_one(record, semaphore)
            for record in records
        ])
        predictions = [item[0] for item in record_results]
        errors = [item[1] for item in record_results if item[1] is not None]
        seed_results = None
        if seed_cases is not None:
            seed_results = await interaction_metrics.run_seed_smoke(seed_cases, interaction_checker.check)

    results = {
        "ner": ner_metrics.compute(predictions, records),
        "linking": linking_metrics.compute(predictions, records),
        "interactions": interaction_metrics.compute(
            predictions,
            records,
            seed_cases=seed_cases,
            seed_results=seed_results,
        ),
        "fp_taxonomy": await fp_taxonomy.compute(predictions, records),
    }
    return {
        "predictions": predictions,
        "results": results,
        "seed_results": seed_results,
        "errors": errors,
    }


async def _run_one(record: dict, semaphore: asyncio.Semaphore) -> tuple[dict, dict | None]:
    async with semaphore:
        trace = BenchmarkTrace()
        token = active_benchmark_trace.set(trace)
        total_start = time.perf_counter()
        drugs = []
        interactions_response = None
        error = None
        try:
            analyze_start = time.perf_counter()
            drugs = await drug_analyzer.analyze(str(record["ocr_text"]))
            trace.add_elapsed("analyze", time.perf_counter() - analyze_start)
        except Exception as exc:
            trace.add_elapsed("analyze", time.perf_counter() - analyze_start)
            error = _error_record(record, "analyze", exc)
        else:
            interaction_start = time.perf_counter()
            try:
                interactions_response = await interaction_checker.check([drug["name"] for drug in drugs])
                trace.add_elapsed("interactions", time.perf_counter() - interaction_start)
            except Exception as exc:
                trace.add_elapsed("interactions", time.perf_counter() - interaction_start)
                error = _error_record(record, "interactions", exc)
        finally:
            trace.add_elapsed("total", time.perf_counter() - total_start)
            active_benchmark_trace.reset(token)

        return {
            "record_id": str(record.get("id", "")),
            "category": record.get("category"),
            "ocr_noise_level": record.get("ocr_noise_level"),
            "drugs": drugs,
            "interactions": interactions_response,
            "ner_entities": trace.ner_entities,
            "link_attempts": trace.link_attempts,
            "elapsed_ms": {key: trace.elapsed_ms.get(key, 0.0) for key in ELAPSED_KEYS},
        }, error


def _error_record(record: dict, stage: str, exc: Exception) -> dict:
    return {
        "record_id": str(record.get("id", "")),
        "stage": stage,
        "error_class": exc.__class__.__name__,
        "message": str(exc),
    }


def load_seed_cases(path: str | Path | None = DEFAULT_SEED_CASES) -> dict | None:
    if path is None:
        return None
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def write_local_outputs(
    *,
    output_dir: str | Path,
    predictions: list[dict],
    results: dict,
    manifest: dict,
    errors: list[dict] | None = None,
) -> dict[str, Path]:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    predictions_path = output_path / "predictions.jsonl"
    with open(predictions_path, "w", encoding="utf-8") as handle:
        for prediction in predictions:
            json.dump(prediction, handle, ensure_ascii=False, sort_keys=True)
            handle.write("\n")
    errors_path = output_path / "errors.jsonl"
    with open(errors_path, "w", encoding="utf-8") as handle:
        for error in errors or []:
            json.dump(error, handle, ensure_ascii=False, sort_keys=True)
            handle.write("\n")
    artifacts = write_run_artifacts(
        output_dir=output_path,
        results=results,
        manifest=manifest,
        summary_markdown=summary_markdown(results),
    )
    artifacts["predictions"] = predictions_path
    artifacts["errors"] = errors_path
    return artifacts


def summary_metrics(results: dict) -> dict:
    return {
        "ner_strict_f1": results.get("ner", {}).get("strict", {}).get("f1"),
        "ner_lenient_f1": results.get("ner", {}).get("lenient", {}).get("f1"),
        "linking_coverage": results.get("linking", {}).get("coverage"),
        "linking_nil_rate": results.get("linking", {}).get("nil_rate"),
        "interactions_total_pairs_checked": results.get("interactions", {}).get("descriptive", {}).get("total_pairs_checked"),
        "interactions_ddinter_hit_rate": results.get("interactions", {}).get("descriptive", {}).get("ddinter_hit_rate"),
        "interactions_openfda_hit_rate": results.get("interactions", {}).get("descriptive", {}).get("openfda_hit_rate"),
        "interactions_unknown_rate": results.get("interactions", {}).get("descriptive", {}).get("unknown_rate"),
        "seed_smoke_recall": results.get("interactions", {}).get("seed_smoke", {}).get("recall"),
        "seed_smoke_false_alarm_rate": results.get("interactions", {}).get("seed_smoke", {}).get("false_alarm_rate"),
        "fp_total": results.get("fp_taxonomy", {}).get("total_fp"),
    }


def summary_markdown(results: dict) -> str:
    metrics = summary_metrics(results)
    lines = ["# PillChecker benchmark summary", ""]
    for key, value in metrics.items():
        lines.append(f"- `{key}`: {value}")
    lines.append("")
    return "\n".join(lines)


def build_manifest(
    *,
    run_id: str,
    dataset_revision: str,
    dataset_path: str,
    command: str,
    sample_size: int,
    output_prefix: str,
    results: dict,
    random_seed: int | str | None = None,
) -> dict:
    return {
        "run_id": run_id,
        "timestamp_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "git_commit": _git_commit(),
        "dataset_repo": DEFAULT_DATASET_REPO,
        "dataset_revision": dataset_revision,
        "dataset_path": dataset_path,
        "bucket_output_prefix": output_prefix,
        "command": command,
        "model_ids": {
            "ner": ner_model.MODEL_ID,
            "severity": severity_classifier.MODEL_ID,
            "ddinter": "DDInter 2.0",
            "openfda": "OpenFDA drug label API",
        },
        "thresholds": {
            "ner_default": 0.85,
            "ner_sweep": "0.50:1.00:0.05",
            "severity_min_confidence": 0.7,
            "rxnorm_fallback_min_score": 10.0,
        },
        "sample_size": sample_size,
        "random_seed": random_seed,
        "metrics": summary_metrics(results),
    }


def _git_commit() -> str:
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        )
    except Exception:
        return "0" * 7
    return completed.stdout.strip()


def _run_id() -> str:
    return f"tier1-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-{uuid4().hex[:8]}"


def _output_prefix(run_id: str) -> str:
    return validate_output_prefix(f"benchmark-results/{date.today().isoformat()}/{run_id}/")


async def _main_async(args: argparse.Namespace) -> int:
    if not args.local_dataset and not args.revision:
        print("--revision is required unless --local-dataset is provided", file=sys.stderr)
        return 2
    try:
        records, meta = load_benchmark_records(
            local_path=args.local_dataset,
            revision=args.revision,
        )
    except Exception as exc:
        print(f"Failed to load benchmark records: {exc}", file=sys.stderr)
        return 2

    if args.limit is not None:
        records = records[:args.limit]

    if not await ensure_ddinter_db(args):
        print("DDInter DB is missing or unreadable", file=sys.stderr)
        return 3
    if not ner_model.is_loaded():
        try:
            ner_model.load_model()
        except Exception as exc:
            print(f"Failed to load NER model: {exc}", file=sys.stderr)
            return 4

    seed_cases = load_seed_cases(args.seed_cases)
    output = await run_benchmark(records, concurrency=args.concurrency, seed_cases=seed_cases)
    run_id = args.run_id or _run_id()
    output_prefix = validate_output_prefix(args.output_prefix) if args.output_prefix else _output_prefix(run_id)
    output_dir = Path(args.output_dir) if args.output_dir else Path("benchmark-results") / run_id
    manifest = build_manifest(
        run_id=run_id,
        dataset_revision=args.revision or "local",
        dataset_path=meta.path,
        command=" ".join(sys.argv),
        sample_size=len(records),
        output_prefix=output_prefix,
        results=output["results"],
        random_seed=args.random_seed,
    )
    artifacts = write_local_outputs(
        output_dir=output_dir,
        predictions=output["predictions"],
        results=output["results"],
        manifest=manifest,
        errors=output["errors"],
    )
    if not args.local_only:
        upload_run_artifacts(artifacts=artifacts, output_prefix=output_prefix)
    print(f"Wrote benchmark artifacts to {output_dir}")
    return 0


async def ensure_ddinter_db(args: argparse.Namespace) -> bool:
    """Ensure the local DDInter DB exists, optionally from the GitHub release source."""
    if args.ddinter_db_output:
        ddinter_db.DB_PATH = args.ddinter_db_output
        ddinter_db.client.db_path = args.ddinter_db_output
        ddinter_db.client._conn = None

    if await ddinter_db.client.health_check():
        return True

    repo = args.ddinter_db_repo or os.environ.get("INTERACTION_DB_REPO")
    tag = args.ddinter_db_tag or os.environ.get("INTERACTION_DB_TAG")
    if args.no_ddinter_db_download or not repo or not tag:
        return False

    output = Path(args.ddinter_db_output or ddinter_db.client.db_path)
    try:
        download_interaction_db.download_release_asset(
            repo=repo,
            tag=tag,
            output=output,
            asset=args.ddinter_db_asset,
            token=os.environ.get("GITHUB_TOKEN"),
            sha256=args.ddinter_db_sha256 or os.environ.get("INTERACTION_DB_SHA256"),
        )
    except Exception as exc:
        print(
            f"Failed to download DDInter DB from GitHub release {repo}@{tag}: {exc}",
            file=sys.stderr,
        )
        return False

    ddinter_db.DB_PATH = str(output)
    ddinter_db.client.db_path = str(output)
    ddinter_db.client._conn = None
    return await ddinter_db.client.health_check()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--revision", default=None, help="Pinned HF dataset revision.")
    parser.add_argument("--local-dataset", default=None, help="Local benchmark JSON path for smoke runs.")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--concurrency", type=int, default=8)
    parser.add_argument("--local-only", action="store_true", help="Do not upload to the HF experiments bucket.")
    parser.add_argument("--output-dir", default=None)
    parser.add_argument("--output-prefix", default=None)
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--random-seed", default=None)
    parser.add_argument("--seed-cases", default=str(DEFAULT_SEED_CASES))
    parser.add_argument(
        "--ddinter-db-repo",
        default=None,
        help="GitHub repo that publishes ddinter.db; defaults to INTERACTION_DB_REPO.",
    )
    parser.add_argument(
        "--ddinter-db-tag",
        default=None,
        help="GitHub release tag for ddinter.db; defaults to INTERACTION_DB_TAG.",
    )
    parser.add_argument("--ddinter-db-asset", default=download_interaction_db.DEFAULT_ASSET)
    parser.add_argument(
        "--ddinter-db-output",
        default=None,
        help="Local DDInter DB path; defaults to app client INTERACTION_DB_PATH.",
    )
    parser.add_argument(
        "--ddinter-db-sha256",
        default=None,
        help="Expected DDInter DB SHA256; defaults to INTERACTION_DB_SHA256.",
    )
    parser.add_argument(
        "--no-ddinter-db-download",
        action="store_true",
        help="Fail if the local DDInter DB is missing instead of using the GitHub release source.",
    )
    args = parser.parse_args()
    return asyncio.run(_main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
