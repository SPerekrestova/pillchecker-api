---
title: PillChecker Staging
emoji: 📚
colorFrom: green
colorTo: indigo
sdk: docker
pinned: true
app_port: 8000
license: mit
---

# PillChecker API

PillChecker helps users find out if two medications are safe to take at the same time. This repository contains the backend API that identifies drugs from OCR text and checks for dangerous interactions using DrugBank pharmaceutical data.

[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.19792062.svg)](https://doi.org/10.5281/zenodo.19792062)

> **MEDICAL DISCLAIMER**
>
> This service is provided for **informational and self-educational purposes only**. While the application utilizes data from respected pharmaceutical sources, the information provided should **not** be treated as medical advice, diagnosis, or treatment.
>
> The developer of this project **does not have any medical qualifications**. This tool was built as a technical exercise to explore NLP and medical data integration.
>
> **Always consult with a qualified healthcare professional** (such as a doctor or pharmacist) before making any decisions regarding your medications or health. The developer assumes **no responsibility or liability** for any errors, omissions, or consequences arising from the use of the information provided by this service.

## Architecture

### Drug Identification

Converts unstructured OCR text into standardized drug records using a multi-step strategy:

1. **OCR Cleaning**: The `ocr_cleaner` normalizes common OCR artifacts before NER: digit-letter confusion (`0`/`o`, `1`/`l`), `rn`→`m` in drug names, ligatures, invisible characters, and whitespace.
2. **NER**: The **[OpenMed-NER-PharmaDetect-BioPatient-108M](https://huggingface.co/OpenMed/OpenMed-NER-PharmaDetect-BioPatient-108M)** model (108M parameters) extracts chemical entity names from the cleaned text.
3. **Fallback**: If NER yields no results, an approximate term search via the **RxNorm REST API** catches brand names (e.g., "Advil" -> ibuprofen).
4. **Enrichment**: A regex parser extracts dosages (e.g., "400 mg"), and the RxNorm API maps every identified drug to its **RxCUI** for standardized downstream lookups.
5. **Confidence**: Results with NER score below 0.85 or sourced from the RxNorm fallback are flagged with `needs_confirmation = true` to prompt user verification.

### Interaction Checking

Drug-drug interactions are resolved against the **DrugBank** pharmaceutical database through direct async SQLite access:

1. **DrugBank SQLite client**: `app/clients/drugbank_db.py` opens the pre-built DrugBank SQLite database (~17,400 drugs) with `aiosqlite` and FTS5 search.
2. **Bidirectional lookup**: For each drug pair, the checker queries both directions (A->B and B->A) in parallel using `asyncio.gather()`.
3. **Severity classification**: Interaction descriptions are first parsed by a deterministic **template parser** that matches regex patterns in DrugBank text. If the parser cannot determine severity, a **DeBERTa v3** zero-shot classifier is used as fallback. Unknown severity defaults to `major` with `uncertain = true`.
4. **Caching**: DrugBank interaction records are cached in-process for 4 hours; RxNorm lookups are cached for 24 hours.

### Transparency

Both `/analyze` and `/interactions` responses include:
- `data_sources`: which models and databases were used for the result
- `limitations` (interactions only): scope disclaimers about what the system does and does not cover

### Docker Build

The image uses a three-stage build to keep layers small and reproducible:

- **Stage 1 (Python)**: `uv` installs Python dependencies into an isolated venv.
- **Stage 2 (DB downloader)**: the pinned DrugBank SQLite database is downloaded from GitHub Releases.
- **Stage 3 (Runtime)**: combines the venv, SQLite database, and app code. NER and severity models are pre-downloaded so the image is fully self-contained.

## API Endpoints

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `GET` | `/health` | No | Liveness check |
| `GET` | `/health/data` | No | Readiness -- confirms DrugBank SQLite connection |
| `POST` | `/analyze` | API key | Extract drugs from OCR text |
| `POST` | `/interactions` | API key | Check interactions for a list of drug names |
| `POST` | `/admin/cache/clear` | API key | Clear all in-memory caches |

## Eval Benchmark

The benchmark suite and raw results have been migrated to the Hugging Face Hub for better reproducibility and visualization.

*   **Benchmark Dataset:** [SPerva/pillchecker-ner-benchmark](https://huggingface.co/datasets/SPerva/pillchecker-ner-benchmark)
*   **Result History:** [hf://buckets/SPerva/pillchecker-experiments](https://huggingface.co/buckets/SPerva/pillchecker-experiments)
*   **Methodology:** See the dataset card on Hugging Face for details on the current 500-case benchmark sample.

| Pipeline (Clean Text) | Precision | Recall | F1 |
|------------------------|-----------|--------|----|
| Bare NER Baseline | 46.9% | 84.4% | 60.3% |
| Full Pipeline | 71.6% | 81.0% | 76.0% |

See [`AGENTS.md`](AGENTS.md) for HF/GitHub ownership rules and [`eval/README.md`](eval/README.md) for the current benchmark plan, missing ground-truth fields, and Hugging Face asset cleanup rules.

## Staging & Deployment

The API is deployed as a staging environment on Hugging Face Spaces for remote testing:

*   **Staging Space:** [sperva-pillchecker-staging](https://huggingface.co/spaces/SPerva/pillchecker-staging)
*   **API Docs:** [sperva-pillchecker-staging.hf.space/docs](https://sperva-pillchecker-staging.hf.space/docs)


- **[PillChecker Collection](https://huggingface.co/collections/SPerva/pillchecker-69ee0f67dee76ff7ae9ea30a)** -- Central hub for all models and datasets used in this project.
- **[OpenMed NER PharmaDetect](https://huggingface.co/OpenMed/OpenMed-NER-PharmaDetect-BioPatient-108M)** -- drug entity recognition model (108M params). License: Apache 2.0
- **[RxNorm REST API](https://lhncbc.nlm.nih.gov/RxNav/APIs/RxNormAPIs.html)** -- drug name normalization and RxCUI mapping. Provided by NLM (free to use).
- **[DrugBank](https://www.drugbank.com/)** -- pharmaceutical database providing structured drug-drug interaction data. Accessed through a pinned SQLite database generated by the [openpharma-org/drugbank-mcp-server](https://github.com/openpharma-org/drugbank-mcp-server) project.
- **[DeBERTa-v3-base-mnli-fever-anli](https://huggingface.co/MoritzLaurer/DeBERTa-v3-base-mnli-fever-anli)** -- zero-shot classifier for interaction severity. License: MIT
- **[Hugging Face Transformers](https://huggingface.co/docs/transformers)** -- NLP pipeline library. License: Apache 2.0

## Citation

If you use this software or the benchmark dataset in your research, please cite it as:

```bibtex
@software{perekrestova_pillchecker_2026,
  author = {Perekrestova, Svetlana},
  orcid = {0009-0003-2905-6040},
  title = {PillChecker API: Pharmaceutical Entity Extraction and Interaction Checker},
  version = {1.2.2},
  doi = {10.5281/zenodo.19792062},
  url = {https://github.com/SPerekrestova/pillchecker-api},
  date = {2026-04-26},
  publisher = {Zenodo},
  note = {GitHub Repository}
}
```

