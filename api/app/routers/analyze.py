from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException, Query

from app.schemas.scorecard import AnalyzeResponse, ErrorResponse, NarrativeResponse
from app.services.analyzer import AnalyzerServiceError, analyze_ticker, get_narrative

router = APIRouter(prefix="/analyze", tags=["analyze"])

StrategyQuery = Literal["value", "growth"]


@router.get(
    "/{ticker}",
    response_model=AnalyzeResponse,
    responses={
        400: {"model": ErrorResponse},
        429: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
        504: {"model": ErrorResponse},
    },
    summary="Analyze a single ticker",
    description="Run dual-track Business Quality + Valuation Safety scoring.",
)
def analyze_endpoint(
    ticker: str,
    mode: StrategyQuery = Query(default="value", description="value | growth"),
) -> AnalyzeResponse:
    try:
        return analyze_ticker(ticker, mode=mode)
    except AnalyzerServiceError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={"detail": str(exc), "code": exc.code},
        ) from exc
