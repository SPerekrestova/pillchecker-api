# PillChecker evaluation methodology

This file describes how the PillChecker OCR-to-ingredient pipeline and downstream interaction checker should be evaluated. Repository/Hugging Face governance rules for agents live in [`../AGENTS.md`](../AGENTS.md).

## Evaluation assets

| Asset | Purpose |
| --- | --- |
| [`SPerva/pillchecker-ner-benchmark`](https://huggingface.co/datasets/SPerva/pillchecker-ner-benchmark) | Current benchmark input cases. |
| [`hf://buckets/SPerva/pillchecker-experiments`](https://huggingface.co/buckets/SPerva/pillchecker-experiments) | Historical benchmark result runs and reports. |
| [`benchmark_record.schema.json`](benchmark_record.schema.json) | Expected shape for benchmark input records. |
| [`benchmark_run_manifest.schema.json`](benchmark_run_manifest.schema.json) | Expected shape for benchmark run metadata. |

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
4. source routing accuracy between DrugBank and OpenFDA fallback evidence.

Until this ground truth exists, interaction metrics should be treated as smoke tests rather than benchmark claims.

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
4. Add benchmark runners that read the HF dataset, write manifest-backed bucket results, and can be reproduced from a GitHub commit.
5. Reintroduce any GLiNER comparison only with reproducible code, configuration, and stored artifacts.
