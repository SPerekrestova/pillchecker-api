"""POST /interactions — check drug-drug interactions."""

from fastapi import APIRouter

from app.api.schemas import InteractionsDataSources, InteractionsRequest, InteractionsResponse
from app.nlp import severity_classifier
from app.services import interaction_checker

router = APIRouter()


from app.main import limiter
from fastapi import Request

@router.post("/interactions", response_model=InteractionsResponse)
@limiter.limit("10/minute")
async def check_interactions(request: Request, body: InteractionsRequest):
    result = await interaction_checker.check(body.drugs)
    return InteractionsResponse(
        **result,
        data_sources=InteractionsDataSources(
            severity_classifier=severity_classifier.MODEL_ID,
        ),
    )
