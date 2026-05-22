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
from eval.metrics import pipeline as pipeline_metrics
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
LEAF_ELAPSED_KEYS = (
    "ocr_clean",
    "ner",
    "rxnorm",
    "ddinter_rxcui",
    "ddinter_fts",
    "openfda",
    "severity",
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
    rxnorm_attempts: list[dict] = field(default_factory=list)
    interaction_attempts: list[dict] = field(default_factory=list)
    ner_entities: list[dict] = field(default_factory=list)
    pipeline_errors: list[dict] = field(default_factory=list)
    error_signatures: set[tuple[str, str]] = field(default_factory=set)
    phase: str | None = None
    active_interaction_attempt: dict | None = None

    def add_elapsed(self, key: str, seconds: float) -> None:
        self.elapsed_ms[key] = round(self.elapsed_ms.get(key, 0.0) + seconds * 1000, 3)

    def record_error(self, stage: str, exc: Exception) -> None:
        signature = (exc.__class__.__name__, str(exc))
        if signature in self.error_signatures:
            for item in self.pipeline_errors:
                if item.get("error_class") == signature[0] and item.get("message") == signature[1]:
                    stages = item.setdefault("stages", [item.get("stage")])
                    if stage not in stages:
                        stages.append(stage)
                    break
            return
        self.error_signatures.add(signature)
        self.pipeline_errors.append({
            "stage": stage,
            "stages": [stage],
            "error_class": exc.__class__.__name__,
            "message": str(exc),
        })

    def component_timings(self) -> dict[str, float]:
        timings = {key: self.elapsed_ms.get(key, 0.0) for key in ELAPSED_KEYS}
        timings["critical_path"] = round(sum(timings.get(key, 0.0) for key in LEAF_ELAPSED_KEYS), 3)
        timings["slowest_component_ms"] = round(max(timings.get(key, 0.0) for key in LEAF_ELAPSED_KEYS), 3)
        return timings

    def slowest_component(self) -> str:
        return max(LEAF_ELAPSED_KEYS, key=lambda key: self.elapsed_ms.get(key, 0.0))


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
        _record_rxnorm_attempt("get_rxcui"),
    ))
    patch(rxnorm_client, "approximate_term", _async_wrapper(
        rxnorm_client.approximate_term,
        "rxnorm",
        _record_rxnorm_attempt("approximate_term"),
    ))
    patch(rxnorm_client, "search_by_name", _async_wrapper(
        rxnorm_client.search_by_name,
        "rxnorm",
        _record_rxnorm_attempt("search_by_name"),
    ))
    patch(rxnorm_client, "get_drug_details", _async_wrapper(
        rxnorm_client.get_drug_details,
        "rxnorm",
        _record_rxnorm_attempt("get_drug_details"),
    ))
    patch(ddinter_db.client, "lookup_by_rxcui", _async_wrapper(
        ddinter_db.client.lookup_by_rxcui,
        "ddinter_rxcui",
        _record_interaction_component("ddinter_rxcui"),
    ))
    patch(ddinter_db.client, "lookup_by_name_fts", _async_wrapper(
        ddinter_db.client.lookup_by_name_fts,
        "ddinter_fts",
        _record_interaction_component("ddinter_fts"),
    ))
    patch(openfda_client, "check_pair", _async_wrapper(
        openfda_client.check_pair,
        "openfda",
        _record_interaction_component("openfda"),
    ))
    patch(severity_classifier, "classify", _sync_wrapper(severity_classifier.classify, "severity"))
    patch(interaction_checker, "_format_openfda", _async_wrapper(interaction_checker._format_openfda, "severity"))
    patch(interaction_checker, "_resolve_pair", _resolve_pair_wrapper(interaction_checker._resolve_pair))

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
        error = None
        try:
            result = original(*args, **kwargs)
            return result
        except Exception as exc:
            error = exc
            raise
        finally:
            if trace is not None:
                elapsed = time.perf_counter() - start
                trace.add_elapsed(key, elapsed)
                if error is not None:
                    trace.record_error(key, error)
                if recorder is not None:
                    recorder(trace, args, kwargs, result, error, round(elapsed * 1000, 3))

    return wrapper


def _async_wrapper(original, key: str, recorder=None):
    @wraps(original)
    async def wrapper(*args, **kwargs):
        trace = active_benchmark_trace.get()
        start = time.perf_counter()
        result = None
        error = None
        try:
            result = await original(*args, **kwargs)
            return result
        except Exception as exc:
            error = exc
            raise
        finally:
            if trace is not None:
                elapsed = time.perf_counter() - start
                trace.add_elapsed(key, elapsed)
                if error is not None:
                    trace.record_error(key, error)
                if recorder is not None:
                    recorder(trace, args, kwargs, result, error, round(elapsed * 1000, 3))

    return wrapper


def _record_ner_entities(
    trace: BenchmarkTrace,
    _args: tuple,
    _kwargs: dict,
    entities: list | None,
    _error: Exception | None,
    _elapsed_ms: float,
) -> None:
    if entities is None:
        return
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


def _record_rxnorm_attempt(method: str):
    def recorder(
        trace: BenchmarkTrace,
        args: tuple,
        _kwargs: dict,
        result,
        error: Exception | None,
        elapsed_ms: float,
    ) -> None:
        query = None if method == "get_drug_details" else args[0] if args else None
        rxcui = _rxnorm_rxcui(method, result)
        status = "error" if error is not None else "hit" if rxcui or _rxnorm_has_result(method, result) else "miss"
        attempt = {
            "stage": trace.phase,
            "method": method,
            "query": query,
            "input_rxcui": args[0] if method == "get_drug_details" and args else None,
            "rxcui": rxcui,
            "status": status,
            "elapsed_ms": elapsed_ms,
            "output": _rxnorm_output(method, result),
        }
        if error is not None:
            attempt["error"] = {
                "class": error.__class__.__name__,
                "message": str(error),
            }
        trace.rxnorm_attempts.append(attempt)
        if method == "get_rxcui":
            trace.link_attempts.append({
                "name": query,
                "rxcui": rxcui,
                "method": "rxnorm_exact",
                "stage": trace.phase,
                "status": status,
            })

    return recorder


def _rxnorm_has_result(method: str, result) -> bool:
    if method in {"approximate_term", "search_by_name"}:
        return bool(result)
    return result is not None


def _rxnorm_rxcui(method: str, result) -> str | None:
    if result is None:
        return None
    if method == "get_rxcui":
        return str(result) if result else None
    if method in {"approximate_term", "search_by_name"} and result:
        return str(getattr(result[0], "rxcui", "") or "") or None
    if method == "get_drug_details":
        return str(result.get("rxcui") or "") if isinstance(result, dict) and result.get("rxcui") else None
    return None


def _rxnorm_output(method: str, result):
    if result is None:
        return None
    if method in {"approximate_term", "search_by_name"}:
        return [
            {
                "rxcui": getattr(candidate, "rxcui", None),
                "name": getattr(candidate, "name", None),
                "score": getattr(candidate, "score", None),
                "synonym": getattr(candidate, "synonym", None),
                "tty": getattr(candidate, "tty", None),
            }
            for candidate in result
        ]
    if isinstance(result, dict):
        return {
            key: result.get(key)
            for key in ("rxcui", "name", "tty", "synonym")
            if key in result
        } or result
    return result


def _resolve_pair_wrapper(original):
    @wraps(original)
    async def wrapper(drug_a: str, drug_b: str, rxcui_by_name: dict[str, str | None]):
        trace = active_benchmark_trace.get()
        previous_attempt = trace.active_interaction_attempt if trace is not None else None
        attempt = None
        if trace is not None:
            attempt = {
                "drug_a": drug_a,
                "drug_b": drug_b,
                "rxcui_a": rxcui_by_name.get(drug_a),
                "rxcui_b": rxcui_by_name.get(drug_b),
            }
            trace.interaction_attempts.append(attempt)
            trace.active_interaction_attempt = attempt
        try:
            entry, bucket = await original(drug_a, drug_b, rxcui_by_name)
        except Exception as exc:
            if trace is not None and attempt is not None:
                attempt["final_source"] = "error"
                attempt["miss_reason"] = "exception"
                _finalize_interaction_attempt(attempt)
            raise
        finally:
            if trace is not None:
                trace.active_interaction_attempt = previous_attempt
        if attempt is not None:
            attempt["final_source"] = bucket
            attempt["final_severity"] = entry.get("severity") if entry else None
            attempt["miss_reason"] = None if entry else "no_source_hit"
            _finalize_interaction_attempt(attempt)
        return entry, bucket

    return wrapper


def _record_interaction_component(component: str):
    def recorder(
        trace: BenchmarkTrace,
        args: tuple,
        _kwargs: dict,
        result,
        error: Exception | None,
        elapsed_ms: float,
    ) -> None:
        attempt = trace.active_interaction_attempt
        if attempt is None:
            return
        block = attempt.setdefault(component, {"calls": []} if component == "openfda" else {})
        call = {
            "input": _interaction_input(component, args),
            "status": "error" if error is not None else "hit" if result else "miss",
            "elapsed_ms": elapsed_ms,
            "output": _interaction_output(component, result),
        }
        if error is not None:
            call["error"] = {
                "class": error.__class__.__name__,
                "message": str(error),
            }
        if component == "openfda":
            block.setdefault("calls", []).append(call)
            if block.get("status") != "hit":
                block.update({key: value for key, value in call.items() if key != "input"})
                block["input"] = call["input"]
        else:
            block.update(call)

    return recorder


def _interaction_input(component: str, args: tuple) -> dict:
    if component == "ddinter_rxcui":
        return {
            "rxcui_a": args[0] if len(args) > 0 else None,
            "rxcui_b": args[1] if len(args) > 1 else None,
        }
    return {
        "drug_a": args[0] if len(args) > 0 else None,
        "drug_b": args[1] if len(args) > 1 else None,
    }


def _interaction_output(component: str, result):
    if result is None:
        return None
    if component.startswith("ddinter"):
        return {
            key: result.get(key)
            for key in ("drug_a_id", "drug_b_id", "drug_a_name", "drug_b_name", "severity", "atc_category", "source")
            if key in result
        }
    if component == "openfda":
        return {
            "description_present": bool(result.get("description")) if isinstance(result, dict) else bool(result),
        }
    return result


def _finalize_interaction_attempt(attempt: dict) -> None:
    rxcui_missing = not attempt.get("rxcui_a") or not attempt.get("rxcui_b")
    defaults = {
        "ddinter_rxcui": {
            "status": "skipped",
            "reason": "missing_rxcui" if rxcui_missing else "not_called",
            "input": {"rxcui_a": attempt.get("rxcui_a"), "rxcui_b": attempt.get("rxcui_b")},
            "elapsed_ms": 0.0,
            "output": None,
        },
        "ddinter_fts": {
            "status": "skipped",
            "reason": "ddinter_rxcui_hit" if attempt.get("ddinter_rxcui", {}).get("status") == "hit" else "not_called",
            "input": {"drug_a": attempt.get("drug_a"), "drug_b": attempt.get("drug_b")},
            "elapsed_ms": 0.0,
            "output": None,
        },
        "openfda": {
            "status": "skipped",
            "reason": "ddinter_hit" if attempt.get("final_source") == "ddinter" else "not_called",
            "input": {"drug_a": attempt.get("drug_a"), "drug_b": attempt.get("drug_b")},
            "elapsed_ms": 0.0,
            "output": None,
            "calls": [],
        },
    }
    for key, value in defaults.items():
        attempt.setdefault(key, value)


async def run_benchmark(
    records: list[dict],
    *,
    concurrency: int,
    seed_cases: dict | None,
    record_timeout_seconds: float | None = None,
) -> dict:
    """Run the benchmark over already-loaded records."""
    if concurrency < 1:
        raise ValueError("concurrency must be at least 1")
    if record_timeout_seconds is not None and record_timeout_seconds <= 0:
        raise ValueError("record_timeout_seconds must be positive")
    semaphore = asyncio.Semaphore(concurrency)
    wall_start = time.perf_counter()
    with install_benchmark_instrumentation():
        record_results = await asyncio.gather(*[
            _run_one_with_timeout(
                record,
                semaphore,
                record_timeout_seconds=record_timeout_seconds,
            )
            for record in records
        ])
        predictions = [item[0] for item in record_results]
        errors = [item[1] for item in record_results if item[1] is not None]
        seed_results = None
        if seed_cases is not None:
            seed_results = await interaction_metrics.run_seed_smoke(seed_cases, interaction_checker.check)
    wall_time_seconds = time.perf_counter() - wall_start

    rxnorm_results = linking_metrics.compute(predictions, records)
    linking_results = {
        key: rxnorm_results.get(key)
        for key in (
            "coverage",
            "fallback_rate",
            "nil_rate",
            "n_link_attempts",
            "n_drugs_total",
            "acc_at_1",
            "incorrect_link_rate",
        )
    }
    results = {
        "overall": pipeline_metrics.overall(
            predictions,
            errors,
            concurrency=concurrency,
            wall_time_seconds=wall_time_seconds,
        ),
        "timing": pipeline_metrics.timing(predictions),
        "ner": ner_metrics.compute(predictions, records),
        "linking": linking_results,
        "rxnorm": rxnorm_results,
        "interactions": interaction_metrics.compute(
            predictions,
            records,
            seed_cases=seed_cases,
            seed_results=seed_results,
        ),
        "errors": pipeline_metrics.errors(errors),
        "fp_taxonomy": await fp_taxonomy.compute(predictions, records),
    }
    return {
        "predictions": predictions,
        "results": results,
        "seed_results": seed_results,
        "errors": errors,
    }


async def _run_one_with_timeout(
    record: dict,
    semaphore: asyncio.Semaphore,
    *,
    record_timeout_seconds: float | None,
) -> tuple[dict, dict | None]:
    async with semaphore:
        if record_timeout_seconds is None:
            return await _run_one(record)
        try:
            return await asyncio.wait_for(
                _run_one(record),
                timeout=record_timeout_seconds,
            )
        except asyncio.TimeoutError:
            return _timeout_prediction(record, record_timeout_seconds), _timeout_error_record(
                record,
                record_timeout_seconds,
            )


async def _run_one(record: dict) -> tuple[dict, dict | None]:
    trace = BenchmarkTrace()
    token = active_benchmark_trace.set(trace)
    total_start = time.perf_counter()
    drugs = []
    interactions_response = None
    error = None
    try:
        analyze_start = time.perf_counter()
        trace.phase = "analyze"
        drugs = await drug_analyzer.analyze(str(record["ocr_text"]))
        trace.add_elapsed("analyze", time.perf_counter() - analyze_start)
    except Exception as exc:
        trace.add_elapsed("analyze", time.perf_counter() - analyze_start)
        trace.record_error("analyze", exc)
        error = _error_record(record, "analyze", exc)
    else:
        interaction_start = time.perf_counter()
        try:
            trace.phase = "interactions"
            interactions_response = await interaction_checker.check([drug["name"] for drug in drugs])
            trace.add_elapsed("interactions", time.perf_counter() - interaction_start)
        except Exception as exc:
            trace.add_elapsed("interactions", time.perf_counter() - interaction_start)
            trace.record_error("interactions", exc)
            error = _error_record(record, "interactions", exc)
    finally:
        trace.phase = None
        trace.add_elapsed("total", time.perf_counter() - total_start)
        active_benchmark_trace.reset(token)

    elapsed_ms = {key: trace.elapsed_ms.get(key, 0.0) for key in ELAPSED_KEYS}
    return {
        "record_id": str(record.get("id", "")),
        "category": record.get("category"),
        "ocr_noise_level": record.get("ocr_noise_level"),
        "drugs": drugs,
        "interactions": interactions_response,
        "ner_entities": trace.ner_entities,
        "ner_diagnostics": ner_metrics.diagnostics_for_entities(
            trace.ner_entities,
            [str(name) for name in record.get("expected_names", [])],
        ),
        "link_attempts": trace.link_attempts,
        "rxnorm_attempts": trace.rxnorm_attempts,
        "interaction_attempts": trace.interaction_attempts,
        "pipeline_errors": trace.pipeline_errors,
        "elapsed_ms": elapsed_ms,
        "component_timings_ms": trace.component_timings(),
        "slowest_component": trace.slowest_component(),
    }, error


def _timeout_prediction(record: dict, timeout_seconds: float) -> dict:
    elapsed_ms = {key: 0.0 for key in ELAPSED_KEYS}
    elapsed_ms["total"] = round(timeout_seconds * 1000, 3)
    pipeline_error = _timeout_error_record(record, timeout_seconds)
    return {
        "record_id": str(record.get("id", "")),
        "category": record.get("category"),
        "ocr_noise_level": record.get("ocr_noise_level"),
        "drugs": [],
        "interactions": None,
        "ner_entities": [],
        "ner_diagnostics": ner_metrics.diagnostics_for_entities(
            [],
            [str(name) for name in record.get("expected_names", [])],
        ),
        "link_attempts": [],
        "rxnorm_attempts": [],
        "interaction_attempts": [],
        "pipeline_errors": [pipeline_error],
        "elapsed_ms": elapsed_ms,
        "component_timings_ms": {
            **elapsed_ms,
            "critical_path": 0.0,
            "slowest_component_ms": elapsed_ms["total"],
        },
        "slowest_component": "total",
    }


def _error_record(record: dict, stage: str, exc: Exception) -> dict:
    return {
        "record_id": str(record.get("id", "")),
        "stage": stage,
        "error_class": exc.__class__.__name__,
        "message": str(exc),
    }


def _timeout_error_record(record: dict, timeout_seconds: float) -> dict:
    return {
        "record_id": str(record.get("id", "")),
        "stage": "record_timeout",
        "error_class": "TimeoutError",
        "message": f"record exceeded {timeout_seconds:g}s timeout",
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
        "linking_coverage": results.get("rxnorm", results.get("linking", {})).get("coverage"),
        "linking_nil_rate": results.get("rxnorm", results.get("linking", {})).get("nil_rate"),
        "interactions_total_pairs_checked": results.get("interactions", {}).get("descriptive", {}).get("total_pairs_checked"),
        "interactions_ddinter_hit_rate": results.get("interactions", {}).get("descriptive", {}).get("ddinter_hit_rate"),
        "interactions_ddinter_rxcui_hit_rate": results.get("interactions", {}).get("descriptive", {}).get("ddinter_rxcui_hit_rate"),
        "interactions_openfda_hit_rate": results.get("interactions", {}).get("descriptive", {}).get("openfda_hit_rate"),
        "interactions_unknown_rate": results.get("interactions", {}).get("descriptive", {}).get("unknown_rate"),
        "records_completed": results.get("overall", {}).get("records_completed"),
        "records_errored": results.get("overall", {}).get("records_errored"),
        "timeout_count": results.get("overall", {}).get("timeout_count"),
        "slowest_component": results.get("timing", {}).get("slowest_component"),
        "total_p95_ms": results.get("timing", {}).get("components", {}).get("total", {}).get("p95_ms"),
        "seed_smoke_recall": results.get("interactions", {}).get("seed_smoke", {}).get("recall"),
        "seed_smoke_false_alarm_rate": results.get("interactions", {}).get("seed_smoke", {}).get("false_alarm_rate"),
        "fp_total": results.get("fp_taxonomy", {}).get("total_fp"),
    }


def summary_markdown(results: dict) -> str:
    metrics = summary_metrics(results)
    lines = [
        "# PillChecker benchmark summary",
        "",
        "> Interaction and RxNorm metrics are not accuracy-certified unless reviewed labels are present.",
        "",
        "## Top-line metrics",
        "",
    ]
    for key, value in metrics.items():
        lines.append(f"- `{key}`: {value}")
    lines.extend(["", "## Component timing", ""])
    for component, values in results.get("timing", {}).get("components", {}).items():
        lines.append(
            f"- `{component}`: p50={values.get('p50_ms')} ms, "
            f"p95={values.get('p95_ms')} ms, p99={values.get('p99_ms')} ms"
        )
    lines.extend(["", "## RxNorm diagnostics", ""])
    for item in results.get("rxnorm", results.get("linking", {})).get("unresolved_queries", [])[:10]:
        lines.append(f"- unresolved `{item.get('query')}` via `{item.get('method')}` in `{item.get('stage')}`")
    lines.extend(["", "## Interaction diagnostics", ""])
    descriptive = results.get("interactions", {}).get("descriptive", {})
    lines.append(f"- source counts: `{descriptive.get('source_counts')}`")
    for item in descriptive.get("top_unknown_pairs", [])[:10]:
        lines.append(f"- unknown pair `{item.get('drug_a')}` + `{item.get('drug_b')}`: {item.get('count')}")
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
    concurrency: int | None = None,
    random_seed: int | str | None = None,
    ddinter_db: dict | None = None,
) -> dict:
    manifest = {
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
        "concurrency": concurrency,
        "metric_schema_version": "benchmark-diagnostics-v1",
        "random_seed": random_seed,
        "metrics": summary_metrics(results),
    }
    if ddinter_db is not None:
        manifest["ddinter_db"] = ddinter_db
    return manifest


def ddinter_metadata_from_args(args: argparse.Namespace) -> dict:
    return {
        "repo": args.ddinter_db_repo or os.environ.get("INTERACTION_DB_REPO"),
        "tag": args.ddinter_db_tag or os.environ.get("INTERACTION_DB_TAG"),
        "asset": args.ddinter_db_asset,
        "sha256": args.ddinter_db_sha256 or os.environ.get("INTERACTION_DB_SHA256"),
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
    output = await run_benchmark(
        records,
        concurrency=args.concurrency,
        seed_cases=seed_cases,
        record_timeout_seconds=args.record_timeout_seconds,
    )
    run_id = args.run_id or _run_id()
    output_prefix = validate_output_prefix(args.output_prefix) if args.output_prefix else _output_prefix(run_id)
    output_dir = Path(args.output_dir) if args.output_dir else Path("benchmark-results") / run_id
    manifest = build_manifest(
        run_id=run_id,
        dataset_revision=args.revision or "local",
        dataset_path=meta.path,
        command=" ".join(sys.argv),
        sample_size=len(records),
        concurrency=args.concurrency,
        output_prefix=output_prefix,
        results=output["results"],
        random_seed=args.random_seed,
        ddinter_db=ddinter_metadata_from_args(args),
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
    parser.add_argument(
        "--record-timeout-seconds",
        type=float,
        default=120.0,
        help="Maximum wall-clock seconds for one benchmark record before recording a timeout error.",
    )
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


def exit_process(exit_code: int) -> None:
    """Exit normally, or force-exit in Cloud Run if upload libraries keep threads alive."""
    if os.environ.get("BENCHMARK_FORCE_OS_EXIT") == "1":
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(exit_code)
    raise SystemExit(exit_code)


if __name__ == "__main__":
    exit_process(main())
