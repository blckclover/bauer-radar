"""
Bridge to repo-root ``analyzer_core.py`` — all scoring stays in Python.

Adds the repository root to ``sys.path`` so we import the existing module
without duplicating business logic.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Literal

# Repo root (dividend-analyzer/)
_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from analyzer_core import (  # noqa: E402
    FCF_PAYOUT_DEATH_THRESHOLD,
    NET_DEBT_EBITDA_DEATH_THRESHOLD,
    STRATEGY_GROWTH,
    STRATEGY_VALUE,
    StockReport,
    analyze_symbol,
    build_company_narrative,
    is_growth_strategy,
    normalize_strategy_mode,
)

from app.config import settings
from app.schemas.scorecard import (
    AnalyzeResponse,
    FcfHistoryPoint,
    MetricItem,
    NarrativeResponse,
    QualityScore,
    RedTeamFinding,
    ScorecardResult,
    ScoreDimension,
    ValuationScore,
)
from app.services.cache import cache_get, cache_set

StrategyMode = Literal["value", "growth"]

_RATE_LIMIT_PATTERN = re.compile(
    r"429|rate.?limit|resource_exhausted|quota|too many requests",
    re.IGNORECASE,
)


class AnalyzerServiceError(Exception):
    """Raised when upstream analysis fails."""

    def __init__(self, message: str, *, status_code: int = 503, code: str = "analyzer_error"):
        super().__init__(message)
        self.status_code = status_code
        self.code = code


def _normalize_mode(mode: str) -> StrategyMode:
    normalized = normalize_strategy_mode(mode)
    return "growth" if normalized == STRATEGY_GROWTH else "value"


def _slugify_category(category: str) -> str:
    token = re.sub(r"[^\w]+", "-", category.lower()).strip("-")
    return token[:48] or "dimension"


def _fmt_pct(value: float | None, *, signed: bool = False) -> str:
    if value is None:
        return "N/A"
    pct = value * 100.0
    if signed:
        return f"{pct:+.1f}%"
    return f"{pct:.1f}%"


def _build_metrics(report: StockReport, growth: bool) -> list[MetricItem]:
    """Extended master-variable grid for dashboard + stock detail pages."""
    m = report.master

    def _pe() -> MetricItem:
        return MetricItem(
            id="forward-pe",
            label="Forward P/E",
            value=f"{m.forward_pe:.1f}x" if m.forward_pe is not None else "N/A",
            tooltip="Forward 十二個月本益比",
        )

    def _peg() -> MetricItem:
        return MetricItem(
            id="peg",
            label="前瞻 PEG",
            value=f"{m.peg_ratio:.2f}" if m.peg_ratio is not None else "N/A",
            subtext="成長/估值剪刀差",
            tooltip="PEG 剪刀差 · 成長 vs 估值",
        )

    def _fcf_yield() -> MetricItem:
        return MetricItem(
            id="fcf-yield",
            label="FCF Yield",
            value=_fmt_pct(m.fcf_yield),
            tooltip="FCF / 市值",
        )

    def _roic() -> MetricItem:
        return MetricItem(
            id="roic",
            label="ROIC",
            value=_fmt_pct(m.roic),
            tooltip="投入資本回報率",
        )

    def _fcf_payout() -> MetricItem:
        return MetricItem(
            id="fcf-payout",
            label="FCF 支付率",
            value=_fmt_pct(m.fcf_payout_ratio),
            tooltip="股息 / 自由現金流 · >90% 死亡懲罰",
        )

    def _nd_ebitda() -> MetricItem:
        return MetricItem(
            id="nd-ebitda",
            label="淨債務/EBITDA",
            value=f"{float(m.net_debt_ebitda):.1f}x" if m.net_debt_ebitda is not None else "N/A",
            tooltip="槓桿安全線 · >3.0x 死亡懲罰",
        )

    def _rev_cagr() -> MetricItem:
        return MetricItem(
            id="rev-cagr-5y",
            label="5Y 營收 CAGR",
            value=_fmt_pct(m.revenue_cagr_5y, signed=True)
            if m.revenue_cagr_5y is not None
            else "N/A",
            tooltip="五年營收複合年增率",
        )

    if growth:
        return [
            _pe(),
            _peg(),
            MetricItem(
                id="capex",
                label="CapEx 擴張率",
                value=_fmt_pct(m.capex_growth, signed=True)
                if m.capex_growth is not None
                else "N/A",
                subtext="季 YoY · 產業擴張",
            ),
            MetricItem(
                id="surprise",
                label="近一季 Surprise",
                value=_fmt_pct(m.surprise_latest_pct, signed=True)
                if m.surprise_latest_pct is not None
                else "—",
                subtext=f"連續超預期 {m.surprise_beat_streak} 季",
            ),
            MetricItem(
                id="gross",
                label="毛利率",
                value=_fmt_pct(m.gross_margins),
                subtext="定價權 proxy",
            ),
            _fcf_yield(),
            _nd_ebitda(),
        ]

    return [
        _pe(),
        _peg(),
        _fcf_yield(),
        _roic(),
        _fcf_payout(),
        _nd_ebitda(),
        _rev_cagr(),
    ]


def _build_dimensions(report: StockReport) -> list[ScoreDimension]:
    dimensions: list[ScoreDimension] = []
    for detail in report.score_details:
        if detail.max_points <= 0:
            continue
        weight_pct = detail.max_points  # component max ≈ weight in 100-pt scale
        dimensions.append(
            ScoreDimension(
                id=_slugify_category(detail.category),
                label=detail.category,
                earned=float(detail.earned or 0.0),
                max_points=float(detail.max_points or 0.0),
                weight_pct=weight_pct,
                rationale=detail.rationale or None,
            )
        )
    return dimensions


def _build_red_team_findings(report: StockReport) -> list[RedTeamFinding]:
    findings: list[RedTeamFinding] = []
    m = report.master
    quality = report.business_quality_score or report.total_score
    valuation = report.valuation_safety_score

    if not is_growth_strategy(report.strategy_mode):
        if m.net_debt_ebitda is not None and m.net_debt_ebitda > NET_DEBT_EBITDA_DEATH_THRESHOLD:
            findings.append(
                RedTeamFinding(
                    id="death-nd-ebitda",
                    severity="critical",
                    title="債務槓桿嚴重超標",
                    description=(
                        "淨債務/EBITDA 超過死亡門檻，觸發財務安全一票否決，"
                        "企業品質分強制封頂。"
                    ),
                    metric=f"Net Debt/EBITDA {m.net_debt_ebitda:.1f}x",
                )
            )
        if m.fcf_payout_ratio is not None and m.fcf_payout_ratio > FCF_PAYOUT_DEATH_THRESHOLD:
            findings.append(
                RedTeamFinding(
                    id="death-fcf-payout",
                    severity="critical",
                    title="FCF 支付率透支",
                    description="FCF 支付率超過 90%，觸發現金流一票否決。",
                    metric=f"FCF Payout {m.fcf_payout_ratio * 100:.1f}%",
                )
            )

    if quality >= 70 and valuation < 50:
        findings.append(
            RedTeamFinding(
                id="valuation-trap",
                severity="warning",
                title="估值透支風險",
                description="品質極優但估值過高，需警惕「偉大公司買太貴」陷阱。",
                metric=f"Quality {quality:.1f} / Valuation {valuation:.1f}",
            )
        )

    if m.operating_margin_red_flag and m.operating_margin_red_flag_msg:
        findings.append(
            RedTeamFinding(
                id="om-red-flag",
                severity="warning",
                title="營業利益率紅旗",
                description=m.operating_margin_red_flag_msg,
            )
        )

    if m.capex_red_flag and m.capex_red_flag_msg:
        findings.append(
            RedTeamFinding(
                id="capex-red-flag",
                severity="warning",
                title="CapEx 雙面刃",
                description=m.capex_red_flag_msg,
            )
        )

    trend = report.trend_signal or {}
    if is_growth_strategy(report.strategy_mode) and trend.get("current_signal") == "bullish":
        findings.append(
            RedTeamFinding(
                id="timing-bullish",
                severity="info",
                title="右側結構確立",
                description="價格站上中期均線群，呈現右側動能結構。",
            )
        )

    return findings


def _build_fcf_history(report: StockReport) -> list[FcfHistoryPoint]:
    points: list[FcfHistoryPoint] = []
    for row in report.fcf_history or []:
        points.append(
            FcfHistoryPoint(
                fiscal_year=int(row.fiscal_year),
                free_cash_flow=float(row.free_cash_flow),
                period_end=str(row.period_end or ""),
                source=str(row.source or ""),
            )
        )
    return points


def _report_to_scorecard(report: StockReport) -> ScorecardResult:
    mode = _normalize_mode(report.strategy_mode)
    growth = mode == "growth"
    return ScorecardResult(
        symbol=report.symbol,
        company_name=report.company_name or report.symbol,
        strategy_mode=mode,
        quality=QualityScore(
            value=float(report.business_quality_score or report.total_score or 0.0),
            max=100.0,
            label="企業品質分",
            grade=report.grade_label or "",
            grade_emoji=report.grade_emoji or "",
        ),
        valuation=ValuationScore(
            value=float(report.valuation_safety_score or 0.0),
            max=100.0,
            label="估值安全邊際",
        ),
        dimensions=_build_dimensions(report),
        metrics=_build_metrics(report, growth),
    )


def _classify_exception(exc: Exception) -> AnalyzerServiceError:
    msg = str(exc)
    if _RATE_LIMIT_PATTERN.search(msg):
        return AnalyzerServiceError(
            "AI 伺服器目前擁擠（429），請稍後重試。",
            status_code=429,
            code="rate_limit",
        )
    if "timeout" in msg.lower() or "timed out" in msg.lower():
        return AnalyzerServiceError(
            "資料來源連線逾時，請稍後重試。",
            status_code=504,
            code="timeout",
        )
    return AnalyzerServiceError(
        f"分析失敗：{msg}",
        status_code=503,
        code="analyzer_error",
    )


def analyze_ticker(ticker: str, *, mode: str = STRATEGY_VALUE) -> AnalyzeResponse:
    """Run full ``analyze_symbol`` pipeline and map to API schema."""
    sym = ticker.upper().strip()
    if not sym or not re.fullmatch(r"[A-Z][A-Z0-9.\-]{0,9}", sym):
        raise AnalyzerServiceError("無效的股票代號。", status_code=400, code="invalid_ticker")

    strategy = normalize_strategy_mode(mode)
    cache_key = f"analyze:{sym}:{strategy}"
    if settings.enable_analyze_cache:
        cached = cache_get(cache_key)
        if isinstance(cached, AnalyzeResponse):
            return cached.model_copy(update={"data_source": "cache"})

    try:
        report = analyze_symbol(sym, strategy_mode=strategy)
    except Exception as exc:
        raise _classify_exception(exc) from exc

    commentary = (report.analyst_commentary or "").strip() or None
    if commentary and _RATE_LIMIT_PATTERN.search(commentary):
        commentary = None

    response = AnalyzeResponse(
        scorecard=_report_to_scorecard(report),
        red_team_findings=_build_red_team_findings(report),
        analyst_commentary=commentary,
        fcf_history=_build_fcf_history(report),
        data_source="live",
    )

    if settings.enable_analyze_cache:
        cache_set(cache_key, response, ttl_seconds=settings.cache_ttl_seconds)

    return response


def get_narrative(ticker: str, *, mode: str = STRATEGY_VALUE) -> NarrativeResponse:
    """Generate company narrative via ``build_company_narrative``."""
    sym = ticker.upper().strip()
    if not sym or not re.fullmatch(r"[A-Z][A-Z0-9.\-]{0,9}", sym):
        raise AnalyzerServiceError("無效的股票代號。", status_code=400, code="invalid_ticker")

    strategy = normalize_strategy_mode(mode)
    try:
        result = build_company_narrative(sym, strategy_mode=strategy)
    except Exception as exc:
        raise _classify_exception(exc) from exc

    text = (result.text or "").strip()
    if _RATE_LIMIT_PATTERN.search(text) or text.startswith("⚠️"):
        text = ""

    return NarrativeResponse(
        symbol=sym,
        text=text,
        live_news_degraded=bool(result.live_news_degraded),
        strategy_mode=_normalize_mode(strategy),
    )
