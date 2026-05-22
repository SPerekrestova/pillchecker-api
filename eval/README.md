# PillChecker evaluation methodology

This file describes how the PillChecker OCR-to-ingredient pipeline and downstream interaction checker should be evaluated. Repository/Hugging Face governance rules for agents live in [`../AGENTS.md`](../AGENTS.md).

## Evaluation assets

| Asset | Purpose |
| --- | --- |
| [`SPerva/pillchecker-ner-benchmark`](https://huggingface.co/datasets/SPerva/pillchecker-ner-benchmark) | Current benchmark input cases. |
| [`hf://buckets/SPerva/pillchecker-experiments`](https://huggingface.co/buckets/SPerva/pillchecker-experiments) | Historical benchmark result runs and reports. |
| [`benchmark_record.schema.json`](benchmark_record.schema.json) | Expected shape for benchmark input records. |
| [`benchmark_run_manifest.schema.json`](benchmark_run_manifest.schema.json) | Expected shape for benchmark run metadata. |
| [`benchmark_results.schema.json`](benchmark_results.schema.json) | Expected shape for Tier 1 benchmark result summaries. |
| [`interaction_label_candidates.schema.json`](interaction_label_candidates.schema.json) | Expected shape for review-only interaction label candidate queues. |

The current published benchmark sample contains 500 synthesized pack-label texts generated from [MattBastar/Medicine_Details](https://huggingface.co/datasets/MattBastar/Medicine_Details). Each record currently includes `id`, `category`, `ocr_text`, `expected_names`, and `source_composition`. The sample has 199 unique expected ingredient names; an audit found exact RxNorm matches for 183 of them and 16 names requiring review.

## Why the current sample is 500 records

The source dataset has more than 11k product rows, but those rows are not yet a validated evaluation benchmark. The current 500-record sample is a reviewable seed split: it is small enough to audit manually, exercise many source categories and ingredient strings, and avoid publishing stronger accuracy claims before RxNorm links, clean-text references, interaction positives, and known-safe pairs are reviewed.

Scaling should be staged rather than copying all 11k+ rows into the benchmark at once:

1. stratify the full source dataset by category, ingredient count, OCR difficulty, and active-ingredient frequency;
2. expand to a larger fixed benchmark split after adding reviewed `expected_rxcuis` and cleaner references;
3. keep a separate stress-test split for the full 11k+ source rows where labels are weak or generated;
4. report metrics separately for reviewed benchmark records and weakly labeled stress-test records.

## Active-ingredient extraction evaluation

Evaluate the `/analyze` pipeline against `expected_names` with:

1. strict ingredient precision, recall, and F1 after normalization;
2. lenient precision, recall, and F1 for casing, punctuation, and salt-form variants;
3. false-positive taxonomy for brand names, excipients, dosages, packaging words, and OCR artifacts;
4. confidence calibration and threshold sweeps for `needs_confirmation` behavior.

The benchmark should report pipeline configuration, model IDs, confidence thresholds, sample size, dataset revision, and Git commit in the run manifest.

## RxNorm linking evaluation

RxNorm linking recall and NIL behavior require reviewed `expected_rxcuis` plus `rxnorm_resolution` status in the benchmark records. Use `prepare_rxnorm_labels.py` to create a reviewable candidate file before changing the canonical HF dataset. Once those labels are populated, evaluate:

1. ingredient-to-RxCUI exact-match accuracy;
2. missing-link rate for valid ingredients;
3. incorrect-link rate for ambiguous names;
4. fallback behavior when NER misses an ingredient but RxNorm approximate search recovers it.

Until reviewed `expected_rxcuis` exists in the canonical dataset, project docs should not make strong RxNorm-linking accuracy claims from this dataset.

## OCR cleaner evaluation

OCR-cleaner evaluation requires an independent `clean_text` reference for noisy cases. Once available, evaluate:

1. character error rate before and after cleaning;
2. word error rate before and after cleaning;
3. downstream active-ingredient extraction impact;
4. cleaner regressions on already-clean labels.

Do not use cleaner-generated output as its own oracle.

## Interaction-checking evaluation

Interaction evaluation requires `expected_interactions` and known-safe pairs. `interaction_seed_cases.json` contains a small curated seed set for developing interaction benchmarks, but it is not a statistically representative benchmark split. Once fuller ground truth is curated, evaluate:

1. interaction recall for known interacting ingredient pairs;
2. false-alarm rate on known-safe pairs;
3. severity accuracy for `minor`, `moderate`, `major`, and `unknown` labels;
4. source routing accuracy between DDInter and OpenFDA fallback evidence.

Until this ground truth exists, interaction metrics should be treated as smoke tests rather than benchmark claims.

## Tier 1 runner

Tier 1 benchmark entrypoints:

1. `python -m eval.prepare_interaction_labels --revision <hf-rev> --out candidates.json` generates review-only interaction candidates for dual and multi-ingredient records. DDInter and OpenFDA hits are source suggestions only; emitted candidates always use `is_ground_truth: false` and `review_status: "unreviewed"` until a human reviewer promotes them into canonical `expected_interactions` or `known_safe_pairs`.
2. `python -m eval.run_benchmark --revision <hf-rev> --limit 25 --local-only` runs the benchmark pipeline locally and writes `results.json`, `manifest.json`, `predictions.jsonl`, `errors.jsonl`, and `summary.md` under `benchmark-results/<run-id>/`.

The runner loads benchmark inputs from the HF dataset and writes benchmark outputs to the HF experiments bucket when `--local-only` is not set. DDInter data is not stored in HF: if the local SQLite file is absent, configure `INTERACTION_DB_REPO`, `INTERACTION_DB_TAG`, and optionally `INTERACTION_DB_SHA256` so the runner can fetch `ddinter.db` from the pinned GitHub release source.

`predictions.jsonl` includes benchmark-only diagnostics for each record:

1. `elapsed_ms` preserves the original 10 timing keys: `ocr_clean`, `ner`, `rxnorm`, `ddinter_rxcui`, `ddinter_fts`, `openfda`, `severity`, `analyze`, `interactions`, and `total`.
2. `component_timings_ms` repeats those keys and adds `critical_path` plus `slowest_component_ms`; `critical_path` is the sum of the non-aggregate component buckets, and `slowest_component` names the largest non-aggregate component bucket for that record.
3. `ner_diagnostics` includes predicted entities plus per-record strict and lenient TP/FP/FN counts when `expected_names` is present.
4. `rxnorm_attempts` records benchmark-stage, method, query, returned RxCUI, status, elapsed time, output summary, and error metadata for RxNorm calls.
5. `interaction_attempts` records one row per checked pair, including pair names, RxCUIs, DDInter RxCUI lookup, DDInter FTS lookup, OpenFDA fallback, final source, final severity, and miss reason.
6. `pipeline_errors` records timeout or component errors tied to the record without requiring the whole benchmark to fail.

Timing measurements intentionally overlap: `analyze` includes OCR, NER, and RxNorm work; `interactions` includes DDInter, OpenFDA, and severity work; `total` includes the top-level phases plus benchmark overhead. Do not sum all timing keys as a disjoint latency partition. Starting with `metric_schema_version: "benchmark-diagnostics-v1"`, the `rxnorm` timing bucket covers all benchmark-wrapped RxNorm calls (`get_rxcui`, `approximate_term`, `search_by_name`, and `get_drug_details`), so compare it with earlier runs only as a changed-instrumentation metric.

`results.json` groups rollups by `overall`, `timing`, `ner`, `linking`, `rxnorm`, `interactions`, `errors`, and `fp_taxonomy`. `linking` is kept for backward compatibility with the original link-coverage fields; `rxnorm` carries those core fields plus RxNorm attempt diagnostics such as method hit/miss/error counts, unresolved queries, and canonicalization collisions. Interaction diagnostics report DDInter RxCUI hit rate, DDInter FTS rescue rate, OpenFDA rescue rate, source counts, and common unknown pairs. These are routing/source-coverage diagnostics unless reviewed `expected_interactions` and `known_safe_pairs` are present.

`manifest.json` includes `metric_schema_version`, dataset revision, run id, sample size, model IDs, concurrency, and DDInter release metadata. `summary.md` highlights top-line metrics, timing bottlenecks, unresolved RxNorm queries, unknown interaction pairs, and an explicit warning when outputs are not accuracy-certified.

Use `--record-timeout-seconds` to bound each input record so a stuck RxNorm, OpenFDA, or model path records a `record_timeout` error instead of hanging the whole run. Use `--local-only` for development and smoke runs. Without `--local-only`, result artifacts upload to the experiments bucket under an immutable `benchmark-results/<YYYY-MM-DD>/<run-id>/` prefix; do not commit generated candidate JSON or benchmark result directories to GitHub.

## GCP Tier 1 execution

The canonical cloud path is `.github/workflows/tier1-benchmark.yml`, dispatched manually from GitHub Actions. It builds the `benchmark-runner` Docker target, deploys Cloud Run Job `pillchecker-benchmark-tier1` in `europe-west1`, runs `python -m eval.run_benchmark`, and validates uploaded artifacts in `hf://buckets/SPerva/pillchecker-experiments`.

Manual inputs:

1. `dataset_revision`: required pinned HF dataset revision.
2. `limit`: default `25`; use `1` for a smoke dispatch.
3. `run_id`: optional immutable run id; generated from the GitHub run when blank.
4. `concurrency`: default `8`.
5. `upload`: default `true`; keep enabled for validation.
6. `record_timeout_seconds`: default `120`.

The workflow uses Secret Manager `HF_TOKEN`, GitHub/GCP WIF secrets, and `INTERACTION_DB_REPO`, `INTERACTION_DB_TAG`, plus optional `INTERACTION_DB_SHA256`. The HF Space is not a benchmark worker and is not a result store; benchmark execution belongs in Cloud Run Jobs and immutable outputs belong in the HF experiments bucket.

## Experiment workflow

1. Pin the Git commit, dataset revision, model IDs, confidence thresholds, and command.
2. Run the evaluation against a fixed sample or full benchmark split.
3. Write `manifest.json` following `benchmark_run_manifest.schema.json`.
4. Store result artifacts under `benchmark-results/<YYYY-MM-DD>/<run-id>/` in the experiments bucket.
5. Keep large result JSON files out of GitHub; commit only lightweight methodology, schemas, and orchestration code.
6. Update the dataset card when the benchmark methodology or schema changes.

## Current progress

Completed:

1. The current 500-case NER benchmark sample is published on Hugging Face.
2. Historical OpenMed baseline results are preserved in the experiments bucket.
3. Public README and dataset card now describe the current 500-case sample size.
4. The unreproducible GLiNER best-result claim has been removed from project-facing README tables until its code, configuration, and artifacts are reproducible.
5. RxNorm label preparation is reproducible via `prepare_rxnorm_labels.py`; current exact-match coverage is 183/199 unique ingredient names.
6. Initial interaction-positive and known-safe seed pairs are stored in `interaction_seed_cases.json` for benchmark development.

Next evaluation work:

1. Review the 16 non-exact RxNorm ingredient names and then update the canonical HF benchmark records.
2. Add independent `clean_text` references for OCR-noise cases.
3. Expand interaction-positive and known-safe ingredient pairs beyond the seed set.
4. Dispatch the GCP Tier 1 workflow with `limit=1` and then `limit=25`; require an empty `errors.jsonl` for the smoke gate before reporting metrics.
5. Reintroduce any GLiNER comparison only with reproducible code, configuration, and stored artifacts.
