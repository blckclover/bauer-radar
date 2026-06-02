"""Reversal Scan / Hunter service — wraps analyzer_core turnaround screener."""

from __future__ import annotations

import re
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from analyzer_core import (  # noqa: E402
    TurnaroundOpportunity,
    fetch_index_constituents_safe,
    find_turnaround_opportunities,
)

from app.schemas.hunter import HunterScanRequest, HunterScanResponse, TurnaroundCandidate
from app.services.analyzer import AnalyzerServiceError, _classify_exception


def _resolve_universe(request: HunterScanRequest) -> tuple[list[str], str, str]:
    if request.universe == "custom":
        tickers = [t.upper().strip() for t in request.tickers if t.strip()]
        seen: set[str] = set()
        ordered: list[str] = []
        for sym in tickers:
            if sym and sym not in seen and re.fullmatch(r"[A-Z][A-Z0-9.\-]{0,9}", sym):
                seen.add(sym)
                ordered.append(sym)
        if not ordered:
            raise AnalyzerServiceError(
                "自訂 universe 需提供至少一個有效 ticker。",
                status_code=400,
                code="invalid_universe",
            )
        return ordered, "custom", "custom"

    tickers, source = fetch_index_constituents_safe(request.universe)
    return tickers, request.universe, source


def _opp_to_candidate(opp: TurnaroundOpportunity) -> TurnaroundCandidate:
    red_flag = False
    if opp.net_debt_ebitda is not None and opp.net_debt_ebitda >= 3.0:
        red_flag = True
    if opp.gross_margin_yoy_change_pp is not None and opp.gross_margin_yoy_change_pp < -5:
        red_flag = True
    if opp.value_defense_score is not None and opp.value_defense_score < 50:
        red_flag = True

    return TurnaroundCandidate(
        symbol=opp.symbol,
        company_name=opp.company_name,
        drawdown_pct=opp.drawdown_pct,
        current_price=opp.current_price,
        six_month_high=opp.six_month_high,
        latest_fcf=opp.latest_fcf,
        latest_fcf_fiscal_year=opp.latest_fcf_fiscal_year,
        fcf_source=opp.fcf_source or "",
        interest_coverage=opp.interest_coverage,
        gross_margin=opp.gross_margin,
        gross_margin_yoy_change_pp=opp.gross_margin_yoy_change_pp,
        net_debt_ebitda=opp.net_debt_ebitda,
        fifty_two_week_high=opp.fifty_two_week_high,
        price_vs_52w_high=opp.price_vs_52w_high,
        peg_ratio=opp.peg_ratio,
        value_defense_score=opp.value_defense_score,
        value_grade_emoji=opp.value_grade_emoji or "",
        value_grade_label=opp.value_grade_label or "",
        reason_tag=opp.reason_tag or "",
        reason_comment=opp.reason_comment or "",
        red_team_flag=red_flag,
    )


def run_hunter_scan(request: HunterScanRequest) -> HunterScanResponse:
    """Execute turnaround scan over index universe or custom ticker list."""
    try:
        tickers, universe_key, source = _resolve_universe(request)
    except AnalyzerServiceError:
        raise
    except Exception as exc:
        raise _classify_exception(exc) from exc

    try:
        raw = find_turnaround_opportunities(
            tickers,
            min_drawdown_pct=float(request.min_drop_percent),
            enrich_scores=request.enrich_scores,
            enrich_tags=request.enrich_tags,
        )
    except Exception as exc:
        raise _classify_exception(exc) from exc

    candidates = [_opp_to_candidate(opp) for opp in raw]
    return HunterScanResponse(
        candidates=candidates,
        scanned_count=len(tickers),
        hit_count=len(candidates),
        universe=universe_key,
        universe_source=source,
        min_drop_percent=float(request.min_drop_percent),
    )
