---
license: mit
task_categories:
  - token-classification
language:
  - en
tags:
  - ner
  - pharmaceutical
  - ocr
  - drug-names
  - benchmark
  - medical
size_categories:
  - 10K<n<100K
citation: |
  @software{perekrestova_pillchecker_2026,
    author = {Perekrestova, Svetlana},
    title = {PillChecker API: Pharmaceutical Entity Extraction and Interaction Checker},
    version = {1.2.2},
    doi = {10.5281/zenodo.19792062},
    url = {https://github.com/SPerekrestova/pillchecker-api},
    date = {2026-04-26},
    publisher = {Zenodo},
    note = {GitHub Repository}
  }
---

# PillChecker NER Benchmark

Benchmark dataset for evaluating Named Entity Recognition (NER) models on pharmaceutical packaging text.

## Dataset Description

**11,796 synthesized pack-label texts** generated from the [MattBastar/Medicine_Details](https://huggingface.co/datasets/MattBastar/Medicine_Details) dataset, designed to simulate OCR output from photos of pill packaging.

Each case contains:
- `id`: Unique case identifier
- `category`: `single_ingredient`, `dual_ingredient`, or `multi_ingredient`
- `ocr_text`: Synthesized pharmaceutical label text (clean or with OCR noise)
- `expected_names`: Ground-truth list of active pharmaceutical ingredients
- `source_composition`: Original composition string from source dataset

## Use Case

This dataset tests whether NER models can extract **active pharmaceutical ingredients** from short, formulaic packaging text — a domain significantly different from biomedical literature.

## Baseline Results

Evaluated with [OpenMed/OpenMed-NER-PharmaDetect-BioPatient-108M](https://huggingface.co/OpenMed/OpenMed-NER-PharmaDetect-BioPatient-108M):

| Pipeline | Precision | Recall | F1 |
|----------|-----------|--------|-----|
| Bare NER (clean) | 46.9% | 84.4% | 60.3% |
| Full Pipeline (clean) | 71.6% | 81.0% | 76.0% |
| **GLiNER Union (clean)** | **78.0%** | **93.6%** | **85.1%** |

## Source

Part of the [PillChecker](https://github.com/SPerekrestova/pillchecker-api) project.
