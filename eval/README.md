# PillChecker evaluation and Hugging Face asset plan

This file records the current evaluation architecture, the Hugging Face resource inventory, and the cleanup plan for benchmark assets. Agent-facing repository rules live in [`../AGENTS.md`](../AGENTS.md).

## Current sources

| Source | Role | Current state |
| --- | --- | --- |
| GitHub `SPerekrestova/pillchecker-api` | Canonical application code and deployment workflow | Main branch has the FastAPI service, direct SQLite DrugBank client, tests, Docker build, and HF Space sync workflow. |
| PR #53 `feat/benchmark` | Benchmark experiment proposal | Useful NER/linking ideas, but should not be merged as-is because some scripts are placeholders or require missing ground truth. |
| HF Space `SPerva/pillchecker-staging` | Staging deployment mirror | Mostly mirrors GitHub main, but has stale benchmark scripts that will be pruned by the GitHub -> HF Space sync after merge. |
| HF Dataset `SPerva/pillchecker-ner-benchmark` | Canonical benchmark cases | Contains `data/benchmark.json`; duplicate result JSON files were removed. The dataset lacks `expected_rxcuis`, `expected_interactions`, and clean OCR references needed for complete evaluation. |
| HF Bucket `hf://buckets/SPerva/pillchecker-experiments` | Benchmark result history | Contains `BENCHMARK.md` and versioned result files under `benchmark-results/`, including the legacy root `results.json` moved to `benchmark-results/legacy/results.json`. |
| HF Dataset `SPerva/ml-intern-sessions` | Private agent trace archive | Contains one substantive ML Intern trace; the empty JSONL file was removed. It is not a canonical project artifact store. |
| Devin session `devin-edd6eef4cda74faf909cb8bd08d3f7c8` | PR #45 follow-up context | Confirms the project moved from a Node.js MCP process to direct Python SQLite DrugBank access and fixed error propagation/health-check behavior. |

## What is missing

1. `expected_rxcuis` per benchmark case, so RxNorm/linking recall and oracle analysis can be measured.
2. `clean_text` or another non-circular OCR reference per case, so OCR cleaner CER/WER can be evaluated.
3. `expected_interactions` plus known-safe pairs, so interaction recall, false-alarm rate, and severity accuracy are meaningful.
4. Reproducible GLiNER experiment code/configuration if GLiNER results remain in project-facing docs.
5. Ground-truth population for the current published 500-case benchmark sample; earlier docs overstated the published dataset as 11,796 cases.

## Redundant or unsafe assets

| Asset | Classification | Recommendation |
| --- | --- | --- |
| HF Space `scripts/benchmark.py`, `scripts/benchmark_ocr.py`, `scripts/benchmark_interactions.py` | Stale Space-only files | Prune via the GitHub-to-HF Space sync workflow; benchmark code should not live only in the Space. |
| HF Dataset `results/*.json` | Duplicate benchmark outputs | Removed after approval; bucket result copies remain canonical. |
| HF Dataset `SPerva/ml-intern-sessions/.../a720491d-*.jsonl` | Empty trace file | Removed after approval. |
| HF Bucket root `results.json` | Legacy unversioned result | Moved after approval to `benchmark-results/legacy/results.json`; root copy removed. |
| README GLiNER best-result claim | Not reproducible from main | Remove or label as external until the experiment code and config are in the repo or dataset card. |
| PR #53 benchmark scripts | Partially useful but not production-ready | Extract design ideas; do not merge wholesale until the missing dataset fields exist. |

## Canonical storage layout

| Information type | Canonical location | Notes |
| --- | --- | --- |
| Runtime API code, Dockerfiles, tests, sync workflow | GitHub | GitHub remains the source of truth for deployable code. |
| Small evaluation docs and schema definitions | GitHub `eval/` | Keep docs, schemas (`benchmark_record.schema.json`, `benchmark_run_manifest.schema.json`), and lightweight orchestration scripts here. Do not commit large datasets or result blobs. |
| Benchmark input cases | HF Dataset `SPerva/pillchecker-ner-benchmark` | Store `data/benchmark.json` with the added ground-truth fields and dataset card methodology. |
| Benchmark run outputs | HF Bucket `SPerva/pillchecker-experiments` | Store dated immutable outputs, e.g. `benchmark-results/YYYY-MM-DD/<run-id>/results.json` plus a manifest. |
| Staging deployment | HF Space `SPerva/pillchecker-staging` | Space should be generated from GitHub main and should not be manually edited. |
| Agent traces / exploratory notes | Private HF Dataset `SPerva/ml-intern-sessions` | Keep private and non-canonical; promote only reviewed conclusions into GitHub or the benchmark dataset card. |
| Wiki material | Devin wiki / README links | Use for navigable architecture explanations, not as the only copy of benchmark data. |

## Benchmark plan

### Phase 1: make the current NER benchmark reproducible

1. Keep `SPerva/pillchecker-ner-benchmark` as the source of benchmark cases and validate records against `benchmark_record.schema.json`.
2. Add a manifest to every benchmark run that follows `benchmark_run_manifest.schema.json`.
3. Evaluate:
   - strict/lenient active-ingredient precision, recall, F1;
   - confidence calibration and threshold sweep;
   - false-positive taxonomy with a better split than `other`;
   - RxNorm linking success/NIL rate.

### Phase 2: add missing ground truth

1. Populate `expected_rxcuis` for all or a representative stratified subset.
2. Add `clean_text` for OCR-noise cases.
3. Curate at least 200 interaction examples and a matched known-safe set.
4. Re-run oracle analysis after `expected_rxcuis` exists.

### Phase 3: expand beyond NER

1. Measure interaction detection recall and false-alarm rate against the curated interaction set.
2. Measure severity parser/classifier accuracy on known interaction descriptions.
3. Reintroduce GLiNER only with code, config, and artifacts that can reproduce the reported numbers.

## Sync pipeline

The Space sync should be one-way and deterministic:

```text
GitHub main -> GitHub Actions -> scripts/sync_hf_space.py -> SPerva/pillchecker-staging
```

The workflow should prune stale deployable paths before upload, which prevents manually added Space-only files from persisting. Benchmark datasets/results should not flow through the Space sync; they are managed separately through the HF Dataset and bucket.

For benchmark outputs, use a manual workflow or local script that uploads only generated result artifacts to `hf://buckets/SPerva/pillchecker-experiments/benchmark-results/<date>/<run-id>/` and updates the dataset card only when methodology changes.

## Cleanup status

Completed after explicit approval:

1. Deleted duplicate HF dataset files under `SPerva/pillchecker-ner-benchmark/results/*.json` after verifying bucket copies were retained.
2. Deleted the empty private trace `SPerva/ml-intern-sessions/sessions/2026-05-06/a720491d-d166-47b8-baad-1c2e71bb4ec1.jsonl`.
3. Moved bucket root `results.json` to `benchmark-results/legacy/results.json` and removed the root copy.

Still pending:

1. Close or supersede PR #53 after extracting any useful benchmark ideas into a grounded follow-up plan.
2. Let the GitHub -> HF Space sync prune stale Space-only benchmark scripts after this PR merges to `main`.
