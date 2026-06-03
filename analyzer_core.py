"""Core dividend / FCF analysis with 100-point safety scoring."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from io import StringIO

import pandas as pd
import requests
import streamlit as st
import yfinance as yf

# Neutral default universe for CLI / cron when no custom list is supplied
DEFAULT_SCAN_UNIVERSE: tuple[str, ...] = (
    "AAPL",
    "MSFT",
    "NVDA",
    "JNJ",
    "KO",
    "INTC",
    "BA",
    "DIS",
)

YEARS_REQUIRED = 5
WEIGHT_FCF = 40.0
WEIGHT_DIV = 30.0
WEIGHT_PAYOUT = 20.0
WEIGHT_BETA = 10.0
STRATEGY_VALUE = "value"
STRATEGY_GROWTH = "growth"
STRATEGY_LABEL_VALUE = "🛡️ 價值防禦模式 (長線穩定、現金流、股息)"
STRATEGY_LABEL_GROWTH = "🚀 動能成長模式 (波段趨勢、技術面、科技願景)"
STRATEGY_LABELS: tuple[str, ...] = (STRATEGY_LABEL_VALUE, STRATEGY_LABEL_GROWTH)
STRATEGY_LABEL_TO_MODE: dict[str, str] = {
    STRATEGY_LABEL_VALUE: STRATEGY_VALUE,
    STRATEGY_LABEL_GROWTH: STRATEGY_GROWTH,
}

# Red Team Protocol — no score may imply absolute safety above this cap
SCORE_CAP = 95.0
VALUATION_TRAP_QUALITY_MIN = 70.0
VALUATION_TRAP_SAFETY_MAX = 50.0

# --- Master-grade scoring weights (DGI value defence — master asymmetric model) ---
# 🛡️ Value defence — 35 / 25 / 25 / 15 with death penalties
WEIGHT_VALUE_QUALITY = 35.0     # ROIC + gross-margin stability + operating margin
WEIGHT_VALUE_SAFETY = 25.0      # Net Debt/EBITDA + interest coverage
WEIGHT_VALUE_CASHFLOW = 25.0    # FCF payout ratio + dividend growth streak
WEIGHT_VALUE_REVENUE = 15.0     # 5Y revenue CAGR / revenue stability floor
# Asymmetric death-penalty thresholds (value mode only)
NET_DEBT_EBITDA_DEATH_THRESHOLD = 3.0
FCF_PAYOUT_DEATH_THRESHOLD = 0.90
VALUE_SCORE_DEATH_CAP = 69.0
FCF_PAYOUT_EXTRA_PENALTY = 10.0
# Turnaround radar — anti-bankruptcy gate (shared with death penalty)
NET_DEBT_EBITDA_MAX = 3.0
# 🚀 Growth momentum — nerfed technicals; quality vs valuation split
WEIGHT_GROWTH_FUNDAMENTAL = 30.0   # revenue / CapEx fundamental growth
WEIGHT_GROWTH_SURPRISE = 25.0      # EPS surprise / revision
WEIGHT_GROWTH_PEG_VAL = 25.0       # PEG relative-growth valuation
WEIGHT_GROWTH_TECH_TIMING = 15.0   # SMA timing auxiliary only (demoted)
WEIGHT_GROWTH_RISK_BUFFER = 5.0    # leverage / red-flag risk cushion (quality track)
# Legacy aliases (backward compat for helpers)
WEIGHT_GROWTH_FORWARD = WEIGHT_GROWTH_FUNDAMENTAL + WEIGHT_GROWTH_PEG_VAL
WEIGHT_GROWTH_MOMENTUM = WEIGHT_GROWTH_TECH_TIMING

# Legacy growth weights retained for backward-compatible helpers
WEIGHT_GROWTH_REVENUE = 40.0
WEIGHT_GROWTH_BETA = 20.0
PENALTY_FCF_PER_YEAR = 10.0
PENALTY_DIV_PER_YEAR = 8.0

# CapEx (capital expenditure) rows in yfinance quarterly cash-flow statements
CAPEX_CF_ROW_NAMES = (
    "Capital Expenditure",
    "CapitalExpenditures",
    "Capital Expenditures",
    "PurchaseOfPPE",
)
EARNINGS_SURPRISE_LOOKBACK = 8

SEC_USER_AGENT = "DividendAnalyzer/3.0 (research@example.com)"
SEC_HEADERS = {"User-Agent": SEC_USER_AGENT}
OCF_TAG = "NetCashProvidedByUsedInOperatingActivities"
CAPEX_TAGS = (
    "PaymentsToAcquirePropertyPlantAndEquipment",
    "PaymentsToAcquireProductiveAssets",
)

# Turnaround — anti-value-trap: reject shrinking core businesses
TURNAROUND_LOOKBACK = "6mo"
TURNAROUND_MIN_DRAWDOWN_PCT = 15.0
TURNAROUND_REVENUE_CAGR_YEARS = 3
TURNAROUND_STRUCTURAL_GM_DECLINE_PP = 5.0
# Sector gross-margin median proxies (%, TTM) — anti structural decay vs peers
SECTOR_GROSS_MARGIN_MEDIAN_PCT: dict[str, float] = {
    "Technology": 55.0,
    "Healthcare": 58.0,
    "Financial Services": 45.0,
    "Consumer Cyclical": 38.0,
    "Consumer Defensive": 32.0,
    "Industrials": 28.0,
    "Energy": 25.0,
    "Utilities": 35.0,
    "Real Estate": 50.0,
    "Communication Services": 48.0,
    "Basic Materials": 22.0,
}
DEFAULT_SECTOR_GM_MEDIAN_PCT = 35.0
# Valuation attractiveness — price vs 52-week high OR trailing PEG
TURNAROUND_52W_HIGH_RATIO_MAX = 0.75   # current / 52w high < 0.75 → ≥25% off highs
TURNAROUND_PEG_MAX = 1.5
RND_ROW_NAMES = (
    "ResearchAndDevelopment",
    "Research And Development",
    "ResearchAndDevelopmentExpense",
    "ResearchAndDevelopmentExpenseExcludingAcquiredInProcessCost",
)

# Institutional defensive filters appended to the reversal radar
INTEREST_COVERAGE_MIN = 3.0
# Max allowed YoY gross-margin contraction in percentage points before a
# ticker is treated as having lost pricing power.
GROSS_MARGIN_YOY_MAX_DECLINE_PP = 5.0
EBIT_ROW_NAMES = (
    "EBIT",
    "Ebit",
    "OperatingIncome",
    "Operating Income",
    "NormalizedEBITDA",
)
INTEREST_EXPENSE_ROW_NAMES = (
    "InterestExpense",
    "Interest Expense",
    "InterestExpenseNonOperating",
    "NetInterestIncome",
)
GROSS_PROFIT_ROW_NAMES = (
    "GrossProfit",
    "Gross Profit",
)
TOTAL_REVENUE_ROW_NAMES = (
    "TotalRevenue",
    "Total Revenue",
    "OperatingRevenue",
)
EBITDA_ROW_NAMES = (
    "EBITDA",
    "NormalizedEBITDA",
    "Ebitda",
)
TOTAL_DEBT_ROW_NAMES = (
    "TotalDebt",
    "Total Debt",
    "LongTermDebt",
    "Long Term Debt And Capital Lease Obligation",
)
CASH_ROW_NAMES = (
    "CashAndCashEquivalents",
    "Cash And Cash Equivalents",
    "CashCashEquivalentsAndShortTermInvestments",
)
STOCKHOLDER_EQUITY_ROW_NAMES = (
    "StockholdersEquity",
    "Total Stockholder Equity",
    "CommonStockEquity",
    "Total Equity Gross Minority Interest",
)
# Operating-margin YoY decline ≥ this many pp triggers a pricing-power red flag
OPERATING_MARGIN_RED_FLAG_PP = 2.0
# CapEx YoY expansion above this while margins shrink → efficiency-trap red flag
CAPEX_EXPANSION_RED_FLAG = 0.20
# CapEx YoY decline beyond this triggers dialectic forward-guidance note for AI
CAPEX_DECLINE_DIALECTIC_THRESHOLD = -0.10

SCORECARD_DIMENSIONS: tuple[str, ...] = (
    "1. 財務安全 (Financial Runway)",
    "2. 現金流健康度 (FCF Reality)",
    "3. 核心成長性 (Growth Momentum)",
    "4. 科技/AI 題材含金量 (Tech Narrative Catalyst)",
    "5. 產業定價權與競爭優勢 (Moat Stability)",
    "6. 前瞻估值吸引力 (Valuation Safety Margin)",
)

# Index scan universes — Wikipedia constituents with hardcoded fallback
WIKI_INDEX_PAGES: dict[str, str] = {
    "dow30": "https://en.wikipedia.org/wiki/Dow_Jones_Industrial_Average",
    "nasdaq100": "https://en.wikipedia.org/wiki/Nasdaq-100",
    "sp500": "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
}
FALLBACK_SCAN_UNIVERSE: tuple[str, ...] = (
    "AAPL",
    "MSFT",
    "NVDA",
    "GOOGL",
    "AMZN",
    "META",
    "BRK-B",
    "LLY",
    "AVGO",
    "JPM",
    "TSLA",
    "V",
    "UNH",
    "XOM",
    "MA",
    "PG",
    "JNJ",
    "HD",
    "COST",
    "ABBV",
)
_SYMBOL_COLUMN_CANDIDATES = ("Symbol", "Ticker", "Ticker symbol")
_INDEX_EXPECTED_COUNTS: dict[str, tuple[int, int]] = {
    "dow30": (25, 35),
    "nasdaq100": (90, 110),
    "sp500": (450, 520),
}
_TICKER_PATTERN = re.compile(r"^[A-Z]{1,6}([.-][A-Z]{1,2})?$")

# Right-side trend / MA crossover signals (positions 1, 3, 4)
TREND_HISTORY_PERIOD = "1y"
SMA_SHORT = 20
SMA_LONG = 50
MIN_TREND_BARS = SMA_LONG + 1  # need prior bar for crossover detection
TrendSignalName = str  # "Buy" | "Sell" | "Hold" | "Wait"


@dataclass
class TrendSignal:
    """Right-side trading signal from SMA-20 / SMA-50 crossover rules."""

    current_signal: str
    current_price: float
    sma_20: float
    sma_50: float
    symbol: str = ""
    prev_sma_20: float | None = None
    prev_sma_50: float | None = None
    as_of_date: str | None = None

    def to_dict(self) -> dict[str, float | str | None]:
        return {
            "current_signal": self.current_signal,
            "current_price": round(self.current_price, 2),
            "sma_20": round(self.sma_20, 2),
            "sma_50": round(self.sma_50, 2),
            "symbol": self.symbol or None,
            "prev_sma_20": round(self.prev_sma_20, 2) if self.prev_sma_20 is not None else None,
            "prev_sma_50": round(self.prev_sma_50, 2) if self.prev_sma_50 is not None else None,
            "as_of_date": self.as_of_date,
        }


@dataclass
class TurnaroundOpportunity:
    """Candidate: price weak vs 6M high but latest fiscal FCF still positive."""

    symbol: str
    company_name: str
    drawdown_pct: float
    current_price: float
    six_month_high: float
    latest_fcf: float
    latest_fcf_fiscal_year: int | None
    fcf_source: str
    rd_expense: float | None = None
    rd_fiscal_year: int | None = None
    interest_coverage: float | None = None
    gross_margin: float | None = None
    gross_margin_yoy_change_pp: float | None = None
    net_debt_ebitda: float | None = None
    # Valuation filter outputs
    fifty_two_week_high: float | None = None
    price_vs_52w_high: float | None = None   # current / 52w high
    peg_ratio: float | None = None
    # Value-defense scoring loop (100-pt engine)
    value_defense_score: float | None = None
    value_grade_emoji: str = ""
    value_grade_label: str = ""
    # LLM mispricing reason tag
    reason_tag: str = ""
    reason_comment: str = ""


NEWS_LOOKBACK_DAYS = 14
NEWS_MIN_ITEMS = 5
NEWS_MAX_ITEMS = 8


@dataclass
class LiveNewsItem:
    title: str
    published: str
    summary: str = ""
    publisher: str = ""


@dataclass
class NarrativeResult:
    text: str
    live_news_degraded: bool = False


@dataclass
class YearFCF:
    fiscal_year: int
    period_end: str
    free_cash_flow: float
    source: str


@dataclass
class YearDividend:
    calendar_year: int
    dividend_per_share: float
    yoy_growth: float | None


@dataclass
class ScoreDetail:
    category: str
    max_points: float
    earned: float
    rationale: str


@dataclass
class MasterMetrics:
    """Forward-looking master-grade financial variables for EV / risk-premium scoring."""

    peg_ratio: float | None = None          # trailingPegRatio — growth/valuation scissors
    capex_growth: float | None = None       # YoY growth of quarterly CapEx (expansion lead)
    capex_latest: float | None = None       # latest quarterly CapEx magnitude (abs, USD)
    roe: float | None = None                # returnOnEquity (secondary to ROIC)
    roa: float | None = None                # returnOnAssets (ROIC fallback)
    roic: float | None = None               # returnOnCapitalEmployed or strict ROIC
    gross_margins: float | None = None      # pricing power proxy (TTM)
    gross_margin_volatility: float | None = None  # max-min gross margin range (pp, 3-5Y)
    interest_coverage: float | None = None  # EBIT / |interest expense|
    net_debt_ebitda: float | None = None    # (totalDebt - cash) / EBITDA
    fcf_payout_ratio: float | None = None   # |dividends paid| / FCF
    revenue_growth: float | None = None     # revenueGrowth (fallback signal)
    revenue_cagr_5y: float | None = None    # 5-year revenue CAGR from filings
    surprise_latest_pct: float | None = None  # latest EPS surprise %
    surprise_beat_streak: int = 0           # consecutive recent beats
    surprise_sample: int = 0                # number of reported quarters compared
    surprise_beats: int = 0                 # beats within the sample
    # Period-stamped margin / CapEx trend (quarterly vs TTM — never conflate)
    latest_quarter_label: str = ""          # e.g. "2025-Q3 (quarterly filing)"
    yoy_quarter_label: str = ""
    operating_margin_latest: float | None = None   # latest quarter OM %
    operating_margin_yoy: float | None = None      # same quarter prior year OM %
    operating_margin_change_pp: float | None = None  # YoY change in percentage points
    operating_margin_red_flag: bool = False
    operating_margin_red_flag_msg: str = ""
    capex_red_flag: bool = False
    capex_red_flag_msg: str = ""
    ttm_operating_margin: float | None = None      # yfinance info — trailing twelve months
    ttm_gross_margin: float | None = None
    ttm_revenue_growth: float | None = None        # info.revenueGrowth (TTM proxy)
    forward_pe: float | None = None                # forwardPE — valuation margin input
    fcf_yield: float | None = None                 # FCF / market cap
    data_as_of: str = ""                           # ISO date of latest price / quarter


@dataclass
class ScorecardItem:
    """Single row in the Master Investment Scorecard (1–10 institutional rating)."""

    dimension: str
    score: int
    rationale: str


@dataclass
class StockReport:
    symbol: str
    company_name: str
    fcf_history: list[YearFCF] = field(default_factory=list)
    div_history: list[YearDividend] = field(default_factory=list)
    payout_ratio: float | None = None
    beta: float | None = None
    score_details: list[ScoreDetail] = field(default_factory=list)
    total_score: float = 0.0                       # legacy alias → business_quality_score
    business_quality_score: float = 0.0            # Business Quality 0–100
    valuation_margin_score: float = 0.0            # Valuation Safety Score 0–100
    grade_label: str = ""
    grade_emoji: str = ""
    analyst_commentary: str = ""
    # Legacy booleans for charts / quick flags
    fcf_pass: bool | None = None
    fcf_note: str = ""
    div_pass: bool | None = None
    div_note: str = ""
    trend_signal: dict[str, float | str | None] | None = None
    strategy_mode: str = STRATEGY_VALUE
    master: MasterMetrics = field(default_factory=MasterMetrics)
    investment_scorecard: list[ScorecardItem] = field(default_factory=list)

    @property
    def overall_pass(self) -> bool | None:
        if self.business_quality_score <= 0 and not self.score_details:
            return None
        return (
            self.business_quality_score >= 70
            and self.valuation_margin_score >= VALUATION_TRAP_SAFETY_MAX
        )

    @property
    def valuation_safety_score(self) -> float:
        """Alias — Red Team Protocol naming."""
        return self.valuation_margin_score


@lru_cache(maxsize=1)
def _symbol_to_cik() -> dict[str, str]:
    resp = requests.get(
        "https://www.sec.gov/files/company_tickers.json",
        headers=SEC_HEADERS,
        timeout=30,
    )
    resp.raise_for_status()
    return {
        row["ticker"].upper(): str(row["cik_str"]).zfill(10)
        for row in resp.json().values()
    }


def _sec_fy_values(facts: dict, tag: str) -> dict[int, tuple[str, float]]:
    if tag not in facts:
        return {}
    out: dict[int, tuple[str, float]] = {}
    for item in facts[tag]["units"]["USD"]:
        if item.get("form") != "10-K" or item.get("fp") != "FY":
            continue
        fy = int(item.get("fy") or item["end"][:4])
        end = item["end"]
        if fy not in out or end > out[fy][0]:
            out[fy] = (end, float(item["val"]))
    return out


def fetch_fcf_from_sec(symbol: str, years: int = YEARS_REQUIRED) -> list[YearFCF]:
    cik = _symbol_to_cik()[symbol.upper()]
    url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
    resp = requests.get(url, headers=SEC_HEADERS, timeout=45)
    resp.raise_for_status()
    gaap = resp.json()["facts"]["us-gaap"]

    ocf = _sec_fy_values(gaap, OCF_TAG)
    capex: dict[int, tuple[str, float]] = {}
    for tag in CAPEX_TAGS:
        for fy, pair in _sec_fy_values(gaap, tag).items():
            if fy not in capex or pair[0] > capex[fy][0]:
                capex[fy] = pair

    rows: list[YearFCF] = []
    for fy in sorted(set(ocf) & set(capex), reverse=True)[:years]:
        fcf = ocf[fy][1] - capex[fy][1]
        rows.append(
            YearFCF(
                fiscal_year=fy,
                period_end=ocf[fy][0],
                free_cash_flow=fcf,
                source="SEC EDGAR",
            )
        )
    return rows


def _pick_row(df: pd.DataFrame, *names: str) -> pd.Series | None:
    if df is None or df.empty:
        return None
    for name in names:
        if name in df.index:
            return df.loc[name]
    return None


def _safe_ticker_info(ticker: yf.Ticker, symbol: str) -> dict:
    try:
        info = ticker.info
        if isinstance(info, dict):
            return info
    except Exception:
        pass
    return {}


def _company_name(info: dict | None, symbol: str) -> str:
    info = info if isinstance(info, dict) else {}
    for key in ("longName", "shortName", "displayName"):
        value = info.get(key)
        if value:
            return str(value)
    return symbol.upper()


def _safe_beta(info: dict) -> float | None:
    try:
        beta = info.get("beta")
        if beta is not None and not (isinstance(beta, float) and pd.isna(beta)):
            return float(beta)
    except (TypeError, ValueError):
        pass
    return None


def _safe_info_float(info: dict, key: str) -> float | None:
    try:
        value = info.get(key)
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def fetch_business_summary(symbol: str) -> tuple[str, str, str]:
    """Return (longBusinessSummary, sector, industry) from yfinance."""
    sym = symbol.upper().strip()
    info = _safe_ticker_info(yf.Ticker(sym), sym)
    summary = str(info.get("longBusinessSummary") or "").strip()
    sector = str(info.get("sector") or "").strip()
    industry = str(info.get("industry") or "").strip()
    return summary, sector, industry


def _parse_news_timestamp(entry: dict) -> datetime | None:
    """Extract publish time from a yfinance news dict."""
    for key in ("providerPublishTime", "pubDate", "published_at", "publishDate"):
        raw = entry.get(key)
        if raw is None:
            continue
        try:
            if isinstance(raw, (int, float)):
                return datetime.fromtimestamp(float(raw), tz=timezone.utc)
            if isinstance(raw, str):
                text = raw.strip()
                if text.isdigit():
                    return datetime.fromtimestamp(float(text), tz=timezone.utc)
                return pd.Timestamp(text).to_pydatetime().replace(tzinfo=timezone.utc)
        except Exception:
            continue
    return None


def _extract_news_summary(entry: dict) -> str:
    """Best-effort summary from yfinance news payload."""
    for key in ("summary", "description", "text"):
        val = entry.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    content = entry.get("content")
    if isinstance(content, dict):
        for key in ("summary", "description", "title"):
            val = content.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()
    return ""


def fetch_ticker_live_news(
    symbol: str,
    *,
    lookback_days: int = NEWS_LOOKBACK_DAYS,
    max_items: int = NEWS_MAX_ITEMS,
    ticker: yf.Ticker | None = None,
) -> list[LiveNewsItem]:
    """
    Fetch recent ticker-specific headlines via yfinance ``ticker.news``.

    Returns up to ``max_items`` stories within ``lookback_days`` (7–14 day window).
    Never raises — returns empty list on failure.
    """
    sym = symbol.upper().strip()
    if not sym:
        return []

    cutoff = datetime.now(tz=timezone.utc) - timedelta(days=lookback_days)
    t = ticker or yf.Ticker(sym)

    try:
        raw_news = t.news
    except Exception:
        return []

    if not isinstance(raw_news, list) or not raw_news:
        return []

    parsed: list[tuple[datetime, LiveNewsItem]] = []
    for entry in raw_news:
        if not isinstance(entry, dict):
            continue
        title = str(entry.get("title") or "").strip()
        if not title:
            continue

        published_dt = _parse_news_timestamp(entry)
        if published_dt and published_dt < cutoff:
            continue

        published_label = (
            published_dt.strftime("%Y-%m-%d")
            if published_dt
            else "Recent"
        )
        parsed.append(
            (
                published_dt or datetime.now(tz=timezone.utc),
                LiveNewsItem(
                    title=title,
                    published=published_label,
                    summary=_extract_news_summary(entry),
                    publisher=str(entry.get("publisher") or entry.get("source") or "").strip(),
                ),
            )
        )

    parsed.sort(key=lambda row: row[0], reverse=True)
    items = [item for _, item in parsed[:max_items]]
    if len(items) < NEWS_MIN_ITEMS and len(raw_news) >= NEWS_MIN_ITEMS:
        # Relax date filter if feed is sparse but headlines exist
        relaxed: list[LiveNewsItem] = []
        for entry in raw_news:
            if not isinstance(entry, dict):
                continue
            title = str(entry.get("title") or "").strip()
            if not title:
                continue
            published_dt = _parse_news_timestamp(entry)
            relaxed.append(
                LiveNewsItem(
                    title=title,
                    published=published_dt.strftime("%Y-%m-%d") if published_dt else "Recent",
                    summary=_extract_news_summary(entry),
                    publisher=str(entry.get("publisher") or entry.get("source") or "").strip(),
                )
            )
            if len(relaxed) >= max_items:
                break
        if len(relaxed) > len(items):
            items = relaxed[:max_items]
    return items


def format_live_news_block(items: list[LiveNewsItem]) -> str:
    """Plain-text block for Gemini — live news section."""
    if not items:
        return ""
    lines: list[str] = []
    for index, item in enumerate(items, start=1):
        lines.append(f"{index}. [{item.published}] {item.title}")
        if item.publisher:
            lines.append(f"   Publisher: {item.publisher}")
        if item.summary:
            lines.append(f"   Summary: {item.summary}")
    return "\n".join(lines)


def fetch_fcf_from_yfinance(symbol: str, years: int = YEARS_REQUIRED) -> list[YearFCF]:
    try:
        cf = yf.Ticker(symbol).get_cashflow(freq="yearly")
    except Exception:
        return []
    if cf is None or cf.empty:
        return []

    fcf_row = _pick_row(cf, "FreeCashFlow", "Free Cash Flow")
    ocf_row = _pick_row(
        cf,
        "OperatingCashFlow",
        "Operating Cash Flow",
        "CashFlowFromContinuingOperatingActivities",
    )
    capex_row = _pick_row(cf, "CapitalExpenditure", "Capital Expenditure")

    rows: list[YearFCF] = []
    for col in sorted(cf.columns, reverse=True):
        dt = pd.Timestamp(col)
        val = None
        if fcf_row is not None and pd.notna(fcf_row.get(dt)):
            val = float(fcf_row[dt])
        elif ocf_row is not None and capex_row is not None:
            if pd.notna(ocf_row.get(dt)) and pd.notna(capex_row.get(dt)):
                val = float(ocf_row[dt]) + float(capex_row[dt])
        if val is None:
            continue
        rows.append(
            YearFCF(
                fiscal_year=dt.year,
                period_end=dt.strftime("%Y-%m-%d"),
                free_cash_flow=val,
                source="Yahoo Finance",
            )
        )
        if len(rows) >= years:
            break
    return rows


def fetch_fcf(symbol: str) -> list[YearFCF]:
    sec_error: str | None = None
    try:
        rows = fetch_fcf_from_sec(symbol)
        if rows:
            return rows[:YEARS_REQUIRED]
    except Exception as exc:
        sec_error = str(exc)

    rows = fetch_fcf_from_yfinance(symbol)
    if sec_error and rows:
        for row in rows:
            row.source = f"Yahoo Finance (SEC fallback: {sec_error[:40]})"
    return rows[:YEARS_REQUIRED]


def fetch_dividends(symbol: str, ticker: yf.Ticker | None = None) -> list[YearDividend]:
    try:
        divs = (ticker or yf.Ticker(symbol)).dividends
    except Exception:
        return []
    if divs is None or divs.empty:
        return []

    by_year = divs.groupby(divs.index.year).sum().sort_index()
    current_year = datetime.now().year
    completed = [int(y) for y in by_year.index if int(y) < current_year]

    need = YEARS_REQUIRED + 1
    window = completed[-need:] if len(completed) >= need else completed

    history: list[YearDividend] = []
    for i, year in enumerate(window):
        dps = float(by_year[year])
        yoy = None
        if i > 0:
            prev = float(by_year[window[i - 1]])
            yoy = (dps - prev) / prev if prev > 0 else None
        history.append(YearDividend(calendar_year=year, dividend_per_share=dps, yoy_growth=yoy))
    return history


def fetch_payout_ratio(symbol: str, ticker: yf.Ticker | None = None) -> float | None:
    """Latest fiscal-year payout = |cash dividends| / net income."""
    t = ticker or yf.Ticker(symbol)
    try:
        info = _safe_ticker_info(t, symbol)
        raw = info.get("payoutRatio")
        if raw is not None:
            try:
                val = float(raw)
                if 0 <= val <= 2:
                    return val
            except (TypeError, ValueError):
                pass
    except Exception:
        pass

    try:
        cf = t.get_cashflow(freq="yearly")
        inc = t.get_income_stmt(freq="yearly")
    except Exception:
        return None

    if cf is None or cf.empty or inc is None or inc.empty:
        return None

    div_row = _pick_row(cf, "CashDividendsPaid", "Cash Dividends Paid")
    ni_row = _pick_row(inc, "NetIncome", "Net Income")
    if div_row is None or ni_row is None:
        return None

    for col in sorted(cf.columns, reverse=True):
        dt = pd.Timestamp(col)
        if dt not in ni_row.index:
            continue
        d, n = div_row.get(dt), ni_row.get(dt)
        if pd.notna(d) and pd.notna(n) and float(n) > 0:
            return abs(float(d)) / float(n)
    return None


def _six_month_price_drawdown(
    ticker: yf.Ticker,
    period: str = TURNAROUND_LOOKBACK,
) -> tuple[float, float, float] | None:
    """
    Return (current_price, period_high, drawdown_pct) for the lookback window.

    drawdown_pct is a positive number when price is below the period high
    (e.g. 18.3 means 18.3% below the 6-month high).
    """
    try:
        hist = ticker.history(period=period)
        if hist is None or hist.empty:
            return None
        close = hist["Close"].dropna()
        if len(close) < 2:
            return None
        period_high = float(close.max())
        current = float(close.iloc[-1])
        if period_high <= 0:
            return None
        drawdown_pct = (period_high - current) / period_high * 100.0
        return current, period_high, drawdown_pct
    except Exception:
        return None


def fetch_latest_fcf_snapshot(
    symbol: str,
    ticker: yf.Ticker | None = None,
) -> tuple[float | None, int | None, str | None]:
    """
    Latest fiscal-year FCF via existing SEC-first `fetch_fcf` pipeline.

    Reuses the same helpers as core financial scoring so turnaround facts stay
    consistent with the passive safety screen.
    """
    try:
        rows = fetch_fcf(symbol.upper())
        if not rows:
            return None, None, None
        latest = rows[0]
        return latest.free_cash_flow, latest.fiscal_year, latest.source
    except Exception:
        return None, None, None


def fetch_latest_rd_expense(
    symbol: str,
    ticker: yf.Ticker | None = None,
) -> tuple[float | None, int | None]:
    """Latest annual R&D from income statement (tech / innovation fact reserve)."""
    t = ticker or yf.Ticker(symbol)
    try:
        income = t.get_income_stmt(freq="yearly")
    except Exception:
        return None, None
    if income is None or income.empty:
        return None, None

    rnd_row = _pick_row(income, *RND_ROW_NAMES)
    if rnd_row is None:
        return None, None

    try:
        for col in sorted(income.columns, reverse=True):
            dt = pd.Timestamp(col)
            val = rnd_row.get(dt)
            if val is not None and pd.notna(val):
                return abs(float(val)), dt.year
    except Exception:
        pass
    return None, None


def compute_interest_coverage(ticker: yf.Ticker) -> float | None:
    """EBIT / |interest expense| from the latest annual income statement.

    Returns None when there is no meaningful interest expense (debt-light) or
    when data is unavailable; never raises.
    """
    try:
        income = ticker.get_income_stmt(freq="yearly")
    except Exception:
        return None
    if income is None or income.empty:
        return None

    ebit_row = _pick_row(income, *EBIT_ROW_NAMES)
    interest_row = _pick_row(income, *INTEREST_EXPENSE_ROW_NAMES)
    if ebit_row is None or interest_row is None:
        return None
    try:
        latest_col = sorted(income.columns, reverse=True)[0]
        ebit = float(ebit_row.get(latest_col))
        interest = abs(float(interest_row.get(latest_col)))
    except (TypeError, ValueError, IndexError):
        return None
    if pd.isna(ebit) or pd.isna(interest) or interest <= 0:
        return None
    return round(ebit / interest, 2)


def fetch_roic(info: dict, ticker: yf.Ticker) -> tuple[float | None, float | None]:
    """Return (roic, roa). ROIC priority: returnOnCapitalEmployed → strict ROIC → ROA."""
    roa = _safe_info_float(info, "returnOnAssets")
    roce = _safe_info_float(info, "returnOnCapitalEmployed")
    if roce is not None:
        return roce, roa

    try:
        bs = ticker.get_balance_sheet(freq="yearly")
        inc = ticker.get_income_stmt(freq="yearly")
    except Exception:
        return roa, roa

    if bs is None or bs.empty or inc is None or inc.empty:
        return roa, roa

    ebit_row = _pick_row(inc, *EBIT_ROW_NAMES)
    debt_row = _pick_row(bs, *TOTAL_DEBT_ROW_NAMES)
    equity_row = _pick_row(bs, *STOCKHOLDER_EQUITY_ROW_NAMES)
    cash_row = _pick_row(bs, *CASH_ROW_NAMES)
    if ebit_row is None or equity_row is None:
        return roa, roa

    try:
        latest_col = sorted(inc.columns, reverse=True)[0]
        ebit = float(ebit_row.get(latest_col))
        equity = float(equity_row.get(latest_col))
        debt = float(debt_row.get(latest_col)) if debt_row is not None else 0.0
        cash = float(cash_row.get(latest_col)) if cash_row is not None else 0.0
    except (TypeError, ValueError, IndexError):
        return roa, roa

    if pd.isna(ebit) or pd.isna(equity):
        return roa, roa

    invested_capital = debt + equity - cash
    if invested_capital <= 0:
        return roa, roa

    roic = ebit / invested_capital
    return round(roic, 4), roa


def fetch_net_debt_ebitda(info: dict, ticker: yf.Ticker) -> float | None:
    """Net Debt / EBITDA — leverage signal for DGI safety screen."""
    direct = _safe_info_float(info, "netDebtToEbitda")
    if direct is not None and direct >= 0:
        return round(direct, 2)

    total_debt = _safe_info_float(info, "totalDebt")
    cash = _safe_info_float(info, "totalCash") or _safe_info_float(info, "cash")
    ebitda = _safe_info_float(info, "ebitda")

    if total_debt is not None and cash is not None and ebitda is not None and ebitda > 0:
        return round((total_debt - cash) / ebitda, 2)

    try:
        bs = ticker.get_balance_sheet(freq="yearly")
        inc = ticker.get_income_stmt(freq="yearly")
    except Exception:
        return None
    if bs is None or bs.empty:
        return None

    debt_row = _pick_row(bs, *TOTAL_DEBT_ROW_NAMES)
    cash_row = _pick_row(bs, *CASH_ROW_NAMES)
    if debt_row is None:
        return None

    try:
        latest_col = sorted(bs.columns, reverse=True)[0]
        debt = float(debt_row.get(latest_col))
        cash_val = float(cash_row.get(latest_col)) if cash_row is not None else 0.0
    except (TypeError, ValueError, IndexError):
        return None

    if ebitda is None and inc is not None and not inc.empty:
        ebitda_row = _pick_row(inc, *EBITDA_ROW_NAMES)
        if ebitda_row is not None:
            try:
                ebitda = float(ebitda_row.get(latest_col))
            except (TypeError, ValueError):
                ebitda = None

    if ebitda is None or pd.isna(ebitda) or ebitda <= 0:
        return None

    net_debt = debt - cash_val
    return round(net_debt / ebitda, 2)


def fetch_fcf_payout_ratio(
    symbol: str,
    ticker: yf.Ticker,
    info: dict,
) -> float | None:
    """FCF payout = |cash dividends paid| / free cash flow (latest fiscal year).

    Falls back to yfinance payoutRatio when FCF-based ratio is unavailable.
    """
    try:
        cf = ticker.get_cashflow(freq="yearly")
    except Exception:
        cf = None

    if cf is not None and not cf.empty:
        div_row = _pick_row(cf, "CashDividendsPaid", "Cash Dividends Paid")
        fcf_row = _pick_row(cf, "FreeCashFlow", "Free Cash Flow")
        if div_row is not None and fcf_row is not None:
            for col in sorted(cf.columns, reverse=True):
                try:
                    div = abs(float(div_row.get(col)))
                    fcf = float(fcf_row.get(col))
                except (TypeError, ValueError):
                    continue
                if pd.notna(div) and pd.notna(fcf) and fcf > 0:
                    return round(div / fcf, 4)

    return fetch_payout_ratio(symbol, ticker=ticker)


def fetch_revenue_cagr_5y(ticker: yf.Ticker) -> float | None:
    """5-year revenue CAGR from annual income statements."""
    try:
        inc = ticker.get_income_stmt(freq="yearly")
    except Exception:
        return None
    if inc is None or inc.empty:
        return None

    rev_row = _pick_row(inc, *TOTAL_REVENUE_ROW_NAMES)
    if rev_row is None:
        return None

    col_dates = sorted(inc.columns, reverse=True)
    revenues: list[float] = []
    for col in col_dates[:6]:
        try:
            val = float(rev_row.get(col))
        except (TypeError, ValueError):
            continue
        if pd.notna(val) and val > 0:
            revenues.append(val)

    if len(revenues) < 2:
        return None

    years = len(revenues) - 1
    if years <= 0 or revenues[-1] <= 0:
        return None

    cagr = (revenues[0] / revenues[-1]) ** (1.0 / years) - 1.0
    return round(cagr, 4)


def fetch_revenue_cagr_3y(ticker: yf.Ticker) -> float | None:
    """3-year revenue CAGR from annual income statements."""
    try:
        inc = ticker.get_income_stmt(freq="yearly")
    except Exception:
        return None
    if inc is None or inc.empty:
        return None

    rev_row = _pick_row(inc, *TOTAL_REVENUE_ROW_NAMES)
    if rev_row is None:
        return None

    col_dates = sorted(inc.columns, reverse=True)
    revenues: list[float] = []
    for col in col_dates[: TURNAROUND_REVENUE_CAGR_YEARS + 1]:
        try:
            val = float(rev_row.get(col))
        except (TypeError, ValueError):
            continue
        if pd.notna(val) and val > 0:
            revenues.append(val)

    if len(revenues) < 2:
        return None

    years = len(revenues) - 1
    if years <= 0 or revenues[-1] <= 0:
        return None

    cagr = (revenues[0] / revenues[-1]) ** (1.0 / years) - 1.0
    return round(cagr, 4)


def _compute_fcf_yield(info: dict, symbol: str, ticker: yf.Ticker) -> float | None:
    """FCF yield = latest fiscal FCF / market cap."""
    mkt_cap = _safe_info_float(info, "marketCap")
    if mkt_cap is None or mkt_cap <= 0:
        return None
    fcf_val, _, _ = fetch_latest_fcf_snapshot(symbol, ticker=ticker)
    if fcf_val is None or fcf_val <= 0:
        return None
    return round(fcf_val / mkt_cap, 4)


def fetch_gross_margin_volatility(ticker: yf.Ticker, years: int = 5) -> float | None:
    """Max-min gross margin range (percentage points) over recent fiscal years."""
    try:
        inc = ticker.get_income_stmt(freq="yearly")
    except Exception:
        return None
    if inc is None or inc.empty:
        return None

    gross_row = _pick_row(inc, *GROSS_PROFIT_ROW_NAMES)
    rev_row = _pick_row(inc, *TOTAL_REVENUE_ROW_NAMES)
    if gross_row is None or rev_row is None:
        return None

    margins: list[float] = []
    for col in sorted(inc.columns, reverse=True)[:years]:
        try:
            g = float(gross_row.get(col))
            r = float(rev_row.get(col))
        except (TypeError, ValueError, ZeroDivisionError):
            continue
        if pd.notna(g) and pd.notna(r) and r > 0:
            margins.append(g / r)

    if len(margins) < 2:
        return None

    return round((max(margins) - min(margins)) * 100.0, 2)


def fetch_capex_growth(ticker: yf.Ticker) -> tuple[float | None, float | None]:
    """YoY growth of quarterly CapEx as an expansion / industry-tailwind lead signal.

    Compares the latest quarter's CapEx magnitude against the year-ago quarter
    (4 quarters back). Returns (growth_ratio, latest_abs_capex). Never raises.
    """
    try:
        cashflow = ticker.quarterly_cashflow
    except Exception:
        return None, None
    if cashflow is None or cashflow.empty:
        return None, None

    capex_row = _pick_row(cashflow, *CAPEX_CF_ROW_NAMES)
    if capex_row is None:
        return None, None

    cols = sorted(cashflow.columns, reverse=True)
    if not cols:
        return None, None
    try:
        latest = abs(float(capex_row.get(cols[0])))
    except (TypeError, ValueError):
        return None, None
    if pd.isna(latest):
        return None, None

    if len(cols) < 5:
        return None, round(latest, 2)
    try:
        year_ago = abs(float(capex_row.get(cols[4])))
    except (TypeError, ValueError):
        return None, round(latest, 2)
    if pd.isna(year_ago) or year_ago <= 0:
        return None, round(latest, 2)
    return round((latest - year_ago) / year_ago, 4), round(latest, 2)


def fetch_earnings_surprise(ticker: yf.Ticker) -> dict | None:
    """Compare EPS Estimate vs Actual across recent quarters.

    Returns a dict with the latest surprise %, consecutive beat streak, and
    beat count over the sampled window. None when data is unavailable.
    """
    df = None
    try:
        df = ticker.get_earnings_dates(limit=EARNINGS_SURPRISE_LOOKBACK + 4)
    except Exception:
        try:
            df = ticker.earnings_dates
        except Exception:
            df = None
    if df is None or getattr(df, "empty", True):
        return None

    est_col = next((c for c in df.columns if "Estimate" in str(c)), None)
    act_col = next(
        (c for c in df.columns if "Reported" in str(c) or "Actual" in str(c)),
        None,
    )
    if est_col is None or act_col is None:
        return None

    rows: list[tuple[object, float, float]] = []
    for idx, row in df.iterrows():
        est = row.get(est_col)
        act = row.get(act_col)
        if est is None or act is None or pd.isna(est) or pd.isna(act):
            continue
        rows.append((idx, float(est), float(act)))
    if not rows:
        return None

    try:
        rows.sort(key=lambda r: r[0], reverse=True)
    except Exception:
        pass
    rows = rows[:EARNINGS_SURPRISE_LOOKBACK]

    latest_idx, latest_est, latest_act = rows[0]
    latest_pct = (
        (latest_act - latest_est) / abs(latest_est) * 100.0
        if latest_est != 0
        else None
    )

    beat_streak = 0
    for _, est, act in rows:
        if act > est:
            beat_streak += 1
        else:
            break
    beats = sum(1 for _, est, act in rows if act > est)

    return {
        "latest_surprise_pct": round(latest_pct, 1) if latest_pct is not None else None,
        "beat_streak": beat_streak,
        "beats": beats,
        "sample": len(rows),
    }


def _quarter_label(col: object) -> str:
    """Human-readable fiscal quarter label from a statement column timestamp."""
    try:
        ts = pd.Timestamp(col)
        return f"{ts.year}-Q{(ts.month - 1) // 3 + 1} (as-of {ts.strftime('%Y-%m-%d')})"
    except Exception:
        return str(col)


def fetch_operating_margin_trend(ticker: yf.Ticker) -> dict:
    """Latest-quarter operating margin vs the year-ago quarter (YoY trend).

    Returns period-stamped margins and optional red-flag messages. Never raises.
    """
    out: dict = {
        "latest_quarter_label": "",
        "yoy_quarter_label": "",
        "operating_margin_latest": None,
        "operating_margin_yoy": None,
        "operating_margin_change_pp": None,
        "operating_margin_red_flag": False,
        "operating_margin_red_flag_msg": "",
    }
    try:
        quarterly = ticker.quarterly_income_stmt
    except Exception:
        return out
    if quarterly is None or quarterly.empty:
        return out

    op_row = _pick_row(quarterly, *EBIT_ROW_NAMES)
    rev_row = _pick_row(quarterly, *TOTAL_REVENUE_ROW_NAMES)
    if op_row is None or rev_row is None:
        return out

    cols = sorted(quarterly.columns, reverse=True)
    if len(cols) < 5:
        return out

    latest_col, yoy_col = cols[0], cols[4]
    try:
        rev_latest = float(rev_row.get(latest_col))
        rev_yoy = float(rev_row.get(yoy_col))
        op_latest = float(op_row.get(latest_col))
        op_yoy = float(op_row.get(yoy_col))
    except (TypeError, ValueError):
        return out
    if rev_latest <= 0 or rev_yoy <= 0:
        return out

    om_latest = op_latest / rev_latest
    om_yoy = op_yoy / rev_yoy
    change_pp = (om_latest - om_yoy) * 100.0

    out.update(
        {
            "latest_quarter_label": _quarter_label(latest_col),
            "yoy_quarter_label": _quarter_label(yoy_col),
            "operating_margin_latest": round(om_latest * 100.0, 2),
            "operating_margin_yoy": round(om_yoy * 100.0, 2),
            "operating_margin_change_pp": round(change_pp, 2),
        }
    )
    if change_pp <= -OPERATING_MARGIN_RED_FLAG_PP:
        out["operating_margin_red_flag"] = True
        out["operating_margin_red_flag_msg"] = (
            f"【紅旗警告】：營業利益率 YoY {om_yoy*100:.1f}% → {om_latest*100:.1f}% "
            f"（{change_pp:+.1f}pp），獲利能力衰退，面臨定價權危機或成本失控"
        )
    return out


def _evaluate_capex_red_flag(
    capex_growth: float | None,
    operating_margin_change_pp: float | None,
) -> tuple[bool, str]:
    """CapEx expansion paired with margin erosion → efficiency-trap warning."""
    if capex_growth is None or operating_margin_change_pp is None:
        return False, ""
    if capex_growth >= CAPEX_EXPANSION_RED_FLAG and operating_margin_change_pp < -1.0:
        return True, (
            f"【紅旗警告】：CapEx 季 YoY 擴張 {capex_growth*100:+.1f}%，"
            f"但營業利益率同步下滑 {operating_margin_change_pp:+.1f}pp，"
            "可能存在資本效率陷阱或過度投資風險"
        )
    return False, ""


def fetch_master_metrics(
    symbol: str,
    info: dict | None,
    ticker: yf.Ticker | None = None,
) -> MasterMetrics:
    """Aggregate master-grade variables; core metrics served from SQLite cache."""
    from data_layer import get_financial_data

    info = info or {}
    t = ticker or yf.Ticker(symbol)
    sym = symbol.upper().strip()

    try:
        cached = get_financial_data(sym)
    except Exception:
        cached = None

    capex_growth, capex_latest = fetch_capex_growth(t)
    surprise = fetch_earnings_surprise(t)
    margin_trend = fetch_operating_margin_trend(t)
    capex_flag, capex_msg = _evaluate_capex_red_flag(
        capex_growth, margin_trend.get("operating_margin_change_pp")
    )

    if cached is not None and cached.ticker:
        roic, roa = cached.roic, cached.roa
        if roic is None and roa is None:
            roic, roa = fetch_roic(info, t)
    else:
        roic, roa = fetch_roic(info, t)

    return MasterMetrics(
        peg_ratio=_safe_info_float(info, "trailingPegRatio"),
        capex_growth=capex_growth,
        capex_latest=capex_latest,
        roe=_safe_info_float(info, "returnOnEquity") or (cached.roe if cached else None),
        roa=roa,
        roic=roic,
        gross_margins=_safe_info_float(info, "grossMargins"),
        gross_margin_volatility=(
            cached.gross_margin_volatility if cached else fetch_gross_margin_volatility(t)
        ),
        interest_coverage=(
            cached.interest_coverage if cached else compute_interest_coverage(t)
        ),
        net_debt_ebitda=(
            cached.net_debt_ebitda if cached else fetch_net_debt_ebitda(info, t)
        ),
        fcf_payout_ratio=(
            cached.fcf_payout_ratio if cached else fetch_fcf_payout_ratio(sym, t, info)
        ),
        revenue_growth=_safe_info_float(info, "revenueGrowth"),
        revenue_cagr_5y=(
            cached.revenue_cagr_5y if cached else fetch_revenue_cagr_5y(t)
        ),
        surprise_latest_pct=(surprise or {}).get("latest_surprise_pct"),
        surprise_beat_streak=(surprise or {}).get("beat_streak", 0),
        surprise_sample=(surprise or {}).get("sample", 0),
        surprise_beats=(surprise or {}).get("beats", 0),
        latest_quarter_label=str(margin_trend.get("latest_quarter_label", "")),
        yoy_quarter_label=str(margin_trend.get("yoy_quarter_label", "")),
        operating_margin_latest=margin_trend.get("operating_margin_latest"),
        operating_margin_yoy=margin_trend.get("operating_margin_yoy"),
        operating_margin_change_pp=margin_trend.get("operating_margin_change_pp"),
        operating_margin_red_flag=bool(margin_trend.get("operating_margin_red_flag")),
        operating_margin_red_flag_msg=str(margin_trend.get("operating_margin_red_flag_msg", "")),
        capex_red_flag=capex_flag,
        capex_red_flag_msg=capex_msg,
        ttm_operating_margin=_safe_info_float(info, "operatingMargins"),
        ttm_gross_margin=_safe_info_float(info, "grossMargins"),
        ttm_revenue_growth=_safe_info_float(info, "revenueGrowth"),
        forward_pe=_safe_info_float(info, "forwardPE") or _safe_info_float(info, "trailingPE"),
        fcf_yield=_compute_fcf_yield(info, sym, t),
    )


def _sector_gross_margin_median_pct(info: dict | None) -> float:
    """Proxy industry median gross margin from yfinance sector label."""
    info = info or {}
    sector = str(info.get("sector") or info.get("industry") or "").strip()
    if not sector:
        return DEFAULT_SECTOR_GM_MEDIAN_PCT
    for key, median in SECTOR_GROSS_MARGIN_MEDIAN_PCT.items():
        if key.lower() in sector.lower() or sector.lower() in key.lower():
            return median
    return DEFAULT_SECTOR_GM_MEDIAN_PCT


def _margin_above_industry_or_stable(
    ticker: yf.Ticker,
    info: dict | None,
) -> bool:
    """
    Latest-quarter GM above sector median proxy AND no structural YoY collapse.
    """
    margin_ok, latest_gm_pct, _ = _gross_margin_filter(ticker)
    if latest_gm_pct is None:
        return False
    if not margin_ok:
        return False
    sector_median = _sector_gross_margin_median_pct(info)
    return latest_gm_pct >= sector_median


def _anti_value_trap_filter(ticker: yf.Ticker, info: dict | None = None) -> bool:
    """
    Anti-structural-decay gate (Red Team Protocol).

    Pass when:
      · 3Y revenue CAGR > 0, OR
      · latest-quarter gross margin ≥ sector-median proxy AND no structural collapse.

    Hard reject when 3Y CAGR is known and ≤ 0 (shrinking core business).
    """
    cagr_3y = fetch_revenue_cagr_3y(ticker)
    if cagr_3y is not None:
        if cagr_3y <= 0:
            return False
        return True

    return _margin_above_industry_or_stable(ticker, info)


def _passes_right_side_filter(
    ticker: yf.Ticker,
) -> tuple[bool, dict | None]:
    """Technical right-side gate: latest Close must sit above SMA20.

    Returns (passed, trend_signal). When the SMA cannot be computed we treat the
    structure as unverifiable and reject (institutional defensive default).
    """
    try:
        trend = detect_trend_signals(ticker)
    except Exception:
        return False, None
    if not trend:
        return False, None
    try:
        close = float(trend.get("current_price"))
        sma_20 = float(trend.get("sma_20"))
    except (TypeError, ValueError):
        return False, trend
    return close > sma_20, trend


def _interest_coverage_filter(
    ticker: yf.Ticker,
) -> tuple[bool, float | None]:
    """Debt-moat gate: interest coverage = EBIT / |Interest Expense|.

    Only rejects a ticker that actually carries interest expense and whose
    coverage is below `INTEREST_COVERAGE_MIN`. Debt-light names (no meaningful
    interest expense) or missing data pass through untouched.
    """
    try:
        income = ticker.get_income_stmt(freq="yearly")
    except Exception:
        return True, None
    if income is None or income.empty:
        return True, None

    ebit_row = _pick_row(income, *EBIT_ROW_NAMES)
    interest_row = _pick_row(income, *INTEREST_EXPENSE_ROW_NAMES)
    if ebit_row is None or interest_row is None:
        return True, None

    try:
        latest_col = sorted(income.columns, reverse=True)[0]
        ebit = float(ebit_row.get(latest_col))
        interest = abs(float(interest_row.get(latest_col)))
    except (TypeError, ValueError, IndexError):
        return True, None

    if pd.isna(ebit) or pd.isna(interest) or interest <= 0:
        return True, None

    coverage = ebit / interest
    return coverage >= INTEREST_COVERAGE_MIN, round(coverage, 2)


def _gross_margin_filter(
    ticker: yf.Ticker,
) -> tuple[bool, float | None, float | None]:
    """Pricing-power gate: latest-quarter gross margin vs the year-ago quarter.

    Rejects when gross margin contracted by more than
    `GROSS_MARGIN_YOY_MAX_DECLINE_PP` percentage points YoY (loss of pricing
    power). Missing quarterly data passes through.

    Returns (passed, latest_margin, yoy_change_pp).
    """
    try:
        quarterly = ticker.quarterly_income_stmt
    except Exception:
        return True, None, None
    if quarterly is None or quarterly.empty:
        return True, None, None

    gross_row = _pick_row(quarterly, *GROSS_PROFIT_ROW_NAMES)
    revenue_row = _pick_row(quarterly, *TOTAL_REVENUE_ROW_NAMES)
    if gross_row is None or revenue_row is None:
        return True, None, None

    cols = sorted(quarterly.columns, reverse=True)
    if len(cols) < 5:
        return True, None, None

    latest_col, yoy_col = cols[0], cols[4]
    try:
        gm_latest = float(gross_row.get(latest_col)) / float(revenue_row.get(latest_col))
        gm_yoy = float(gross_row.get(yoy_col)) / float(revenue_row.get(yoy_col))
    except (TypeError, ValueError, ZeroDivisionError):
        return True, None, None

    if pd.isna(gm_latest) or pd.isna(gm_yoy):
        return True, None, None

    change_pp = (gm_latest - gm_yoy) * 100.0
    passed = change_pp >= -GROSS_MARGIN_YOY_MAX_DECLINE_PP
    return passed, round(gm_latest * 100.0, 1), round(change_pp, 1)


def _net_debt_ebitda_filter(net_debt_ebitda: float | None) -> tuple[bool, float | None]:
    """Anti-bankruptcy gate: Net Debt / EBITDA must be strictly below 3.0x."""
    if net_debt_ebitda is None:
        return False, None
    return net_debt_ebitda < NET_DEBT_EBITDA_MAX, net_debt_ebitda


def _fetch_fifty_two_week_high(
    info: dict,
    ticker: yf.Ticker,
) -> float | None:
    """52-week high from yfinance info or trailing 1Y history."""
    high = _safe_info_float(info, "fiftyTwoWeekHigh")
    if high is not None and high > 0:
        return high
    try:
        hist = ticker.history(period="1y")
        if hist is not None and not hist.empty and "High" in hist.columns:
            val = float(hist["High"].max())
            return val if val > 0 else None
    except Exception:
        pass
    return None


def _valuation_attractiveness_filter(
    current_price: float,
    info: dict,
    ticker: yf.Ticker,
) -> tuple[bool, float | None, float | None, float | None]:
    """
    Valuation gate: (price / 52w high) < 0.75 OR trailing PEG < 1.5.

    Returns (passed, price_to_52w_ratio, peg, fifty_two_week_high).
    Rejects when neither condition can be verified.
    """
    high_52 = _fetch_fifty_two_week_high(info, ticker)
    ratio: float | None = None
    if high_52 is not None and high_52 > 0:
        ratio = current_price / high_52

    peg = _safe_info_float(info, "trailingPegRatio")

    passed = False
    if ratio is not None and ratio < TURNAROUND_52W_HIGH_RATIO_MAX:
        passed = True
    if peg is not None and peg > 0 and peg < TURNAROUND_PEG_MAX:
        passed = True

    return passed, ratio, peg, high_52


def compute_value_defense_score_only(symbol: str) -> tuple[float, str, str]:
    """
    Run the 🛡️ value-defense 100-pt engine without LLM commentary.

    Returns (total_score, grade_emoji, grade_label). Never raises.
    """
    sym = symbol.upper().strip()
    try:
        ticker = yf.Ticker(sym)
        info = _safe_ticker_info(ticker, sym)
        fcf_rows = fetch_fcf(sym)
        div_rows = fetch_dividends(sym, ticker=ticker)
        payout = fetch_payout_ratio(sym, ticker=ticker)
        beta = _safe_beta(info)
        trend = detect_trend_signals(sym)
        master = fetch_master_metrics(sym, info, ticker=ticker)
        _, quality, valuation, emoji, label = compute_scores(
            fcf_rows,
            div_rows,
            payout,
            beta,
            strategy_mode=STRATEGY_VALUE,
            trend_signal=trend,
            info=info,
            symbol=sym,
            ticker=ticker,
            master=master,
        )
        return quality, emoji, label
    except Exception:
        return 0.0, "🔴", "防禦不足"


def _attach_value_defense_score(opp: TurnaroundOpportunity) -> TurnaroundOpportunity:
    """Enrich a turnaround hit with 100-pt value-defense score."""
    total, emoji, label = compute_value_defense_score_only(opp.symbol)
    opp.value_defense_score = total
    opp.value_grade_emoji = emoji
    opp.value_grade_label = label
    return opp


def _attach_reason_tag(opp: TurnaroundOpportunity) -> TurnaroundOpportunity:
    """Enrich with Gemini mispricing reason tag (fallback when API unavailable)."""
    try:
        news = fetch_ticker_live_news(opp.symbol)
        news_block = format_live_news_block(news)
    except Exception:
        news_block = "（無可用新聞）"

    context = (
        f"Ticker: {opp.symbol}\n"
        f"Company: {opp.company_name}\n"
        f"Drawdown vs 6M high: -{opp.drawdown_pct:.1f}%\n"
        f"Value defense score: {opp.value_defense_score or 'N/A'}/100\n"
        f"PEG: {opp.peg_ratio if opp.peg_ratio is not None else 'N/A'}\n"
        f"Price / 52w high: "
        f"{opp.price_vs_52w_high if opp.price_vs_52w_high is not None else 'N/A'}\n\n"
        f"Recent headlines:\n{news_block}"
    )
    tag, comment = _cached_llm_turnaround_reason_tag(opp.symbol.upper(), context)
    opp.reason_tag = tag
    opp.reason_comment = comment
    return opp


def _screen_single_turnaround(
    symbol: str,
    min_drawdown_pct: float,
    lookback_period: str,
) -> TurnaroundOpportunity | None:
    """
    Per-ticker pipeline with institutional defensive filters:
      price drawdown gate → positive FCF fact → right-side (Close > SMA20)
      → anti-bankruptcy (Net Debt/EBITDA < 3) → interest coverage > 3x
      → gross-margin pricing-power → R&D fact reserve.

    Core metrics served from SQLite cache via data_layer for scan speed.
    """
    from data_layer import get_financial_data

    sym = symbol.upper().strip()
    if not sym:
        return None

    try:
        fin = get_financial_data(sym)
    except Exception:
        return None

    ticker = yf.Ticker(sym)
    info = _safe_ticker_info(ticker, sym)
    name = fin.company_name or _company_name(info, sym)

    price_facts = _six_month_price_drawdown(ticker, period=lookback_period)
    if price_facts is None:
        return None

    current_price, period_high, drawdown_pct = price_facts
    if drawdown_pct <= min_drawdown_pct:
        return None

    # Filter 0 — valuation attractiveness: ≥25% off 52w high OR PEG < 1.5.
    val_ok, price_ratio, peg, high_52 = _valuation_attractiveness_filter(
        current_price, info, ticker
    )
    if not val_ok:
        return None

    fcf_val = fin.latest_fcf
    fcf_year = fin.fcf_fiscal_year
    fcf_source = fin.fcf_source or "cache/yfinance"
    if fcf_val is None or fcf_val <= 0:
        fcf_val, fcf_year, fcf_source = fetch_latest_fcf_snapshot(sym, ticker=ticker)
        if fcf_val is None or fcf_val <= 0:
            return None

    # Filter 1 — technical right-side: reject names still chinning below SMA20.
    right_side_ok, _trend = _passes_right_side_filter(ticker)
    if not right_side_ok:
        return None

    # Filter 2 — anti-bankruptcy: Net Debt / EBITDA must stay below 3.0x.
    nd_ebitda = fin.net_debt_ebitda
    leverage_ok, nd_ebitda = _net_debt_ebitda_filter(nd_ebitda)
    if not leverage_ok:
        return None

    # Filter 3 — debt moat: interest coverage must clear 3.0x when debt exists.
    interest_coverage = fin.interest_coverage
    if interest_coverage is not None:
        coverage_ok = interest_coverage >= INTEREST_COVERAGE_MIN
    else:
        coverage_ok, interest_coverage = _interest_coverage_filter(ticker)
    if not coverage_ok:
        return None

    # Filter 4 — pricing power: gross margin must not collapse YoY.
    margin_ok, gross_margin, gm_change_pp = _gross_margin_filter(ticker)
    if not margin_ok:
        return None

    # Filter 5 — anti-value-trap: reject shrinking core businesses.
    if not _anti_value_trap_filter(ticker, info):
        return None

    rd_expense, rd_year = fetch_latest_rd_expense(sym, ticker=ticker)

    return TurnaroundOpportunity(
        symbol=sym,
        company_name=name,
        drawdown_pct=round(drawdown_pct, 1),
        current_price=round(current_price, 2),
        six_month_high=round(period_high, 2),
        latest_fcf=fcf_val,
        latest_fcf_fiscal_year=fcf_year,
        fcf_source=fcf_source or "unknown",
        rd_expense=rd_expense,
        rd_fiscal_year=rd_year,
        interest_coverage=interest_coverage,
        gross_margin=gross_margin,
        gross_margin_yoy_change_pp=gm_change_pp,
        net_debt_ebitda=nd_ebitda,
        fifty_two_week_high=round(high_52, 2) if high_52 is not None else None,
        price_vs_52w_high=round(price_ratio, 3) if price_ratio is not None else None,
        peg_ratio=round(peg, 2) if peg is not None else None,
    )


def find_turnaround_opportunities(
    ticker_list: list[str],
    *,
    min_drawdown_pct: float = TURNAROUND_MIN_DRAWDOWN_PCT,
    lookback_period: str = TURNAROUND_LOOKBACK,
    enrich_scores: bool = True,
    enrich_tags: bool = True,
) -> list[TurnaroundOpportunity]:
    """
    Active turnaround screener — integrated with 🛡️ value-defense scoring loop.

    Filters (all mandatory):
      6M drawdown > 15% · valuation (52w high ≥25% off OR PEG < 1.5)
      FCF > 0 · Close > SMA20 · Net Debt/EBITDA < 3 · interest coverage > 3x
      gross margin YoY stable · 3Y revenue CAGR > 0 (anti-value-trap)

    Post-scan enrichment (default on):
      · 100-pt value-defense score per candidate
      · Gemini mispricing reason tag ([產業週期下行] / [短期利空] / [成長放緩但護城河存])

    Core metrics via `data_layer` SQLite cache. Sorted by defense score, then drawdown.
    """
    candidates: list[TurnaroundOpportunity] = []

    for raw in ticker_list:
        try:
            hit = _screen_single_turnaround(raw, min_drawdown_pct, lookback_period)
            if hit is not None:
                candidates.append(hit)
        except Exception:
            continue

    if enrich_scores:
        for i, hit in enumerate(candidates):
            try:
                candidates[i] = _attach_value_defense_score(hit)
            except Exception:
                continue

    if enrich_tags:
        for i, hit in enumerate(candidates):
            try:
                candidates[i] = _attach_reason_tag(hit)
            except Exception:
                continue

    candidates.sort(
        key=lambda o: (o.value_defense_score or 0.0, o.drawdown_pct),
        reverse=True,
    )
    return candidates


def normalize_equity_ticker(symbol: str) -> str:
    """Normalize Wikipedia / vendor symbols for yfinance (e.g. BRK.B → BRK-B)."""
    token = str(symbol).strip().upper().replace(".", "-")
    token = re.sub(r"\s+", "", token)
    return token


def _is_plausible_ticker(symbol: str) -> bool:
    return bool(symbol) and bool(_TICKER_PATTERN.match(symbol))


def _normalize_table_columns(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    if isinstance(out.columns, pd.MultiIndex):
        out.columns = [
            str(levels[0]).strip() if str(levels[0]).strip() else str(levels[-1]).strip()
            for levels in out.columns
        ]
    else:
        out.columns = [str(c).strip() for c in out.columns]
    return out


def _symbols_from_frame(df: pd.DataFrame) -> list[str]:
    frame = _normalize_table_columns(df)
    columns = {str(c).strip(): c for c in frame.columns}

    for candidate in _SYMBOL_COLUMN_CANDIDATES:
        if candidate in columns:
            values = frame[columns[candidate]].dropna().astype(str).tolist()
            cleaned = [
                normalize_equity_ticker(v)
                for v in values
                if _is_plausible_ticker(normalize_equity_ticker(v))
            ]
            if cleaned:
                return cleaned

    for col_name, col in columns.items():
        lower = col_name.lower()
        if "symbol" in lower or lower == "ticker":
            values = frame[col].dropna().astype(str).tolist()
            cleaned = [
                normalize_equity_ticker(v)
                for v in values
                if _is_plausible_ticker(normalize_equity_ticker(v))
            ]
            if cleaned:
                return cleaned
    return []


def _read_html_tables(html: str, **kwargs) -> list[pd.DataFrame]:
    """Parse HTML tables with lxml first, then html5lib."""
    last_error: Exception | None = None
    buffer = StringIO(html)
    for flavor in ("lxml", "html5lib"):
        try:
            buffer.seek(0)
            return pd.read_html(buffer, flavor=flavor, **kwargs)
        except ImportError as exc:
            last_error = exc
            continue
        except ValueError:
            raise
        except Exception as exc:
            last_error = exc
            continue
    if last_error:
        raise last_error
    raise ValueError("No HTML parser available for Wikipedia tables")


def _fetch_wikipedia_tables(url: str) -> list[pd.DataFrame]:
    resp = requests.get(url, headers=SEC_HEADERS, timeout=45)
    resp.raise_for_status()
    html = resp.text

    collected: list[pd.DataFrame] = []
    seen_ids: set[int] = set()

    def _append_tables(found: list[pd.DataFrame]) -> None:
        for table in found:
            tid = id(table)
            if tid not in seen_ids:
                seen_ids.add(tid)
                collected.append(table)

    for attrs in (
        {"class": "wikitable"},
    ):
        try:
            _append_tables(_read_html_tables(html, attrs=attrs))
        except ValueError:
            continue
        except Exception:
            continue

    if not collected:
        try:
            _append_tables(_read_html_tables(html, match="Symbol"))
        except ValueError:
            pass

    try:
        _append_tables(_read_html_tables(html))
    except ValueError:
        pass

    if not collected:
        raise ValueError(f"No Wikipedia tables parsed for {url}")
    return collected


def _extract_symbols_from_tables(
    tables: list[pd.DataFrame],
    index_key: str | None = None,
) -> list[str]:
    expected = _INDEX_EXPECTED_COUNTS.get(index_key or "")
    best: list[str] = []

    for table in tables:
        symbols = _symbols_from_frame(table)
        if not symbols:
            continue
        if expected:
            low, high = expected
            if low <= len(symbols) <= high:
                return symbols
        if len(symbols) > len(best):
            best = symbols

    return best


def fetch_index_constituents(index_key: str) -> list[str]:
    """
    Fetch latest index constituents from Wikipedia.

    Raises on network/parse failures — callers should fall back to
    `FALLBACK_SCAN_UNIVERSE` when needed.
    """
    url = WIKI_INDEX_PAGES.get(index_key)
    if not url:
        raise ValueError(f"Unknown index key: {index_key}")

    last_error: Exception | None = None
    symbols: list[str] = []

    try:
        tables = _fetch_wikipedia_tables(url)
        symbols = _extract_symbols_from_tables(tables, index_key=index_key)
    except Exception as exc:
        last_error = exc

    if not symbols:
        raise ValueError(f"No symbols parsed for index: {index_key}") from last_error

    seen: set[str] = set()
    ordered: list[str] = []
    for sym in symbols:
        if sym and sym not in seen:
            seen.add(sym)
            ordered.append(sym)
    return ordered


def fetch_social_sentiment(ticker: str) -> dict | None:
    """
    Social arbitrage hook (Module 2 — reserved).

    未來將接入 Chris Camillo 風格的趨勢感測邏輯，整合 Reddit / TikTok /
    其他社群訊號，用於「財報前敘事套利」與異常社會熱度偵測。

    TODO: Wire Reddit / TikTok / X APIs and normalize sentiment scores.
    """
    _ = ticker.upper().strip()
    return None


def fetch_index_constituents_safe(index_key: str) -> tuple[list[str], str]:
    """Return (tickers, source) where source is 'wikipedia' or 'fallback'."""
    try:
        return fetch_index_constituents(index_key), "wikipedia"
    except Exception:
        return list(FALLBACK_SCAN_UNIVERSE), "fallback"


def _daily_close_with_smas(hist: pd.DataFrame) -> pd.DataFrame | None:
    """Build close + SMA_20 + SMA_50 frame; None if insufficient history."""
    try:
        if hist is None or hist.empty or "Close" not in hist.columns:
            return None
        close = hist["Close"].dropna()
        if len(close) < MIN_TREND_BARS:
            return None
        frame = pd.DataFrame({"close": close})
        frame["sma_20"] = frame["close"].rolling(SMA_SHORT).mean()
        frame["sma_50"] = frame["close"].rolling(SMA_LONG).mean()
        frame = frame.dropna()
        if len(frame) < 2:
            return None
        return frame
    except Exception:
        return None


def _classify_trend_signal(
    close: float,
    sma_20: float,
    sma_50: float,
    prev_sma_20: float,
    prev_sma_50: float,
) -> str:
    """
    Map latest bar to trader position labels (strict evaluation order).

    1. Buy  — golden cross + price above SMA_50 defense line
    2. Sell — death cross (SMA_20 crosses below SMA_50)
    3. Wait — SMA_20 < SMA_50 (bearish stack; never Hold while short < medium)
    4. Hold — SMA_20 >= SMA_50 without a fresh crossover trigger
    """
    golden_cross = prev_sma_20 <= prev_sma_50 and sma_20 > sma_50
    death_cross = prev_sma_20 >= prev_sma_50 and sma_20 < sma_50

    if golden_cross and close > sma_50:
        return "Buy"
    if death_cross:
        return "Sell"
    if sma_20 < sma_50:
        return "Wait"
    return "Hold"


def detect_trend_signals(
    ticker: str | yf.Ticker,
    *,
    period: str = TREND_HISTORY_PERIOD,
) -> dict[str, float | str | None] | None:
    """
    Right-side trend detector using 1Y daily bars and SMA-20 / SMA-50 crossovers.

    Auxiliary module for per-symbol timing (integrates with `analyze_symbol`).

    Returns None when history is missing or too short; never raises on bad tickers.
    """
    try:
        if isinstance(ticker, str):
            sym = ticker.upper().strip()
            yf_ticker = yf.Ticker(sym)
        else:
            yf_ticker = ticker
            sym = str(getattr(ticker, "ticker", "") or "").upper()

        hist = yf_ticker.history(period=period)
        frame = _daily_close_with_smas(hist)
        if frame is None:
            return None

        latest = frame.iloc[-1]
        previous = frame.iloc[-2]

        close = float(latest["close"])
        sma_20 = float(latest["sma_20"])
        sma_50 = float(latest["sma_50"])
        prev_sma_20 = float(previous["sma_20"])
        prev_sma_50 = float(previous["sma_50"])

        signal = _classify_trend_signal(
            close, sma_20, sma_50, prev_sma_20, prev_sma_50
        )

        as_of = frame.index[-1]
        as_of_str = as_of.strftime("%Y-%m-%d") if hasattr(as_of, "strftime") else str(as_of)

        return TrendSignal(
            current_signal=signal,
            current_price=close,
            sma_20=sma_20,
            sma_50=sma_50,
            symbol=sym,
            prev_sma_20=prev_sma_20,
            prev_sma_50=prev_sma_50,
            as_of_date=as_of_str,
        ).to_dict()
    except Exception:
        return None


def score_fcf_component(rows: list[YearFCF]) -> ScoreDetail:
    max_pts = WEIGHT_FCF
    if not rows:
        return ScoreDetail(
            "FCF 連續為正",
            max_pts,
            0.0,
            "無法取得自由現金流年報序列，扣滿 40 分。",
        )

    available = min(len(rows), YEARS_REQUIRED)
    window = rows[:available]
    proportional_max = max_pts * (available / YEARS_REQUIRED)
    failed = [r for r in window if r.free_cash_flow <= 0]
    penalty = PENALTY_FCF_PER_YEAR * len(failed)
    earned = max(0.0, proportional_max - penalty)

    if not failed and available == YEARS_REQUIRED:
        rationale = (
            f"最近 {YEARS_REQUIRED} 個財年 FCF 全為正，拿滿 {max_pts:.0f} 分。"
        )
    elif not failed:
        rationale = (
            f"僅有 {available} 年 SEC/雅虎數據（目標 {YEARS_REQUIRED} 年），"
            f"等比例滿分 {proportional_max:.1f}，全部為正未扣分。"
        )
    else:
        bad = ", ".join(str(r.fiscal_year) for r in failed)
        rationale = (
            f"評估 {available} 年（等比例滿分 {proportional_max:.1f}），"
            f"負值/零值財年：{bad}，每處扣 {PENALTY_FCF_PER_YEAR:.0f} 分，得 {earned:.1f} 分。"
        )
    return ScoreDetail("FCF 連續為正", max_pts, round(earned, 1), rationale)


def score_dividend_growth_component(history: list[YearDividend]) -> ScoreDetail:
    max_pts = WEIGHT_DIV
    if len(history) < 2:
        return ScoreDetail(
            "股息連續成長",
            max_pts,
            0.0,
            "股息歷史不足，無法評估連續成長，扣滿 30 分。",
        )

    growth_checks = [h.yoy_growth for h in history[1:]]
    target_checks = growth_checks[-YEARS_REQUIRED:]
    available = len(target_checks)
    if available == 0:
        return ScoreDetail("股息連續成長", max_pts, 0.0, "無有效年度可比較，扣滿 30 分。")

    proportional_max = max_pts * (available / YEARS_REQUIRED)
    failed_indices = [
        i for i, g in enumerate(target_checks) if not (g is not None and g > 0)
    ]
    penalty = PENALTY_DIV_PER_YEAR * len(failed_indices)
    earned = max(0.0, proportional_max - penalty)

    if not failed_indices and available == YEARS_REQUIRED:
        yrs = [h.calendar_year for h in history[-YEARS_REQUIRED - 1 :]]
        rationale = (
            f"{yrs[0]}→{yrs[-1]} 連續 {YEARS_REQUIRED} 年 DPS 上升，拿滿 {max_pts:.0f} 分。"
        )
    elif not failed_indices:
        rationale = (
            f"僅 {available} 年成長紀錄，等比例滿分 {proportional_max:.1f}，"
            "期間皆 YoY 正成長。"
        )
    else:
        flat_years = [
            str(history[-YEARS_REQUIRED + i].calendar_year)
            for i in failed_indices
            if i < len(history)
        ]
        rationale = (
            f"評估最近 {available} 年成長（滿分 {proportional_max:.1f}），"
            f"未增長年份：{', '.join(flat_years) or '見細項'}，"
            f"每處扣 {PENALTY_DIV_PER_YEAR:.0f} 分，得 {earned:.1f} 分。"
        )
    return ScoreDetail("股息連續成長", max_pts, round(earned, 1), rationale)


def score_payout_component(payout: float | None) -> ScoreDetail:
    max_pts = WEIGHT_PAYOUT
    if payout is None:
        return ScoreDetail(
            "股息發放率",
            max_pts,
            0.0,
            "無法取得發放率（payout ratio），本項 0 分。",
        )

    pct = payout * 100
    if 0.30 <= payout <= 0.65:
        earned = 20.0
        tier = "核心安全區間 30%–65%"
    elif 0.10 <= payout < 0.30:
        earned = 15.0
        tier = "偏保守/成長留存區 10%–29%"
    elif 0.66 <= payout <= 0.80:
        earned = 10.0
        tier = "偏高但可接受 66%–80%"
    else:
        earned = 0.0
        tier = "超出理想區間（<10% 或 >80%）"

    rationale = f"最新發放率 {pct:.1f}%（{tier}），本項得 {earned:.0f}/{max_pts:.0f} 分。"
    return ScoreDetail("股息發放率", max_pts, earned, rationale)


def score_beta_component(beta: float | None) -> ScoreDetail:
    max_pts = WEIGHT_BETA
    if beta is None:
        return ScoreDetail(
            "Beta 波動",
            max_pts,
            0.0,
            "無法取得 Beta，本項 0 分。",
        )

    if beta <= 0.8:
        earned = 10.0
        band = "低波動 ≤0.8"
    elif beta <= 1.2:
        earned = 7.0
        band = "市場中性 0.8–1.2"
    else:
        earned = 3.0
        band = "高波動 >1.2"

    rationale = f"Beta={beta:.2f}（{band}），本項得 {earned:.0f}/{max_pts:.0f} 分。"
    return ScoreDetail("Beta 波動", max_pts, earned, rationale)


def score_revenue_potential_component(
    revenue_growth: float | None,
    info: dict,
    symbol: str,
    ticker: yf.Ticker | None = None,
) -> ScoreDetail:
    """Revenue & forward potential — R&D incubation floor for pre-revenue biotech."""
    max_pts = WEIGHT_GROWTH_REVENUE
    info = info or {}

    if revenue_growth is not None and revenue_growth > 0:
        pct = revenue_growth * 100
        if revenue_growth >= 0.20:
            earned, band = max_pts, "高速成長 ≥20%"
        elif revenue_growth >= 0.10:
            earned, band = max_pts * 0.85, "強勁成長 10%–20%"
        elif revenue_growth >= 0.03:
            earned, band = max_pts * 0.70, "穩健成長 3%–10%"
        else:
            earned, band = max_pts * 0.55, "低個位數正成長"
        rationale = f"營收成長 {pct:.1f}%（{band}），本項得 {earned:.1f}/{max_pts:.0f} 分。"
        return ScoreDetail("營收與未來預期", max_pts, round(earned, 1), rationale)

    rd_expense, rd_year = fetch_latest_rd_expense(symbol, ticker=ticker)
    total_revenue = _safe_info_float(info, "totalRevenue")
    qtr_momentum = _safe_info_float(info, "earningsQuarterlyGrowth")
    if qtr_momentum is None:
        qtr_momentum = _safe_info_float(info, "earningsGrowth")

    earned = 0.0
    rationale_parts: list[str] = []

    if revenue_growth is not None and revenue_growth <= 0:
        pct = revenue_growth * 100
        rationale_parts.append(f"年度營收成長 {pct:.1f}%（成長股常見陣痛期）")
    else:
        rationale_parts.append("年度營收成長數據缺失")

    if qtr_momentum is not None:
        q_pct = qtr_momentum * 100
        if qtr_momentum > 0.05:
            earned = max(earned, max_pts * 0.75)
            rationale_parts.append(f"季報動能 +{q_pct:.1f}%")
        elif qtr_momentum > 0:
            earned = max(earned, max_pts * 0.55)
            rationale_parts.append(f"季報微幅正成長 +{q_pct:.1f}%")
        else:
            rationale_parts.append(f"季報動能 {q_pct:.1f}%")

    if rd_expense and total_revenue and total_revenue > 0:
        rd_ratio = rd_expense / total_revenue
        rd_pct = rd_ratio * 100
        if rd_ratio >= 0.40:
            earned = max(earned, max_pts * 0.90)
            rationale_parts.append(
                f"R&D ${rd_expense/1e6:.0f}M 佔營收 {rd_pct:.1f}%（{rd_year or '最新'} 財年 · 重度孵化）"
            )
        elif rd_ratio >= 0.25:
            earned = max(earned, max_pts * 0.78)
            rationale_parts.append(f"R&D 佔營收 {rd_pct:.1f}%（高投入創新期）")
        elif rd_ratio >= 0.12:
            earned = max(earned, max_pts * 0.62)
            rationale_parts.append(f"R&D 佔營收 {rd_pct:.1f}%（中度研發投入）")
        elif rd_ratio >= 0.05:
            earned = max(earned, max_pts * 0.45)
            rationale_parts.append(f"R&D 佔營收 {rd_pct:.1f}%")
    elif rd_expense and rd_expense > 0:
        earned = max(earned, max_pts * 0.50)
        rationale_parts.append(
            f"最新 R&D ${rd_expense/1e6:.0f}M（{rd_year or '最新'} 財年 · 生技/新創孵化中）"
        )

    if earned <= 0:
        earned = max_pts * 0.30
        rationale_parts.append("給予孵化期基礎分，避免因短期營收為負直接歸零")

    rationale = " · ".join(rationale_parts) + f"，本項得 {earned:.1f}/{max_pts:.0f} 分。"
    return ScoreDetail("營收與未來預期", max_pts, round(earned, 1), rationale)


def score_growth_momentum_component(
    trend: dict[str, float | str | None] | None,
) -> ScoreDetail:
    """Legacy alias → demoted technical timing auxiliary (15 pts)."""
    return score_growth_technical_timing_component(trend)


def score_growth_technical_timing_component(
    trend: dict[str, float | str | None] | None,
) -> ScoreDetail:
    """Technical timing auxiliary — SMA cluster for entry timing only (15 pts max)."""
    max_pts = WEIGHT_GROWTH_TECH_TIMING
    category = "技術面輔助 (Timing)"
    if not trend:
        return ScoreDetail(
            category,
            max_pts,
            max_pts * 0.40,
            "趨勢數據不足；Timing 輔助給予中性基礎分（不主導決策）。",
        )

    signal = str(trend.get("current_signal", "Hold"))
    try:
        price = float(trend.get("current_price", 0))
        sma_20 = float(trend.get("sma_20", 0))
        sma_50 = float(trend.get("sma_50", 0))
    except (TypeError, ValueError):
        return ScoreDetail(category, max_pts, max_pts * 0.30, "均線數據格式異常。")

    above_20 = price > sma_20
    above_50 = price > sma_50

    if above_20 and above_50:
        earned = max_pts
        band = "均線群確認 · 可作 Timing 加分（非基本面主導）"
    elif above_20:
        earned = max_pts * 0.65
        band = "站上 SMA20 · 短線 Timing 尚可"
    elif above_50:
        earned = max_pts * 0.45
        band = "SMA50 上方但 SMA20 下方 · 整理區"
    elif signal == "Wait":
        earned = max_pts * 0.20
        band = "弱勢結構 · Timing 不利"
    else:
        earned = max_pts * 0.10
        band = "均線下方 · 僅供觀察"

    rationale = (
        f"收盤 ${price:.2f} | SMA20 ${sma_20:.2f} | SMA50 ${sma_50:.2f} · "
        f"{band}，本項得 {earned:.1f}/{max_pts:.0f} 分（Timing 輔助）。"
    )
    return ScoreDetail(category, max_pts, round(earned, 1), rationale)


def score_growth_beta_component(beta: float | None) -> ScoreDetail:
    """Growth-mode beta: reward explosive elasticity in the 1.1–1.8 sweet spot."""
    max_pts = WEIGHT_GROWTH_BETA
    if beta is None:
        return ScoreDetail(
            "Beta 彈性",
            max_pts,
            max_pts * 0.35,
            "無 Beta 數據，給予中性基礎分（35%）。",
        )

    if 1.1 <= beta <= 1.8:
        earned = max_pts
        band = "理想彈性區間 1.1–1.8"
    elif 0.8 <= beta < 1.1:
        earned = max_pts * 0.65
        band = "偏低彈性 0.8–1.1"
    elif 1.8 < beta <= 2.5:
        earned = max_pts * 0.55
        band = "高彈性 1.8–2.5"
    elif beta > 2.5:
        earned = max_pts * 0.12
        band = "波動率過高 >2.5"
    elif beta < 0.5:
        earned = max_pts * 0.15
        band = "毫無動能 <0.5"
    else:
        earned = max_pts * 0.45
        band = "中性區 0.5–0.8"

    rationale = f"Beta={beta:.2f}（{band}），本項得 {earned:.1f}/{max_pts:.0f} 分。"
    return ScoreDetail("Beta 彈性", max_pts, round(earned, 1), rationale)


def _growth_excluded_component(category: str, note: str) -> ScoreDetail:
    """Placeholder — growth mode never scores FCF / dividend / payout."""
    return ScoreDetail(category, 0.0, 0.0, note)


def score_value_quality_component(master: MasterMetrics) -> ScoreDetail:
    """🛡️ Enterprise quality (35): ROIC + GM stability + operating margin."""
    max_pts = WEIGHT_VALUE_QUALITY
    category = "企業品質與護城河"
    earned = 0.0
    parts: list[str] = []

    # ROIC — max 13
    roic = master.roic if master.roic is not None else master.roa
    if roic is not None:
        if roic >= 0.15:
            sub, tag = 13.0, "卓越 ≥15%"
        elif roic >= 0.12:
            sub, tag = 10.5, "優異 12%–15%"
        elif roic >= 0.10:
            sub, tag = 8.0, "穩健 10%–12%"
        elif roic >= 0.07:
            sub, tag = 5.0, "普通 7%–10%"
        elif roic >= 0.04:
            sub, tag = 2.5, "偏弱 4%–7%"
        elif roic > 0:
            sub, tag = 1.0, "低 <4%"
        else:
            sub, tag = 0.0, "為負（資本配置失敗）"
        earned += sub
        src = "ROIC" if master.roic is not None else "ROA proxy"
        parts.append(f"{src} {roic*100:.1f}%（{tag}）")
        if master.roe is not None and master.roic is not None and master.roe > master.roic * 1.8:
            parts.append(f"⚠ ROE {master.roe*100:.1f}% 顯著高於 ROIC，留意槓桿撐高假象")
    else:
        earned += 13.0 * 0.30
        parts.append("ROIC 數據缺失（給予中性基礎）")

    # Gross margin stability — max 9
    gm_vol = master.gross_margin_volatility
    if gm_vol is not None:
        if gm_vol <= 5.0:
            sub, tag = 9.0, "極穩定 ≤5pp"
        elif gm_vol <= 10.0:
            sub, tag = 6.0, "穩健 5–10pp"
        elif gm_vol <= 15.0:
            sub, tag = 3.5, "波動 10–15pp"
        elif gm_vol <= 20.0:
            sub, tag = 1.5, "不穩 15–20pp"
        else:
            sub, tag = 0.0, "劇烈波動 >20pp"
        earned += sub
        parts.append(f"毛利率波動 {gm_vol:.1f}pp（{tag}）")
    else:
        earned += 9.0 * 0.30
        parts.append("毛利率穩定度數據不足")

    # Operating margin — max 13
    om = master.ttm_operating_margin
    if om is None and master.operating_margin_latest is not None:
        om = master.operating_margin_latest / 100.0
    if om is not None:
        if om >= 0.20:
            sub, tag = 13.0, "強勢 ≥20%"
        elif om >= 0.15:
            sub, tag = 10.5, "優良 15%–20%"
        elif om >= 0.10:
            sub, tag = 8.0, "穩健 10%–15%"
        elif om >= 0.05:
            sub, tag = 4.5, "普通 5%–10%"
        elif om > 0:
            sub, tag = 2.0, "薄利 <5%"
        else:
            sub, tag = 0.0, "為負"
        earned += sub
        parts.append(f"營業利益率 {om*100:.1f}%（{tag}）")
    else:
        earned += 13.0 * 0.30
        parts.append("營業利益率數據缺失")

    rationale = " · ".join(parts) + f"，本項得 {earned:.1f}/{max_pts:.0f} 分。"
    return ScoreDetail(category, max_pts, round(earned, 1), rationale)


def score_value_cashflow_component(
    master: MasterMetrics,
    div_rows: list[YearDividend],
) -> ScoreDetail:
    """🛡️ Cashflow quality (25): FCF payout + dividend growth streak."""
    max_pts = WEIGHT_VALUE_CASHFLOW
    category = "現金流品質"
    earned = 0.0
    parts: list[str] = []

    # FCF payout ratio — max 12.5
    fcf_pay = master.fcf_payout_ratio
    if fcf_pay is not None:
        if fcf_pay > FCF_PAYOUT_DEATH_THRESHOLD:
            sub, tag = 0.0, f"危險 >{FCF_PAYOUT_DEATH_THRESHOLD*100:.0f}%（死亡懲罰觸發）"
        elif fcf_pay <= 0.50:
            sub, tag = 12.5, "安全 ≤50%"
        elif fcf_pay <= 0.70:
            sub, tag = 9.0, "穩健 50%–70%"
        elif fcf_pay <= 0.80:
            sub, tag = 6.0, "偏緊 70%–80%"
        else:
            sub, tag = 2.5, f"警戒 80%–{FCF_PAYOUT_DEATH_THRESHOLD*100:.0f}%"
        earned += sub
        parts.append(f"FCF 支付率 {fcf_pay*100:.1f}%（{tag}）")
    else:
        earned += 12.5 * 0.35
        parts.append("FCF 支付率數據不足（給予中性基礎）")

    div_detail = score_dividend_growth_component(div_rows)
    div_part = div_detail.earned / WEIGHT_DIV * 12.5
    earned += div_part
    parts.append(f"股息成長 {div_part:.1f}/12.5 — {div_detail.rationale.split('，本項')[0]}")

    rationale = " · ".join(parts) + f"，合計 {earned:.1f}/{max_pts:.0f} 分。"
    return ScoreDetail(category, max_pts, round(earned, 1), rationale)


def score_value_safety_component(master: MasterMetrics) -> ScoreDetail:
    """🛡️ Financial safety (25): Net Debt/EBITDA + interest coverage."""
    max_pts = WEIGHT_VALUE_SAFETY
    category = "財務安全防線"
    earned = 0.0
    parts: list[str] = []

    # Net Debt / EBITDA — max 12.5
    nd_ebitda = master.net_debt_ebitda
    if nd_ebitda is not None:
        if nd_ebitda > NET_DEBT_EBITDA_DEATH_THRESHOLD:
            sub, tag = 0.0, f"高槓桿 >{NET_DEBT_EBITDA_DEATH_THRESHOLD:.0f}x（死亡懲罰觸發）"
        elif nd_ebitda <= 2.0:
            sub, tag = 12.5, "穩健 ≤2x"
        elif nd_ebitda <= 2.5:
            sub, tag = 10.0, "可接受 2–2.5x"
        else:
            sub, tag = 6.0, f"偏緊 2.5–{NET_DEBT_EBITDA_DEATH_THRESHOLD:.0f}x"
        earned += sub
        parts.append(f"淨債務/EBITDA {nd_ebitda:.1f}x（{tag}）")
    else:
        earned += 12.5 * 0.50
        parts.append("淨債務/EBITDA 數據不足")

    cov = master.interest_coverage
    if cov is not None:
        if cov >= 5.0:
            sub, tag = 12.5, "充裕 ≥5x"
        elif cov >= 4.0:
            sub, tag = 10.0, "穩健 4–5x"
        elif cov >= 3.0:
            sub, tag = 6.0, "及格 3–4x"
        elif cov >= 1.5:
            sub, tag = 2.5, "偏緊 1.5–3x"
        else:
            sub, tag = 0.0, "脆弱 <1.5x"
        earned += sub
        parts.append(f"利息保障 {cov:.1f}x（{tag}）")
    else:
        earned += 12.5 * 0.85
        parts.append("低負債結構（無顯著利息支出）")

    rationale = " · ".join(parts) + f"，本項得 {earned:.1f}/{max_pts:.0f} 分。"
    return ScoreDetail(category, max_pts, round(earned, 1), rationale)


def score_value_revenue_stability_component(master: MasterMetrics) -> ScoreDetail:
    """🛡️ Revenue stability floor (15): 5Y revenue CAGR."""
    max_pts = WEIGHT_VALUE_REVENUE
    category = "營收穩定"
    cagr = master.revenue_cagr_5y

    if cagr is not None:
        if cagr < 0:
            earned, tag = 0.0, "負成長（衰退型價值陷阱風險）"
        elif cagr >= 0.05:
            earned, tag = max_pts, "強勁 ≥5%"
        elif cagr >= 0.03:
            earned, tag = 10.0, "溫和 3%–5%"
        elif cagr >= 0:
            earned, tag = 6.0, "停滯 0%–3%"
        else:
            earned, tag = 0.0, "衰退"
        rationale = f"5Y 營收 CAGR {cagr*100:+.1f}%（{tag}），本項得 {earned:.1f}/{max_pts:.0f} 分。"
    else:
        rev = master.revenue_growth or master.ttm_revenue_growth
        if rev is not None and rev >= 0.05:
            earned = max_pts * 0.70
            rationale = (
                f"5Y CAGR 不足，以 TTM 營收增速 {rev*100:+.1f}% 輔助，"
                f"本項得 {earned:.1f}/{max_pts:.0f} 分。"
            )
        elif rev is not None and rev < 0:
            earned = 0.0
            rationale = f"TTM 營收衰退 {rev*100:+.1f}%，本項得 0/{max_pts:.0f} 分。"
        else:
            earned = max_pts * 0.35
            rationale = f"營收成長數據不足，給予中性基礎 {earned:.1f}/{max_pts:.0f} 分。"

    return ScoreDetail(category, max_pts, round(earned, 1), rationale)


def _apply_value_death_penalties(
    details: list[ScoreDetail],
    master: MasterMetrics,
) -> float:
    """Asymmetric death penalties — safety/cashflow zero-out + cap / extra deduct."""
    total = sum(d.earned for d in details)
    cap_total = False

    if (
        master.net_debt_ebitda is not None
        and master.net_debt_ebitda > NET_DEBT_EBITDA_DEATH_THRESHOLD
    ):
        for d in details:
            if "財務安全" in d.category:
                total -= d.earned
                d.earned = 0.0
                d.rationale += (
                    f" 【不對稱死亡懲罰】淨債務/EBITDA {master.net_debt_ebitda:.1f}x > "
                    f"{NET_DEBT_EBITDA_DEATH_THRESHOLD:.0f}x，財務安全類歸零，"
                    f"總分封頂 {VALUE_SCORE_DEATH_CAP:.0f}。"
                )
        cap_total = True

    if (
        master.fcf_payout_ratio is not None
        and master.fcf_payout_ratio > FCF_PAYOUT_DEATH_THRESHOLD
    ):
        for d in details:
            if "現金流" in d.category:
                total -= d.earned
                d.earned = 0.0
                d.rationale += (
                    f" 【不對稱死亡懲罰】FCF 支付率 {master.fcf_payout_ratio*100:.1f}% > "
                    f"{FCF_PAYOUT_DEATH_THRESHOLD*100:.0f}%，現金流類歸零，"
                    f"額外扣 {FCF_PAYOUT_EXTRA_PENALTY:.0f} 分。"
                )
        total = max(0.0, total - FCF_PAYOUT_EXTRA_PENALTY)

    if cap_total:
        total = min(total, VALUE_SCORE_DEATH_CAP)

    return apply_score_cap(total)


def score_earnings_surprise_component(
    master: MasterMetrics,
    *,
    category: str,
    max_pts: float,
) -> ScoreDetail:
    """Earnings surprise (consensus repricing): reward consecutive beats / upward revision."""
    streak = master.surprise_beat_streak or 0
    latest = master.surprise_latest_pct
    sample = master.surprise_sample or 0

    if sample == 0:
        return ScoreDetail(
            category,
            max_pts,
            round(max_pts * 0.35, 1),
            "近期財報預期偏差數據不足，給予中性基礎分（35%）。",
        )

    if streak >= 4:
        earned, tag = max_pts, f"連續 {streak} 季超越市場預期（強勁預期上調動能）"
    elif streak == 3:
        earned, tag = max_pts * 0.85, "連續 3 季超預期"
    elif streak == 2:
        earned, tag = max_pts * 0.70, "連續 2 季超預期"
    elif streak == 1:
        earned, tag = max_pts * 0.55, "最近一季超越市場預期"
    elif latest is not None and latest > 0:
        earned, tag = max_pts * 0.50, "最新一季正向偏差但動能不連續"
    else:
        earned, tag = max_pts * 0.20, "最新一季不及市場預期（預期下修風險）"

    latest_txt = f"{latest:+.1f}%" if latest is not None else "N/A"
    rationale = (
        f"最新一季 Surprise {latest_txt} · 樣本 {sample} 季 · {tag}，"
        f"本項得 {earned:.1f}/{max_pts:.0f} 分。"
    )
    return ScoreDetail(category, max_pts, round(earned, 1), rationale)


def score_forward_asymmetry_component(master: MasterMetrics) -> ScoreDetail:
    """Legacy alias — fundamental growth leg (30 pts)."""
    return score_growth_fundamental_component(master)


def score_growth_fundamental_component(master: MasterMetrics) -> ScoreDetail:
    """🚀 Fundamental growth (30): revenue momentum + CapEx expansion."""
    max_pts = WEIGHT_GROWTH_FUNDAMENTAL
    category = "基本面增長"
    earned = 0.0
    parts: list[str] = []

    rev = master.revenue_growth or master.ttm_revenue_growth
    if rev is not None and rev > 0:
        if rev >= 0.20:
            sub, tag = 18.0, "高速 ≥20%"
        elif rev >= 0.10:
            sub, tag = 15.0, "強勁 10%–20%"
        elif rev >= 0.05:
            sub, tag = 11.0, "穩健 5%–10%"
        else:
            sub, tag = 7.0, "低個位數"
        earned += sub
        parts.append(f"營收成長 {rev*100:.1f}%（{tag}）")
    elif master.revenue_cagr_5y is not None and master.revenue_cagr_5y > 0:
        sub = min(18.0, 18.0 * (master.revenue_cagr_5y / 0.15))
        earned += sub
        parts.append(f"5Y 營收 CAGR {master.revenue_cagr_5y*100:+.1f}%")
    else:
        earned += 18.0 * 0.25
        parts.append("營收成長數據不足")

    cg = master.capex_growth
    if cg is not None:
        cg_pct = cg * 100
        if cg >= 0.25:
            sub, tag = 12.0, "CapEx 擴張 ≥25%"
        elif cg >= 0.10:
            sub, tag = 9.0, "CapEx 擴張 10%–25%"
        elif cg >= 0.0:
            sub, tag = 6.0, "CapEx 溫和擴張"
        elif cg >= -0.15:
            sub, tag = 3.0, "CapEx 收縮"
        else:
            sub, tag = 1.0, "CapEx 大幅收縮"
        earned += sub
        parts.append(f"CapEx YoY {cg_pct:+.1f}%（{tag}）")
    else:
        earned += 12.0 * 0.35
        parts.append("CapEx 動態缺失")

    rationale = " · ".join(parts) + f"，本項得 {earned:.1f}/{max_pts:.0f} 分。"
    return ScoreDetail(category, max_pts, round(earned, 1), rationale)


def score_growth_risk_buffer_component(
    master: MasterMetrics,
    beta: float | None = None,
) -> ScoreDetail:
    """🚀 Risk buffer (5): leverage, red flags, volatility — quality-track cushion."""
    max_pts = WEIGHT_GROWTH_RISK_BUFFER
    category = "風險緩衝"
    earned = max_pts * 0.55
    parts: list[str] = []

    if master.net_debt_ebitda is not None:
        if master.net_debt_ebitda > NET_DEBT_EBITDA_DEATH_THRESHOLD:
            earned = max_pts * 0.10
            parts.append(f"淨債務/EBITDA {master.net_debt_ebitda:.1f}x 超標")
        elif master.net_debt_ebitda < 1.5:
            earned = max(earned, max_pts * 0.90)
            parts.append(f"槓桿溫和 {master.net_debt_ebitda:.1f}x")

    if master.operating_margin_red_flag:
        earned = min(earned, max_pts * 0.25)
        parts.append("營業利益率紅旗")
    if master.capex_red_flag:
        earned = min(earned, max_pts * 0.35)
        parts.append("CapEx 效率陷阱紅旗")

    if beta is not None:
        if beta > 2.5:
            earned = min(earned, max_pts * 0.20)
            parts.append(f"Beta {beta:.2f} 過高")
        elif 0.9 <= beta <= 1.8:
            earned = max(earned, max_pts * 0.75)

    if not parts:
        parts.append("無重大結構紅旗")
    rationale = " · ".join(parts) + f"，本項得 {earned:.1f}/{max_pts:.0f} 分。"
    return ScoreDetail(category, max_pts, round(earned, 1), rationale)


def score_growth_peg_valuation_component(master: MasterMetrics) -> ScoreDetail:
    """🚀 PEG relative-growth valuation (25) — isolated valuation track."""
    max_pts = WEIGHT_GROWTH_PEG_VAL
    category = "估值相對成長 (PEG)"
    peg = master.peg_ratio
    if peg is not None and peg > 0:
        if peg <= 1.0:
            earned, tag = max_pts, "PEG ≤1 · 成長被低估"
        elif peg <= 1.5:
            earned, tag = max_pts * 0.78, "PEG 1.0–1.5 · 合理"
        elif peg <= 2.0:
            earned, tag = max_pts * 0.55, "PEG 1.5–2.0 · 偏滿"
        elif peg <= 3.0:
            earned, tag = max_pts * 0.30, "PEG 2.0–3.0 · 透支風險"
        else:
            earned, tag = max_pts * 0.10, "PEG >3 · 定價過度"
        rationale = f"PEG {peg:.2f}（{tag}），本項得 {earned:.1f}/{max_pts:.0f} 分。"
    else:
        earned = max_pts * 0.35
        rationale = f"PEG 缺失，給予中性基礎 {earned:.1f}/{max_pts:.0f} 分。"
    return ScoreDetail(category, max_pts, round(earned, 1), rationale)


def score_valuation_safety_component(
    master: MasterMetrics,
    info: dict | None = None,
) -> ScoreDetail:
    """
    Valuation Safety Score (100): Forward P/E + PEG + FCF Yield.

    Isolated from Business Quality — exposes 'great company, bad price' traps.
    """
    max_pts = 100.0
    category = "估值安全分"
    info = info or {}
    earned = 0.0
    parts: list[str] = []

    fpe = master.forward_pe or _safe_info_float(info, "forwardPE")
    if fpe is None or fpe <= 0:
        fpe = _safe_info_float(info, "trailingPE")
    if fpe is not None and fpe > 0:
        if fpe <= 15:
            sub, tag = 40.0, "深度折價 ≤15x"
        elif fpe <= 20:
            sub, tag = 32.0, "合理 15–20x"
        elif fpe <= 25:
            sub, tag = 22.0, "偏滿 20–25x"
        elif fpe <= 35:
            sub, tag = 10.0, "高估 25–35x"
        else:
            sub, tag = 2.0, "透支 >35x（偉大公司買太貴陷阱）"
        earned += sub
        parts.append(f"Forward P/E {fpe:.1f}x（{tag}）")
    else:
        earned += 16.0
        parts.append("Forward P/E 缺失")

    peg = master.peg_ratio
    if peg is not None and peg > 0:
        if peg <= 1.0:
            sub, tag = 35.0, "PEG ≤1"
        elif peg <= 1.5:
            sub, tag = 28.0, "PEG 1.0–1.5"
        elif peg <= 2.0:
            sub, tag = 18.0, "PEG 1.5–2.0"
        elif peg <= 3.0:
            sub, tag = 8.0, "PEG 2.0–3.0"
        else:
            sub, tag = 2.0, "PEG >3"
        earned += sub
        parts.append(f"PEG {peg:.2f}（{tag}）")
    else:
        earned += 12.0
        parts.append("PEG 缺失")

    fcf_y = master.fcf_yield
    if fcf_y is not None and fcf_y > 0:
        if fcf_y >= 0.06:
            sub, tag = 25.0, "FCF Yield ≥6%"
        elif fcf_y >= 0.04:
            sub, tag = 20.0, "FCF Yield 4%–6%"
        elif fcf_y >= 0.025:
            sub, tag = 14.0, "FCF Yield 2.5%–4%"
        elif fcf_y >= 0.015:
            sub, tag = 8.0, "FCF Yield 1.5%–2.5%"
        else:
            sub, tag = 3.0, "FCF Yield <1.5%"
        earned += sub
        parts.append(f"FCF Yield {fcf_y*100:.2f}%（{tag}）")
    else:
        earned += 8.0
        parts.append("FCF Yield 缺失")

    rationale = " · ".join(parts) + f"，估值安全 {earned:.1f}/{max_pts:.0f} 分。"
    raw = round(min(earned, max_pts), 1)
    return ScoreDetail(category, max_pts, apply_score_cap(raw), rationale)


def score_valuation_margin_component(
    master: MasterMetrics,
    info: dict | None = None,
) -> ScoreDetail:
    """Legacy alias → Valuation Safety Score."""
    return score_valuation_safety_component(master, info)


def apply_score_cap(score: float) -> float:
    """Red Team Protocol — absolute safety scores cannot exceed SCORE_CAP."""
    try:
        value = float(score)
    except (TypeError, ValueError):
        return 0.0
    return round(min(max(0.0, value), SCORE_CAP), 1)


def grade_from_score(total: float, *, growth: bool = False) -> tuple[str, str]:
    if growth:
        if total >= 85:
            return "📈", "右側結構確立"
        if total >= 70:
            return "🟡", "動能蓄勢中"
        return "🔴", "趨勢待確認"
    if total >= 85:
        return "🛡️", "財務防禦確立"
    if total >= 70:
        return "🟡", "體質穩健"
    return "🔴", "防禦不足"


def evaluate_fcf(rows: list[YearFCF]) -> tuple[bool | None, str]:
    if not rows:
        return None, "No FCF data"
    window = rows[:YEARS_REQUIRED]
    if len(window) < YEARS_REQUIRED:
        ok = all(r.free_cash_flow > 0 for r in window)
        return ok, f"Only {len(window)} fiscal years available"
    if all(r.free_cash_flow > 0 for r in window):
        return True, f"All {YEARS_REQUIRED} years FCF > 0"
    return False, "Non-positive FCF in window"


def evaluate_dividends(history: list[YearDividend]) -> tuple[bool | None, str]:
    if len(history) < YEARS_REQUIRED + 1:
        return None, "Insufficient dividend history"
    recent = [h.yoy_growth for h in history[1:]][-YEARS_REQUIRED:]
    if all(g is not None and g > 0 for g in recent):
        return True, f"{YEARS_REQUIRED} consecutive YoY DPS increases"
    return False, "Dividend growth streak broken"


def _fmt_pct(value: float | None, *, scale: bool = True) -> str:
    if value is None:
        return "N/A"
    return f"{value * 100:.1f}%" if scale else f"{value:.1f}%"


def format_master_metrics_block(master: MasterMetrics) -> str:
    """Readable block of forward-looking master variables for AI prompt context.

    Explicitly separates quarterly filing data from TTM (trailing-twelve-month)
    info fields so the LLM cannot conflate periods.
    """
    if master is None:
        master = MasterMetrics()
    capex = (
        f"{master.capex_growth * 100:+.1f}% YoY" if master.capex_growth is not None else "N/A"
    )
    cov = f"{master.interest_coverage:.1f}x" if master.interest_coverage is not None else "低負債/未知"
    surprise = (
        f"{master.surprise_latest_pct:+.1f}%" if master.surprise_latest_pct is not None else "N/A"
    )

    lines = [
        "=== MASTER DATA FEED (strict period labels — do NOT mix quarterly vs TTM) ===",
        "",
        "[A] QUARTERLY FILING DATA (latest reported quarter vs same quarter prior year):",
    ]
    if master.latest_quarter_label:
        om_latest = (
            f"{master.operating_margin_latest:.1f}%"
            if master.operating_margin_latest is not None
            else "N/A"
        )
        om_yoy = (
            f"{master.operating_margin_yoy:.1f}%"
            if master.operating_margin_yoy is not None
            else "N/A"
        )
        chg = (
            f"{master.operating_margin_change_pp:+.1f}pp YoY"
            if master.operating_margin_change_pp is not None
            else "N/A"
        )
        lines.extend(
            [
                f"- Latest quarter: {master.latest_quarter_label}",
                f"- YoY comparison quarter: {master.yoy_quarter_label}",
                f"- Operating Margin (quarterly): {om_latest} vs {om_yoy} prior year ({chg})",
            ]
        )
        if master.operating_margin_red_flag and master.operating_margin_red_flag_msg:
            lines.append(f"- {master.operating_margin_red_flag_msg}")
    else:
        lines.append("- Operating Margin trend: quarterly data unavailable")

    lines.extend(
        [
            f"- CapEx expansion (quarterly YoY): {capex}",
        ]
    )
    if master.capex_red_flag and master.capex_red_flag_msg:
        lines.append(f"- {master.capex_red_flag_msg}")
    if (
        master.capex_growth is not None
        and master.capex_growth <= CAPEX_DECLINE_DIALECTIC_THRESHOLD
    ):
        lines.append(
            f"- 【CapEx 前瞻辯證】：季 CapEx YoY {master.capex_growth * 100:+.1f}% 大幅下滑——"
            "禁止單向解讀；須同時評估短期 FCF 美化 vs 中長期 Tech Narrative 動能流失。"
        )

    lines.extend(
        [
            "",
            "[B] TTM / TRAILING METRICS (yfinance info — NOT the same period as [A]):",
            f"- TTM Gross Margin: {_fmt_pct(master.ttm_gross_margin)}",
            f"- TTM Operating Margin: {_fmt_pct(master.ttm_operating_margin)}",
            f"- TTM Revenue Growth (revenueGrowth): {_fmt_pct(master.ttm_revenue_growth)}",
            f"- Trailing PEG (trailingPegRatio): {master.peg_ratio if master.peg_ratio is not None else 'N/A'}",
            f"- Forward P/E: {master.forward_pe if master.forward_pe is not None else 'N/A'}",
            f"- FCF Yield (FCF/MktCap): {_fmt_pct(master.fcf_yield)}",
            "",
            "[C] RETURN QUALITY & CONSENSUS:",
            f"- ROIC: {_fmt_pct(master.roic)} | ROA: {_fmt_pct(master.roa)} | ROE: {_fmt_pct(master.roe)}",
            f"- Gross Margin Volatility (3-5Y range): "
            f"{f'{master.gross_margin_volatility:.1f}pp' if master.gross_margin_volatility is not None else 'N/A'}",
            f"- Net Debt / EBITDA: {master.net_debt_ebitda if master.net_debt_ebitda is not None else 'N/A'}",
            f"- FCF Payout Ratio: {_fmt_pct(master.fcf_payout_ratio)}",
            f"- 5Y Revenue CAGR: {_fmt_pct(master.revenue_cagr_5y)}",
            f"- Interest Coverage (latest annual): {cov}",
            (
                f"- Earnings Surprise (latest quarter): {surprise} · "
                f"beat streak {master.surprise_beat_streak}Q · "
                f"{master.surprise_beats}/{master.surprise_sample} beats in sample"
            ),
        ]
    )
    if master.data_as_of:
        lines.append(f"\nData as-of: {master.data_as_of}")
    return "\n".join(lines)


def _format_master_commentary_context(report: StockReport) -> str:
    from llm_processor import CAPEX_DIALECTIC_CONSTRAINT

    mode_label = (
        STRATEGY_LABEL_GROWTH
        if is_growth_strategy(report.strategy_mode)
        else STRATEGY_LABEL_VALUE
    )
    quality = report.business_quality_score or report.total_score
    valuation = report.valuation_margin_score
    lines = [
        f"Ticker: {report.symbol}",
        f"Company: {report.company_name}",
        f"Strategy: {mode_label}",
        f"Business Quality Score: {quality:.1f}/100",
        f"Valuation Margin Score: {valuation:.1f}/100",
        f"Grade (quality-based): {report.grade_emoji} {report.grade_label}",
    ]
    if quality >= VALUATION_TRAP_QUALITY_MIN and valuation < VALUATION_TRAP_SAFETY_MAX:
        lines.append(
            f"⚠ VALUATION TRAP ALERT: Business quality elite but Valuation Safety <"
            f"{VALUATION_TRAP_SAFETY_MAX:.0f} — Red Team MUST attack overvaluation / "
            "priced-in perfection."
        )
    lines.extend([
        "",
        format_master_metrics_block(report.master),
        "",
        "Score breakdown:",
    ])
    for d in report.score_details:
        if is_growth_strategy(report.strategy_mode) and d.max_points <= 0:
            continue
        lines.append(f"- {d.category}: {d.earned}/{d.max_points} — {d.rationale}")
    if report.trend_signal:
        ts = report.trend_signal
        try:
            price = float(ts.get("current_price", 0))
            sma_20 = float(ts.get("sma_20", 0))
            sma_50 = float(ts.get("sma_50", 0))
            above_both = price > sma_20 and price > sma_50
        except (TypeError, ValueError):
            above_both = False
        lines.extend(
            [
                "",
                "Technical facts:",
                f"- Signal: {ts.get('current_signal')}",
                f"- Price: {ts.get('current_price')} | SMA20: {ts.get('sma_20')} | SMA50: {ts.get('sma_50')}",
                f"- Price above BOTH SMA20 and SMA50: {above_both}",
                f"- As of: {ts.get('as_of_date')}",
            ]
        )
        if above_both:
            lines.append(
                "- 技術結構：價格已站上中期均線群，呈現右側打底結構（中期上升軌道支撐）。"
            )
    lines.extend(["", "=== AI FORWARD GUIDANCE CONSTRAINT ===", CAPEX_DIALECTIC_CONSTRAINT])
    return "\n".join(lines)


def _build_value_analyst_commentary(report: StockReport) -> str:
    quality = report.business_quality_score or report.total_score
    valuation = report.valuation_margin_score
    sections: list[str] = [
        "AI 首席分析師決策點評",
        f"{report.symbol} · {report.company_name}",
        "策略戰術：🛡️ 價值防禦模式",
        f"綜合評分（雙軌 · 封頂{SCORE_CAP:.0f}）：企業品質 {quality:.1f} · 估值安全 {valuation:.1f} — "
        f"{report.grade_emoji} {report.grade_label}",
        "",
        "【評分明細（微觀原因）】",
    ]
    for d in report.score_details:
        delta = d.earned - d.max_points
        tag = "✅" if d.earned >= d.max_points * 0.85 else ("⚠️" if d.earned > 0 else "❌")
        sections.append(
            f"- {tag} {d.category}：{d.earned:.1f} / {d.max_points:.0f} 分 — {d.rationale}"
        )

    sections.append("")
    sections.append("【右側趨勢訊號（SMA 20/50）】")
    if report.trend_signal:
        ts = report.trend_signal
        label_map = {
            "Buy": "位置 3 · 買入（Golden Cross，動能啟動）",
            "Sell": "位置 4 · 賣出（Death Cross，動能衰竭）",
            "Wait": "位置 1 · 觀望（弱勢下跌中）",
            "Hold": "持有（正向趨勢，無強烈反轉觸發）",
        }
        sig = str(ts.get("current_signal", "Hold"))
        sections.append(
            f"- {label_map.get(sig, sig)} | 收盤 ${ts.get('current_price')} "
            f"| SMA20 ${ts.get('sma_20')} | SMA50 ${ts.get('sma_50')}"
        )
        if ts.get("as_of_date"):
            sections.append(f"- 資料截至：{ts['as_of_date']}")
    else:
        sections.append("- 趨勢數據不足，無法計算 SMA 交叉訊號。")

    m = report.master
    sections.append("")
    sections.append("【DGI 防禦硬指標】")
    roic_txt = _fmt_pct(m.roic) if m.roic is not None else _fmt_pct(m.roa)
    sections.append(
        f"- ROIC / 資本回報：{roic_txt} · ROE {_fmt_pct(m.roe)}"
        + (" · ⚠ ROE 顯著高於 ROIC" if m.roe and m.roic and m.roe > m.roic * 1.8 else "")
    )
    fcf_pay = _fmt_pct(m.fcf_payout_ratio)
    nd_ebitda = f"{m.net_debt_ebitda:.1f}x" if m.net_debt_ebitda is not None else "N/A"
    rev_cagr = _fmt_pct(m.revenue_cagr_5y)
    sections.append(
        f"- FCF 支付率：{fcf_pay} · 淨債務/EBITDA {nd_ebitda} · 5Y 營收 CAGR {rev_cagr}"
    )
    cov_txt = f"{m.interest_coverage:.1f}x" if m.interest_coverage is not None else "低負債/未知"
    gm_vol = (
        f"{m.gross_margin_volatility:.1f}pp"
        if m.gross_margin_volatility is not None
        else "N/A"
    )
    sections.append(
        f"- 利息保障 {cov_txt} · 毛利率波動 {gm_vol} · "
        f"營業利益率 {_fmt_pct(m.ttm_operating_margin)}"
    )

    sections.append("")
    sections.append("【投資風格提示】")
    sections.append(
        "- 本模式以 企業品質(35) + 財務安全(25) + 現金流品質(25) + 營收穩定(15) 計分，"
        "含不對稱死亡懲罰（槓桿 >3x 封頂 69 分；FCF 支付率 >90% 歸零並扣 10 分）；"
        "建議與 產業景氣、估值與個人風險偏好 一併考量。"
    )

    if quality >= VALUATION_TRAP_QUALITY_MIN and valuation < VALUATION_TRAP_SAFETY_MAX:
        sections.append(
            "\n⚠️ 品質極優，但估值過高，注意安全邊際。"
            "紅隊必須質疑：當前價格已透支多少未來的完美預期？"
        )
    elif quality >= 85:
        sections.append(
            "\n結論：護城河與現金流紀律俱佳；仍須確認估值邊際是否提供足夠安全墊。"
        )
    elif quality >= 70:
        sections.append(
            "\n結論：體質穩健，但存在可改進項（見 ⚠️ 項目）；"
            "適合觀察名單或分批佈局。"
        )
    else:
        sections.append(
            "\n結論：防禦不足，建議降低倉位權重或等待護城河質量與現金流紀律修復後再評估。"
        )

    return "\n".join(sections)


def _format_growth_commentary_context(report: StockReport) -> str:
    lines = [
        f"Ticker: {report.symbol}",
        f"Company: {report.company_name}",
        f"Strategy: {STRATEGY_LABEL_GROWTH}",
        f"Business Quality: {report.business_quality_score or report.total_score:.1f}/100",
        f"Valuation Margin: {report.valuation_margin_score:.1f}/100",
        f"Grade: {report.grade_emoji} {report.grade_label}",
        "",
        "Score breakdown (FCF/Dividend/Payout excluded — weight 0):",
    ]
    for d in report.score_details:
        if d.max_points <= 0:
            continue
        lines.append(f"- {d.category}: {d.earned}/{d.max_points} — {d.rationale}")
    if report.trend_signal:
        ts = report.trend_signal
        try:
            price = float(ts.get("current_price", 0))
            sma_20 = float(ts.get("sma_20", 0))
            sma_50 = float(ts.get("sma_50", 0))
            above_both = price > sma_20 and price > sma_50
        except (TypeError, ValueError):
            above_both = False
        lines.extend(
            [
                "",
                "Technical facts:",
                f"- Signal: {ts.get('current_signal')}",
                f"- Price: {ts.get('current_price')}",
                f"- SMA20: {ts.get('sma_20')}",
                f"- SMA50: {ts.get('sma_50')}",
                f"- Price above BOTH SMA20 and SMA50: {above_both}",
                f"- As of: {ts.get('as_of_date')}",
            ]
        )
        if above_both:
            lines.append(
                "- MANDATORY: Describe as 「價格已站上中期均線群，呈現右側打底結構」 and "
                "confirm transition into mid-term uptrend. Avoid retail lexicon (no 突破/多頭雛形/飆股/爆發)."
            )
    return "\n".join(lines)


def _build_growth_analyst_commentary_fallback(report: StockReport) -> str:
    quality = report.business_quality_score or report.total_score
    valuation = report.valuation_margin_score
    sections: list[str] = [
        "AI 首席分析師決策點評",
        f"{report.symbol} · {report.company_name}",
        "策略戰術：🚀 動能成長模式 · 紅隊審查視角",
        f"雙軌得分（封頂{SCORE_CAP:.0f}）：企業品質 {quality:.1f} · 估值安全 {valuation:.1f} — "
        f"{report.grade_emoji} {report.grade_label}",
        "",
        "【評分明細（動能引擎）】",
    ]
    for d in report.score_details:
        if d.max_points <= 0:
            continue
        tag = "✅" if d.earned >= d.max_points * 0.85 else ("⚠️" if d.earned > 0 else "❌")
        sections.append(
            f"- {tag} {d.category}：{d.earned:.1f} / {d.max_points:.0f} 分 — {d.rationale}"
        )
    if report.trend_signal:
        ts = report.trend_signal
        try:
            price = float(ts.get("current_price", 0))
            sma_20 = float(ts.get("sma_20", 0))
            sma_50 = float(ts.get("sma_50", 0))
            breakout = price > sma_20 and price > sma_50
        except (TypeError, ValueError):
            breakout = False
        breakout_line = (
            "- 📈 價格已站上中期均線群，呈現右側打底結構 — 收盤同時站上 SMA20 & SMA50，"
            "確認價格轉入中期上升軌道。"
            if breakout
            else f"- 交叉訊號：{ts.get('current_signal')}"
        )
        sections.extend(
            [
                "",
                "【技術面物理事實】",
                f"- 收盤 ${ts.get('current_price')} · SMA20 ${ts.get('sma_20')} · SMA50 ${ts.get('sma_50')}",
                breakout_line,
            ]
        )
    m = report.master
    peg_txt = f"{m.peg_ratio:.2f}" if m.peg_ratio is not None else "N/A"
    capex_txt = f"{m.capex_growth*100:+.1f}% YoY" if m.capex_growth is not None else "N/A"
    surprise_txt = (
        f"{m.surprise_latest_pct:+.1f}%" if m.surprise_latest_pct is not None else "N/A"
    )
    sections.extend(
        [
            "",
            "【前瞻硬指標（不對稱性輸入）】",
            f"- 前瞻 PEG {peg_txt} · CapEx 擴張率 {capex_txt} · "
            f"最新 Surprise {surprise_txt}（連續超預期 {m.surprise_beat_streak} 季）",
        ]
    )
    sections.append(
        "\n機構視角結論：本模式 零權重 評估 FCF / 股息 / 發放率，避免對燒錢新創的防禦偏見。"
        "聚焦 PEG 剪刀差 + CapEx 擴張、右側通道支撐 與 預期修正動態。"
    )
    return "\n".join(sections)


@st.cache_data(ttl=3600, show_spinner=False)
def _cached_llm_value_commentary(symbol: str, context: str) -> str | None:
    """Cache value-mode analyst commentary — keyed by ticker + context."""
    from llm_processor import generate_value_analyst_commentary

    return generate_value_analyst_commentary(context)


@st.cache_data(ttl=3600, show_spinner=False)
def _cached_llm_growth_commentary(symbol: str, context: str) -> str | None:
    """Cache growth-mode analyst commentary — keyed by ticker + context."""
    from llm_processor import generate_growth_analyst_commentary

    return generate_growth_analyst_commentary(context)


@st.cache_data(ttl=3600, show_spinner=False)
def _cached_llm_investment_scorecard(
    symbol: str,
    growth: bool,
    context: str,
) -> tuple[tuple[str, int, str], ...] | None:
    """Cache Master Investment Scorecard rows as a hashable tuple."""
    from llm_processor import generate_investment_scorecard

    raw = generate_investment_scorecard(context, growth=growth)
    if not raw:
        return None
    return tuple(
        (str(row["dimension"]), int(row["score"]), str(row["rationale"]))
        for row in raw
    )


@st.cache_data(ttl=3600, show_spinner=False)
def _cached_llm_turnaround_reason_tag(symbol: str, context: str) -> tuple[str, str]:
    """Cache Gemini mispricing reason tag for turnaround radar hits."""
    from llm_processor import generate_turnaround_reason_tag

    return generate_turnaround_reason_tag(context)


@st.cache_data(ttl=3600, show_spinner=False)
def _cached_llm_value_narrative(
    symbol: str,
    strategy_mode: str,
    business_summary: str,
    sector: str,
    industry: str,
) -> str:
    """Cache value-mode tech narrative (static business summary)."""
    from llm_processor import generate_company_narrative_text

    return generate_company_narrative_text(symbol, business_summary, sector, industry)


@st.cache_data(ttl=3600, show_spinner=False)
def _cached_llm_growth_narrative(
    symbol: str,
    strategy_mode: str,
    business_summary: str,
    sector: str,
    industry: str,
    live_news_text: str,
    trend_json: str,
    master_text: str,
) -> str:
    """Cache growth-mode live-news narrative — trend serialized as JSON."""
    from llm_processor import generate_growth_narrative_text

    trend: dict | None = None
    if trend_json:
        try:
            trend = json.loads(trend_json)
        except json.JSONDecodeError:
            trend = None
    return generate_growth_narrative_text(
        symbol,
        business_summary,
        sector,
        industry,
        live_news_text=live_news_text,
        trend_signal=trend,
        master_text=master_text,
    )


def clear_gemini_llm_cache() -> None:
    """Clear all Streamlit-cached Gemini LLM responses (sidebar refresh)."""
    _cached_llm_value_commentary.clear()
    _cached_llm_growth_commentary.clear()
    _cached_llm_investment_scorecard.clear()
    _cached_llm_turnaround_reason_tag.clear()
    _cached_llm_value_narrative.clear()
    _cached_llm_growth_narrative.clear()


def build_analyst_commentary(report: StockReport) -> tuple[str, list[ScorecardItem]]:
    """Return (commentary markdown, investment scorecard rows)."""
    growth = is_growth_strategy(report.strategy_mode)
    strategy_tagline = (
        "🚀 動能成長模式 · 紅隊審查 / 剝離成長敘事 vs 估值透支"
        if growth
        else "🛡️ 價值防禦模式 · 紅隊審查 / 剝離好公司 vs 好價格"
    )
    context = _format_master_commentary_context(report)
    sym = report.symbol.upper()

    if growth:
        llm_text = _cached_llm_growth_commentary(sym, context)
    else:
        llm_text = _cached_llm_value_commentary(sym, context)

    if llm_text:
        commentary = (
            f"AI 首席分析師決策點評\n"
            f"{report.symbol} · {report.company_name} · "
            f"策略戰術：{strategy_tagline}\n\n"
            f"{llm_text.strip()}"
        )
    elif growth:
        commentary = _build_growth_analyst_commentary_fallback(report)
    else:
        commentary = _build_value_analyst_commentary(report)

    raw_scorecard = _cached_llm_investment_scorecard(sym, growth, context)
    if raw_scorecard:
        scorecard = [
            ScorecardItem(
                dimension=dim,
                score=score,
                rationale=rationale,
            )
            for dim, score, rationale in raw_scorecard
        ]
    else:
        scorecard = _build_scorecard_fallback(report)

    return commentary, scorecard


def _build_scorecard_fallback(report: StockReport) -> list[ScorecardItem]:
    """Deterministic 1–10 scorecard when Gemini is unavailable."""
    m = report.master
    rows: list[ScorecardItem] = []

    # 1 Financial runway — interest coverage + margin red flags
    runway = 7
    if m.interest_coverage is not None and m.interest_coverage < 3:
        runway = 4
    if m.operating_margin_red_flag:
        runway = max(1, runway - 2)
    rows.append(
        ScorecardItem(
            "1. 財務安全 (Financial Runway)",
            runway,
            f"利息保障 {m.interest_coverage or '低負債'}x；"
            + ("營業利益率紅旗已觸發。" if m.operating_margin_red_flag else "資產負債結構尚可。"),
        )
    )

    # 2 FCF reality
    fcf_pts = 5
    if report.fcf_pass is True:
        fcf_pts = 8
    elif report.fcf_pass is False:
        fcf_pts = 3
    rows.append(
        ScorecardItem(
            "2. 現金流健康度 (FCF Reality)",
            fcf_pts,
            report.fcf_note or "依最近 FCF 序列評估。",
        )
    )

    # 3 Growth momentum
    gm = 5
    if m.revenue_growth and m.revenue_growth > 0.10:
        gm = 8
    elif m.surprise_beat_streak >= 2:
        gm = 7
    rows.append(
        ScorecardItem(
            "3. 核心成長性 (Growth Momentum)",
            gm,
            f"營收成長 {_fmt_pct(m.revenue_growth)} · Surprise streak {m.surprise_beat_streak}Q",
        )
    )

    # 4 Tech narrative
    peg = m.peg_ratio
    tn = 6 if peg is None else (8 if peg <= 1.5 else 5)
    capex_txt = (
        f"{m.capex_growth * 100:+.1f}% YoY" if m.capex_growth is not None else "N/A"
    )
    rows.append(
        ScorecardItem(
            "4. 科技/AI 題材含金量 (Tech Narrative Catalyst)",
            tn,
            f"PEG {peg if peg is not None else 'N/A'} · CapEx {capex_txt}",
        )
    )

    # 5 Moat
    moat = 6
    if m.gross_margins and m.gross_margins >= 0.40:
        moat = 8
    if m.operating_margin_red_flag:
        moat = max(2, moat - 3)
    rows.append(
        ScorecardItem(
            "5. 產業定價權與競爭優勢 (Moat Stability)",
            moat,
            f"毛利率 {_fmt_pct(m.gross_margins)} · OM YoY "
            f"{m.operating_margin_change_pp:+.1f}pp"
            if m.operating_margin_change_pp is not None
            else f"毛利率 {_fmt_pct(m.gross_margins)}",
        )
    )

    # 6 Valuation
    val = 6
    if peg is not None:
        if peg <= 1.0:
            val = 9
        elif peg <= 2.0:
            val = 7
        else:
            val = 4
    rows.append(
        ScorecardItem(
            "6. 前瞻估值吸引力 (Valuation Safety Margin)",
            val,
            f"Trailing PEG {peg if peg is not None else 'N/A'}",
        )
    )
    return rows


def normalize_strategy_mode(strategy_mode: str) -> str:
    """Map UI label or internal code to canonical value/growth."""
    if strategy_mode in (STRATEGY_VALUE, STRATEGY_GROWTH):
        return strategy_mode
    return STRATEGY_LABEL_TO_MODE.get(strategy_mode, STRATEGY_VALUE)


def is_growth_strategy(strategy_mode: str) -> bool:
    return normalize_strategy_mode(strategy_mode) == STRATEGY_GROWTH


def compute_scores(
    fcf_rows: list[YearFCF],
    div_rows: list[YearDividend],
    payout: float | None,
    beta: float | None,
    *,
    strategy_mode: str,
    trend_signal: dict[str, float | str | None] | None = None,
    info: dict | None = None,
    symbol: str = "",
    ticker: yf.Ticker | None = None,
    master: MasterMetrics | None = None,
) -> tuple[list[ScoreDetail], float, float, str, str]:
    """
    Dual-track scoring: Business Quality (100) + Valuation Margin (100).

    Returns (score_details, business_quality_score, valuation_margin_score, emoji, label).
    """
    mode = normalize_strategy_mode(strategy_mode)
    master = master or MasterMetrics()
    info = info or {}

    if mode == STRATEGY_GROWTH:
        fund = score_growth_fundamental_component(master)
        surp = score_earnings_surprise_component(
            master, category="預期修正 Surprise", max_pts=WEIGHT_GROWTH_SURPRISE
        )
        peg_val = score_growth_peg_valuation_component(master)
        risk_buf = score_growth_risk_buffer_component(master, beta)
        tech = score_growth_technical_timing_component(trend_signal)
        excluded = [
            _growth_excluded_component(
                "FCF 連續為正", "🚀 成長模式：歷史 FCF 不計分（權重 0）。"
            ),
            _growth_excluded_component(
                "股息連續成長", "🚀 成長模式：股息不計分（權重 0）。"
            ),
            _growth_excluded_component(
                "股息發放率", "🚀 成長模式：發放率不計分（權重 0）。"
            ),
        ]
        details = excluded + [fund, surp, peg_val, risk_buf, tech]
        quality_raw = fund.earned + surp.earned + risk_buf.earned
        quality_max = (
            WEIGHT_GROWTH_FUNDAMENTAL
            + WEIGHT_GROWTH_SURPRISE
            + WEIGHT_GROWTH_RISK_BUFFER
        )
        business_quality = apply_score_cap(
            min(100.0, quality_raw / quality_max * 100.0)
        )
        valuation_margin = apply_score_cap(
            min(100.0, peg_val.earned / WEIGHT_GROWTH_PEG_VAL * 100.0)
        )
        emoji, label = grade_from_score(business_quality, growth=True)
        return details, business_quality, valuation_margin, emoji, label

    quality_details = [
        score_value_quality_component(master),
        score_value_safety_component(master),
        score_value_cashflow_component(master, div_rows),
        score_value_revenue_stability_component(master),
    ]
    business_quality = _apply_value_death_penalties(quality_details, master)
    val_detail = score_valuation_safety_component(master, info)
    valuation_margin = val_detail.earned
    details = quality_details + [val_detail]
    emoji, label = grade_from_score(business_quality, growth=False)
    return details, business_quality, valuation_margin, emoji, label


def analyze_symbol(symbol: str, *, strategy_mode: str) -> StockReport:
    sym = symbol.upper()
    mode = normalize_strategy_mode(strategy_mode)
    ticker = yf.Ticker(sym)
    info = _safe_ticker_info(ticker, sym)
    name = _company_name(info, sym)

    fcf_rows = fetch_fcf(sym)
    div_rows = fetch_dividends(sym, ticker=ticker)
    payout = fetch_payout_ratio(sym, ticker=ticker)
    beta = _safe_beta(info)
    trend = detect_trend_signals(sym)
    master = fetch_master_metrics(sym, info, ticker=ticker)
    if trend and trend.get("as_of_date"):
        master.data_as_of = str(trend["as_of_date"])

    fcf_pass, fcf_note = evaluate_fcf(fcf_rows)
    div_pass, div_note = evaluate_dividends(div_rows)
    score_details, quality, valuation, emoji, label = compute_scores(
        fcf_rows,
        div_rows,
        payout,
        beta,
        strategy_mode=mode,
        trend_signal=trend,
        info=info,
        symbol=sym,
        ticker=ticker,
        master=master,
    )

    report = StockReport(
        symbol=sym,
        company_name=name,
        fcf_history=fcf_rows,
        div_history=div_rows,
        payout_ratio=payout,
        beta=beta,
        score_details=score_details,
        total_score=quality,
        business_quality_score=quality,
        valuation_margin_score=valuation,
        grade_label=label,
        grade_emoji=emoji,
        fcf_pass=fcf_pass,
        fcf_note=fcf_note,
        div_pass=div_pass,
        div_note=div_note,
        trend_signal=trend,
        strategy_mode=mode,
        master=master,
    )
    commentary, scorecard = build_analyst_commentary(report)
    report.analyst_commentary = commentary
    report.investment_scorecard = scorecard
    return report


def build_company_narrative(
    symbol: str,
    *,
    strategy_mode: str = STRATEGY_VALUE,
) -> NarrativeResult:
    """Generate tech narrative — static summary (value) or live-news fusion (growth)."""
    sym = symbol.upper().strip()
    yf_ticker = yf.Ticker(sym)
    summary, sector, industry = fetch_business_summary(sym)
    mode = normalize_strategy_mode(strategy_mode)

    if is_growth_strategy(mode):
        live_news: list[LiveNewsItem] = []
        degraded = False
        try:
            live_news = fetch_ticker_live_news(sym, ticker=yf_ticker)
            if not live_news:
                degraded = True
        except Exception:
            live_news = []
            degraded = True

        trend = detect_trend_signals(yf_ticker)
        live_block = format_live_news_block(live_news)
        info = _safe_ticker_info(yf_ticker, sym)
        master = fetch_master_metrics(sym, info, ticker=yf_ticker)
        master_block = format_master_metrics_block(master)
        trend_json = json.dumps(trend or {}, sort_keys=True, default=str)
        text = _cached_llm_growth_narrative(
            sym,
            mode,
            summary or "",
            sector or "",
            industry or "",
            live_block,
            trend_json,
            master_block,
        )
        if text.startswith("⚠️") and summary:
            text = _cached_llm_value_narrative(sym, mode, summary, sector or "", industry or "")
        elif not text.strip():
            text = summary or "暫無可用敘事資料。"
        return NarrativeResult(text=text, live_news_degraded=degraded)

    if not summary:
        return NarrativeResult(
            text="尚無官方業務摘要（longBusinessSummary），暫時無法生成科技敘事。",
            live_news_degraded=False,
        )
    text = _cached_llm_value_narrative(sym, mode, summary, sector or "", industry or "")
    return NarrativeResult(text=text, live_news_degraded=False)


def analyze_all(
    symbols: list[str] | tuple[str, ...] | None = None,
    *,
    strategy_mode: str = STRATEGY_VALUE,
) -> list[StockReport]:
    """Analyze a user-supplied symbol list; returns empty when none provided."""
    if not symbols:
        return []
    seen: set[str] = set()
    reports: list[StockReport] = []
    for raw in symbols:
        sym = raw.upper().strip()
        if not sym or sym in seen:
            continue
        seen.add(sym)
        reports.append(analyze_symbol(sym, strategy_mode=strategy_mode))
    return reports


def _detail_score(report: StockReport, *keywords: str) -> float | None:
    for detail in report.score_details:
        if any(key in detail.category for key in keywords):
            return detail.earned
    return None


def reports_to_summary_df(
    reports: list[StockReport],
    *,
    strategy_mode: str,
) -> pd.DataFrame:
    rows = []
    growth_mode = is_growth_strategy(strategy_mode)
    for r in reports:
        quality = r.business_quality_score or r.total_score
        valuation = r.valuation_margin_score
        grade_emoji, grade_label = grade_from_score(quality, growth=growth_mode)
        grade_display = f"{grade_emoji} {grade_label}"
        if growth_mode:
            row = {
                "Ticker": r.symbol,
                "Company": r.company_name,
                "企業品質分": quality,
                "估值安全分": valuation,
                "等級": grade_display,
                "基本面增長分": _detail_score(r, "基本面增長"),
                "預期修正分": _detail_score(r, "預期修正", "Surprise"),
                "PEG估值分": _detail_score(r, "PEG", "估值相對"),
                "Timing輔助": _detail_score(r, "Timing", "技術面輔助"),
            }
        else:
            row = {
                "Ticker": r.symbol,
                "Company": r.company_name,
                "企業品質分": quality,
                "估值安全分": valuation,
                "等級": grade_display,
                "護城河分": _detail_score(r, "企業品質", "護城河"),
                "現金流品質分": _detail_score(r, "現金流"),
                "財務安全分": _detail_score(r, "財務安全"),
                "營收穩定分": _detail_score(r, "營收穩定"),
            }
        rows.append(row)
    return pd.DataFrame(rows)


def fcf_chart_df(report: StockReport, year_from: int = 2021, year_to: int = 2025) -> pd.DataFrame:
    rows = [
        {
            "Fiscal Year": y.fiscal_year,
            "FCF (USD billions)": y.free_cash_flow / 1e9,
            "Period End": y.period_end,
        }
        for y in report.fcf_history
        if year_from <= y.fiscal_year <= year_to
    ]
    if not rows:
        rows = [
            {
                "Fiscal Year": y.fiscal_year,
                "FCF (USD billions)": y.free_cash_flow / 1e9,
                "Period End": y.period_end,
            }
            for y in report.fcf_history
        ]
    return pd.DataFrame(rows).sort_values("Fiscal Year") if rows else pd.DataFrame()


def dividend_chart_df(report: StockReport, year_from: int = 2020, year_to: int = 2025) -> pd.DataFrame:
    rows = [
        {
            "Year": y.calendar_year,
            "DPS (USD)": y.dividend_per_share,
            "YoY Growth %": (y.yoy_growth * 100) if y.yoy_growth is not None else None,
        }
        for y in report.div_history
        if year_from <= y.calendar_year <= year_to
    ]
    if not rows:
        rows = [
            {
                "Year": y.calendar_year,
                "DPS (USD)": y.dividend_per_share,
                "YoY Growth %": (y.yoy_growth * 100) if y.yoy_growth is not None else None,
            }
            for y in report.div_history
        ]
    return pd.DataFrame(rows).sort_values("Year") if rows else pd.DataFrame()
