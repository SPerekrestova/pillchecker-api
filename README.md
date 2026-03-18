# PillChecker API

PillChecker helps users find out if two medications are safe to take at the same time. This repository contains the backend API that identifies drugs from OCR text and checks for dangerous interactions using DrugBank pharmaceutical data.

> **⚠️ MEDICAL DISCLAIMER**
>
> This service is provided for **informational and self-educational purposes only**. While the application utilizes data from respected pharmaceutical sources, the information provided should **not** be treated as medical advice, diagnosis, or treatment.
>
> The developer of this project **does not have any medical qualifications**. This tool was built as a technical exercise to explore NLP and medical data integration.
>
> **Always consult with a qualified healthcare professional** (such as a doctor or pharmacist) before making any decisions regarding your medications or health. The developer assumes **no responsibility or liability** for any errors, omissions, or consequences arising from the use of the information provided by this service.

## Architecture

### Drug Identification

Converts unstructured OCR text into standardized drug records using a two-pass strategy:

1. **NER**: The **[OpenMed-NER-PharmaDetect](https://huggingface.co/OpenMed/OpenMed-NER-PharmaDetect-ModernClinical-149M)** model (149M parameters) extracts chemical entity names from noisy text.
2. **Fallback**: If NER yields no results, an approximate term search via the **RxNorm REST API** catches brand names (e.g., "Advil" → ibuprofen).
3. **Enrichment**: A regex parser extracts dosages (e.g., "400 mg"), and the RxNorm API maps every identified drug to its **RxCUI** for standardized downstream lookups.

### Interaction Checking

Drug–drug interactions are resolved against the **DrugBank** pharmaceutical database via a vendored MCP server:

1. **DrugBank MCP server**: A Node.js process (vendored under `drugbank-mcp-server/`) communicates over stdio using the Model Context Protocol. It serves a pre-built SQLite database (~19,800 drugs) with structured pairwise interaction data.
2. **Bidirectional lookup**: For each drug pair, the checker queries both directions (A→B and B→A) in parallel using `asyncio.gather()`.
3. **Severity classification**: Interaction descriptions are classified as *major*, *moderate*, or *minor* by a **DeBERTa v3** zero-shot model, with a regex fallback for descriptions containing explicit severity keywords.
4. **Caching**: Drug interaction records are cached in-process for 24 hours to avoid repeated MCP round-trips.

### Docker Build

The image uses a three-stage build to keep layers small and reproducible:

- **Stage 1 (Python)**: `uv` installs Python dependencies into an isolated venv.
- **Stage 2 (Node.js)**: `npm ci` installs Node dependencies; the DrugBank SQLite database is downloaded from GitHub Releases.
- **Stage 3 (Runtime)**: Combines the venv, Node binary, and built MCP server. NER and severity models are pre-downloaded so the image is fully self-contained.

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Liveness check |
| `GET` | `/health/data` | Readiness — confirms DrugBank MCP connection |
| `POST` | `/analyze` | Extract drugs from OCR text |
| `POST` | `/interactions` | Check interactions for a list of drug names |

## Acknowledgments

- **[OpenMed NER PharmaDetect](https://huggingface.co/OpenMed/OpenMed-NER-PharmaDetect-ModernClinical-149M)** — drug entity recognition model. License: Apache 2.0
- **[RxNorm REST API](https://lhncbc.nlm.nih.gov/RxNav/APIs/RxNormAPIs.html)** — drug name normalization and RxCUI mapping. Provided by NLM (free to use).
- **[DrugBank](https://www.drugbank.com/)** — pharmaceutical database providing structured drug–drug interaction data. Accessed via the [openpharma-org/drugbank-mcp-server](https://github.com/openpharma-org/drugbank-mcp-server) open-source MCP server.
- **[DeBERTa-v3-base-mnli-fever-anli](https://huggingface.co/MoritzLaurer/DeBERTa-v3-base-mnli-fever-anli)** — zero-shot classifier for interaction severity. License: MIT
- **[Hugging Face Transformers](https://huggingface.co/docs/transformers)** — NLP pipeline library. License: Apache 2.0
