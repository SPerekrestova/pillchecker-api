"""Pydantic request/response models for the PillChecker API."""

from pydantic import BaseModel, Field


# --- POST /analyze ---

class AnalyzeRequest(BaseModel):
    text: str = Field(..., min_length=1, examples=["BRUFEN Ibuprofen 400 mg Film-Coated Tablets"])


class DrugResult(BaseModel):
    rxcui: str | None
    name: str
    dosage: str | None
    form: str | None
    source: str  # "ner" or "rxnorm_fallback"
    confidence: float
    needs_confirmation: bool = False


class AnalyzeDataSources(BaseModel):
    ner_model: str


class AnalyzeResponse(BaseModel):
    drugs: list[DrugResult]
    raw_text: str
    data_sources: AnalyzeDataSources | None = None
    note: str | None = None


# --- POST /interactions ---

class InteractionsRequest(BaseModel):
    drugs: list[str] = Field(..., min_length=2, examples=[["ibuprofen", "warfarin"]])


class DrugRef(BaseModel):
    name: str


class InteractionResult(BaseModel):
    drug_a: str
    drug_b: str
    severity: str
    description: str
    management: str
    uncertain: bool = False


class InteractionsDataSources(BaseModel):
    drugbank_version: str | None = None
    severity_classifier: str


_INTERACTION_LIMITATIONS = [
    "Checks pairwise interactions only — multi-drug cascades are not detected",
    "Does not account for patient-specific factors (age, weight, renal/hepatic function, genetics)",
    "Coverage depends on DrugBank database scope (~19,800 drugs)",
    "Not a substitute for professional medical advice",
]


class InteractionsResponse(BaseModel):
    interactions: list[InteractionResult]
    safe: bool | None
    error: str | None = None
    data_sources: InteractionsDataSources | None = None
    limitations: list[str] = _INTERACTION_LIMITATIONS
