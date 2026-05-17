"""Pydantic request/response models for the PillChecker API."""

from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints


# --- POST /analyze ---

class AnalyzeRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=5000, examples=["BRUFEN Ibuprofen 400 mg Film-Coated Tablets"])


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
    drugs: list[Annotated[str, StringConstraints(min_length=1, max_length=200, strip_whitespace=True)]] = Field(
        ..., min_length=2, examples=[["ibuprofen", "warfarin"]]
    )


class DrugRef(BaseModel):
    name: str


class InteractionResult(BaseModel):
    drug_a: str
    drug_b: str
    rxcui_a: str | None = None
    rxcui_b: str | None = None
    severity: str
    source: Literal["ddinter", "openfda"]
    description: str
    management: str
    uncertain: bool = False


class DDInterDataSource(BaseModel):
    version: str
    license: str
    attribution_url: str


class InteractionsDataSources(BaseModel):
    ddinter: DDInterDataSource | None = None
    severity_classifier: str


_INTERACTION_LIMITATIONS = [
    "Checks pairwise interactions only — multi-drug cascades are not detected",
    "Does not account for patient-specific factors (age, weight, renal/hepatic function, genetics)",
    "Coverage depends on the DDInter 2.0 corpus and OpenFDA labels",
    "Not a substitute for professional medical advice",
]


class InteractionsResponse(BaseModel):
    interactions: list[InteractionResult]
    safe: bool | None
    error: str | None = None
    data_sources: InteractionsDataSources | None = None
    coverage_summary: dict[str, int] = Field(default_factory=lambda: {"ddinter": 0, "openfda": 0, "unknown": 0})
    limitations: list[str] = _INTERACTION_LIMITATIONS
