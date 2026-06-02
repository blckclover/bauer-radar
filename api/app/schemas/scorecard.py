"""Pydantic response schemas — keep in sync with web/types/index.ts."""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class ApiModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        from_attributes=True,
    )


class QualityScore(ApiModel):
    value: float = 0.0
    max: float = 100.0
    label: str = "企業品質分"
    grade: str = ""
    grade_emoji: str = ""


class ValuationScore(ApiModel):
    value: float = 0.0
    max: float = 100.0
    label: str = "估值安全邊際"


class ScoreDimension(ApiModel):
    id: str
    label: str
    earned: float = 0.0
    max_points: float = Field(default=0.0, alias="maxPoints")
    weight_pct: float = Field(default=0.0, alias="weightPct")
    rationale: Optional[str] = None


class MetricItem(ApiModel):
    id: str
    label: str
    value: str = "N/A"
    subtext: Optional[str] = None
    tooltip: Optional[str] = None


class FcfHistoryPoint(ApiModel):
    fiscal_year: int
    free_cash_flow: float
    period_end: str = ""
    source: str = ""


RedTeamSeverity = Literal["critical", "warning", "info"]


class RedTeamFinding(ApiModel):
    id: str
    severity: RedTeamSeverity = "info"
    title: str
    description: str
    metric: Optional[str] = None


class ScorecardResult(ApiModel):
    symbol: str
    company_name: str = Field(default="", alias="companyName")
    strategy_mode: Literal["value", "growth"] = Field(default="value", alias="strategyMode")
    quality: QualityScore = Field(default_factory=QualityScore)
    valuation: ValuationScore = Field(default_factory=ValuationScore)
    dimensions: list[ScoreDimension] = Field(default_factory=list)
    metrics: list[MetricItem] = Field(default_factory=list)


class AnalyzeResponse(ApiModel):
    scorecard: ScorecardResult
    red_team_findings: list[RedTeamFinding] = Field(default_factory=list, alias="redTeamFindings")
    analyst_commentary: Optional[str] = Field(default=None, alias="analystCommentary")
    fcf_history: list[FcfHistoryPoint] = Field(default_factory=list, alias="fcfHistory")
    data_source: Literal["live", "cache", "mock"] = Field(default="live", alias="dataSource")


class NarrativeResponse(ApiModel):
    symbol: str
    text: str = ""
    live_news_degraded: bool = Field(default=False, alias="liveNewsDegraded")
    strategy_mode: Literal["value", "growth"] = Field(default="value", alias="strategyMode")


class ErrorResponse(ApiModel):
    detail: str
    code: Optional[str] = None
