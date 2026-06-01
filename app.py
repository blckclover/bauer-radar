"""Streamlit dashboard — System B scoring + Turnaround Hunter."""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from analyzer_core import (
    TICKERS,
    TICKER_GROUPS,
    StockReport,
    TurnaroundOpportunity,
    analyze_all,
    detect_trend_signals,
    dividend_chart_df,
    fcf_chart_df,
    find_turnaround_opportunities,
    reports_to_summary_df,
)

st.set_page_config(
    page_title="實戰持股安全儀表板",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

GRADE_COLORS = {
    "頂級穩健": "#22c55e",
    "良好": "#eab308",
    "高風險": "#ef4444",
}
CHART_COLORS = ["#3b82f6", "#8b5cf6", "#06b6d4", "#f59e0b", "#ec4899"]
SCORE_COLUMNS = ("綜合安全得分", "FCF分", "股息分", "發放率分", "Beta分")
DEFAULT_HUNTER_UNIVERSE = "PFE, GIS, FLO, NOK, NVO, INTC, BA, DIS"

TREND_BADGE_STYLES: dict[str, tuple[str, str, str, str]] = {
    "Buy": ("#15803d", "#dcfce7", "🟢", "BUY · 右側動能確認（建議進場）"),
    "Sell": ("#b91c1c", "#fee2e2", "🔴", "SELL · 動能衰竭（建議出場）"),
    "Wait": ("#1d4ed8", "#dbeafe", "🔵", "WAIT · 底部觀察中（請勿接刀）"),
    "Hold": ("#b45309", "#fef3c7", "🟡", "HOLD · 趨勢穩定持有"),
}


def _fmt1(value: float | None) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "N/A"
    return f"{float(value):.1f}"


def _fmt_money_large(value: float | None) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "N/A"
    v = float(value)
    if abs(v) >= 1e9:
        return f"${v / 1e9:.2f}B"
    if abs(v) >= 1e6:
        return f"${v / 1e6:.0f}M"
    return f"${v:,.0f}"


def _inject_css() -> None:
    st.markdown(
        """
        <style>
        .main-title { font-size: 2rem; font-weight: 700; margin-bottom: 0.25rem; }
        .subtitle { color: #64748b; margin-bottom: 1.25rem; }
        div[data-testid="stMetric"] {
            background: linear-gradient(135deg, #f8fafc 0%, #f1f5f9 100%);
            padding: 1rem; border-radius: 0.75rem; border: 1px solid #e2e8f0;
        }
        .panic-tag {
            color: #dc2626; font-weight: 800; font-size: 1.05rem;
        }
        .trend-facts {
            color: #475569; font-size: 0.92rem; margin-top: 0.35rem;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _parse_ticker_list(text: str) -> list[str]:
    """Parse comma- or newline-separated tickers; dedupe while preserving order."""
    seen: set[str] = set()
    out: list[str] = []
    normalized = text.replace("\n", ",").replace(";", ",")
    for token in normalized.split(","):
        sym = token.strip().upper()
        if sym and sym not in seen:
            seen.add(sym)
            out.append(sym)
    return out


def _format_summary_df(df: pd.DataFrame) -> pd.DataFrame:
    display = df.copy()
    for col in SCORE_COLUMNS:
        if col not in display.columns:
            continue
        display[col] = display[col].apply(
            lambda v: _fmt1(v) if v is not None and not (isinstance(v, float) and pd.isna(v)) else "N/A"
        )
    return display


def _style_summary_table(df: pd.DataFrame):
    def color_score(val):
        try:
            v = float(val)
        except (TypeError, ValueError):
            return ""
        if v >= 85:
            bg = GRADE_COLORS["頂級穩健"]
        elif v >= 70:
            bg = GRADE_COLORS["良好"]
        else:
            bg = GRADE_COLORS["高風險"]
        return f"background-color: {bg}; color: white; font-weight: 700; text-align: center;"

    def color_grade(val):
        text = str(val)
        if "頂級" in text:
            bg = GRADE_COLORS["頂級穩健"]
        elif "良好" in text:
            bg = GRADE_COLORS["良好"]
        else:
            bg = GRADE_COLORS["高風險"]
        return f"background-color: {bg}; color: white; font-weight: 600; text-align: center;"

    styled = df.style.map(color_score, subset=["綜合安全得分"]).map(
        color_grade, subset=["等級"]
    )
    return styled.set_table_styles(
        [
            {"selector": "th", "props": [("background-color", "#1e293b"), ("color", "white")]},
            {"selector": "td", "props": [("text-align", "center")]},
        ]
    )


def _turnaround_to_dataframe(candidates: list[TurnaroundOpportunity]) -> pd.DataFrame:
    rows = []
    for c in candidates:
        rd = _fmt_money_large(c.rd_expense) if c.rd_expense else "—"
        rows.append(
            {
                "代號": c.symbol,
                "公司名稱": c.company_name,
                "相對半年高點跌幅": f"-{c.drawdown_pct:.1f}%",
                "最新財年 FCF": _fmt_money_large(c.latest_fcf),
                "FCF 財年": c.latest_fcf_fiscal_year or "—",
                "研發費 (R&D)": rd,
                "FCF 來源": c.fcf_source,
            }
        )
    return pd.DataFrame(rows)


def _style_turnaround_table(df: pd.DataFrame):
    def highlight_drawdown(val):
        text = str(val)
        if text.startswith("-"):
            return "color: #dc2626; font-weight: 800; text-align: center; font-size: 1.05em;"
        return "text-align: center;"

    def highlight_fcf(val):
        if str(val).startswith("$"):
            return "color: #15803d; font-weight: 600; text-align: center;"
        return "text-align: center;"

    return (
        df.style.map(highlight_drawdown, subset=["相對半年高點跌幅"])
        .map(highlight_fcf, subset=["最新財年 FCF"])
        .set_table_styles(
            [
                {"selector": "th", "props": [("background-color", "#7f1d1d"), ("color", "white")]},
                {"selector": "td", "props": [("text-align", "center"), ("vertical-align", "middle")]},
            ]
        )
    )


@st.cache_data(ttl=3600, show_spinner="正在抓取 SEC EDGAR、股息與評分數據…")
def load_reports() -> list[StockReport]:
    return analyze_all()


@st.cache_data(ttl=900, show_spinner=False)
def _cached_trend_signal(symbol: str) -> dict | None:
    """Cached SMA trend lookup for Hunter tab (does not touch System B state)."""
    return detect_trend_signals(symbol)


def _fmt_price(value: float | str | None) -> str:
    if value is None:
        return "N/A"
    try:
        return f"${float(value):.2f}"
    except (TypeError, ValueError):
        return "N/A"


def _render_trend_signal_block(trend: dict | None) -> None:
    """Render right-side trend badge + hard price facts."""
    st.markdown("#### 📈 右側動態趨勢")

    if not trend:
        st.markdown(
            '<div style="background:#f1f5f9; padding:0.75rem 1rem; border-radius:0.5rem; '
            'color:#64748b;">趨勢數據不足，無法計算 SMA 20/50 交叉訊號。</div>',
            unsafe_allow_html=True,
        )
        return

    signal = str(trend.get("current_signal", "Hold"))
    border, bg, emoji, label = TREND_BADGE_STYLES.get(signal, TREND_BADGE_STYLES["Hold"])

    st.markdown(
        f"""
        <div style="background:{bg}; border-left: 5px solid {border};
             padding: 0.85rem 1rem; border-radius: 0.5rem; margin-bottom: 0.25rem;">
          <span style="color:{border}; font-weight: 800; font-size: 1.08rem;">
            {emoji} {label}
          </span>
        </div>
        """,
        unsafe_allow_html=True,
    )

    as_of = trend.get("as_of_date") or "—"
    st.markdown(
        f"當前現價: **{_fmt_price(trend.get('current_price'))}** | "
        f"20日均線: **{_fmt_price(trend.get('sma_20'))}** | "
        f"50日防禦線: **{_fmt_price(trend.get('sma_50'))}** "
        f"(數據截至: {as_of})"
    )


def _fcf_bar_chart(report: StockReport) -> go.Figure:
    df = fcf_chart_df(report)
    unit = "Billions USD"
    y_vals = df["FCF (USD billions)"]
    if not y_vals.empty and y_vals.abs().max() < 1:
        df = df.copy()
        df["FCF (USD millions)"] = df["FCF (USD billions)"] * 1000
        y_col = "FCF (USD millions)"
        unit = "Millions USD"
        labels = [f"${v:.1f}M" for v in df[y_col]]
    else:
        y_col = "FCF (USD billions)"
        labels = [f"${v:.1f}B" for v in df[y_col]]

    fig = go.Figure(
        data=[
            go.Bar(
                x=df["Fiscal Year"].astype(str),
                y=df[y_col],
                marker_color=CHART_COLORS[0],
                text=labels,
                textposition="outside",
            )
        ]
    )
    fig.update_layout(
        title=f"{report.symbol} — 自由現金流 FCF",
        xaxis_title="Fiscal Year",
        yaxis_title=unit,
        template="plotly_white",
        height=400,
        margin=dict(t=50, b=40),
    )
    return fig


def _dps_line_chart(report: StockReport) -> go.Figure:
    df = dividend_chart_df(report)
    fig = go.Figure(
        data=[
            go.Scatter(
                x=df["Year"],
                y=df["DPS (USD)"],
                mode="lines+markers",
                line=dict(color=CHART_COLORS[1], width=3),
                marker=dict(size=10),
                hovertemplate="%{x}<br>DPS: $%{y:.3f}<extra></extra>",
            )
        ]
    )
    fig.update_layout(
        title=f"{report.symbol} — 年度股息 DPS",
        xaxis_title="Calendar Year",
        yaxis_title="DPS (USD)",
        template="plotly_white",
        height=400,
        xaxis=dict(dtick=1),
    )
    return fig


def _format_fcf_table(report: StockReport) -> pd.DataFrame:
    df = fcf_chart_df(report)
    if df.empty:
        return df
    out = df.copy()
    if "FCF (USD billions)" in out.columns:
        out["FCF (USD billions)"] = out["FCF (USD billions)"].round(2)
    return out


def _format_dividend_table(report: StockReport) -> pd.DataFrame:
    df = dividend_chart_df(report)
    if df.empty:
        return df
    out = df.copy()
    out["DPS (USD)"] = out["DPS (USD)"].round(3)
    if "YoY Growth %" in out.columns:
        out["YoY Growth %"] = out["YoY Growth %"].round(1)
    return out


def _render_company_detail(report: StockReport) -> None:
    _render_trend_signal_block(report.trend_signal)
    st.caption(f"{report.company_name} · {report.portfolio_group}")

    h1, h2, h3, h4 = st.columns(4)
    h1.metric("綜合安全得分", _fmt1(report.total_score))
    h2.metric("等級", f"{report.grade_emoji} {report.grade_label}")
    h3.metric(
        "發放率",
        f"{report.payout_ratio * 100:.1f}%" if report.payout_ratio is not None else "N/A",
    )
    h4.metric("Beta", _fmt1(report.beta) if report.beta is not None else "N/A")

    chart_left, chart_right = st.columns(2)
    with chart_left:
        st.plotly_chart(_fcf_bar_chart(report), use_container_width=True, key=f"fcf_{report.symbol}")
    with chart_right:
        st.plotly_chart(_dps_line_chart(report), use_container_width=True, key=f"dps_{report.symbol}")

    st.markdown(report.analyst_commentary)

    with st.expander("原始數據與分項得分"):
        for d in report.score_details:
            st.write(
                f"**{d.category}**：{_fmt1(d.earned)} / {_fmt1(d.max_points)} — {d.rationale}"
            )
        c1, c2 = st.columns(2)
        with c1:
            st.dataframe(_format_fcf_table(report), use_container_width=True, hide_index=True)
        with c2:
            st.dataframe(_format_dividend_table(report), use_container_width=True, hide_index=True)


def _render_system_b_tab() -> None:
    """System B passive scoring — isolated from Turnaround Hunter state."""
    reports = load_reports()
    by_symbol = {r.symbol: r for r in reports}
    summary_df = _format_summary_df(reports_to_summary_df(reports))

    groups_txt = " | ".join(
        f"**{g}**：{', '.join(syms)}" for g, syms in TICKER_GROUPS.items()
    )
    st.markdown(f'<p class="subtitle">{groups_txt}</p>', unsafe_allow_html=True)

    top = [r for r in reports if r.total_score >= 85]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("分析標的", len(reports))
    c2.metric("頂級穩健 (≥85)", len(top))
    c3.metric("評分權重", "FCF40 + 股息30 + 發放率20 + Beta10")
    c4.metric(
        "均分",
        _fmt1(sum(r.total_score for r in reports) / len(reports)) if reports else "—",
    )

    st.subheader("綜合摘要")
    st.dataframe(_style_summary_table(summary_df), use_container_width=True, hide_index=True)

    st.markdown("---")
    st.subheader("公司深度分析")
    st.caption("點選下方 Tab 切換公司，圖表與 AI 點評會同步更新。")

    company_tabs = st.tabs(list(TICKERS))
    for tab, sym in zip(company_tabs, TICKERS):
        with tab:
            _render_company_detail(by_symbol[sym])


def _render_turnaround_hunter_tab() -> None:
    """Active turnaround screener — own session_state, no System B dependency."""
    if "hunter_universe_input" not in st.session_state:
        st.session_state.hunter_universe_input = DEFAULT_HUNTER_UNIVERSE
    if "hunter_results" not in st.session_state:
        st.session_state.hunter_results: list[TurnaroundOpportunity] = []
    if "hunter_scanned_count" not in st.session_state:
        st.session_state.hunter_scanned_count = 0

    st.markdown(
        '<p class="subtitle">'
        "在<strong>市場恐慌（股價大跌）</strong>中，尋找<strong>自由現金流仍為正</strong>的硬事實標的。"
        "</p>",
        unsafe_allow_html=True,
    )

    c1, c2, c3 = st.columns(3)
    c1.metric("篩選門檻", "半年高點跌幅 > 15%")
    c2.metric("硬事實", "最新財年 FCF > 0")
    c3.metric("上次命中", len(st.session_state.hunter_results))

    st.markdown("#### 自訂掃描清單")
    st.text_area(
        "輸入股票代號（逗號或換行分隔）",
        height=120,
        help="例如大市值美股：PFE, GIS, INTC … 可自行增刪。",
        key="hunter_universe_input",
    )

    parsed = _parse_ticker_list(st.session_state.hunter_universe_input)
    st.caption(f"已解析 **{len(parsed)}** 檔標的：" + (", ".join(parsed) if parsed else "（無）"))

    col_btn, col_hint = st.columns([1, 2])
    with col_btn:
        run_scan = st.button(
            "開始在垃圾堆中搜尋黃金",
            type="primary",
            use_container_width=True,
            key="hunter_run_button",
        )
    with col_hint:
        st.info("偵探引擎會跳過數據缺失的個股，不會因單一 Ticker 失敗而中斷。")

    if run_scan:
        if not parsed:
            st.warning("請至少輸入一個有效股票代號。")
        else:
            with st.spinner("偵探引擎正在剝離市場噪音，審查核心現金流 facts..."):
                st.session_state.hunter_results = find_turnaround_opportunities(parsed)
                st.session_state.hunter_scanned_count = len(parsed)

    results: list[TurnaroundOpportunity] = st.session_state.hunter_results

    st.markdown("---")
    st.subheader("轉機候選股結果")

    if not results:
        st.warning(
            "尚未命中，或尚未執行掃描。"
            " 請確認清單內有標的符合「半年跌幅 > 15% 且最新 FCF 仍為正」。"
        )
        return

    st.success(
        f"從 {st.session_state.hunter_scanned_count} 檔標的中，"
        f"找到 **{len(results)}** 檔「股價恐慌但現金流仍穩」的轉機候選。"
    )

    result_df = _turnaround_to_dataframe(results)
    st.dataframe(
        _style_turnaround_table(result_df),
        use_container_width=True,
        hide_index=True,
    )

    st.markdown("#### 個股快覽")
    for opp in results:
        with st.expander(
            f"{opp.symbol} · {opp.company_name}  "
            f"|  **-{opp.drawdown_pct:.1f}%**  "
            f"| FCF {_fmt_money_large(opp.latest_fcf)}"
        ):
            _render_trend_signal_block(_cached_trend_signal(opp.symbol))
            d1, d2, d3, d4 = st.columns(4)
            d1.markdown(
                f'<span class="panic-tag">-{opp.drawdown_pct:.1f}%</span>',
                unsafe_allow_html=True,
            )
            d1.caption("相對半年高點跌幅")
            d2.metric("現價", f"${opp.current_price:.2f}")
            d3.metric("半年高點", f"${opp.six_month_high:.2f}")
            d4.metric("最新 FCF", _fmt_money_large(opp.latest_fcf))
            if opp.rd_expense:
                st.markdown(
                    f"**科技新知儲備（R&D）**：{_fmt_money_large(opp.rd_expense)} "
                    f"（{opp.rd_fiscal_year}）"
                )
            st.caption(f"FCF 資料來源：{opp.fcf_source}")


def _render_sidebar() -> None:
    st.sidebar.header("System B 評分")
    st.sidebar.markdown(
        """
        - **FCF** (40)：連續 5 年為正
        - **股息** (30)：連續 5 年成長
        - **發放率** (20)：30–65% 滿分
        - **Beta** (10)：≤0.8 滿分

        **等級**：≥85 🟢 | 70–84 🟡 | <70 🔴
        """
    )
    st.sidebar.header("Turnaround Hunter")
    st.sidebar.markdown(
        """
        1. 半年股價跌幅 **> 15%**
        2. 最新財年 **FCF > 0**（SEC 優先）
        3. 可選 R&D 事實參考
        """
    )
    st.sidebar.header("右側趨勢訊號")
    st.sidebar.markdown(
        """
        - **Buy** 🟢 Golden Cross + 站上 SMA50
        - **Sell** 🔴 Death Cross + 跌破 SMA50
        - **Wait** 🔵 弱勢下跌中
        - **Hold** 🟡 趨勢穩定
        """
    )
    if st.sidebar.button("清除 System B 快取"):
        load_reports.clear()
        st.rerun()


def main() -> None:
    _inject_css()
    st.markdown('<p class="main-title">實戰持股 · 綜合安全儀表板</p>', unsafe_allow_html=True)

    tab_score, tab_hunter = st.tabs(
        [
            "📊 System B · 實戰持股評分",
            "🛡️ 逆向轉機股雷達 (Turnaround Hunter)",
        ]
    )

    with tab_score:
        _render_system_b_tab()

    with tab_hunter:
        _render_turnaround_hunter_tab()

    _render_sidebar()


if __name__ == "__main__":
    main()
