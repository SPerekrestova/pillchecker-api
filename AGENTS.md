# Agent rules for PillChecker API

These rules are authoritative for AI agents working in this repository.

## Source-of-truth rules

1. GitHub is the source of truth for application code, Docker configuration, tests, docs, and workflow definitions.
2. Hugging Face Space `SPerva/pillchecker-staging` is generated from GitHub. Never copy code from the Space back into GitHub as a source of truth.
3. Do not manually edit files in the HF Space. If the Space drifts, fix GitHub and run the GitHub -> HF Space sync.
4. Benchmark data and results do not belong in the Space. Use the HF dataset and bucket listed below.
5. Do not delete or rewrite HF artifacts unless a human explicitly approves the exact paths.
6. Never commit secrets. Use `HF_TOKEN` from GitHub/Devin secrets for Hugging Face writes.

## Hugging Face entity registry

| Entity | Type | Canonical contents | Update rules |
| --- | --- | --- | --- |
| `SPerva/pillchecker-staging` | Space | Staging deployment mirror of deployable GitHub files. | One-way sync from GitHub `main` through `.github/workflows/hf-sync.yml` and `scripts/sync_hf_space.py`. No Space-to-GitHub sync. No manual Space edits. |
| `SPerva/pillchecker-ner-benchmark` | Dataset | Benchmark input cases and dataset card methodology. | Store benchmark cases under `data/`. Do not store result history under `results/`. Add schema changes to `eval/README.md` before changing dataset fields. |
| `hf://buckets/SPerva/pillchecker-experiments` | Bucket | Immutable benchmark run outputs and historical reports. | Store outputs under `benchmark-results/<YYYY-MM-DD>/<run-id>/` with a manifest. Do not place unversioned root `results.json` files. Do not overwrite old runs. |
| `SPerva/ml-intern-sessions` | Dataset | Private exploratory agent traces. | Non-canonical archive only. Promote conclusions into GitHub docs or dataset cards before relying on them. Delete empty traces after approval. |
| `SPerva/pillchecker` collection | Collection | Links to project HF assets. | Keep as navigation only; do not store data in the collection itself. |
| External models such as `OpenMed/OpenMed-NER-PharmaDetect-BioPatient-108M` | Model | Upstream model artifacts. | Treat as read-only dependencies; pin/report model IDs in benchmark manifests. |

## Code update rules

1. Make code changes in GitHub branches and PRs only.
2. Do not push directly to `main`.
3. Keep `.github/workflows/hf-sync.yml` one-way: GitHub `main` -> `SPerva/pillchecker-staging`.
4. If a file should be present in the Space, add it to `DEFAULT_ALLOW_PATTERNS` in `scripts/sync_hf_space.py`.
5. If a file should never be deployed to the Space, add it to `DEFAULT_IGNORE_PATTERNS` or keep it outside the allowlist.
6. Run at least:
   - `git diff --check`
   - `python -m py_compile scripts/sync_hf_space.py` after editing the sync script
   - `uv run pytest tests/ --ignore=tests/test_rxnorm_client.py -v`
7. Update PR descriptions after pushing follow-up commits.

## Benchmark dataset rules

1. Keep generated benchmark cases in `SPerva/pillchecker-ner-benchmark/data/`.
2. Benchmark records should follow `eval/benchmark_record.schema.json`.
3. Required benchmark records should include at minimum:
   - source text used by the pipeline
   - expected active ingredients
   - OCR noise level or source split
   - source medicine metadata needed to reproduce the case
4. Add these fields before using the benchmark for linking or interaction claims:
   - `expected_rxcuis`
   - `clean_text` for OCR-cleaner evaluation
   - `expected_interactions` for interaction recall/severity evaluation
   - known-safe pairs for false-positive measurement
5. The dataset card must explain data generation, license/source, schema, and limitations.
6. Do not commit large benchmark data or result JSON files to GitHub.

## Benchmark result rules

1. Store benchmark outputs in the bucket, not the dataset and not GitHub.
2. Use immutable paths: `benchmark-results/<YYYY-MM-DD>/<run-id>/`.
3. Each run directory should contain:
   - `results.json`
   - `manifest.json` following `eval/benchmark_run_manifest.schema.json`
   - optional markdown summary or plots
4. Root-level files in the bucket should be human-readable summaries only, such as `BENCHMARK.md`.
5. If a result must be superseded, write a new run and mark the old one as superseded in a summary; do not overwrite it.

## Cleanup rules

1. Safe cleanup candidates are duplicate result copies, zero-byte traces, stale Space-only files, and unversioned legacy files after moving them to a versioned legacy path.
2. Before deleting HF data, verify an equivalent canonical copy exists or that the file is genuinely empty/stale.
3. Record cleanup decisions in PR descriptions or `eval/README.md`.
4. For Space trash, prefer fixing the allowlist and letting GitHub -> HF sync prune it after merge.

## Current known issues

1. Benchmark cases still need `expected_rxcuis`, `clean_text`, `expected_interactions`, and known-safe pairs.
2. GLiNER results should stay out of README/project claims until code, configuration, and artifacts are reproducible.
3. Interaction benchmark results are not meaningful until real interaction ground truth exists.
4. OCR-cleaner evaluation must use independent clean references, not cleaner-generated text as its own oracle.
