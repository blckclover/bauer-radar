"""Core dividend / FCF analysis with 100-point safety scoring."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from functools import lru_cache
from io import StringIO

import pandas as pd
import requests
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
WEIGHT_GROWTH_REVENUE = 40.0
WEIGHT_GROWTH_MOMENTUM = 40.0
WEIGHT_GROWTH_BETA = 20.0
PENALTY_FCF_PER_YEAR = 10.0
PENALTY_DIV_PER_YEAR = 8.0

SEC_USER_AGENT = "DividendAnalyzer/3.0 (research@example.com)"
SEC_HEADERS = {"User-Agent": SEC_USER_AGENT}
OCF_TAG = "NetCashProvidedByUsedInOperatingActivities"
CAPEX_TAGS = (
    "PaymentsToAcquirePropertyPlantAndEquipment",
    "PaymentsToAcquireProductiveAssets",
)

# Turnaround screener (active fact-finding radar)
TURNAROUND_LOOKBACK = "6mo"
TURNAROUND_MIN_DRAWDOWN_PCT = 15.0
RND_ROW_NAMES = (
    "ResearchAndDevelopment",
    "Research And Development",
    "ResearchAndDevelopmentExpense",
    "ResearchAndDevelopmentExpenseExcludingAcquiredInProcessCost",
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
class StockReport:
    symbol: str
    company_name: str
    fcf_history: list[YearFCF] = field(default_factory=list)
    div_history: list[YearDividend] = field(default_factory=list)
    payout_ratio: float | None = None
    beta: float | None = None
    score_details: list[ScoreDetail] = field(default_factory=list)
    total_score: float = 0.0
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

    @property
    def overall_pass(self) -> bool | None:
        if self.total_score <= 0 and not self.score_details:
            return None
        return self.total_score >= 70


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


def _screen_single_turnaround(
    symbol: str,
    min_drawdown_pct: float,
    lookback_period: str,
) -> TurnaroundOpportunity | None:
    """
    Per-ticker pipeline: price drawdown gate → FCF fact check → R&D fact.

    Wrapped in try/except at the caller; returns None if any gate fails or
    data is missing (never raises).
    """
    sym = symbol.upper().strip()
    if not sym:
        return None

    ticker = yf.Ticker(sym)
    info = _safe_ticker_info(ticker, sym)
    name = _company_name(info, sym)

    price_facts = _six_month_price_drawdown(ticker, period=lookback_period)
    if price_facts is None:
        return None

    current_price, period_high, drawdown_pct = price_facts
    if drawdown_pct <= min_drawdown_pct:
        return None

    fcf_val, fcf_year, fcf_source = fetch_latest_fcf_snapshot(sym, ticker=ticker)
    if fcf_val is None or fcf_val <= 0:
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
    )


def find_turnaround_opportunities(
    ticker_list: list[str],
    *,
    min_drawdown_pct: float = TURNAROUND_MIN_DRAWDOWN_PCT,
    lookback_period: str = TURNAROUND_LOOKBACK,
) -> list[TurnaroundOpportunity]:
    """
    Active turnaround screener: "garbage heap gold" fact detective.

    Refactor notes (turnaround radar extension):
    -----------------------------------------------
    1. **Price gate (yfinance `.history`)** — scans each ticker for a
       drawdown > `min_drawdown_pct` (default 15%) vs the lookback high
       (default 6 months). Weak price alone is NOT enough; it only qualifies
       for the hard-facts pass.

    2. **Hard facts (reuse existing helpers)** — `_safe_ticker_info`,
       `_company_name`, and `fetch_fcf` (SEC EDGAR first, Yahoo fallback)
       verify the latest fiscal FCF is strictly positive. This strips narrative
       noise: the market may be pessimistic, but the balance sheet still
       generates cash.

    3. **R&D fact reserve** — `fetch_latest_rd_expense` pulls the most recent
       annual research spend when disclosed, as an optional innovation
       capacity signal (not a filter).

    4. **Fault isolation** — each ticker runs inside its own try/except;
       one bad symbol never aborts the full scan.

    Returns candidates sorted by deepest drawdown first (largest % drop).
    """
    candidates: list[TurnaroundOpportunity] = []

    for raw in ticker_list:
        try:
            hit = _screen_single_turnaround(raw, min_drawdown_pct, lookback_period)
            if hit is not None:
                candidates.append(hit)
        except Exception:
            continue

    candidates.sort(key=lambda o: o.drawdown_pct, reverse=True)
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
    """Momentum trigger — full score when price clears both SMA20 and SMA50."""
    max_pts = WEIGHT_GROWTH_MOMENTUM
    if not trend:
        return ScoreDetail(
            "技術面扣扳機",
            max_pts,
            0.0,
            "趨勢數據不足，無法評估右側扣扳機。",
        )

    signal = str(trend.get("current_signal", "Hold"))
    try:
        price = float(trend.get("current_price", 0))
        sma_20 = float(trend.get("sma_20", 0))
        sma_50 = float(trend.get("sma_50", 0))
    except (TypeError, ValueError):
        return ScoreDetail("技術面扣扳機", max_pts, 0.0, "均線數據格式異常。")

    above_20 = price > sma_20
    above_50 = price > sma_50

    if above_20 and above_50:
        earned = max_pts
        band = "🔥 突破站上均線・波段多頭雛形"
    elif above_20 and not above_50:
        earned = max_pts * 0.72
        band = "已站上 SMA20，正在挑戰 SMA50（右側起跑初期）"
    elif above_50 and not above_20:
        earned = max_pts * 0.55
        band = "價格在 SMA50 之上但 SMA20 下方（整理/回踩）"
    elif signal == "Wait":
        earned = max_pts * 0.18
        band = "弱勢下跌 · 尚未出現右側訊號"
    else:
        earned = max_pts * 0.08
        band = "均線下方 · 等待底部確認"

    rationale = (
        f"收盤 ${price:.2f} | SMA20 ${sma_20:.2f} | SMA50 ${sma_50:.2f} · "
        f"{band}，本項得 {earned:.1f}/{max_pts:.0f} 分。"
    )
    return ScoreDetail("技術面扣扳機", max_pts, round(earned, 1), rationale)


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
        band = "黃金爆發級距 1.1–1.8"
    elif 0.8 <= beta < 1.1:
        earned = max_pts * 0.65
        band = "偏低彈性 0.8–1.1"
    elif 1.8 < beta <= 2.5:
        earned = max_pts * 0.55
        band = "高彈性 1.8–2.5"
    elif beta > 2.5:
        earned = max_pts * 0.12
        band = "過度妖股 >2.5"
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


def grade_from_score(total: float, *, growth: bool = False) -> tuple[str, str]:
    if growth:
        if total >= 85:
            return "🚀", "強勢右側標的"
        if total >= 70:
            return "🟡", "動能蓄勢中"
        return "🔴", "趨勢待確認"
    if total >= 85:
        return "🟢", "頂級穩健"
    if total >= 70:
        return "🟡", "良好"
    return "🔴", "高風險"


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


def _build_value_analyst_commentary(report: StockReport) -> str:
    sections: list[str] = [
        "### AI 首席分析師決策點評",
        f"**{report.symbol} · {report.company_name}**",
        "**策略戰術**：🛡️ 價值防禦模式",
        f"**綜合安全得分：{report.total_score:.1f} / 100** — {report.grade_emoji} {report.grade_label}",
        "",
        "#### 評分明細（微觀原因）",
    ]
    for d in report.score_details:
        delta = d.earned - d.max_points
        tag = "✅" if d.earned >= d.max_points * 0.85 else ("⚠️" if d.earned > 0 else "❌")
        sections.append(
            f"- {tag} **{d.category}**：{d.earned:.1f} / {d.max_points:.0f} 分 — {d.rationale}"
        )

    sections.append("")
    sections.append("#### 右側趨勢訊號（SMA 20/50）")
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
            f"- **{label_map.get(sig, sig)}** | 收盤 ${ts.get('current_price')} "
            f"| SMA20 ${ts.get('sma_20')} | SMA50 ${ts.get('sma_50')}"
        )
        if ts.get("as_of_date"):
            sections.append(f"- 資料截至：{ts['as_of_date']}")
    else:
        sections.append("- 趨勢數據不足，無法計算 SMA 交叉訊號。")

    sections.append("")
    sections.append("#### 投資風格提示")
    sections.append(
        "- 100 分制衡量 **FCF 紀律、股息成長、發放率與 Beta**；"
        "建議與 **產業景氣、估值與個人風險偏好** 一併考量，非直接買賣訊號。"
    )

    if report.total_score >= 85:
        sections.append(
            "\n> **結論**：財務紀律面向表現優秀，可作為核心底倉候選；"
            "仍須追蹤產業景氣與估值。"
        )
    elif report.total_score >= 70:
        sections.append(
            "\n> **結論**：整體良好，但存在可改進項（見 ⚠️ 項目）；"
            "適合觀察名單或分批佈局。"
        )
    else:
        sections.append(
            "\n> **結論**：風險偏高，建議降低倉位權重或等待 FCF/股息紀律修復後再評估。"
        )

    return "\n".join(sections)


def _format_growth_commentary_context(report: StockReport) -> str:
    lines = [
        f"Ticker: {report.symbol}",
        f"Company: {report.company_name}",
        f"Strategy: {STRATEGY_LABEL_GROWTH}",
        f"Total Score: {report.total_score}/100",
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
                "- MANDATORY: Emphasize right-side breakout / bullish base (🔥 突破站上均線・波段多頭雛形)."
            )
    return "\n".join(lines)


def _build_growth_analyst_commentary_fallback(report: StockReport) -> str:
    sections: list[str] = [
        "### AI 首席分析師決策點評",
        f"**{report.symbol} · {report.company_name}**",
        "**策略戰術**：🚀 動能成長模式 · VC / 趨勢交易視角",
        f"**綜合動能得分：{report.total_score:.1f} / 100** — {report.grade_emoji} {report.grade_label}",
        "",
        "#### 評分明細（動能引擎）",
    ]
    for d in report.score_details:
        if d.max_points <= 0:
            continue
        tag = "✅" if d.earned >= d.max_points * 0.85 else ("⚠️" if d.earned > 0 else "❌")
        sections.append(
            f"- {tag} **{d.category}**：{d.earned:.1f} / {d.max_points:.0f} 分 — {d.rationale}"
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
            "- **🔥 突破站上均線・波段多頭雛形** — 收盤同時站上 SMA20 & SMA50，"
            "右側動能標的，具備波段交易勝率窗口。"
            if breakout
            else f"- 交叉訊號：**{ts.get('current_signal')}**"
        )
        sections.extend(
            [
                "",
                "#### 技術面物理事實",
                f"- 收盤 **${ts.get('current_price')}** · SMA20 **${ts.get('sma_20')}** · SMA50 **${ts.get('sma_50')}**",
                breakout_line,
            ]
        )
    sections.append(
        "\n> **VC 視角結論**：本模式 **零權重** 評估 FCF / 股息 / 發放率。"
        "聚焦 **營收/R&D 孵化潛力** 與 **均線右側扣扳機**。"
    )
    return "\n".join(sections)


def build_analyst_commentary(report: StockReport) -> str:
    if is_growth_strategy(report.strategy_mode):
        from llm_processor import generate_growth_analyst_commentary

        context = _format_growth_commentary_context(report)
        llm_text = generate_growth_analyst_commentary(context)
        if llm_text:
            return (
                "### AI 首席分析師決策點評\n"
                f"**{report.symbol} · {report.company_name}** · "
                "**策略戰術**：🚀 動能成長模式 · VC / 趨勢交易視角\n\n"
                f"{llm_text.strip()}"
            )
        return _build_growth_analyst_commentary_fallback(report)
    return _build_value_analyst_commentary(report)


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
) -> tuple[list[ScoreDetail], float, str, str]:
    mode = normalize_strategy_mode(strategy_mode)
    if mode == STRATEGY_GROWTH:
        revenue_growth = _safe_info_float(info or {}, "revenueGrowth")
        scored = [
            score_revenue_potential_component(
                revenue_growth, info or {}, symbol, ticker=ticker
            ),
            score_growth_momentum_component(trend_signal),
            score_growth_beta_component(beta),
        ]
        excluded = [
            _growth_excluded_component(
                "FCF 連續為正", "🚀 成長模式：FCF 不計分（權重 0）。"
            ),
            _growth_excluded_component(
                "股息連續成長", "🚀 成長模式：股息不計分（權重 0）。"
            ),
            _growth_excluded_component(
                "股息發放率", "🚀 成長模式：發放率不計分（權重 0）。"
            ),
        ]
        details = excluded + scored
        total = round(sum(d.earned for d in scored), 1)
        emoji, label = grade_from_score(total, growth=True)
        return details, total, emoji, label

    details = [
        score_fcf_component(fcf_rows),
        score_dividend_growth_component(div_rows),
        score_payout_component(payout),
        score_beta_component(beta),
    ]
    total = round(sum(d.earned for d in details), 1)
    emoji, label = grade_from_score(total, growth=False)
    return details, total, emoji, label


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

    fcf_pass, fcf_note = evaluate_fcf(fcf_rows)
    div_pass, div_note = evaluate_dividends(div_rows)
    score_details, total, emoji, label = compute_scores(
        fcf_rows,
        div_rows,
        payout,
        beta,
        strategy_mode=mode,
        trend_signal=trend,
        info=info,
        symbol=sym,
        ticker=ticker,
    )

    report = StockReport(
        symbol=sym,
        company_name=name,
        fcf_history=fcf_rows,
        div_history=div_rows,
        payout_ratio=payout,
        beta=beta,
        score_details=score_details,
        total_score=total,
        grade_label=label,
        grade_emoji=emoji,
        fcf_pass=fcf_pass,
        fcf_note=fcf_note,
        div_pass=div_pass,
        div_note=div_note,
        trend_signal=trend,
        strategy_mode=mode,
    )
    report.analyst_commentary = build_analyst_commentary(report)
    return report


def build_company_narrative(symbol: str) -> str:
    """Generate Gemini-powered tech narrative from yfinance business summary."""
    from llm_processor import generate_company_narrative_text

    sym = symbol.upper().strip()
    summary, sector, industry = fetch_business_summary(sym)
    if not summary:
        return "尚無官方業務摘要（longBusinessSummary），暫時無法生成科技敘事。"
    return generate_company_narrative_text(sym, summary, sector, industry)


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
        if growth_mode:
            row = {
                "Ticker": r.symbol,
                "Company": r.company_name,
                "綜合安全得分": r.total_score,
                "等級": f"{r.grade_emoji} {r.grade_label}",
                "營收潛力分": _detail_score(r, "營收", "預期"),
                "技術面分": _detail_score(r, "扣扳機", "技術"),
                "Beta彈性分": _detail_score(r, "Beta", "彈性"),
            }
        else:
            row = {
                "Ticker": r.symbol,
                "Company": r.company_name,
                "綜合安全得分": r.total_score,
                "等級": f"{r.grade_emoji} {r.grade_label}",
                "FCF分": _detail_score(r, "FCF"),
                "股息分": _detail_score(r, "股息"),
                "發放率分": _detail_score(r, "發放率"),
                "Beta分": _detail_score(r, "Beta"),
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
