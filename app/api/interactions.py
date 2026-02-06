"""POST /interactions — check drug-drug interactions."""

from fastapi import APIRouter

from app.api.schemas import InteractionsRequest, InteractionsResponse
from app.services import interaction_checker

router = APIRouter()


@router.post("/interactions", response_model=InteractionsResponse)
async def check_interactions(request: InteractionsRequest):
    result = interaction_checker.check(request.drugs)
    return InteractionsResponse(**result)
