"""POST /interactions — check drug-drug interactions."""

from fastapi import APIRouter, Request

from app.api.schemas import DDInterDataSource, InteractionsDataSources, InteractionsRequest, InteractionsResponse
from app.main import limiter
from app.nlp import severity_classifier
from app.services import interaction_checker

router = APIRouter()

@router.post("/interactions", response_model=InteractionsResponse)
@limiter.limit("10/minute")
async def check_interactions(request: Request, body: InteractionsRequest):
    result = await interaction_checker.check(body.drugs)
    return InteractionsResponse(
        **result,
        data_sources=InteractionsDataSources(
            ddinter=DDInterDataSource(
                version="2.0",
                license="CC BY-NC-SA 4.0",
                attribution_url="https://ddinter2.scbdd.com/",
            ),
            severity_classifier=severity_classifier.MODEL_ID,
        ),
    )
