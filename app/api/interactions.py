"""POST /interactions — check drug-drug interactions."""

from fastapi import APIRouter

from app.api.schemas import InteractionsDataSources, InteractionsRequest, InteractionsResponse
from app.nlp import severity_classifier
from app.services import interaction_checker

router = APIRouter()


@router.post("/interactions", response_model=InteractionsResponse)
async def check_interactions(request: InteractionsRequest):
    result = await interaction_checker.check(request.drugs)
    return InteractionsResponse(
        **result,
        data_sources=InteractionsDataSources(
            severity_classifier=severity_classifier.MODEL_ID,
        ),
    )
