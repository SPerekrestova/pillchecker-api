# PillChecker API

PillChecker helps users find out if two medications are safe to take at the same time. This repository contains the backend API that identifies drugs from OCR text and checks for dangerous interactions using DrugBank pharmaceutical data.

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

Drug-drug interactions are resolved against the **DrugBank** pharmaceutical database via a vendored MCP server:

1. **DrugBank MCP server**: A Node.js process (vendored under `drugbank-mcp-server/`) communicates over stdio using the Model Context Protocol. It serves a pre-built SQLite database (~17,400 drugs) with structured pairwise interaction data.
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
- **Stage 2 (Node.js)**: `npm ci` installs Node dependencies; the DrugBank SQLite database is downloaded from GitHub Releases.
- **Stage 3 (Runtime)**: Combines the venv, Node binary, and built MCP server. NER and severity models are pre-downloaded so the image is fully self-contained.

## API Endpoints

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `GET` | `/health` | No | Liveness check |
| `GET` | `/health/data` | No | Readiness -- confirms DrugBank MCP connection |
| `POST` | `/analyze` | API key | Extract drugs from OCR text |
| `POST` | `/interactions` | API key | Check interactions for a list of drug names |
| `POST` | `/admin/cache/clear` | API key | Clear all in-memory caches |

## Eval Benchmark

The `eval/` directory contains a benchmark suite that measures NER accuracy on synthesized pharmaceutical pack-label text. See [`eval/BENCHMARK.md`](eval/BENCHMARK.md) for methodology and results.

**Dataset**: 11,796 cases generated from the [MattBastar/Medicine_Details](https://huggingface.co/datasets/MattBastar/Medicine_Details) HuggingFace dataset, with configurable OCR noise levels (clean, light, heavy).

| Pipeline / Noise Level | Precision | Recall | F1 |
|------------------------|-----------|--------|----|
| Bare NER (Clean) | 46.9% | 84.4% | 60.3% |
| Bare NER (Light Noise) | 44.9% | 79.8% | 57.5% |
| Bare NER (Heavy Noise) | 26.2% | 53.5% | 35.2% |
| **Full Pipeline (Clean)** | **71.6%** | **81.0%** | **76.0%** |
| **Full Pipeline (Light Noise)** | **74.4%** | **79.8%** | **77.0%** |
| **Full Pipeline (Heavy Noise)** | **65.6%** | **47.6%** | **55.2%** |

```bash
uv run python eval/prepare_hf_dataset.py           # generate dataset
uv run python eval/benchmark.py --limit 500         # run benchmark
```

## Acknowledgments

- **[OpenMed NER PharmaDetect](https://huggingface.co/OpenMed/OpenMed-NER-PharmaDetect-BioPatient-108M)** -- drug entity recognition model (108M params). License: Apache 2.0
- **[RxNorm REST API](https://lhncbc.nlm.nih.gov/RxNav/APIs/RxNormAPIs.html)** -- drug name normalization and RxCUI mapping. Provided by NLM (free to use).
- **[DrugBank](https://www.drugbank.com/)** -- pharmaceutical database providing structured drug-drug interaction data. Accessed via the [openpharma-org/drugbank-mcp-server](https://github.com/openpharma-org/drugbank-mcp-server) open-source MCP server.
- **[DeBERTa-v3-base-mnli-fever-anli](https://huggingface.co/MoritzLaurer/DeBERTa-v3-base-mnli-fever-anli)** -- zero-shot classifier for interaction severity. License: MIT
- **[Hugging Face Transformers](https://huggingface.co/docs/transformers)** -- NLP pipeline library. License: Apache 2.0
- **[MattBastar/Medicine_Details](https://huggingface.co/datasets/MattBastar/Medicine_Details)** -- benchmark dataset (11.8K medicines with compositions).
