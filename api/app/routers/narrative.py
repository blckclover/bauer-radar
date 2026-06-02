from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException, Query

from app.schemas.scorecard import ErrorResponse, NarrativeResponse
from app.services.analyzer import AnalyzerServiceError, get_narrative

router = APIRouter(prefix="/narrative", tags=["narrative"])

StrategyQuery = Literal["value", "growth"]


@router.get(
    "/{ticker}",
    response_model=NarrativeResponse,
    responses={
        400: {"model": ErrorResponse},
        429: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
        504: {"model": ErrorResponse},
    },
    summary="Company tech narrative",
    description="Value: static business summary. Growth: live-news fusion.",
)
def narrative_endpoint(
    ticker: str,
    mode: StrategyQuery = Query(default="value", description="value | growth"),
) -> NarrativeResponse:
    try:
        return get_narrative(ticker, mode=mode)
    except AnalyzerServiceError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={"detail": str(exc), "code": exc.code},
        ) from exc
