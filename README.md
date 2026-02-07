# PillChecker API

PillChecker helps users find out if two medications are safe to take at the same time. This repository contains the backend API that identifies drugs and checks for dangerous interactions using official FDA data for the PillChecker mobile app.

> **⚠️ MEDICAL DISCLAIMER**
> 
> This service is provided for **informational and self-educational purposes only**. While the application utilizes data from respected sources such as the FDA and RxNorm, the information provided should **not** be treated as medical advice, diagnosis, or treatment.
> 
> The developer of this project **does not have any medical qualifications**. This tool was built as a technical exercise to explore NLP and medical data integration.
> 
> **Always consult with a qualified healthcare professional** (such as a doctor or pharmacist) before making any decisions regarding your medications or health. The developer assumes **no responsibility or liability** for any errors, omissions, or consequences arising from the use of the information provided by this service.

## Data Pipeline

To ensure a license-free and up-to-date knowledge base, the application uses an automated pipeline:

1.  **Fetch**: A sync script downloads bulk JSON drug label partitions directly from the **OpenFDA** public domain repository.
2.  **Parse**: The script extracts specific Structured Product Labeling (SPL) fields: `drug_interactions`, `contraindications`, and `warnings`.
3.  **Store**: These structured text blocks are stored in a local **SQLite** database (`data/fda_interactions.db`) indexed by RxCUI and Drug Name.
4.  **Runtime Inference**: During a check, the engine performs a keyword scan across sections. If a match is found in the `contraindications` section, it is categorized as **Major**; matches in `interactions` or `warnings` are categorized as **Moderate/Minor**.
5.  **Automate**: The pipeline is triggered weekly via GitHub Actions and auto-bootstraps during the first deployment via a Docker entrypoint script.

## Drug Identification Pipeline

The API uses a two-pass identification strategy to convert unstructured OCR text into standardized medical data:

1.  **Pass 1 (NER)**: Uses the **[OpenMed-NER-PharmaDetect](https://huggingface.co/OpenMed/OpenMed-NER-PharmaDetect-ModernClinical-149M)** model (a 149M parameter transformer) from Hugging Face to extract chemical entities (e.g., "Ibuprofen") from noisy text.
2.  **Pass 2 (Fallback)**: If NER fails to find a drug, the system performs an approximate term search using the **RxNorm REST API** on major text blocks to identify brand names (e.g., "Advil").
3.  **Enrichment**: A **Regex-based parser** extracts dosages (e.g., "400mg") and strengths, while the **RxNorm API** links all identified drugs to their **RxCUI** for accurate interaction checking.

## Acknowledgments

This project relies on several high-quality external data sources and models:

- **OpenMed NER PharmaDetect (ModernClinical-149M)**: State-of-the-art medical entity recognition model used for identifying drug names in text.
  - [Model Link](https://huggingface.co/OpenMed/OpenMed-NER-PharmaDetect-ModernClinical-149M)
  - **License**: Apache 2.0

- **RxNorm REST API**: Provided by the National Library of Medicine (NLM), used for drug name normalization and RxCUI mapping.
  - [API Documentation](https://lhncbc.nlm.nih.gov/RxNav/APIs/RxNormAPIs.html)
  - **License**: Free to use (refer to NLM Terms of Service)

- **OpenFDA**: Primary source for Drug-Drug Interaction (DDI) data, sourced directly from Structured Product Labeling (SPL).
  - [OpenFDA Website](https://open.fda.gov/)
  - **License**: **Public Domain** (US Government)

- **Hugging Face Transformers**: Library used to run the NER model and NLP pipeline.
  - [Documentation](https://huggingface.co/docs/transformers/index)
  - **License**: Apache 2.0
