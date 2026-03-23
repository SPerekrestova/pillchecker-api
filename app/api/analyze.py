"""POST /analyze — extract drugs from OCR text."""

from fastapi import APIRouter

from app.api.schemas import AnalyzeDataSources, AnalyzeRequest, AnalyzeResponse, DrugResult
from app.nlp import ner_model
from app.services import drug_analyzer

router = APIRouter()


@router.post("/analyze", response_model=AnalyzeResponse)
async def analyze(request: AnalyzeRequest):
    drugs = await drug_analyzer.analyze(request.text)
    return AnalyzeResponse(
        drugs=[DrugResult(**d) for d in drugs],
        raw_text=request.text,
        data_sources=AnalyzeDataSources(ner_model=ner_model.MODEL_ID),
    )
