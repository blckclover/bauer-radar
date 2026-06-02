"""SQLite-backed financial data cache — reduces yfinance round-trips during scans."""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import yfinance as yf

DEFAULT_DB_PATH = Path(__file__).resolve().parent / "data" / "financial_cache.db"
DEFAULT_TTL_HOURS = 24

_SCHEMA = """
CREATE TABLE IF NOT EXISTS financial_metrics (
    ticker TEXT PRIMARY KEY,
    updated_at TEXT NOT NULL,
    company_name TEXT,
    roic REAL,
    roa REAL,
    roe REAL,
    net_debt_ebitda REAL,
    fcf_payout_ratio REAL,
    interest_coverage REAL,
    revenue_cagr_5y REAL,
    gross_margin_volatility REAL,
    latest_fcf REAL,
    fcf_fiscal_year INTEGER,
    fcf_source TEXT,
    payload_json TEXT
);
CREATE INDEX IF NOT EXISTS idx_financial_metrics_updated
    ON financial_metrics(updated_at);
"""


@dataclass
class FinancialData:
    """Cached core metrics shared by scoring engine and turnaround radar."""

    ticker: str
    updated_at: str
    company_name: str = ""
    roic: float | None = None
    roa: float | None = None
    roe: float | None = None
    net_debt_ebitda: float | None = None
    fcf_payout_ratio: float | None = None
    interest_coverage: float | None = None
    revenue_cagr_5y: float | None = None
    gross_margin_volatility: float | None = None
    latest_fcf: float | None = None
    fcf_fiscal_year: int | None = None
    fcf_source: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def age_hours(self) -> float | None:
        try:
            ts = datetime.fromisoformat(self.updated_at.replace("Z", "+00:00"))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            delta = datetime.now(timezone.utc) - ts.astimezone(timezone.utc)
            return delta.total_seconds() / 3600.0
        except (TypeError, ValueError):
            return None


def _ensure_db_dir(db_path: Path) -> None:
    try:
        db_path.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass


def get_connection(db_path: Path | str | None = None) -> sqlite3.Connection:
    """Open SQLite connection with row factory; never raises on init failure."""
    path = Path(db_path) if db_path else DEFAULT_DB_PATH
    _ensure_db_dir(path)
    conn = sqlite3.connect(str(path), timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        conn.executescript(_SCHEMA)
        conn.commit()
    except sqlite3.Error:
        pass
    return conn


def _is_stale(updated_at: str, ttl_hours: float) -> bool:
    try:
        ts = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        expiry = ts.astimezone(timezone.utc) + timedelta(hours=ttl_hours)
        return datetime.now(timezone.utc) >= expiry
    except (TypeError, ValueError):
        return True


def _row_to_financial(row: sqlite3.Row) -> FinancialData:
    extra: dict[str, Any] = {}
    raw_json = row["payload_json"]
    if raw_json:
        try:
            extra = json.loads(raw_json)
        except json.JSONDecodeError:
            extra = {}
    return FinancialData(
        ticker=str(row["ticker"]),
        updated_at=str(row["updated_at"]),
        company_name=str(row["company_name"] or ""),
        roic=row["roic"],
        roa=row["roa"],
        roe=row["roe"],
        net_debt_ebitda=row["net_debt_ebitda"],
        fcf_payout_ratio=row["fcf_payout_ratio"],
        interest_coverage=row["interest_coverage"],
        revenue_cagr_5y=row["revenue_cagr_5y"],
        gross_margin_volatility=row["gross_margin_volatility"],
        latest_fcf=row["latest_fcf"],
        fcf_fiscal_year=row["fcf_fiscal_year"],
        fcf_source=str(row["fcf_source"] or ""),
        extra=extra,
    )


def _read_cache(ticker: str, db_path: Path | str | None = None) -> FinancialData | None:
    sym = ticker.upper().strip()
    if not sym:
        return None
    try:
        conn = get_connection(db_path)
        try:
            row = conn.execute(
                "SELECT * FROM financial_metrics WHERE ticker = ?",
                (sym,),
            ).fetchone()
        finally:
            conn.close()
        if row is None:
            return None
        return _row_to_financial(row)
    except (sqlite3.Error, OSError, KeyError):
        return None


def _write_cache(data: FinancialData, db_path: Path | str | None = None) -> None:
    sym = data.ticker.upper().strip()
    if not sym:
        return
    payload = {k: v for k, v in data.extra.items()}
    row = {
        "ticker": sym,
        "updated_at": data.updated_at,
        "company_name": data.company_name,
        "roic": data.roic,
        "roa": data.roa,
        "roe": data.roe,
        "net_debt_ebitda": data.net_debt_ebitda,
        "fcf_payout_ratio": data.fcf_payout_ratio,
        "interest_coverage": data.interest_coverage,
        "revenue_cagr_5y": data.revenue_cagr_5y,
        "gross_margin_volatility": data.gross_margin_volatility,
        "latest_fcf": data.latest_fcf,
        "fcf_fiscal_year": data.fcf_fiscal_year,
        "fcf_source": data.fcf_source,
        "payload_json": json.dumps(payload, ensure_ascii=False) if payload else None,
    }
    try:
        conn = get_connection(db_path)
        try:
            conn.execute(
                """
                INSERT INTO financial_metrics (
                    ticker, updated_at, company_name, roic, roa, roe,
                    net_debt_ebitda, fcf_payout_ratio, interest_coverage,
                    revenue_cagr_5y, gross_margin_volatility,
                    latest_fcf, fcf_fiscal_year, fcf_source, payload_json
                ) VALUES (
                    :ticker, :updated_at, :company_name, :roic, :roa, :roe,
                    :net_debt_ebitda, :fcf_payout_ratio, :interest_coverage,
                    :revenue_cagr_5y, :gross_margin_volatility,
                    :latest_fcf, :fcf_fiscal_year, :fcf_source, :payload_json
                )
                ON CONFLICT(ticker) DO UPDATE SET
                    updated_at = excluded.updated_at,
                    company_name = excluded.company_name,
                    roic = excluded.roic,
                    roa = excluded.roa,
                    roe = excluded.roe,
                    net_debt_ebitda = excluded.net_debt_ebitda,
                    fcf_payout_ratio = excluded.fcf_payout_ratio,
                    interest_coverage = excluded.interest_coverage,
                    revenue_cagr_5y = excluded.revenue_cagr_5y,
                    gross_margin_volatility = excluded.gross_margin_volatility,
                    latest_fcf = excluded.latest_fcf,
                    fcf_fiscal_year = excluded.fcf_fiscal_year,
                    fcf_source = excluded.fcf_source,
                    payload_json = excluded.payload_json
                """,
                row,
            )
            conn.commit()
        finally:
            conn.close()
    except (sqlite3.Error, OSError):
        pass


def _fetch_live(ticker: str) -> FinancialData:
    """Pull core metrics from yfinance via analyzer_core helpers (lazy import)."""
    from analyzer_core import (
        _company_name,
        _safe_info_float,
        _safe_ticker_info,
        compute_interest_coverage,
        fetch_fcf_payout_ratio,
        fetch_gross_margin_volatility,
        fetch_latest_fcf_snapshot,
        fetch_net_debt_ebitda,
        fetch_revenue_cagr_5y,
        fetch_roic,
    )

    sym = ticker.upper().strip()
    yt = yf.Ticker(sym)
    info = _safe_ticker_info(yt, sym)
    roic, roa = fetch_roic(info, yt)
    fcf_val, fcf_year, fcf_source = fetch_latest_fcf_snapshot(sym, ticker=yt)

    return FinancialData(
        ticker=sym,
        updated_at=datetime.now(timezone.utc).isoformat(),
        company_name=_company_name(info, sym),
        roic=roic,
        roa=roa,
        roe=_safe_info_float(info, "returnOnEquity"),
        net_debt_ebitda=fetch_net_debt_ebitda(info, yt),
        fcf_payout_ratio=fetch_fcf_payout_ratio(sym, yt, info),
        interest_coverage=compute_interest_coverage(yt),
        revenue_cagr_5y=fetch_revenue_cagr_5y(yt),
        gross_margin_volatility=fetch_gross_margin_volatility(yt),
        latest_fcf=fcf_val,
        fcf_fiscal_year=fcf_year,
        fcf_source=fcf_source or "unknown",
    )


def get_financial_data(
    ticker: str,
    *,
    ttl_hours: float = DEFAULT_TTL_HOURS,
    force_refresh: bool = False,
    db_path: Path | str | None = None,
) -> FinancialData:
    """
    Return cached financial metrics for *ticker*.

    Reads SQLite first; on miss or stale TTL, fetches from yfinance and writes back.
    Never raises — returns a partially empty FinancialData on total failure.
    """
    sym = ticker.upper().strip()
    if not sym:
        return FinancialData(ticker="", updated_at=datetime.now(timezone.utc).isoformat())

    if not force_refresh:
        cached = _read_cache(sym, db_path=db_path)
        if cached is not None and not _is_stale(cached.updated_at, ttl_hours):
            return cached

    try:
        live = _fetch_live(sym)
    except Exception:
        cached = _read_cache(sym, db_path=db_path)
        if cached is not None:
            return cached
        return FinancialData(
            ticker=sym,
            updated_at=datetime.now(timezone.utc).isoformat(),
        )

    try:
        _write_cache(live, db_path=db_path)
    except Exception:
        pass
    return live


def cache_stats(db_path: Path | str | None = None) -> pd.DataFrame:
    """Return cache inventory as a DataFrame (for diagnostics)."""
    try:
        conn = get_connection(db_path)
        try:
            df = pd.read_sql_query(
                "SELECT ticker, updated_at, company_name, net_debt_ebitda, "
                "interest_coverage, latest_fcf FROM financial_metrics "
                "ORDER BY updated_at DESC",
                conn,
            )
        finally:
            conn.close()
        return df
    except Exception:
        return pd.DataFrame()
