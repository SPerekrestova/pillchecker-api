"""POST /analyze — extract drugs from OCR text."""

import re

from fastapi import APIRouter

from app.api.schemas import AnalyzeDataSources, AnalyzeRequest, AnalyzeResponse, DrugResult
from app.nlp import ner_model
from app.services import drug_analyzer

router = APIRouter()

_HTML_TAG = re.compile(r"<[^>]+>")


def _is_predominantly_non_latin(text: str) -> bool:
    """Check if the alphabetic characters are mostly non-Latin."""
    alpha_chars = [c for c in text if c.isalpha()]
    if not alpha_chars:
        return False
    latin_count = sum(1 for c in alpha_chars if c.isascii())
    return (latin_count / len(alpha_chars)) < 0.3


from app.main import limiter
from fastapi import Request

@router.post("/analyze", response_model=AnalyzeResponse)
@limiter.limit("10/minute")
async def analyze(request: AnalyzeRequest, fast_request: Request):
    note = None

    if _is_predominantly_non_latin(request.text):
        drugs = []
        note = "Non-Latin text detected; only Latin-script drug names are supported"
    else:
        drugs = await drug_analyzer.analyze(request.text)

    return AnalyzeResponse(
        drugs=[DrugResult(**d) for d in drugs],
        raw_text=_HTML_TAG.sub("", request.text),
        data_sources=AnalyzeDataSources(ner_model=ner_model.MODEL_ID),
        note=note,
    )
