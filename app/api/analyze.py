"""POST /analyze — extract drugs from OCR text."""

from fastapi import APIRouter

from app.api.schemas import AnalyzeRequest, AnalyzeResponse, DrugResult
from app.services import drug_analyzer

router = APIRouter()


@router.post("/analyze", response_model=AnalyzeResponse)
async def analyze(request: AnalyzeRequest):
    drugs = await drug_analyzer.analyze(request.text)
    return AnalyzeResponse(
        drugs=[DrugResult(**d) for d in drugs],
        raw_text=request.text,
    )
