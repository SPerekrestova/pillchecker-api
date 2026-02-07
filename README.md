# PillChecker API

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

- **Google ML Kit**: Used for high-performance on-device OCR in the mobile client.
  - [Documentation](https://developers.google.com/ml-kit)
  - **License**: Proprietary (Free for use)

- **PaddleOCR**: Used as a robust server-side fallback for complex text extraction.
  - [Project Link](https://github.com/PaddlePaddle/PaddleOCR)
  - **License**: Apache 2.0

- **FastAPI**: High-performance web framework used for the API layer.
  - [Project Link](https://fastapi.tiangolo.com/)
  - **License**: MIT
