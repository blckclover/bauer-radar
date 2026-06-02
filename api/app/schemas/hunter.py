"""Hunter / Reversal Scan schemas."""

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


UniverseKey = Literal["dow30", "sp500", "nasdaq100", "custom"]


class HunterScanRequest(ApiModel):
    universe: UniverseKey = "dow30"
    tickers: list[str] = Field(default_factory=list)
    mode: Literal["value", "growth"] = "value"
    min_drop_percent: float = Field(default=15.0, ge=5.0, le=60.0)
    enrich_scores: bool = True
    enrich_tags: bool = False


class TurnaroundCandidate(ApiModel):
    symbol: str
    company_name: str = ""
    drawdown_pct: float = 0.0
    current_price: float = 0.0
    six_month_high: float = 0.0
    latest_fcf: float = 0.0
    latest_fcf_fiscal_year: Optional[int] = None
    fcf_source: str = ""
    interest_coverage: Optional[float] = None
    gross_margin: Optional[float] = None
    gross_margin_yoy_change_pp: Optional[float] = None
    net_debt_ebitda: Optional[float] = None
    fifty_two_week_high: Optional[float] = None
    price_vs_52w_high: Optional[float] = None
    peg_ratio: Optional[float] = None
    value_defense_score: Optional[float] = None
    value_grade_emoji: str = ""
    value_grade_label: str = ""
    reason_tag: str = ""
    reason_comment: str = ""
    red_team_flag: bool = False


class HunterScanResponse(ApiModel):
    candidates: list[TurnaroundCandidate] = Field(default_factory=list)
    scanned_count: int = 0
    hit_count: int = 0
    universe: str = ""
    universe_source: str = ""
    min_drop_percent: float = 15.0


class HunterScanTaskCreated(ApiModel):
    task_id: str


class HunterTaskStatus(ApiModel):
    task_id: str
    status: Literal["pending", "running", "completed", "failed", "cancelled"]
    progress: int = 0
    message: str = ""
    result: Optional[HunterScanResponse] = None
    error: Optional[str] = None
    error_code: Optional[str] = None
    updated_at: Optional[str] = None
