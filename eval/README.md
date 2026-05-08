# PillChecker evaluation methodology

This file describes how the PillChecker OCR-to-ingredient pipeline and downstream interaction checker should be evaluated. Repository/Hugging Face governance rules for agents live in [`../AGENTS.md`](../AGENTS.md).

## Evaluation assets

| Asset | Purpose |
| --- | --- |
| [`SPerva/pillchecker-ner-benchmark`](https://huggingface.co/datasets/SPerva/pillchecker-ner-benchmark) | Current benchmark input cases. |
| [`hf://buckets/SPerva/pillchecker-experiments`](https://huggingface.co/buckets/SPerva/pillchecker-experiments) | Historical benchmark result runs and reports. |
| [`benchmark_record.schema.json`](benchmark_record.schema.json) | Expected shape for benchmark input records. |
| [`benchmark_run_manifest.schema.json`](benchmark_run_manifest.schema.json) | Expected shape for benchmark run metadata. |

The current published benchmark sample contains 500 synthesized pack-label texts generated from [MattBastar/Medicine_Details](https://huggingface.co/datasets/MattBastar/Medicine_Details). Each record currently includes `id`, `category`, `ocr_text`, `expected_names`, and `source_composition`.

## Active-ingredient extraction evaluation

Evaluate the `/analyze` pipeline against `expected_names` with:

1. strict ingredient precision, recall, and F1 after normalization;
2. lenient precision, recall, and F1 for casing, punctuation, and salt-form variants;
3. false-positive taxonomy for brand names, excipients, dosages, packaging words, and OCR artifacts;
4. confidence calibration and threshold sweeps for `needs_confirmation` behavior.

The benchmark should report pipeline configuration, model IDs, confidence thresholds, sample size, dataset revision, and Git commit in the run manifest.

## RxNorm linking evaluation

RxNorm linking recall and NIL behavior require `expected_rxcuis` in the benchmark records. Once those labels are populated, evaluate:

1. ingredient-to-RxCUI exact-match accuracy;
2. missing-link rate for valid ingredients;
3. incorrect-link rate for ambiguous names;
4. fallback behavior when NER misses an ingredient but RxNorm approximate search recovers it.

Until `expected_rxcuis` exists, project docs should not make strong RxNorm-linking accuracy claims from this dataset.

## OCR cleaner evaluation

OCR-cleaner evaluation requires an independent `clean_text` reference for noisy cases. Once available, evaluate:

1. character error rate before and after cleaning;
2. word error rate before and after cleaning;
3. downstream active-ingredient extraction impact;
4. cleaner regressions on already-clean labels.

Do not use cleaner-generated output as its own oracle.

## Interaction-checking evaluation

Interaction evaluation requires `expected_interactions` and known-safe pairs. Once curated, evaluate:

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

Next evaluation work:

1. Populate `expected_rxcuis` for the current benchmark sample.
2. Add independent `clean_text` references for OCR-noise cases.
3. Curate interaction-positive and known-safe ingredient pairs.
4. Add benchmark scripts that read the HF dataset, write manifest-backed bucket results, and can be reproduced from a GitHub commit.
5. Reintroduce any GLiNER comparison only with reproducible code, configuration, and stored artifacts.
