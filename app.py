"""Streamlit dashboard — core financial scoring + turnaround radar."""
from __future__ import annotations

import html
import re
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import streamlit.components.v1 as components
import yfinance as yf
from plotly.subplots import make_subplots

from analyzer_core import (
    FALLBACK_SCAN_UNIVERSE,
    FCF_PAYOUT_DEATH_THRESHOLD,
    FCF_PAYOUT_EXTRA_PENALTY,
    NET_DEBT_EBITDA_DEATH_THRESHOLD,
    STRATEGY_LABEL_GROWTH,
    STRATEGY_LABEL_VALUE,
    STRATEGY_LABELS,
    STRATEGY_VALUE,
    VALUE_SCORE_DEATH_CAP,
    WEIGHT_GROWTH_FUNDAMENTAL,
    WEIGHT_GROWTH_PEG_VAL,
    WEIGHT_GROWTH_SURPRISE,
    WEIGHT_GROWTH_TECH_TIMING,
    WEIGHT_VALUE_CASHFLOW,
    WEIGHT_VALUE_QUALITY,
    WEIGHT_VALUE_REVENUE,
    WEIGHT_VALUE_SAFETY,
    MasterMetrics,
    ScoreDetail,
    ScorecardItem,
    StockReport,
    TurnaroundOpportunity,
    YearDividend,
    YearFCF,
    clear_gemini_llm_cache,
    analyze_symbol,
    build_company_narrative,
    detect_trend_signals,
    dividend_chart_df,
    fcf_chart_df,
    fetch_index_constituents_safe,
    find_turnaround_opportunities,
    grade_from_score,
    is_growth_strategy,
    normalize_strategy_mode,
    reports_to_summary_df,
)

# Must run before any @st.cache_data registration (decorators execute at import time).
st.set_page_config(
    page_title="股息安全分析儀表板",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

GRADE_COLORS = {
    "財務防禦確立": "#22c55e",
    "體質穩健": "#eab308",
    "防禦不足": "#ef4444",
    "右側結構確立": "#22c55e",
    "動能蓄勢中": "#eab308",
    "趨勢待確認": "#ef4444",
}
CHART_COLORS = ["#3b82f6", "#8b5cf6", "#06b6d4", "#f59e0b", "#ec4899"]
SCORE_COLUMNS_VALUE = ("企業品質分", "估值安全分", "護城河分", "現金流品質分", "財務安全分", "營收穩定分")
SCORE_COLUMNS_GROWTH = ("企業品質分", "估值安全分", "基本面增長分", "PEG估值分", "預期修正分", "Timing輔助", "風險緩衝")

# Institutional factor glossary — surfaced via hover tooltips & glossary expander
METRIC_TOOLTIPS: dict[str, str] = {
    "ROIC": (
        "投入資本回報率，用以衡量管理層真實資本運用效率，"
        "避開舉債操縱 ROE 的價值陷阱。"
    ),
    "FCF 支付率": (
        "自由現金流支付率，大於 90% 視為極度透支，"
        "用以精準預測股息安全性。"
    ),
    "淨債務/EBITDA": (
        "淨債務與稅前息前折舊攤銷前獲利比，機構級核心槓桿指標，"
        "大於 3 倍視為財務高風險。"
    ),
    "5Y 營收 CAGR": (
        "五年營收複合成長率，用於排除「便宜但衰退」的價值陷阱；"
        "負成長直接觸發營收穩定 0 分。"
    ),
    "企業品質分": "Business Quality 0–95（Red Team 封頂）：護城河、現金流、財務、營收。",
    "估值安全分": "Valuation Safety 0–95：Forward P/E、PEG、FCF Yield。<50 觸發買太貴紅燈。",
    "等級": "依企業品質分映射；估值過高時另顯示紅燈警告。",
    "發放率": "每股盈餘發放率（輔助指標）；價值模式以 FCF 支付率為主判斷股息安全。",
    "Beta": "相對大盤波動係數；價值防禦模式不計入 Beta，僅供風險參考。",
    "前瞻 PEG": "前瞻本益成長比，衡量成長是否被低估定價；≤1 代表剪刀差顯著。",
    "CapEx 擴張率": "資本支出年增率，產業擴張領先指標；大幅下滑須辯證解讀 FCF 美化 vs 成長動能流失。",
    "毛利率": "定價權 proxy，反映轉嫁通膨與客戶切換成本。",
    "近一季 Surprise": "最新一季 EPS 相對共識偏差，衡量分析師預期修正動能。",
    "利息保障倍數": "EBIT / 利息費用，衡量債務結構韌性；<3x 為機構紅線。",
}

SCORE_WEIGHT_TOOLTIPS_VALUE: dict[str, str] = {
    "企業品質與護城河": (
        "ROIC + 毛利率穩定度 + 營業利益率（35 分）。"
        "優先 ROIC 而非 ROE，排除槓桿假象。"
    ),
    "現金流品質": (
        "FCF 支付率 + 股息連續成長（25 分）。"
        "支付率 >90% 觸發死亡懲罰：類別歸零並額外扣 10 分。"
    ),
    "財務安全防線": (
        "淨債務/EBITDA + 利息保障（25 分）。"
        "槓桿 >3x 觸發死亡懲罰：類別歸零且總分封頂 69。"
    ),
    "營收穩定": "5Y 營收 CAGR（15 分）；負成長 = 0 分，避免衰退型價值陷阱。",
}

SCORE_WEIGHT_TOOLTIPS_GROWTH: dict[str, str] = {
    "基本面增長": "營收成長 + CapEx 擴張（30 分）→ 併入企業品質軌。",
    "估值相對成長 (PEG)": "PEG 相對成長估值（25 分）→ 併入估值安全分軌。",
    "預期修正 Surprise": "EPS Surprise / 分析師修正（25 分）→ 併入企業品質軌。",
    "技術面輔助 (Timing)": "SMA 均線僅作 Timing 輔助（15 分），不主導決策。",
    "風險緩衝": "紅旗扣分緩衝（5 分）：槓桿、CapEx/利益率陷阱、高 Beta。",
}

SCORECARD_TOOLTIPS: dict[str, str] = {
    "財務安全": "資產負債表韌性：利息保障、淨槓桿與營業利益率紅旗。",
    "現金流健康度": "FCF Reality：自由現金流能否持續覆蓋營運與股東回報。",
    "核心成長性": "營收/獲利動能與 CapEx 投資方向是否一致。",
    "科技/AI 題材": "Tech Narrative 含金量：研發與資本支出是否支撐中長期敘事。",
    "定價權": "Moat Stability：毛利率、ROIC 與競爭對手壓力。",
    "估值": "Valuation Safety Margin：PEG 與預期修正下的安全邊際。",
}
GLOBAL_STRATEGY_KEY = "global_strategy_mode"
ACTIVE_STRATEGY_KEY = "active_strategy"
DEFAULT_HUNTER_UNIVERSE = "AAPL, MSFT, NVDA, INTC, BA, DIS, JNJ, KO"
SCAN_UNIVERSE_OPTIONS: dict[str, str] = {
    "🇺🇸 道瓊 30 (Dow 30) - 快速掃描": "dow30",
    "🦅 納斯達克 100 (Nasdaq 100) - 科技主導": "nasdaq100",
    "🌍 標普 500 (S&P 500) - 全市場深度掃描": "sp500",
    "✍️ 自訂輸入 (Custom Input)": "custom",
}
SCAN_UNIVERSE_LABELS = list(SCAN_UNIVERSE_OPTIONS.keys())
HUNTER_PRESET_KEY = "hunter_scan_preset"
HUNTER_PRESET_OPTIONS: dict[str, str] = {
    "Dow 30 (快速)": "dow30",
    "S&P 500 (完整)": "sp500",
}
HUNTER_SCAN_UNIVERSE_KEY = "hunter_scan_universe_label"
HUNTER_CUSTOM_INPUT_KEY = "hunter_custom_input"
WATCHLIST_INPUT_KEY = "watchlist_input"

TREND_BADGE_STYLES: dict[str, tuple[str, str, str, str]] = {
    "Buy": ("#15803d", "#dcfce7", "🟢", "BUY · 右側動能確認（建議進場）"),
    "Sell": ("#b91c1c", "#fee2e2", "🔴", "SELL · 動能衰竭（建議出場）"),
    "Wait": ("#1d4ed8", "#dbeafe", "🔵", "WAIT · 底部觀察中（請勿接刀）"),
    "Hold": ("#b45309", "#fef3c7", "🟡", "HOLD · 趨勢穩定持有"),
}
TECH_SMA_SHORT = 20
TECH_SMA_LONG = 50
TECH_COLOR_CLOSE = "#00d2d3"
TECH_COLOR_CLOSE_FILL = "rgba(0, 210, 211, 0.22)"
TECH_COLOR_SMA20 = "rgba(234, 179, 8, 0.55)"
TECH_COLOR_SMA50 = "rgba(239, 68, 68, 0.55)"
TECH_DARK_BG = "#0f172a"
TECH_DARK_CARD = "#1e293b"
TECH_ACCENT = "#14b8a6"
TECH_CHART_HEIGHT = 680
TECH_CHART_HEIGHT_VOL = 720
FREQ_OPTIONS = ["日線 (Daily)", "週線 (Weekly)", "月線 (Monthly)"]
INDICATOR_OPTIONS = [
    "SMA 20/50",
    "EMA 12/26/9",
    "成交量 (Volume)",
    "布林通道 (Bollinger Bands)",
]
FREQ_YF_MAP: dict[str, tuple[str, str]] = {
    "日線 (Daily)": ("1d", "1y"),
    "週線 (Weekly)": ("1wk", "2y"),
    "月線 (Monthly)": ("1mo", "max"),
}
COMPANY_TAB_KEY = "company_tab_radio"


def _current_strategy_mode() -> str:
    """Return canonical strategy code (value/growth) from session state."""
    selected = st.session_state.get(ACTIVE_STRATEGY_KEY, STRATEGY_LABEL_VALUE)
    return normalize_strategy_mode(selected)


def _strategy_label_for_mode(mode: str) -> str:
    if is_growth_strategy(mode):
        return STRATEGY_LABEL_GROWTH
    return STRATEGY_LABEL_VALUE


def _strategy_short_name(mode: str | None = None) -> str:
    active = mode or _current_strategy_mode()
    if is_growth_strategy(active):
        return "🚀 動能成長"
    return "💎 價值穩健"


def _strategy_weight_caption(mode: str | None = None) -> str:
    active = mode or _current_strategy_mode()
    if is_growth_strategy(active):
        return "雙軌計分 · 品質(30+25) / 估值(PEG25) / Timing15 / 風險緩衝5 · 封頂95"
    return "雙軌計分 · 品質(35+25+25+15) / 估值(Fwd P/E+PEG+FCF Yield) · 封頂95"


def _on_strategy_mode_change() -> None:
    st.session_state[ACTIVE_STRATEGY_KEY] = st.session_state.get(GLOBAL_STRATEGY_KEY, STRATEGY_LABEL_VALUE)
    st.rerun()


def _render_strategy_control() -> None:
    labels = list(STRATEGY_LABELS)
    if st.session_state.get(GLOBAL_STRATEGY_KEY) not in labels:
        st.session_state[GLOBAL_STRATEGY_KEY] = STRATEGY_LABEL_VALUE
    st.radio(
        "🎯 投資策略戰術",
        labels,
        key=GLOBAL_STRATEGY_KEY,
        horizontal=True,
        on_change=_on_strategy_mode_change,
    )
    mode = _current_strategy_mode()
    st.caption(
        f"評分引擎已切換至：**{_strategy_label_for_mode(mode)}** · "
        f"權重 `{_strategy_weight_caption(mode)}`"
    )


def _score_columns_for_mode(mode: str | None = None) -> tuple[str, ...]:
    if is_growth_strategy(mode or _current_strategy_mode()):
        return SCORE_COLUMNS_GROWTH
    return SCORE_COLUMNS_VALUE


_HTML_FENCE_BLOCK_RE = re.compile(
    r"^\s*```(?:html|HTML)?\s*\n?(.*?)\n?\s*```\s*$",
    re.DOTALL,
)
_HTML_FENCE_LEADING_RE = re.compile(r"^\s*```(?:html|HTML)?\s*\n?", re.IGNORECASE)
_HTML_FENCE_TRAILING_RE = re.compile(r"\n?\s*```\s*$")


_HTML_FENCE_RE = re.compile(r"```(?:html)?\n?", re.IGNORECASE)


def _clean_ai_html(raw: str) -> str:
    """Remove ```html / ``` markdown fences so Streamlit receives pure HTML or text."""
    content = raw or ""
    clean_html = _HTML_FENCE_RE.sub("", content).replace("```", "").strip()
    if not clean_html:
        return ""
    block = _HTML_FENCE_BLOCK_RE.match(clean_html)
    if block:
        inner = block.group(1)
        clean_html = _HTML_FENCE_RE.sub("", inner).replace("```", "").strip()
    clean_html = _HTML_FENCE_LEADING_RE.sub("", clean_html)
    clean_html = _HTML_FENCE_TRAILING_RE.sub("", clean_html)
    return _HTML_FENCE_RE.sub("", clean_html).replace("```", "").strip()


def _render_html(html_content: str) -> None:
    """Render custom HTML/CSS blocks — always strip AI fences and enable HTML parsing."""
    content = html_content or ""
    clean_html = _HTML_FENCE_RE.sub("", content).replace("```", "").strip()
    cleaned = _clean_ai_html(clean_html)
    if cleaned:
        st.markdown(cleaned, unsafe_allow_html=True)


def _is_llm_error_payload(text: object) -> bool:
    """Detect API failures / rate-limit strings that must never be rendered or cached."""
    if text is None:
        return True
    raw = str(text).strip()
    if not raw:
        return True
    lower = raw.lower()
    if raw.startswith("⚠️") or "科技敘事生成失敗" in raw or "生成失敗" in raw:
        return True
    if any(
        token in lower
        for token in ("429", "resource_exhausted", "rate limit", "too many requests", "quota exceeded")
    ):
        return True
    return False


def _safe_render_text(text: object) -> str | None:
    """Return stripped text safe to render, or None when empty / poisoned."""
    if text is None:
        return None
    raw = str(text).strip()
    if not raw or _is_llm_error_payload(raw):
        return None
    cleaned = _clean_ai_html(raw)
    return cleaned if cleaned else None


def _format_narrative_for_card(raw: str) -> str:
    """Strip AI filler / markdown artifacts; convert **bold** to HTML <strong>."""
    text = _clean_ai_html(raw)
    if text.lstrip().startswith("<"):
        return text
    filler_re = re.compile(
        r"^(好的[，,].*?|分析師報告如下[：:].*?|以下是.*?[：:].*?|"
        r"Sure[,.].*?|Here(?:'s| is).*?:)\s*\n?",
        flags=re.IGNORECASE | re.MULTILINE,
    )
    text = filler_re.sub("", text).strip()

    cleaned_lines: list[str] = []
    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue
        if line.startswith("#"):
            continue
        if line.replace("*", "").strip() in ("", "科技願景與最新嘗試"):
            continue
        if "科技願景" in line and len(line) < 48:
            continue
        cleaned_lines.append(line)
    text = "\n".join(cleaned_lines)

    def _bold_to_strong(match: re.Match[str]) -> str:
        return f"<strong>{html.escape(match.group(1))}</strong>"

    text = re.sub(r"\*\*(.+?)\*\*", _bold_to_strong, text)
    text = text.replace("**", "").replace("*", "")

    parts: list[str] = []
    for segment in re.split(r"(<strong>.*?</strong>)", text):
        if segment.startswith("<strong>"):
            parts.append(segment)
        else:
            parts.append(html.escape(segment))
    return "<br>".join("".join(parts).split("\n"))


def _render_narrative_card(symbol: str) -> None:
    st.markdown(
        '<p class="panel-label fx-narrative-heading">'
        "💡 科技願景與最新嘗試 (Company Narrative & Tech Pulse)</p>",
        unsafe_allow_html=True,
    )
    strategy_key = st.session_state.get(ACTIVE_STRATEGY_KEY, STRATEGY_LABEL_VALUE)
    narrative, live_news_degraded = load_company_narrative(strategy_key, symbol)
    safe_narrative = _safe_render_text(narrative)
    if not safe_narrative:
        if _is_llm_error_payload(narrative):
            st.error("目前 AI 伺服器擁擠，請稍後重試。")
        return
    card_html = _format_narrative_for_card(safe_narrative)
    if not card_html:
        return
    if live_news_degraded and is_growth_strategy(strategy_key):
        card_html += (
            '<p class="fx-narrative-footnote">'
            "即時新聞流連線超時 · 目前顯示基礎科技敘事"
            "</p>"
        )
    _render_html(
        f'<div class="fx-narrative-card"><div class="fx-narrative-body">{card_html}</div></div>'
    )


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
        <link rel="preconnect" href="https://fonts.googleapis.com">
        <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
        <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
        """,
        unsafe_allow_html=True,
    )
    st.markdown(
        f"""
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');
        html, body, [class*="css"], .stApp, .stMarkdown, label, p, span, div {{
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif !important;
        }}
        div[data-testid="stMetric"] {{
            background-color: #1E293B !important;
            border: 1px solid #334155 !important;
            border-radius: 8px !important;
            padding: 0.85rem 1rem 0.95rem !important;
            box-shadow: inset 0 1px 0 rgba(148, 163, 184, 0.06);
            min-width: 8.5rem;
            overflow: visible !important;
        }}
        div[data-testid="stMetric"] label {{
            color: #94A3B8 !important;
            font-size: 0.72rem !important;
            font-weight: 600 !important;
            letter-spacing: 0.04em !important;
            text-transform: uppercase !important;
            white-space: normal !important;
            overflow-wrap: anywhere !important;
            line-height: 1.35 !important;
        }}
        div[data-testid="stMetric"] [data-testid="stMetricValue"] {{
            font-size: 1.65rem !important;
            font-weight: 700 !important;
            color: #F1F5F9 !important;
            white-space: normal !important;
            overflow-wrap: anywhere !important;
            line-height: 1.2 !important;
        }}
        div[data-testid="stMetric"] [data-testid="stMetricDelta"] {{
            font-size: 0.78rem !important;
            white-space: normal !important;
            overflow-wrap: anywhere !important;
        }}
        :root {{
            --bg-base: #0f172a;
            --bg-card: #1e293b;
            --accent: {TECH_ACCENT};
            --accent-soft: rgba(20, 184, 166, 0.14);
            --text-muted: #94a3b8;
            --border-subtle: rgba(148, 163, 184, 0.1);
        }}
        .stApp, [data-testid="stAppViewContainer"] {{
            background-color: var(--bg-base) !important;
            margin-top: 0 !important;
        }}
        [data-testid="stAppViewContainer"] .main,
        [data-testid="stMain"] {{
            margin-top: 0 !important;
            overflow: visible !important;
        }}
        header[data-testid="stHeader"] {{
            background: rgba(15, 23, 42, 0.92) !important;
        }}
        section[data-testid="stSidebar"] {{
            background-color: #121212 !important;
            border-right: 1px solid var(--border-subtle) !important;
        }}
        section[data-testid="stSidebar"] > div {{
            background-color: #121212 !important;
        }}
        .block-container {{
            padding-top: 3rem !important;
            padding-bottom: 2.5rem;
            max-width: 1480px;
            margin-top: 0 !important;
            overflow: visible !important;
        }}
        [data-testid="stMainBlockContainer"] {{
            padding-top: 0 !important;
            overflow: visible !important;
        }}
        [data-testid="stAppViewContainer"] .main .block-container {{
            padding-top: 3rem !important;
            margin-top: 0 !important;
        }}
        [data-testid="stHorizontalBlock"] {{
            gap: 0.75rem !important;
            align-items: stretch !important;
            flex-wrap: wrap !important;
            overflow: visible !important;
        }}
        [data-testid="column"] {{
            min-width: min(100%, 9.5rem) !important;
            overflow: visible !important;
        }}
        [data-testid="column"] > div {{
            overflow: visible !important;
            min-width: 0;
        }}
        [data-testid="stVerticalBlock"] > [data-testid="stVerticalBlock"] {{
            gap: 1.15rem;
            overflow: visible !important;
        }}
        [data-testid="stMarkdownContainer"] p,
        [data-testid="stMarkdownContainer"] span,
        [data-testid="stMarkdownContainer"] div {{
            overflow-wrap: anywhere;
            word-break: break-word;
        }}
        [data-testid="stTabs"] {{
            margin-top: 0.75rem;
            margin-bottom: 1.75rem;
        }}
        div[data-testid="stVerticalBlockBorderWrapper"] {{
            background: linear-gradient(145deg, #1e293b 0%, #172033 55%, #121a28 100%) !important;
            border: 1px solid var(--border-subtle) !important;
            border-radius: 10px !important;
            padding: 1rem 1.15rem !important;
            margin: 0.85rem 0 1.35rem !important;
            box-shadow: 0 10px 28px rgba(2, 6, 23, 0.28);
        }}
        .fx-metric-card {{
            background: linear-gradient(160deg, #243044 0%, #1a2332 45%, #121a28 100%);
            border: 1px solid rgba(148, 163, 184, 0.14);
            border-radius: 10px;
            padding: 1rem 1.1rem;
            margin: 0.35rem 0 1.1rem;
            min-height: 88px;
            min-width: 9rem;
            box-shadow: 0 8px 22px rgba(2, 6, 23, 0.22);
            display: flex;
            flex-direction: column;
            justify-content: flex-start;
            overflow: visible;
        }}
        .fx-metric-label {{
            color: #94a3b8;
            font-size: 0.72rem;
            letter-spacing: 0.05em;
            text-transform: uppercase;
            margin-bottom: 0.45rem;
            flex-shrink: 0;
            display: flex;
            align-items: flex-start;
            gap: 0.35rem;
            white-space: normal;
            overflow-wrap: anywhere;
            line-height: 1.35;
        }}
        .fx-metric-tip {{
            position: relative;
            display: inline-flex;
            align-items: center;
            justify-content: center;
            width: 0.95rem;
            height: 0.95rem;
            border-radius: 50%;
            border: 1px solid rgba(148, 163, 184, 0.35);
            color: #64748b;
            font-size: 0.58rem;
            font-weight: 700;
            cursor: help;
            text-transform: none;
            letter-spacing: 0;
            flex-shrink: 0;
        }}
        .fx-metric-tip:hover::after {{
            content: attr(data-tip);
            position: absolute;
            left: 50%;
            bottom: calc(100% + 8px);
            transform: translateX(-50%);
            width: max-content;
            max-width: 240px;
            padding: 0.55rem 0.65rem;
            background: #0f172a;
            border: 1px solid rgba(100, 116, 139, 0.35);
            border-radius: 8px;
            color: #e2e8f0;
            font-size: 0.68rem;
            line-height: 1.45;
            font-weight: 400;
            text-transform: none;
            letter-spacing: 0.01em;
            box-shadow: 0 10px 24px rgba(2, 6, 23, 0.45);
            z-index: 50;
            pointer-events: none;
            white-space: normal;
        }}
        .fx-metric-value {{
            color: #f8fafc;
            font-size: 1.15rem;
            font-weight: 700;
            line-height: 1.3;
            word-break: break-word;
            flex-shrink: 0;
        }}
        .fx-metric-subtext {{
            color: #64748b;
            font-size: 0.68rem;
            line-height: 1.45;
            margin-top: 0.4rem;
            word-break: break-word;
            letter-spacing: 0.01em;
        }}
        .fx-table-card {{
            background: linear-gradient(165deg, #1f2937 0%, #172033 50%, #111827 100%);
            border: 1px solid rgba(148, 163, 184, 0.14);
            border-radius: 10px;
            padding: 0.85rem 0.95rem 1rem;
            margin: 0.65rem 0 1.45rem;
            box-shadow: 0 12px 30px rgba(2, 6, 23, 0.26);
        }}
        .fx-table-title {{
            color: #94a3b8;
            font-size: 0.72rem;
            letter-spacing: 0.06em;
            text-transform: uppercase;
            margin: 0.15rem 0 0.75rem 0.35rem;
        }}
        .fx-table-wrap {{
            overflow-x: auto;
        }}
        table.fx-table {{
            width: 100%;
            border-collapse: collapse;
            font-size: 0.86rem;
        }}
        table.fx-table th {{
            color: #94a3b8;
            font-weight: 600;
            text-align: center;
            padding: 0.65rem 0.55rem;
            border-bottom: 1px solid rgba(148, 163, 184, 0.14);
        }}
        table.fx-table td {{
            color: #e2e8f0;
            text-align: center;
            padding: 0.62rem 0.55rem;
            border-bottom: 1px solid rgba(148, 163, 184, 0.06);
            word-break: break-word;
        }}
        table.fx-table tbody tr:hover td {{
            background: rgba(148, 163, 184, 0.05);
        }}
        table.fx-table td.tone-green {{ color: #4ade80; font-weight: 700; }}
        table.fx-table td.tone-yellow {{ color: #facc15; font-weight: 700; }}
        table.fx-table td.tone-red {{ color: #f87171; font-weight: 700; }}
        .master-scorecard-wrap {{
            background: linear-gradient(165deg, #1a2332 0%, #121a28 100%);
            border: 1px solid rgba(100, 116, 139, 0.18);
            border-radius: 10px;
            padding: 0.85rem 0.95rem 1rem;
            margin: 0.65rem 0 1.25rem;
            box-shadow: 0 8px 22px rgba(2, 6, 23, 0.28);
        }}
        .master-scorecard-title {{
            color: #64748b;
            font-size: 0.68rem;
            letter-spacing: 0.08em;
            text-transform: uppercase;
            margin: 0.1rem 0 0.65rem 0.2rem;
        }}
        table.master-scorecard {{
            width: 100%;
            border-collapse: collapse;
            font-size: 0.78rem;
        }}
        table.master-scorecard th {{
            color: #64748b;
            font-weight: 600;
            text-align: left;
            padding: 0.5rem 0.45rem;
            border-bottom: 1px solid rgba(148, 163, 184, 0.12);
            font-size: 0.68rem;
            letter-spacing: 0.04em;
        }}
        table.master-scorecard td {{
            color: #cbd5e1;
            padding: 0.55rem 0.45rem;
            border-bottom: 1px solid rgba(148, 163, 184, 0.06);
            vertical-align: top;
            line-height: 1.45;
        }}
        table.master-scorecard td.score-cell {{
            text-align: center;
            font-weight: 700;
            font-size: 0.95rem;
            width: 3rem;
            white-space: nowrap;
        }}
        table.master-scorecard td.score-high {{ color: #4ade80; }}
        table.master-scorecard td.score-mid {{ color: #facc15; }}
        table.master-scorecard td.score-low {{ color: #f87171; }}
        table.master-scorecard td.dim-cell {{
            color: #e2e8f0;
            font-weight: 500;
            width: 38%;
        }}
        .scorecard-progress-grid {{
            display: grid;
            grid-template-columns: repeat(2, minmax(11.5rem, 1fr));
            gap: 0.65rem;
            margin: 0.65rem 0 1.25rem;
        }}
        @media (max-width: 900px) {{
            .scorecard-progress-grid {{
                grid-template-columns: 1fr;
            }}
        }}
        .scorecard-progress-card {{
            background: #0f172a;
            border: 1px solid rgba(100, 116, 139, 0.18);
            border-radius: 10px;
            padding: 0.75rem 0.85rem 0.8rem;
            box-shadow: inset 0 1px 0 rgba(148, 163, 184, 0.04);
        }}
        .scorecard-progress-header {{
            display: flex;
            align-items: flex-start;
            justify-content: space-between;
            gap: 0.5rem;
            margin-bottom: 0.45rem;
        }}
        .scorecard-progress-name {{
            color: #e2e8f0;
            font-size: 0.74rem;
            font-weight: 600;
            line-height: 1.35;
            display: flex;
            align-items: flex-start;
            gap: 0.3rem;
            flex: 1 1 auto;
            min-width: 0;
            white-space: normal;
            overflow-wrap: anywhere;
        }}
        .scorecard-progress-score {{
            font-size: 0.82rem;
            font-weight: 700;
            white-space: nowrap;
            flex-shrink: 0;
        }}
        .scorecard-progress-score.score-high {{ color: #4ade80; }}
        .scorecard-progress-score.score-mid {{ color: #facc15; }}
        .scorecard-progress-score.score-low {{ color: #fb923c; }}
        .scorecard-progress-track {{
            height: 6px;
            background: rgba(148, 163, 184, 0.12);
            border-radius: 999px;
            overflow: hidden;
            margin-bottom: 0.45rem;
        }}
        .scorecard-progress-fill {{
            height: 100%;
            border-radius: 999px;
            transition: width 0.3s ease;
        }}
        .scorecard-progress-fill.score-high {{
            background: linear-gradient(90deg, #22c55e 0%, #4ade80 100%);
        }}
        .scorecard-progress-fill.score-mid {{
            background: linear-gradient(90deg, #ca8a04 0%, #facc15 100%);
        }}
        .scorecard-progress-fill.score-low {{
            background: linear-gradient(90deg, #ea580c 0%, #fb923c 100%);
        }}
        .scorecard-progress-rationale {{
            color: #64748b;
            font-size: 0.68rem;
            line-height: 1.45;
            white-space: normal;
            overflow-wrap: anywhere;
        }}
        .scorecard-grid-title {{
            color: #64748b;
            font-size: 0.68rem;
            letter-spacing: 0.08em;
            text-transform: uppercase;
            margin: 0.35rem 0 0.55rem 0.15rem;
        }}
        .valuation-trap-alert {{
            background: rgba(239, 68, 68, 0.12);
            border: 1px solid rgba(239, 68, 68, 0.55);
            color: #fecaca;
            font-weight: 700;
            font-size: 0.92rem;
            padding: 0.75rem 1rem;
            border-radius: 8px;
            margin: 0.65rem 0 1rem;
            text-align: center;
            box-shadow: 0 0 12px rgba(239, 68, 68, 0.15);
        }}
        .terminal-score-grid {{
            display: grid;
            grid-template-columns: repeat(2, minmax(12rem, 1fr));
            gap: 1rem;
            margin: 1.1rem 0 0.85rem;
            overflow: visible;
        }}
        @media (max-width: 768px) {{
            .terminal-score-grid {{ grid-template-columns: 1fr; }}
        }}
        .terminal-score-card {{
            background: linear-gradient(165deg, #1E293B 0%, #172033 100%);
            border: 1px solid #334155;
            border-radius: 10px;
            padding: 1.35rem 1.25rem 1.15rem;
            text-align: center;
            box-shadow: 0 8px 24px rgba(2, 6, 23, 0.35);
        }}
        .terminal-score-label {{
            color: #94A3B8;
            font-size: 0.72rem;
            font-weight: 600;
            letter-spacing: 0.08em;
            text-transform: uppercase;
            margin-bottom: 0.35rem;
            white-space: normal;
            overflow-wrap: anywhere;
            line-height: 1.35;
        }}
        .terminal-score-sublabel {{
            color: #64748B;
            font-size: 0.68rem;
            margin-bottom: 0.55rem;
            white-space: normal;
            overflow-wrap: anywhere;
            line-height: 1.4;
        }}
        .terminal-score-cap {{
            white-space: normal;
            overflow-wrap: anywhere;
            line-height: 1.4;
        }}
        .terminal-score-value {{
            font-size: 48px;
            font-weight: 800;
            line-height: 1.05;
            letter-spacing: -0.02em;
        }}
        .death-penalty-banner {{
            background: linear-gradient(90deg, rgba(127, 29, 29, 0.55) 0%, rgba(69, 10, 10, 0.45) 100%);
            border: 1px solid #EF4444;
            border-left: 4px solid #EF4444;
            color: #FEE2E2;
            font-size: 0.88rem;
            font-weight: 600;
            padding: 0.85rem 1.1rem;
            border-radius: 8px;
            margin: 0.65rem 0 0.85rem;
            line-height: 1.55;
        }}
        .terminal-grade-strip {{
            color: #94A3B8;
            font-size: 0.82rem;
            margin: 0.35rem 0 0.85rem;
        }}
        .ai-terminal-panel {{
            display: none;
        }}
        .ai-terminal-body {{
            border: 1px solid #334155;
            border-radius: 10px;
            background: #0f172a;
            padding: 1rem 1.15rem;
            margin: 0.75rem 0 1.35rem;
            box-shadow: inset 0 1px 0 rgba(148, 163, 184, 0.05);
            color: #cbd5e1;
            font-size: 0.86rem;
            line-height: 1.65;
            white-space: pre-wrap;
            word-break: break-word;
        }}
        .factor-glossary-item {{
            margin: 0 0 0.55rem 0;
            line-height: 1.5;
        }}
        .factor-glossary-dim {{
            color: #5eead4;
            font-size: 0.78rem;
            font-weight: 600;
            display: block;
            margin-bottom: 0.15rem;
        }}
        .factor-glossary-desc {{
            color: #94a3b8;
            font-size: 0.74rem;
        }}
        .panel-heading {{
            color: #f1f5f9;
            font-size: 1.05rem;
            font-weight: 700;
            margin: 0.5rem 0 0.35rem;
            letter-spacing: 0.01em;
        }}
        .panel-subheading {{
            color: #64748b;
            font-size: 0.82rem;
            font-weight: 600;
            margin: 0.85rem 0 0.45rem;
            letter-spacing: 0.04em;
            text-transform: uppercase;
        }}
        .ai-terminal-panel + div[data-testid="stMarkdownContainer"],
        .ai-terminal-panel + div {{
            border: 1px solid #334155;
            border-radius: 10px;
            background: #0f172a;
            padding: 1rem 1.15rem;
            margin: 0.75rem 0 1.35rem;
            box-shadow: inset 0 1px 0 rgba(148, 163, 184, 0.05);
        }}
        .ai-terminal-panel + div h3 {{
            font-size: 0.95rem !important;
            color: #e2e8f0 !important;
            margin: 0.65rem 0 0.35rem !important;
        }}
        .ai-terminal-panel + div h4 {{
            font-size: 0.88rem !important;
            color: #94a3b8 !important;
            margin: 0.55rem 0 0.25rem !important;
        }}
        .ai-terminal-panel + div p,
        .ai-terminal-panel + div li {{
            color: #cbd5e1;
            font-size: 0.86rem;
            line-height: 1.65;
        }}
        .ai-terminal-panel + div strong {{
            color: #f1f5f9;
        }}
        .ai-terminal-panel + div blockquote {{
            border-left: 3px solid var(--accent);
            padding-left: 0.75rem;
            color: #94a3b8;
            margin: 0.5rem 0;
        }}
        .fx-narrative-heading {{
            margin-top: 1.5rem !important;
        }}
        .fx-narrative-card {{
            background: #1e293b;
            border: 1px solid rgba(100, 116, 139, 0.12);
            border-radius: 10px;
            padding: 1.25rem;
            margin: 0.5rem 0 1.25rem;
            box-shadow: 0 6px 18px rgba(2, 6, 23, 0.28);
        }}
        .fx-narrative-body {{
            color: #f1f5f9;
            font-size: 0.9rem;
            line-height: 1.7;
            letter-spacing: 0.01em;
        }}
        .fx-narrative-body strong {{
            color: #ffffff;
            font-weight: 600;
        }}
        .fx-narrative-footnote {{
            color: #475569;
            font-size: 0.65rem;
            line-height: 1.45;
            margin-top: 1.05rem;
            padding-top: 0.65rem;
            border-top: 1px solid rgba(148, 163, 184, 0.08);
            opacity: 0.65;
            letter-spacing: 0.03em;
            font-weight: 400;
        }}
        .strategy-badge {{
            display: inline-block;
            background: rgba(20, 184, 166, 0.12);
            color: #5eead4;
            border-radius: 999px;
            padding: 0.28rem 0.75rem;
            font-size: 0.78rem;
            font-weight: 600;
            margin-bottom: 0.65rem;
        }}
        .fx-chart-empty {{
            background: linear-gradient(165deg, #1e293b 0%, #151d2b 100%);
            border: 1px solid rgba(148, 163, 184, 0.12);
            border-radius: 10px;
            padding: 0.85rem 1rem;
            margin: 0.35rem 0 1rem;
            color: #94a3b8;
            font-size: 0.86rem;
            line-height: 1.55;
        }}
        div[data-testid="stRadio"] > label {{
            color: #94a3b8 !important;
            font-size: 0.82rem !important;
            font-weight: 600 !important;
        }}
        .section-divider {{
            margin: 3rem 0 1.85rem;
            padding: 1.35rem 0 1.1rem;
            border-top: 1px solid rgba(148, 163, 184, 0.16);
            border-bottom: 1px solid rgba(148, 163, 184, 0.08);
            background: linear-gradient(180deg, rgba(30, 41, 59, 0.42) 0%, rgba(15, 23, 42, 0) 100%);
            border-radius: 10px;
        }}
        .section-divider-label {{
            display: block;
            text-align: center;
            color: #64748b;
            font-size: 0.72rem;
            letter-spacing: 0.14em;
            text-transform: uppercase;
        }}
        .sidebar-lab-card {{
            background: linear-gradient(160deg, #1a2332 0%, #121a28 100%);
            border: 1px dashed rgba(148, 163, 184, 0.22);
            border-radius: 10px;
            padding: 0.85rem 0.9rem;
            margin: 0.35rem 0 1rem;
            opacity: 0.72;
        }}
        .sidebar-lab-title {{
            color: #94a3b8;
            font-size: 0.82rem;
            font-weight: 600;
            margin-bottom: 0.35rem;
        }}
        .sidebar-lab-badge {{
            display: inline-block;
            font-size: 0.62rem;
            letter-spacing: 0.08em;
            color: #64748b;
            border: 1px solid rgba(148, 163, 184, 0.25);
            border-radius: 999px;
            padding: 0.12rem 0.45rem;
            margin-bottom: 0.45rem;
        }}
        .sidebar-lab-hint {{
            color: #64748b;
            font-size: 0.72rem;
            line-height: 1.45;
            margin: 0;
        }}
        .main-title {{
            font-size: 1.55rem;
            font-weight: 700;
            margin-bottom: 0.35rem;
            letter-spacing: -0.02em;
            color: #f1f5f9;
        }}
        .subtitle {{
            color: var(--text-muted);
            font-size: 0.92rem;
            margin-bottom: 0.85rem;
            line-height: 1.55;
        }}
        h2, h3, h4, h5 {{
            letter-spacing: -0.01em;
            color: #e2e8f0;
        }}
        [data-testid="stTabs"] button p {{
            font-size: 0.92rem;
            white-space: normal !important;
            overflow-wrap: anywhere !important;
        }}
        div.stButton > button {{
            border-radius: 8px !important;
            font-weight: 600 !important;
            letter-spacing: 0.01em;
            transition: background 0.2s ease, border-color 0.2s ease, color 0.2s ease,
                box-shadow 0.2s ease !important;
            border: 1px solid var(--border-subtle) !important;
            background: #1a2332 !important;
            color: #cbd5e1 !important;
        }}
        div.stButton > button:hover {{
            border-color: rgba(20, 184, 166, 0.45) !important;
            background: rgba(30, 41, 59, 0.95) !important;
            color: #e2e8f0 !important;
        }}
        div.stButton > button[kind="primary"],
        div.stButton > button[data-testid="baseButton-primary"] {{
            background: var(--accent-soft) !important;
            color: #5eead4 !important;
            border: 1px solid var(--accent) !important;
        }}
        div.stButton > button[kind="primary"]:hover,
        div.stButton > button[data-testid="baseButton-primary"]:hover {{
            background: rgba(20, 184, 166, 0.24) !important;
            border-color: #2dd4bf !important;
            color: #99f6e4 !important;
            box-shadow: 0 0 0 1px rgba(45, 212, 191, 0.15) !important;
        }}
        div[data-testid="stDataFrame"] {{
            display: none !important;
        }}
        .section-card {{
            background: var(--bg-card);
            border-radius: 8px;
            padding: 0.85rem 1rem;
            margin-bottom: 0.85rem;
            box-shadow: inset 0 0 0 1px var(--border-subtle);
        }}
        .trend-tag {{
            display: inline-flex;
            align-items: center;
            gap: 0.35rem;
            padding: 0.35rem 0.65rem;
            border-radius: 999px;
            font-size: 0.78rem;
            font-weight: 600;
            letter-spacing: 0.01em;
            margin-bottom: 0.5rem;
        }}
        .trend-facts {{
            color: var(--text-muted);
            font-size: 0.8rem;
            line-height: 1.55;
            margin-top: 0.35rem;
        }}
        div[data-testid="stVerticalBlockBorderWrapper"] div[data-testid="stMarkdownContainer"] h3 {{
            font-size: 0.95rem !important;
            color: #e2e8f0 !important;
            margin: 0.65rem 0 0.35rem !important;
        }}
        div[data-testid="stVerticalBlockBorderWrapper"] div[data-testid="stMarkdownContainer"] h4 {{
            font-size: 0.88rem !important;
            color: var(--text-muted) !important;
            margin: 0.55rem 0 0.25rem !important;
        }}
        div[data-testid="stVerticalBlockBorderWrapper"] div[data-testid="stMarkdownContainer"] p,
        div[data-testid="stVerticalBlockBorderWrapper"] div[data-testid="stMarkdownContainer"] li {{
            color: #cbd5e1;
            font-size: 0.86rem;
            line-height: 1.65;
        }}
        div[data-testid="stVerticalBlockBorderWrapper"] div[data-testid="stMarkdownContainer"] strong {{
            color: #f1f5f9;
        }}
        div[data-testid="stVerticalBlockBorderWrapper"] div[data-testid="stMarkdownContainer"] blockquote {{
            border-left: 3px solid var(--accent);
            padding-left: 0.75rem;
            color: var(--text-muted);
            margin: 0.5rem 0;
        }}
        .panic-tag {{
            color: #f87171;
            font-weight: 700;
            font-size: 0.95rem;
        }}
        .panel-label {{
            color: #64748b;
            font-size: 0.72rem;
            text-transform: uppercase;
            letter-spacing: 0.06em;
            margin-bottom: 0.45rem;
        }}
        div[data-testid="stRadio"] > div {{
            gap: 0.45rem !important;
            flex-wrap: wrap;
            margin-bottom: 0.75rem;
        }}
        div[data-testid="stRadio"] label {{
            background: linear-gradient(160deg, #243044 0%, #1a2332 100%) !important;
            border-radius: 8px !important;
            padding: 0.4rem 0.8rem !important;
            border: 1px solid var(--border-subtle) !important;
            font-size: 0.85rem !important;
            margin-bottom: 0.35rem !important;
        }}
        hr {{
            margin: 1.5rem 0 !important;
            border-color: var(--border-subtle) !important;
        }}
        [data-testid="stExpander"] {{
            border: 1px solid var(--border-subtle) !important;
            border-radius: 8px !important;
            background: var(--bg-card) !important;
            margin-top: 1rem;
        }}
        [data-testid="stExpander"] details summary {{
            overflow: visible !important;
            align-items: center !important;
        }}
        [data-testid="stExpander"] details summary p {{
            margin: 0 !important;
            white-space: normal !important;
            overflow-wrap: anywhere !important;
            line-height: 1.4 !important;
        }}
        div[data-testid="stAlert"] {{
            border-radius: 8px !important;
            border: 1px solid var(--border-subtle) !important;
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def _score_tone(value: object) -> str:
    try:
        score = float(str(value).replace("🛡️", "").strip())
    except (TypeError, ValueError):
        return ""
    if score >= 85:
        return "tone-green"
    if score >= 70:
        return "tone-yellow"
    return "tone-red"


def _format_grade(report: object) -> str:
    """Derive grade from business quality score."""
    growth = is_growth_strategy(_report_strategy_mode(report))
    quality = _report_quality_score(report)
    emoji, label = grade_from_score(quality, growth=growth)
    return f"{emoji} {label}"


def _terminal_score_color(score: float | None) -> str:
    """Semantic terminal colors: >=85 green, 70–84 gray, <70 red."""
    if score is None:
        return "#94A3B8"
    try:
        v = float(score)
    except (TypeError, ValueError):
        return "#94A3B8"
    if v >= 85:
        return "#10B981"
    if v >= 70:
        return "#94A3B8"
    return "#EF4444"


def _score_detail_pair(report: object, *keywords: str) -> tuple[float | None, float | None]:
    """Return (earned, max_points) for first matching score_detail category."""
    details_raw = _rget(report, "score_details", None) or []
    for raw in details_raw:
        detail = _coerce_score_detail(raw)
        if detail.max_points <= 0:
            continue
        if any(k in detail.category for k in keywords):
            return detail.earned, detail.max_points
    return None, None


def _collect_death_penalty_messages(report: object) -> list[str]:
    """Detect asymmetric death penalties for fatal red-flag banners."""
    if is_growth_strategy(_report_strategy_mode(report)):
        return []

    messages: list[str] = []
    m = _report_master(report)

    nd_ebitda = _rget(m, "net_debt_ebitda")
    if nd_ebitda is not None and float(nd_ebitda) > NET_DEBT_EBITDA_DEATH_THRESHOLD:
        messages.append(
            f"🚨 致命紅旗警告：債務槓桿嚴重超標（淨債務/EBITDA {float(nd_ebitda):.1f}x > "
            f"{NET_DEBT_EBITDA_DEATH_THRESHOLD:.0f}x），觸發財務安全一票否決，"
            f"企業品質分強制封頂 {VALUE_SCORE_DEATH_CAP:.0f}。"
        )

    fcf_pay = _rget(m, "fcf_payout_ratio")
    if fcf_pay is not None and float(fcf_pay) > FCF_PAYOUT_DEATH_THRESHOLD:
        messages.append(
            f"🚨 致命紅旗警告：FCF 支付率 {float(fcf_pay) * 100:.1f}% 透支"
            f"（>{FCF_PAYOUT_DEATH_THRESHOLD * 100:.0f}%），觸發現金流一票否決，"
            f"該維度歸零並額外扣 {FCF_PAYOUT_EXTRA_PENALTY:.0f} 分。"
        )

    return messages


def _render_terminal_dual_scores(report: object) -> None:
    """Hero dual-track scores — Quality & Valuation (48px, semantic colors)."""
    quality = _report_quality_score(report)
    valuation = _report_valuation_score(report)
    q_color = _terminal_score_color(quality)
    v_color = _terminal_score_color(valuation)

    _render_html(
        f"""
        <div class="terminal-score-grid">
            <div class="terminal-score-card">
                <div class="terminal-score-label">企業品質分 · Quality</div>
                <div class="terminal-score-sublabel">Business Quality Score</div>
                <div class="terminal-score-value" style="color:{q_color};">{quality:.1f}</div>
                <div class="terminal-score-cap">滿分 100 · Red Team 封頂 95</div>
            </div>
            <div class="terminal-score-card">
                <div class="terminal-score-label">估值安全邊際 · Valuation</div>
                <div class="terminal-score-sublabel">Valuation Safety Score</div>
                <div class="terminal-score-value" style="color:{v_color};">{valuation:.1f}</div>
                <div class="terminal-score-cap">Forward P/E · PEG · FCF Yield</div>
            </div>
        </div>
        <div class="terminal-grade-strip">等級 {_format_grade(report)}</div>
        """
    )


def _render_death_penalty_banners(report: object) -> None:
    """Full-width fatal red-flag banners below hero scores."""
    for msg in _collect_death_penalty_messages(report):
        _render_html(f'<div class="death-penalty-banner">{html.escape(msg)}</div>')


def _render_value_dimension_grid(report: StockReport) -> None:
    """Four-column dimension grid — custom metric cards (avoids column clipping)."""
    dims: list[tuple[str, float, tuple[str, ...], str]] = [
        (
            f"企業品質 · {WEIGHT_VALUE_QUALITY:.0f}%",
            WEIGHT_VALUE_QUALITY,
            ("企業品質", "護城河"),
            SCORE_WEIGHT_TOOLTIPS_VALUE["企業品質與護城河"]
            + " 子指標：ROIC/ROA、毛利率波動、營業利益率。資料：SQLite cache · yfinance · SEC。",
        ),
        (
            f"財務安全 · {WEIGHT_VALUE_SAFETY:.0f}%",
            WEIGHT_VALUE_SAFETY,
            ("財務安全",),
            SCORE_WEIGHT_TOOLTIPS_VALUE["財務安全防線"]
            + " 子指標：Net Debt/EBITDA、利息保障倍數。死亡門檻：槓桿 >3x。",
        ),
        (
            f"現金流品質 · {WEIGHT_VALUE_CASHFLOW:.0f}%",
            WEIGHT_VALUE_CASHFLOW,
            ("現金流",),
            SCORE_WEIGHT_TOOLTIPS_VALUE["現金流品質"]
            + " 子指標：FCF 支付率、股息連續成長。死亡門檻：FCF Payout >90%。",
        ),
        (
            f"營收穩定 · {WEIGHT_VALUE_REVENUE:.0f}%",
            WEIGHT_VALUE_REVENUE,
            ("營收穩定",),
            SCORE_WEIGHT_TOOLTIPS_VALUE["營收穩定"]
            + " 子指標：5Y 營收 CAGR、TTM 營收增速。資料：年度財報 · yfinance。",
        ),
    ]

    items: list[tuple[str, str] | tuple[str, str, str] | tuple[str, str, str, str]] = []
    for label, max_pts, keys, help_text in dims:
        earned, _ = _score_detail_pair(report, *keys)
        earned = earned if earned is not None else 0.0
        items.append((label, f"{earned:.1f}", f"/ {max_pts:.0f} pts", help_text))
    _render_fx_metric_row(items)


def _render_growth_dimension_grid(report: StockReport) -> None:
    """Growth-mode four-column grid (30/25/25/15)."""
    dims: list[tuple[str, float, tuple[str, ...], str]] = [
        (
            f"基本面增長 · {WEIGHT_GROWTH_FUNDAMENTAL:.0f}%",
            WEIGHT_GROWTH_FUNDAMENTAL,
            ("基本面增長",),
            "營收成長 + CapEx 擴張率。資料：yfinance info · 季度現金流。",
        ),
        (
            f"預期修正 · {WEIGHT_GROWTH_SURPRISE:.0f}%",
            WEIGHT_GROWTH_SURPRISE,
            ("預期修正", "Surprise"),
            "EPS Surprise 連續超預期季數。資料：yfinance earnings_history。",
        ),
        (
            f"PEG 估值 · {WEIGHT_GROWTH_PEG_VAL:.0f}%",
            WEIGHT_GROWTH_PEG_VAL,
            ("PEG", "估值相對"),
            "Trailing PEG 相對成長估值剪刀差。資料：yfinance trailingPegRatio。",
        ),
        (
            f"Timing 輔助 · {WEIGHT_GROWTH_TECH_TIMING:.0f}%",
            WEIGHT_GROWTH_TECH_TIMING,
            ("Timing", "技術面輔助"),
            "SMA20/50 均線結構 — 僅作進場 Timing，不主導基本面決策。",
        ),
    ]

    items: list[tuple[str, str] | tuple[str, str, str] | tuple[str, str, str, str]] = []
    for label, max_pts, keys, help_text in dims:
        earned, _ = _score_detail_pair(report, *keys)
        earned = earned if earned is not None else 0.0
        items.append((label, f"{earned:.1f}", f"/ {max_pts:.0f} pts", help_text))
    _render_fx_metric_row(items)


def _render_dimension_grid(report: object) -> None:
    if is_growth_strategy(_report_strategy_mode(report)):
        _render_growth_dimension_grid(report)
    else:
        _render_value_dimension_grid(report)


def _valuation_trap_warning(report: object) -> bool:
    quality = _report_quality_score(report)
    val = _report_valuation_score(report)
    return quality >= 70 and val < 50


def _render_valuation_trap_alert(report: object) -> None:
    if not _valuation_trap_warning(report):
        return
    _render_html(
        '<div class="valuation-trap-alert">'
        "⚠️ 品質極優，但估值過高，注意安全邊際"
        "</div>"
    )


def _grade_tone(value: object) -> str:
    text = str(value)
    if "財務防禦確立" in text or "右側結構" in text:
        return "tone-green"
    if "體質穩健" in text or "動能蓄勢" in text:
        return "tone-yellow"
    return "tone-red"


def _metric_tooltip(label: str) -> str:
    return METRIC_TOOLTIPS.get(label, "")


def _scorecard_tooltip(dimension: str) -> str:
    for key, tip in SCORECARD_TOOLTIPS.items():
        if key in dimension:
            return tip
    return "機構級 1–10 分主觀量化維度，由 MASTER DATA FEED 驅動。"


def _scorecard_short_name(dimension: str) -> str:
    text = dimension
    if ". " in text:
        text = text.split(". ", 1)[1]
    if "(" in text:
        text = text.split("(", 1)[0].strip()
    return text


def _parse_metric_item(
    item: tuple[str, str] | tuple[str, str, str] | tuple[str, str, str, str],
) -> tuple[str, str, str, str]:
    label, value = item[0], item[1]
    subtext = ""
    tooltip = _metric_tooltip(label)
    if len(item) == 3:
        subtext = item[2]
    elif len(item) >= 4:
        subtext = item[2] or ""
        tooltip = item[3] or tooltip
    return label, value, subtext, tooltip


def _render_fx_metric_row(
    items: list[tuple[str, str] | tuple[str, str, str] | tuple[str, str, str, str]],
) -> None:
    """Render a row of gradient metric cards. Optional: subtext, tooltip (4th)."""
    if not items:
        return
    cols = st.columns(len(items))
    for col, item in zip(cols, items):
        label, value, subtext, tooltip = _parse_metric_item(item)
        tip_html = ""
        if tooltip:
            tip_html = (
                f'<span class="fx-metric-tip" data-tip="{html.escape(tooltip)}">?</span>'
            )
        sub_html = (
            f'<div class="fx-metric-subtext">{html.escape(subtext)}</div>'
            if subtext
            else ""
        )
        with col:
            _render_html(
                f"""
                <div class="fx-metric-card">
                    <div class="fx-metric-label">{html.escape(label)}{tip_html}</div>
                    <div class="fx-metric-value">{html.escape(str(value))}</div>
                    {sub_html}
                </div>
                """
            )


def _render_factor_glossary(mode: str | None = None) -> None:
    """Expandable institutional factor glossary for scoring transparency."""
    active = mode or _current_strategy_mode()
    tips = SCORE_WEIGHT_TOOLTIPS_GROWTH if is_growth_strategy(active) else SCORE_WEIGHT_TOOLTIPS_VALUE
    with st.expander("📊 量化因子方法論 · Factor Methodology"):
        for dim, desc in tips.items():
            _render_html(
                f'<p class="factor-glossary-item">'
                f'<span class="factor-glossary-dim">{html.escape(dim)}</span>'
                f'<span class="factor-glossary-desc">{html.escape(desc)}</span>'
                f"</p>"
            )
        st.caption("核心 Metric 卡片上的 ? 圖示可 hover 查看單項因子定義。")


def _sanitize_ai_commentary(raw: str) -> str:
    """Strip exposed Markdown headers/artifacts before terminal render."""
    text = _clean_ai_html(raw)
    filler_re = re.compile(
        r"^(好的[，,].*?|分析師報告如下[：:].*?|以下是.*?[：:].*?|"
        r"Sure[,.].*?|Here(?:'s| is).*?:)\s*\n?",
        flags=re.IGNORECASE | re.MULTILINE,
    )
    text = filler_re.sub("", text).strip()

    cleaned: list[str] = []
    for line in text.split("\n"):
        stripped = line.strip()
        if not stripped:
            cleaned.append("")
            continue
        if stripped.startswith("#"):
            stripped = re.sub(r"^#+\s*", "", stripped)
        stripped = stripped.replace("**", "")
        if stripped.startswith(">"):
            stripped = stripped.lstrip(">").strip()
        cleaned.append(stripped)
    return "\n".join(cleaned).strip()


def _render_fx_table_card(df: pd.DataFrame, *, title: str = "") -> None:
    """Render a dataframe as a custom HTML gradient table card."""
    if df.empty:
        st.caption("（無資料）")
        return

    headers = "".join(f"<th>{html.escape(str(col))}</th>" for col in df.columns)
    rows: list[str] = []
    for _, row in df.iterrows():
        cells: list[str] = []
        for col in df.columns:
            raw = row[col]
            val = html.escape(str(raw))
            tone = ""
            if col == "企業品質分":
                tone = _score_tone(raw)
            elif col == "估值安全分":
                tone = _score_tone(raw)
            elif col == "等級":
                tone = _grade_tone(raw)
            elif col in ("防禦模式得分",):
                tone = _score_tone(raw)
            elif col == "相對半年高點跌幅":
                tone = "tone-red"
            elif col == "最新財年 FCF" and str(raw).startswith("$"):
                tone = "tone-green"
            cls = f' class="{tone}"' if tone else ""
            cells.append(f"<td{cls}>{val}</td>")
        rows.append(f"<tr>{''.join(cells)}</tr>")

    title_html = (
        f'<div class="fx-table-title">{html.escape(title)}</div>' if title else ""
    )
    _render_html(
        f"""
        <div class="fx-table-card">
            {title_html}
            <div class="fx-table-wrap">
                <table class="fx-table">
                    <thead><tr>{headers}</tr></thead>
                    <tbody>{"".join(rows)}</tbody>
                </table>
            </div>
        </div>
        """
    )


def _render_ai_terminal_block(text: str | None) -> None:
    """Finance-terminal styled block for AI commentary — no raw Markdown headers."""
    safe = _safe_render_text(text)
    if not safe:
        if text and _is_llm_error_payload(text):
            st.error("目前 AI 伺服器擁擠，請稍後重試。")
        return
    clean = _sanitize_ai_commentary(safe)
    if not clean:
        return
    _render_html('<div class="ai-terminal-panel"></div>')
    _render_html(
        f'<div class="ai-terminal-body">{html.escape(clean).replace(chr(10), "<br>")}</div>'
    )


def _scorecard_tone(score: int) -> str:
    if score >= 8:
        return "score-high"
    if score >= 5:
        return "score-mid"
    return "score-low"


def _render_investment_scorecard(report: object) -> None:
    """Six-dimension Master Scorecard as a Fintech progress-bar grid (1–10)."""
    rows_raw = _rget(report, "investment_scorecard", None) or []
    if not rows_raw:
        return

    cards: list[str] = []
    for raw in rows_raw:
        if isinstance(raw, ScorecardItem):
            item = raw
        elif isinstance(raw, dict):
            item = _coerce_scorecard_item(raw)
        else:
            item = _coerce_scorecard_item(raw)

        rationale = _safe_render_text(item.rationale)
        if not rationale:
            continue

        tone = _scorecard_tone(item.score)
        pct = max(0, min(100, item.score * 10))
        short_name = _scorecard_short_name(item.dimension)
        if not short_name:
            continue
        tip = _scorecard_tooltip(item.dimension)
        tip_html = ""
        if tip:
            tip_html = (
                f'<span class="fx-metric-tip" data-tip="{html.escape(tip)}">?</span>'
            )
        cards.append(
            f"""
            <div class="scorecard-progress-card">
                <div class="scorecard-progress-header">
                    <div class="scorecard-progress-name">
                        {html.escape(short_name)}{tip_html}
                    </div>
                    <div class="scorecard-progress-score {tone}">{item.score}/10</div>
                </div>
                <div class="scorecard-progress-track">
                    <div class="scorecard-progress-fill {tone}" style="width:{pct}%;"></div>
                </div>
                <div class="scorecard-progress-rationale">{html.escape(rationale)}</div>
            </div>
            """
        )

    if not cards:
        return

    scorecard_html = (
        f"""
        <div class="scorecard-grid-title">
            Master Investment Scorecard · 大師級多空量化項目評價表
        </div>
        <div class="scorecard-progress-grid">
            {"".join(cards)}
        </div>
        """
    )
    clean_html = _HTML_FENCE_RE.sub("", scorecard_html).replace("```", "").strip()
    _render_html(clean_html)


def _render_deep_analysis_divider() -> None:
    """Visual separator between scan workspace and deep-dive analysis."""
    st.markdown(
        """
        <div class="section-divider">
            <span class="section-divider-label">深度研究區 · Deep Dive Workspace</span>
        </div>
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


def _format_summary_df(df: pd.DataFrame, *, score_columns: tuple[str, ...] | None = None) -> pd.DataFrame:
    display = df.copy()
    cols = score_columns or SCORE_COLUMNS_VALUE
    for col in cols:
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
            color = "#4ade80"
        elif v >= 70:
            color = "#facc15"
        else:
            color = "#f87171"
        return f"color: {color}; font-weight: 700; text-align: center;"

    def color_grade(val):
        text = str(val)
        if "財務防禦確立" in text or "右側結構" in text:
            color = "#4ade80"
        elif "體質穩健" in text or "動能蓄勢" in text:
            color = "#facc15"
        else:
            color = "#f87171"
        return f"color: {color}; font-weight: 600; text-align: center;"

    score_cols = [c for c in ("企業品質分", "估值安全分") if c in df.columns]
    styled = df.style
    for col in score_cols:
        styled = styled.map(color_score, subset=[col])
    styled = styled.map(color_grade, subset=["等級"])
    return styled.set_table_styles(
        [
            {
                "selector": "th",
                "props": [
                    ("background-color", "#1e293b"),
                    ("color", "#94a3b8"),
                    ("font-weight", "600"),
                    ("font-size", "0.82rem"),
                    ("border", "none"),
                    ("padding", "8px 12px"),
                ],
            },
            {
                "selector": "td",
                "props": [
                    ("text-align", "center"),
                    ("background-color", "#0f172a"),
                    ("color", "#e2e8f0"),
                    ("border", "none"),
                    ("padding", "8px 12px"),
                    ("font-size", "0.88rem"),
                ],
            },
            {"selector": "table", "props": [("border-collapse", "collapse")]},
        ]
    )


def _turnaround_to_dataframe(candidates: list[TurnaroundOpportunity]) -> pd.DataFrame:
    rows = []
    for c in candidates:
        rd = _fmt_money_large(c.rd_expense) if c.rd_expense else "—"
        coverage = (
            f"{c.interest_coverage:.1f}x" if c.interest_coverage is not None else "低負債"
        )
        nd_ebitda = (
            f"{c.net_debt_ebitda:.1f}x" if c.net_debt_ebitda is not None else "—"
        )
        if c.value_defense_score is not None:
            score_cell = f"{c.value_defense_score:.1f}"
            if c.value_defense_score >= 85:
                score_cell = f"🛡️ {score_cell}"
        else:
            score_cell = "—"
        if c.reason_tag:
            tag_cell = f"{c.reason_tag} {c.reason_comment}".strip()
        else:
            tag_cell = "—"
        peg_cell = f"{c.peg_ratio:.2f}" if c.peg_ratio is not None else "—"
        if c.price_vs_52w_high is not None:
            off_high = f"-{(1 - c.price_vs_52w_high) * 100:.1f}%"
        else:
            off_high = "—"
        if c.gross_margin is not None:
            margin = f"{c.gross_margin:.1f}%"
            if c.gross_margin_yoy_change_pp is not None:
                sign = "+" if c.gross_margin_yoy_change_pp >= 0 else ""
                margin += f"（YoY {sign}{c.gross_margin_yoy_change_pp:.1f}pp）"
        else:
            margin = "—"
        rows.append(
            {
                "代號": c.symbol,
                "公司名稱": c.company_name,
                "防禦模式得分": score_cell,
                "錯殺原因標籤": tag_cell,
                "相對半年高點跌幅": f"-{c.drawdown_pct:.1f}%",
                "距52週高點": off_high,
                "PEG": peg_cell,
                "最新財年 FCF": _fmt_money_large(c.latest_fcf),
                "淨債務/EBITDA": nd_ebitda,
                "利息保障倍數": coverage,
                "毛利率 (YoY)": margin,
                "研發費 (R&D)": rd,
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


@st.cache_data(ttl=3600, show_spinner=False)
def _validate_ticker_symbol(symbol: str) -> bool:
    """Return True if yfinance returns non-empty ~1M daily history for the symbol."""
    try:
        sym = symbol.upper().strip()
        if not sym:
            return False
        hist = yf.Ticker(sym).history(period="1mo", interval="1d")
        if hist is None or hist.empty:
            return False
        return True
    except Exception:
        return False


@st.cache_data(ttl=3600, show_spinner=False)
def load_report_for_symbol(strategy_mode: str, symbol: str) -> StockReport:
    """Per-symbol cache keyed by strategy_mode + symbol (strategy first for isolation)."""
    mode = normalize_strategy_mode(strategy_mode)
    return analyze_symbol(symbol.upper(), strategy_mode=mode)


@st.cache_data(ttl=3600, show_spinner="正在生成科技敘事…")
def load_company_narrative(strategy_mode: str, symbol: str) -> tuple[str, bool]:
    """Cache keyed by strategy_mode + symbol; returns (body, live_news_degraded)."""
    result = build_company_narrative(symbol.upper(), strategy_mode=strategy_mode)
    return result.text, result.live_news_degraded


def _init_session_state() -> None:
    if "analyzed_tickers" not in st.session_state:
        st.session_state.analyzed_tickers = []
    if WATCHLIST_INPUT_KEY not in st.session_state:
        st.session_state[WATCHLIST_INPUT_KEY] = ""
    if HUNTER_PRESET_KEY not in st.session_state:
        st.session_state[HUNTER_PRESET_KEY] = list(HUNTER_PRESET_OPTIONS.keys())[0]
    if HUNTER_CUSTOM_INPUT_KEY not in st.session_state:
        st.session_state[HUNTER_CUSTOM_INPUT_KEY] = DEFAULT_HUNTER_UNIVERSE
    if "hunter_results" not in st.session_state:
        st.session_state.hunter_results = []
    if "hunter_scanned_count" not in st.session_state:
        st.session_state.hunter_scanned_count = 0
    if "focus_ticker" not in st.session_state:
        st.session_state.focus_ticker = None
    if "scroll_to_analysis" not in st.session_state:
        st.session_state.scroll_to_analysis = False
    if GLOBAL_STRATEGY_KEY not in st.session_state:
        st.session_state[GLOBAL_STRATEGY_KEY] = STRATEGY_LABEL_VALUE
    if ACTIVE_STRATEGY_KEY not in st.session_state:
        st.session_state[ACTIVE_STRATEGY_KEY] = st.session_state[GLOBAL_STRATEGY_KEY]


def _unlock_ticker_for_analysis(symbol: str) -> None:
    st.session_state[ACTIVE_STRATEGY_KEY] = st.session_state.get(GLOBAL_STRATEGY_KEY, STRATEGY_LABEL_VALUE)
    sym = symbol.upper().strip()
    if not sym:
        return
    if sym not in st.session_state.analyzed_tickers:
        if not _validate_ticker_symbol(sym):
            st.error(f"⚠️ 找不到代碼 {sym} 或該代碼已下市，請確認後重新輸入。")
            return
        st.session_state.analyzed_tickers.append(sym)
    st.session_state.focus_ticker = sym
    st.session_state[COMPANY_TAB_KEY] = sym
    st.session_state.scroll_to_analysis = True
    st.rerun()


def _load_watchlist_tickers() -> None:
    """Parse watchlist input, validate tickers, append only valid symbols."""
    st.session_state[ACTIVE_STRATEGY_KEY] = st.session_state.get(GLOBAL_STRATEGY_KEY, STRATEGY_LABEL_VALUE)

    parsed = _parse_ticker_list(st.session_state.get(WATCHLIST_INPUT_KEY, ""))
    if not parsed:
        st.warning("請輸入至少一個有效股票代號（以逗號分隔）。")
        return

    to_validate = [sym for sym in parsed if sym not in st.session_state.analyzed_tickers]
    valid_new: list[str] = []
    invalid: list[str] = []

    for sym in to_validate:
        if _validate_ticker_symbol(sym):
            valid_new.append(sym)
        else:
            invalid.append(sym)

    for sym in invalid:
        st.error(f"⚠️ 找不到代碼 {sym} 或該代碼已下市，請確認後重新輸入。")

    if not valid_new:
        if not invalid and parsed:
            st.info("清單中的標的皆已在深度分析中。")
        return

    for sym in valid_new:
        st.session_state.analyzed_tickers.append(sym)

    st.session_state.focus_ticker = valid_new[0]
    st.session_state[COMPANY_TAB_KEY] = valid_new[0]
    st.session_state.scroll_to_analysis = True
    st.rerun()


def _build_reports_map(tickers: list[str]) -> dict[str, StockReport]:
    """Load cached per-symbol reports using active strategy from session state."""
    strategy_key = st.session_state.get(ACTIVE_STRATEGY_KEY, STRATEGY_LABEL_VALUE)
    reports: dict[str, StockReport] = {}
    for raw in tickers:
        sym = raw.upper().strip()
        if not sym:
            continue
        reports[sym] = _coerce_report(load_report_for_symbol(strategy_key, sym))
    return reports


@st.cache_data(ttl=86400, show_spinner="正在載入成分股清單…")
def _cached_index_constituents(index_key: str) -> tuple[tuple[str, ...], str]:
    """Cached Wikipedia index constituents; returns (tickers, source)."""
    tickers, source = fetch_index_constituents_safe(index_key)
    return tuple(tickers), source


def _resolve_hunter_universe() -> tuple[list[str], str, str]:
    """Resolve scan tickers — preset (Dow 30 / S&P 500) or advanced selectbox."""
    use_advanced = st.session_state.get("hunter_use_advanced", False)
    if not use_advanced:
        preset = st.session_state.get(
            HUNTER_PRESET_KEY, list(HUNTER_PRESET_OPTIONS.keys())[0]
        )
        index_key = HUNTER_PRESET_OPTIONS.get(preset, "dow30")
        tickers, source = _cached_index_constituents(index_key)
        return list(tickers), source, preset

    label = st.session_state.get(HUNTER_SCAN_UNIVERSE_KEY, SCAN_UNIVERSE_LABELS[0])
    index_key = SCAN_UNIVERSE_OPTIONS.get(label, "dow30")

    if index_key == "custom":
        parsed = _parse_ticker_list(st.session_state.get(HUNTER_CUSTOM_INPUT_KEY, ""))
        return parsed, "custom", label

    tickers, source = _cached_index_constituents(index_key)
    return list(tickers), source, label


@st.cache_data(ttl=900, show_spinner=False)
def _cached_trend_signal(symbol: str) -> dict | None:
    """Cached SMA trend lookup for turnaround radar tab."""
    return detect_trend_signals(symbol)


def _fmt_price(value: float | str | None) -> str:
    if value is None:
        return "N/A"
    try:
        return f"${float(value):.2f}"
    except (TypeError, ValueError):
        return "N/A"


def _render_trend_signal_block(trend: dict | None, *, growth_mode: bool = False) -> None:
    """Render compact right-side trend tag + price facts."""
    st.markdown('<p class="panel-label">右側動態趨勢</p>', unsafe_allow_html=True)

    if not trend:
        st.markdown(
            '<div class="section-card" style="color:#64748b;font-size:0.85rem;">'
            "趨勢數據不足，無法計算 SMA 20/50 交叉訊號。"
            "</div>",
            unsafe_allow_html=True,
        )
        return

    signal = str(trend.get("current_signal", "Hold"))
    try:
        price = float(trend.get("current_price", 0))
        sma_20 = float(trend.get("sma_20", 0))
        sma_50 = float(trend.get("sma_50", 0))
        bullish_breakout = price > sma_20 and price > sma_50
    except (TypeError, ValueError):
        bullish_breakout = False

    if growth_mode and bullish_breakout:
        border, bg, emoji, label = (
            "#14b8a6",
            "rgba(20, 184, 166, 0.10)",
            "📈",
            "價格站上中期均線群 · 右側結構確立",
        )
    else:
        border, bg, emoji, label = TREND_BADGE_STYLES.get(signal, TREND_BADGE_STYLES["Hold"])

    st.markdown(
        f"""
        <div class="trend-tag" style="background:{bg}; color:{border};
             box-shadow: inset 0 0 0 1px {border}33;">
          {emoji} {label}
        </div>
        """,
        unsafe_allow_html=True,
    )

    as_of = trend.get("as_of_date") or "—"
    st.markdown(
        f'<p class="trend-facts">'
        f"現價 <strong>{_fmt_price(trend.get('current_price'))}</strong> · "
        f"SMA20 <strong>{_fmt_price(trend.get('sma_20'))}</strong> · "
        f"SMA50 <strong>{_fmt_price(trend.get('sma_50'))}</strong><br>"
        f"截至 {as_of}</p>",
        unsafe_allow_html=True,
    )


def _chart_df_ready(df: pd.DataFrame | None, *required_columns: str) -> bool:
    if df is None or df.empty:
        return False
    return all(col in df.columns for col in required_columns)


def _render_chart_empty_notice(message: str) -> None:
    st.markdown(
        f'<div class="fx-chart-empty">{html.escape(message)}</div>',
        unsafe_allow_html=True,
    )


def _fcf_bar_chart(report: StockReport, *, height: int = 400) -> go.Figure | None:
    df = fcf_chart_df(report)
    if not _chart_df_ready(df, "Fiscal Year", "FCF (USD billions)"):
        return None

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
                name="FCF",
                marker_color=CHART_COLORS[0],
                text=labels,
                textposition="outside",
            )
        ]
    )
    fig.update_layout(
        title=dict(text="自由現金流 FCF", font=dict(size=13, color="#94a3b8")),
        xaxis_title="",
        yaxis_title=unit,
        template="plotly_dark",
        paper_bgcolor=TECH_DARK_CARD,
        plot_bgcolor=TECH_DARK_CARD,
        height=height,
        margin=dict(t=36, b=28, l=40, r=16),
        showlegend=False,
    )
    fig.update_xaxes(showgrid=False)
    fig.update_yaxes(gridcolor="#334155", zeroline=False)
    return fig


def _render_fcf_chart_section(report: StockReport, *, height: int = 240) -> None:
    fig = _fcf_bar_chart(report, height=height)
    if fig is None:
        _render_chart_empty_notice(
            "ℹ️ 無可用自由現金流 (FCF) 年度數據可供繪圖"
            "（可能上市年限較短、財報尚未揭露，或 SEC 資料缺失）。"
        )
        return
    st.plotly_chart(
        fig,
        use_container_width=True,
        key=f"fcf_{report.symbol}",
    )


def _dps_line_chart(report: StockReport, *, height: int = 400) -> go.Figure | None:
    df = dividend_chart_df(report)
    if not _chart_df_ready(df, "Year", "DPS (USD)"):
        return None

    fig = go.Figure(
        data=[
            go.Scatter(
                x=df["Year"],
                y=df["DPS (USD)"],
                mode="lines+markers",
                name="DPS",
                line=dict(color=CHART_COLORS[1], width=2.5),
                marker=dict(size=7),
                hovertemplate="%{x}<br>DPS: $%{y:.3f}<extra></extra>",
            )
        ]
    )
    fig.update_layout(
        title=dict(text="年度股息 DPS", font=dict(size=13, color="#94a3b8")),
        xaxis_title="",
        yaxis_title="DPS (USD)",
        template="plotly_dark",
        paper_bgcolor=TECH_DARK_CARD,
        plot_bgcolor=TECH_DARK_CARD,
        height=height,
        margin=dict(t=36, b=28, l=40, r=16),
        showlegend=False,
        xaxis=dict(dtick=1),
    )
    fig.update_xaxes(showgrid=False)
    fig.update_yaxes(gridcolor="#334155", zeroline=False)
    return fig


def _render_dps_chart_section(report: StockReport, *, height: int = 240) -> None:
    fig = _dps_line_chart(report, height=height)
    if fig is None:
        _render_chart_empty_notice(
            "ℹ️ 該標的歷史上未曾發放股息，無年度股息 (DPS) 數據可供繪圖。"
        )
        return
    st.plotly_chart(
        fig,
        use_container_width=True,
        key=f"dps_{report.symbol}",
    )


@st.cache_data(ttl=900, show_spinner=False)
def _fetch_market_history(
    symbol: str, interval: str, period: str
) -> pd.DataFrame | None:
    """Fetch OHLCV history for technical chart; returns None on any failure."""
    try:
        sym = symbol.upper().strip()
        hist = yf.Ticker(sym).history(period=period, interval=interval)
        if hist is None or hist.empty:
            return None
        cols = ["Open", "High", "Low", "Close"]
        if not all(c in hist.columns for c in cols):
            return None
        df = hist[cols].copy()
        if "Volume" in hist.columns:
            df["Volume"] = hist["Volume"]
        df = df.dropna(subset=["Close"])
        if df.empty:
            return None
        return df
    except Exception:
        return None


def _min_bars_for_indicators(indicators: list[str]) -> int:
    need = 1
    if "SMA 20/50" in indicators:
        need = max(need, TECH_SMA_LONG)
    if "EMA 12/26/9" in indicators:
        need = max(need, 26)
    if "布林通道 (Bollinger Bands)" in indicators:
        need = max(need, 20)
    return need


def _compute_chart_indicators(df: pd.DataFrame, indicators: list[str]) -> pd.DataFrame:
    out = df.copy()
    if "SMA 20/50" in indicators:
        out["SMA20"] = out["Close"].rolling(TECH_SMA_SHORT).mean()
        out["SMA50"] = out["Close"].rolling(TECH_SMA_LONG).mean()
    if "EMA 12/26/9" in indicators:
        out["EMA12"] = out["Close"].ewm(span=12, adjust=False).mean()
        out["EMA26"] = out["Close"].ewm(span=26, adjust=False).mean()
        out["EMA9"] = out["Close"].ewm(span=9, adjust=False).mean()
    if "布林通道 (Bollinger Bands)" in indicators:
        out["BB_MID"] = out["Close"].rolling(20).mean()
        bb_std = out["Close"].rolling(20).std()
        out["BB_UPPER"] = out["BB_MID"] + 2 * bb_std
        out["BB_LOWER"] = out["BB_MID"] - 2 * bb_std
    return out


def _drop_indicator_warmup(df: pd.DataFrame, indicators: list[str]) -> pd.DataFrame:
    subset = ["Close"]
    if "SMA 20/50" in indicators:
        subset.extend(["SMA20", "SMA50"])
    if "EMA 12/26/9" in indicators:
        subset.extend(["EMA12", "EMA26", "EMA9"])
    if "布林通道 (Bollinger Bands)" in indicators:
        subset.extend(["BB_MID", "BB_UPPER", "BB_LOWER"])
    existing = [c for c in subset if c in df.columns]
    if not existing:
        return df
    return df.dropna(subset=existing)


def _price_range_columns(df: pd.DataFrame, indicators: list[str]) -> list[str]:
    cols = ["Close"]
    if "SMA 20/50" in indicators:
        cols.extend(["SMA20", "SMA50"])
    if "EMA 12/26/9" in indicators:
        cols.extend(["EMA12", "EMA26", "EMA9"])
    if "布林通道 (Bollinger Bands)" in indicators:
        cols.extend(["BB_UPPER", "BB_LOWER", "BB_MID"])
    return [c for c in cols if c in df.columns]


def render_technical_chart(
    symbol: str,
    frequency: str = "日線 (Daily)",
    indicators: list[str] | None = None,
) -> go.Figure | None:
    """
    Close-price area chart with optional overlays and volume subplot.

    Supports daily / weekly / monthly intervals via yfinance, range selector
    (1M/3M/6M/YTD/1Y), and dynamic indicator toggles.
    """
    if indicators is None:
        indicators = ["SMA 20/50"]
    try:
        sym = symbol.upper().strip()
        interval, period = FREQ_YF_MAP.get(frequency, ("1d", "1y"))
        raw = _fetch_market_history(sym, interval, period)
        if raw is None or raw.empty:
            return None
        if len(raw) < _min_bars_for_indicators(indicators):
            return None

        df = _compute_chart_indicators(raw, indicators)
        df = _drop_indicator_warmup(df, indicators)
        if df.empty:
            return None

        end_dt = pd.Timestamp(df.index[-1])
        default_start = end_dt - pd.DateOffset(months=3)
        if default_start < pd.Timestamp(df.index[0]):
            default_start = pd.Timestamp(df.index[0])

        price_cols = _price_range_columns(df, indicators)
        y_min = float(df[price_cols].min().min()) * 0.95
        y_max = float(df[price_cols].max().max()) * 1.05

        show_volume = "成交量 (Volume)" in indicators and "Volume" in df.columns
        range_selector = dict(
            buttons=[
                dict(count=1, label="1M", step="month", stepmode="backward"),
                dict(count=3, label="3M", step="month", stepmode="backward"),
                dict(count=6, label="6M", step="month", stepmode="backward"),
                dict(step="year", stepmode="todate", label="YTD"),
                dict(step="all", label="1Y"),
            ],
            bgcolor=TECH_DARK_BG,
            activecolor="#475569",
            bordercolor="#64748b",
            borderwidth=1,
            font=dict(color="#e2e8f0", size=11),
            x=0,
            y=-0.2,
            xanchor="left",
            yanchor="top",
        )

        if show_volume:
            fig = make_subplots(
                rows=2,
                cols=1,
                shared_xaxes=True,
                vertical_spacing=0.04,
                row_heights=[0.72, 0.28],
                subplot_titles=("", ""),
            )
            price_row, vol_row = 1, 2
            chart_height = TECH_CHART_HEIGHT_VOL
        else:
            fig = go.Figure()
            price_row, vol_row = None, None
            chart_height = TECH_CHART_HEIGHT

        def _add_price_trace(trace: go.Scatter) -> None:
            if show_volume:
                fig.add_trace(trace, row=price_row, col=1)
            else:
                fig.add_trace(trace)

        _add_price_trace(
            go.Scatter(
                x=df.index,
                y=df["Close"],
                mode="lines",
                name="收盤價",
                line=dict(color=TECH_COLOR_CLOSE, width=2),
                fill="tozeroy",
                fillcolor=TECH_COLOR_CLOSE_FILL,
            )
        )

        if "SMA 20/50" in indicators:
            _add_price_trace(
                go.Scatter(
                    x=df.index,
                    y=df["SMA20"],
                    mode="lines",
                    name="SMA20",
                    line=dict(color=TECH_COLOR_SMA20, width=1.5),
                )
            )
            _add_price_trace(
                go.Scatter(
                    x=df.index,
                    y=df["SMA50"],
                    mode="lines",
                    name="SMA50",
                    line=dict(color=TECH_COLOR_SMA50, width=1.5),
                )
            )

        if "EMA 12/26/9" in indicators:
            _add_price_trace(
                go.Scatter(
                    x=df.index,
                    y=df["EMA12"],
                    mode="lines",
                    name="EMA12",
                    line=dict(color="rgba(96, 165, 250, 0.7)", width=1.5),
                )
            )
            _add_price_trace(
                go.Scatter(
                    x=df.index,
                    y=df["EMA26"],
                    mode="lines",
                    name="EMA26",
                    line=dict(color="rgba(167, 139, 250, 0.7)", width=1.5),
                )
            )
            _add_price_trace(
                go.Scatter(
                    x=df.index,
                    y=df["EMA9"],
                    mode="lines",
                    name="EMA9",
                    line=dict(color="rgba(52, 211, 153, 0.65)", width=1.5),
                )
            )

        if "布林通道 (Bollinger Bands)" in indicators:
            _add_price_trace(
                go.Scatter(
                    x=df.index,
                    y=df["BB_UPPER"],
                    mode="lines",
                    name="BB Upper",
                    line=dict(color="rgba(148, 163, 184, 0.45)", width=1, dash="dot"),
                )
            )
            _add_price_trace(
                go.Scatter(
                    x=df.index,
                    y=df["BB_LOWER"],
                    mode="lines",
                    name="BB Lower",
                    line=dict(color="rgba(148, 163, 184, 0.45)", width=1, dash="dot"),
                    fill="tonexty",
                    fillcolor="rgba(148, 163, 184, 0.08)",
                )
            )

        if show_volume:
            vol_colors = [
                "#22c55e" if row["Close"] >= row["Open"] else "#ef4444"
                for _, row in df.iterrows()
            ]
            fig.add_trace(
                go.Bar(
                    x=df.index,
                    y=df["Volume"],
                    name="Volume",
                    marker_color=vol_colors,
                    opacity=0.75,
                ),
                row=vol_row,
                col=1,
            )

        layout_kwargs = dict(
            template="plotly_dark",
            paper_bgcolor=TECH_DARK_BG,
            plot_bgcolor=TECH_DARK_BG,
            font=dict(color="#e2e8f0", size=12),
            hovermode="x unified",
            height=chart_height,
            margin=dict(t=20, b=60, l=40, r=40),
            legend=dict(
                orientation="h",
                yanchor="bottom",
                y=1.02,
                x=0,
                bgcolor="rgba(15, 23, 42, 0.4)",
            ),
        )
        if not show_volume:
            layout_kwargs["xaxis_rangeslider_visible"] = False

        fig.update_layout(**layout_kwargs)

        if show_volume:
            fig.update_yaxes(
                range=[y_min, y_max],
                showgrid=True,
                gridcolor="#334155",
                zeroline=False,
                title_text="Price",
                row=1,
                col=1,
            )
            fig.update_yaxes(
                showgrid=False,
                zeroline=False,
                title_text="Vol",
                row=2,
                col=1,
            )
            fig.update_xaxes(
                type="date",
                range=[default_start, end_dt],
                showgrid=False,
                zeroline=False,
                showticklabels=False,
                row=1,
                col=1,
            )
            fig.update_xaxes(
                type="date",
                range=[default_start, end_dt],
                showgrid=False,
                zeroline=False,
                showspikes=True,
                spikemode="across",
                spikesnap="cursor",
                spikecolor="#64748b",
                spikethickness=1,
                row=2,
                col=1,
            )
            fig.update_xaxes(rangeselector=range_selector, row=2, col=1)
        else:
            fig.update_layout(
                xaxis=dict(
                    type="date",
                    range=[default_start, end_dt],
                    rangeslider=dict(visible=False),
                    showgrid=False,
                    zeroline=False,
                    showspikes=True,
                    spikemode="across",
                    spikesnap="cursor",
                    spikecolor="#64748b",
                    spikethickness=1,
                ),
                yaxis=dict(
                    range=[y_min, y_max],
                    showgrid=True,
                    gridcolor="#334155",
                    zeroline=False,
                    title_text="Price (USD)",
                    showspikes=True,
                    spikemode="across",
                    spikesnap="cursor",
                    spikecolor="#64748b",
                    spikethickness=1,
                ),
            )
            fig.update_xaxes(rangeselector=range_selector)

        # Plotly.js renders literal "undefined" when title is explicitly null — strip it.
        fig.update_layout(title=dict(text=""))

        return fig
    except Exception:
        return None


def _display_technical_chart(symbol: str) -> None:
    """Chart controls + render block with safe fallback."""
    sym = symbol.upper()
    ctrl_freq, ctrl_ind = st.columns(2)
    with ctrl_freq:
        frequency = st.selectbox(
            "數據頻率",
            FREQ_OPTIONS,
            index=0,
            key=f"tech_freq_{sym}",
            label_visibility="visible",
        )
    with ctrl_ind:
        indicators = st.multiselect(
            "附加指標",
            INDICATOR_OPTIONS,
            default=["SMA 20/50"],
            key=f"tech_ind_{sym}",
        )

    freq_label = frequency.split("(")[0].strip()
    st.markdown(
        f'<p class="panel-label">📉 {sym} · {freq_label}技術線圖（預設近3個月）</p>',
        unsafe_allow_html=True,
    )
    fig = render_technical_chart(sym, frequency=frequency, indicators=indicators)
    ind_suffix = "_".join(i.split()[0] for i in indicators) or "base"
    if fig is not None:
        st.plotly_chart(
            fig,
            use_container_width=True,
            key=f"tech_{sym}_{frequency.split()[0]}_{ind_suffix}",
        )
    else:
        st.warning(
            f"暫時無法載入 **{sym}** 的技術線圖"
            f"（{frequency} · 指標：{', '.join(indicators) or '無'}）。"
            "可能為 API 限制、資料不足或該標的暫無行情。"
        )


def _render_watchlist_bar() -> None:
    """Top watchlist input — user-defined ticker universe."""
    with st.container(border=True):
        st.markdown('<p class="panel-label">自訂觀察清單</p>', unsafe_allow_html=True)
        col_input, col_btn = st.columns([4, 1])
        with col_input:
            st.text_input(
                "股票代號（逗號分隔）",
                placeholder="AAPL, MSFT, NVDA",
                key=WATCHLIST_INPUT_KEY,
                label_visibility="collapsed",
            )
        with col_btn:
            load_clicked = st.button(
                "載入深度分析",
                type="primary",
                use_container_width=True,
                key="watchlist_load_button",
            )
        if load_clicked:
            _load_watchlist_tickers()
        loaded = st.session_state.analyzed_tickers
        if loaded:
            st.caption(f"已載入 **{len(loaded)}** 檔：" + ", ".join(loaded))
        _render_strategy_control()


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


def _rget(obj: object, key: str, default: object = None) -> object:
    """Read ``key`` from either an object (attribute) or a dict uniformly.

    Tolerates None and missing keys/attributes, returning ``default``.
    """
    if obj is None:
        return default
    if isinstance(obj, dict):
        value = obj.get(key, default)
    else:
        value = getattr(obj, key, default)
    return default if value is None else value


def _report_strategy_mode(report: object) -> str:
    return str(_rget(report, "strategy_mode", STRATEGY_VALUE) or STRATEGY_VALUE)


def _report_quality_score(report: object) -> float:
    q = _rget(report, "business_quality_score", None)
    if q is None:
        q = _rget(report, "total_score", 0.0)
    try:
        return float(q or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _report_valuation_score(report: object) -> float:
    v = _rget(report, "valuation_safety_score", None)
    if v is None:
        v = _rget(report, "valuation_margin_score", 0.0)
    try:
        return float(v or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _report_master(report: object) -> MasterMetrics:
    raw = _rget(report, "master", None) or _rget(report, "master_metrics", None)
    return _coerce_master(raw)


def _coerce_master(raw: object) -> MasterMetrics:
    """Normalize a master-metrics payload (dict / object / None) into MasterMetrics."""
    if isinstance(raw, MasterMetrics):
        return raw
    if raw is None:
        return MasterMetrics()
    return MasterMetrics(
        peg_ratio=_rget(raw, "peg_ratio"),
        capex_growth=_rget(raw, "capex_growth"),
        capex_latest=_rget(raw, "capex_latest"),
        roe=_rget(raw, "roe"),
        roa=_rget(raw, "roa"),
        roic=_rget(raw, "roic"),
        gross_margins=_rget(raw, "gross_margins"),
        gross_margin_volatility=_rget(raw, "gross_margin_volatility"),
        interest_coverage=_rget(raw, "interest_coverage"),
        net_debt_ebitda=_rget(raw, "net_debt_ebitda"),
        fcf_payout_ratio=_rget(raw, "fcf_payout_ratio"),
        revenue_growth=_rget(raw, "revenue_growth"),
        revenue_cagr_5y=_rget(raw, "revenue_cagr_5y"),
        surprise_latest_pct=_rget(raw, "surprise_latest_pct"),
        surprise_beat_streak=_rget(raw, "surprise_beat_streak", 0),
        surprise_sample=_rget(raw, "surprise_sample", 0),
        surprise_beats=_rget(raw, "surprise_beats", 0),
        latest_quarter_label=str(_rget(raw, "latest_quarter_label", "")),
        yoy_quarter_label=str(_rget(raw, "yoy_quarter_label", "")),
        operating_margin_latest=_rget(raw, "operating_margin_latest"),
        operating_margin_yoy=_rget(raw, "operating_margin_yoy"),
        operating_margin_change_pp=_rget(raw, "operating_margin_change_pp"),
        operating_margin_red_flag=bool(_rget(raw, "operating_margin_red_flag", False)),
        operating_margin_red_flag_msg=str(_rget(raw, "operating_margin_red_flag_msg", "")),
        capex_red_flag=bool(_rget(raw, "capex_red_flag", False)),
        capex_red_flag_msg=str(_rget(raw, "capex_red_flag_msg", "")),
        ttm_operating_margin=_rget(raw, "ttm_operating_margin"),
        ttm_gross_margin=_rget(raw, "ttm_gross_margin"),
        ttm_revenue_growth=_rget(raw, "ttm_revenue_growth"),
        forward_pe=_rget(raw, "forward_pe"),
        fcf_yield=_rget(raw, "fcf_yield"),
        data_as_of=str(_rget(raw, "data_as_of", "")),
    )


def _coerce_scorecard_item(raw: object) -> ScorecardItem:
    if isinstance(raw, ScorecardItem):
        return raw
    try:
        score = int(_rget(raw, "score", 5) or 5)
    except (TypeError, ValueError):
        score = 5
    return ScorecardItem(
        dimension=str(_rget(raw, "dimension", "")),
        score=max(1, min(10, score)),
        rationale=str(_rget(raw, "rationale", "")),
    )


def _coerce_score_detail(raw: object) -> ScoreDetail:
    if isinstance(raw, ScoreDetail):
        return raw
    return ScoreDetail(
        category=str(_rget(raw, "category", "")),
        max_points=float(_rget(raw, "max_points", 0.0) or 0.0),
        earned=float(_rget(raw, "earned", 0.0) or 0.0),
        rationale=str(_rget(raw, "rationale", "")),
    )


def _coerce_year_fcf(raw: object) -> YearFCF:
    if isinstance(raw, YearFCF):
        return raw
    return YearFCF(
        fiscal_year=int(_rget(raw, "fiscal_year", 0) or 0),
        period_end=str(_rget(raw, "period_end", "")),
        free_cash_flow=float(_rget(raw, "free_cash_flow", 0.0) or 0.0),
        source=str(_rget(raw, "source", "")),
    )


def _coerce_year_div(raw: object) -> YearDividend:
    if isinstance(raw, YearDividend):
        return raw
    return YearDividend(
        calendar_year=int(_rget(raw, "calendar_year", 0) or 0),
        dividend_per_share=float(_rget(raw, "dividend_per_share", 0.0) or 0.0),
        yoy_growth=_rget(raw, "yoy_growth"),
    )


def _coerce_report(report: object) -> StockReport:
    """Accept a StockReport OR a dict and return a fully-typed StockReport.

    Guarantees attribute-style access for every downstream rendering helper
    (charts, AI commentary, tables) regardless of backend payload shape.
    """
    if isinstance(report, StockReport):
        return report
    if not isinstance(report, dict):
        # Unknown object that already supports attribute access — pass through.
        return report  # type: ignore[return-value]

    master = _coerce_master(report.get("master") or report.get("master_metrics"))
    details = [_coerce_score_detail(d) for d in (report.get("score_details") or [])]
    fcf_history = [_coerce_year_fcf(y) for y in (report.get("fcf_history") or [])]
    div_history = [_coerce_year_div(y) for y in (report.get("div_history") or [])]

    return StockReport(
        symbol=str(report.get("symbol") or ""),
        company_name=str(report.get("company_name") or ""),
        fcf_history=fcf_history,
        div_history=div_history,
        payout_ratio=report.get("payout_ratio"),
        beta=report.get("beta"),
        score_details=details,
        total_score=float(report.get("total_score", 0.0) or 0.0),
        business_quality_score=float(
            report.get("business_quality_score", report.get("total_score", 0.0)) or 0.0
        ),
        valuation_safety_score=float(
            report.get(
                "valuation_safety_score",
                report.get("valuation_margin_score", 0.0),
            )
            or 0.0
        ),
        grade_label=str(report.get("grade_label") or ""),
        grade_emoji=str(report.get("grade_emoji") or ""),
        analyst_commentary=str(report.get("analyst_commentary") or ""),
        fcf_pass=report.get("fcf_pass"),
        fcf_note=str(report.get("fcf_note") or ""),
        div_pass=report.get("div_pass"),
        div_note=str(report.get("div_note") or ""),
        trend_signal=report.get("trend_signal"),
        strategy_mode=str(report.get("strategy_mode") or STRATEGY_VALUE),
        master=master,
        investment_scorecard=[
            _coerce_scorecard_item(row)
            for row in (report.get("investment_scorecard") or [])
        ],
    )


def _render_master_metric_row(report: object) -> None:
    """Forward-looking master variables (PEG / CapEx / ROE / margin / surprise).

    Tolerates both StockReport objects and raw dict payloads.
    """
    m = _rget(report, "master", None)
    if m is None:
        m = _rget(report, "master_metrics", None)

    peg_v = _rget(m, "peg_ratio")
    capex_v = _rget(m, "capex_growth")
    cov_v = _rget(m, "interest_coverage")
    gross_v = _rget(m, "gross_margins")
    roe_v = _rget(m, "roe")
    surprise_pct = _rget(m, "surprise_latest_pct")
    surprise_streak = _rget(m, "surprise_beat_streak", 0)
    surprise_sample = _rget(m, "surprise_sample", 0)

    def _pct(v: object) -> str:
        return f"{float(v) * 100:.1f}%" if v is not None else "N/A"

    peg = f"{float(peg_v):.2f}" if peg_v is not None else "N/A"
    capex = f"{float(capex_v) * 100:+.1f}%" if capex_v is not None else "N/A"
    cov = f"{float(cov_v):.1f}x" if cov_v is not None else "低負債"
    if surprise_pct is not None:
        surprise_val = f"{float(surprise_pct):+.1f}%"
        surprise_sub = f"連續超預期 {surprise_streak} 季"
    elif surprise_sample:
        surprise_val = "—"
        surprise_sub = f"連續超預期 {surprise_streak} 季"
    else:
        surprise_val, surprise_sub = "N/A", "預期偏差數據不足"

    if is_growth_strategy(str(_rget(report, "strategy_mode", STRATEGY_VALUE))):
        items = [
            ("前瞻 PEG", peg, "成長/估值剪刀差"),
            ("CapEx 擴張率", capex, "季 YoY · 產業擴張領先"),
            ("毛利率", _pct(gross_v), "定價權 proxy"),
            ("近一季 Surprise", surprise_val, surprise_sub),
        ]
    else:
        roic_v = _rget(m, "roic")
        roe_v = _rget(m, "roe")
        fcf_pay_v = _rget(m, "fcf_payout_ratio")
        nd_ebitda_v = _rget(m, "net_debt_ebitda")
        rev_cagr_v = _rget(m, "revenue_cagr_5y")
        fpe_v = _rget(m, "forward_pe")
        fcf_y_v = _rget(m, "fcf_yield")
        items = [
            ("Forward P/E", f"{float(fpe_v):.1f}x" if fpe_v is not None else "N/A", "估值邊際核心"),
            ("PEG", peg, "成長/估值剪刀差"),
            ("FCF Yield", _pct(fcf_y_v), "FCF / 市值"),
            ("ROIC", _pct(roic_v) if roic_v is not None else _pct(roe_v), "資本回報 · 優先於 ROE"),
        ]
        items_extra = [
            ("FCF 支付率", _pct(fcf_pay_v), "股息 / 自由現金流"),
            ("淨債務/EBITDA", f"{float(nd_ebitda_v):.1f}x" if nd_ebitda_v is not None else "N/A", "槓桿安全線"),
            ("5Y 營收 CAGR", _pct(rev_cagr_v), "營收穩定底線"),
        ]
        _render_fx_metric_row(items)
        _render_fx_metric_row(items_extra)
        return


def _render_company_detail(report: StockReport) -> None:
    report = _coerce_report(report)
    mode_label = _strategy_label_for_mode(report.strategy_mode)
    st.markdown(
        f'<p class="subtitle" style="margin-bottom:0.35rem;">'
        f"{html.escape(report.symbol)} · {html.escape(report.company_name)}</p>",
        unsafe_allow_html=True,
    )
    st.markdown(f'<span class="strategy-badge">{html.escape(mode_label)}</span>', unsafe_allow_html=True)

    _render_terminal_dual_scores(report)
    _render_death_penalty_banners(report)
    _render_valuation_trap_alert(report)
    _render_dimension_grid(report)

    payout_cell = (
        f"{report.payout_ratio * 100:.1f}%"
        if report.payout_ratio is not None
        else "N/A"
    )
    beta_v = _fmt1(report.beta) if report.beta is not None else "N/A"
    nd = report.master.net_debt_ebitda
    nd_v = f"{nd:.1f}x" if nd is not None else "N/A"
    _render_fx_metric_row(
        [
            ("EPS 發放率", payout_cell, "", "Trailing payout ratio · yfinance info"),
            ("Beta", beta_v, "", "相對大盤波動係數 · 風險參考"),
            (
                "淨債務/EBITDA",
                nd_v,
                "",
                "槓桿安全線 · >3.0x 觸發死亡懲罰",
            ),
        ]
    )

    _render_master_metric_row(report)
    _render_factor_glossary(report.strategy_mode)

    chart_col, side_col = st.columns([0.67, 0.33], gap="medium")
    with chart_col:
        _display_technical_chart(report.symbol)
    with side_col:
        _render_trend_signal_block(
            report.trend_signal,
            growth_mode=is_growth_strategy(report.strategy_mode),
        )
        _render_narrative_card(report.symbol)
        _render_investment_scorecard(report)
        commentary = _safe_render_text(_rget(report, "analyst_commentary", None))
        if commentary:
            st.markdown('<p class="panel-label">AI 決策點評</p>', unsafe_allow_html=True)
            _render_ai_terminal_block(commentary)
        elif _is_llm_error_payload(_rget(report, "analyst_commentary", None)):
            st.markdown('<p class="panel-label">AI 決策點評</p>', unsafe_allow_html=True)
            st.error("目前 AI 伺服器擁擠，請稍後重試。")
        _render_fcf_chart_section(report, height=240)
        _render_dps_chart_section(report, height=240)

    with st.expander("原始數據與分項得分"):
        for d in report.score_details:
            if is_growth_strategy(report.strategy_mode) and d.max_points <= 0:
                st.caption(f"{d.category} — {d.rationale}")
                continue
            st.write(
                f"{d.category}：{_fmt1(d.earned)} / {_fmt1(d.max_points)} — {d.rationale}"
            )
        c1, c2 = st.columns(2)
        with c1:
            _render_fx_table_card(_format_fcf_table(report), title="FCF 原始數據")
        with c2:
            _render_fx_table_card(_format_dividend_table(report), title="股息原始數據")


def _scroll_to_analysis_section() -> None:
    """Smooth-scroll to company deep-analysis block after Hunter unlock."""
    components.html(
        """
        <script>
        (function () {
            const doc = window.parent.document;
            const nodes = doc.querySelectorAll('h2, h3, [data-testid="stMarkdownContainer"] p');
            for (const node of nodes) {
                const text = (node.textContent || '').trim();
                if (text.includes('公司深度分析')) {
                    node.scrollIntoView({ behavior: 'smooth', block: 'start' });
                    break;
                }
            }
        })();
        </script>
        """,
        height=0,
    )


def _render_core_scoring_tab() -> None:
    """Core financial scoring — summary for user-loaded watchlist."""
    tickers: list[str] = st.session_state.analyzed_tickers
    mode = _current_strategy_mode()
    weight_caption = _strategy_weight_caption(mode)
    st.markdown(
        f'<p class="subtitle">100 分制財務紀律評分 · {html.escape(weight_caption)}</p>',
        unsafe_allow_html=True,
    )
    _render_factor_glossary(mode)

    if not tickers:
        st.info("請從上方輸入股票代號並載入，或使用轉機雷達解鎖標的，以查看綜合摘要。")
        return

    by_symbol = _build_reports_map(tickers)
    reports = [_coerce_report(by_symbol[s]) for s in tickers if s in by_symbol]

    top = [r for r in reports if _report_quality_score(r) >= 85]
    val_traps = [r for r in reports if _valuation_trap_warning(r)]
    _render_fx_metric_row(
        [
            ("分析標的", str(len(reports))),
            ("高品質 (≥85)", str(len(top))),
            ("估值紅燈 (<50)", str(len(val_traps))),
            ("評分權重", _strategy_short_name(mode), weight_caption),
            (
                "均品質分",
                _fmt1(sum(_report_quality_score(r) for r in reports) / len(reports))
                if reports
                else "—",
            ),
        ]
    )

    summary_df = _format_summary_df(
        reports_to_summary_df(reports, strategy_mode=mode),
        score_columns=_score_columns_for_mode(mode),
    )
    st.markdown('<p class="panel-label">綜合摘要</p>', unsafe_allow_html=True)
    _render_fx_table_card(summary_df, title="Watchlist Summary")


def _render_company_deep_analysis() -> None:
    """Dynamic per-ticker view driven by session_state.analyzed_tickers."""
    tickers: list[str] = st.session_state.analyzed_tickers
    _render_deep_analysis_divider()
    st.markdown('<p class="panel-heading">公司深度分析</p>', unsafe_allow_html=True)
    st.caption(
        f"已解鎖 {len(tickers)} 檔 · 選擇標的切換（含從轉機雷達解鎖的新標的）"
    )

    if not tickers:
        st.info(
            "請從上方輸入股票代號，或使用轉機雷達進行掃描以載入深度分析。"
        )
        return

    if COMPANY_TAB_KEY not in st.session_state:
        st.session_state[COMPANY_TAB_KEY] = tickers[0]

    focus = st.session_state.get("focus_ticker")
    if focus and focus.upper() in [t.upper() for t in tickers]:
        st.session_state[COMPANY_TAB_KEY] = focus.upper()
        st.session_state.focus_ticker = None

    if st.session_state.get(COMPANY_TAB_KEY) not in tickers:
        st.session_state[COMPANY_TAB_KEY] = tickers[0]

    selected = st.radio(
        "選擇公司",
        options=tickers,
        horizontal=True,
        key=COMPANY_TAB_KEY,
        label_visibility="collapsed",
    )

    if st.session_state.pop("scroll_to_analysis", False):
        _scroll_to_analysis_section()

    by_symbol = _build_reports_map(tickers)
    report = by_symbol.get(selected.upper())
    if report is None:
        st.error(f"無法載入 {selected} 的財報資料。")
    else:
        _render_company_detail(report)


def _render_turnaround_hunter_tab() -> None:
    """Turnaround radar — index universes or custom list feed analyzed_tickers."""
    st.markdown(
        '<p class="panel-label" style="margin-top:0.25rem;">掃描工作區 · Reversal Scan Workspace</p>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<p class="subtitle">'
        "逆向價值投資閉環 · 雷達篩選 → 🛡️ 100分防禦評分 → Gemini 錯殺標籤"
        "</p>",
        unsafe_allow_html=True,
    )

    preset = st.radio(
        "掃描母體",
        list(HUNTER_PRESET_OPTIONS.keys()),
        horizontal=True,
        key=HUNTER_PRESET_KEY,
        help="S&P 500 完整掃描依賴 SQLite 本地快取以降低 API 阻斷風險。",
    )
    use_advanced = st.toggle("進階母體選項（Nasdaq 100 / 自訂）", key="hunter_use_advanced")

    _render_fx_metric_row(
        [
            ("價格濾網", "半年跌幅 > 15%", "Close > SMA20 右側確認"),
            ("估值濾網", "距52週高點 ≥25% 或 PEG<1.5", "錯殺確認"),
            ("防破產濾網", "淨債務/EBITDA < 3x", "FCF > 0 · 利息保障 > 3x"),
            ("防結構腐壞", "3Y 營收 CAGR > 0", "拒絕萎縮本業價值陷阱"),
            ("評分引擎", "🛡️ 100分防禦模式", "≥85 分優先排序"),
            ("上次命中", str(len(st.session_state.hunter_results))),
        ]
    )

    if use_advanced:
        st.markdown('<p class="panel-label">進階掃描母體 (Advanced Universe)</p>', unsafe_allow_html=True)
        selected_label = st.selectbox(
            "選擇掃描母體 (Scan Universe)",
            SCAN_UNIVERSE_LABELS,
            key=HUNTER_SCAN_UNIVERSE_KEY,
            label_visibility="collapsed",
        )
        index_key = SCAN_UNIVERSE_OPTIONS[selected_label]
        if index_key == "custom":
            st.text_area(
                "輸入股票代號（逗號或換行分隔）",
                height=120,
                placeholder="AAPL, MSFT, NVDA",
                help="僅在「自訂輸入」模式下使用。",
                key=HUNTER_CUSTOM_INPUT_KEY,
            )
    else:
        if preset == "S&P 500 (完整)":
            st.info(
                "⏱ S&P 500 完整掃描（六道濾網 + 防禦評分 + 錯殺標籤）"
                "依賴 SQLite 快取，約需 3–6 分鐘。"
            )
        else:
            st.caption("⏱ Dow 30 快速掃描，通常 30–90 秒完成（含防禦評分）。")

    parsed, source, _ = _resolve_hunter_universe()

    if use_advanced:
        index_key = SCAN_UNIVERSE_OPTIONS.get(
            st.session_state.get(HUNTER_SCAN_UNIVERSE_KEY, SCAN_UNIVERSE_LABELS[0]), "dow30"
        )
        if index_key == "custom":
            preview = ", ".join(parsed[:12]) + (" …" if len(parsed) > 12 else "")
            st.caption(
                f"已解析 {len(parsed)} 檔自訂標的："
                + (preview if parsed else "（無）")
            )
        elif source == "fallback":
            st.caption(
                f"已載入 {len(parsed)} 檔成分股 · 已啟用離線市值前 20 大備用清單"
            )
        else:
            st.caption(f"已載入 {len(parsed)} 檔成分股 · 來源：Wikipedia 最新成分股")
        if index_key == "sp500":
            st.info(
                "⏱ 標普 500 全市場 × 六道濾網（SQLite 快取加速）需時約 3–6 分鐘。"
            )
        elif index_key == "nasdaq100":
            st.caption("⏱ 掃描納斯達克 100（六道濾網 · SQLite 快取）約需 1–2 分鐘。")
        elif index_key == "dow30":
            st.caption("⏱ 道瓊 30 多濾網掃描，通常 30–60 秒 完成。")
    elif preset == "S&P 500 (完整)":
        st.caption(f"已載入 {len(parsed)} 檔 S&P 500 成分股 · SQLite 快取已啟用")
    else:
        st.caption(f"已載入 {len(parsed)} 檔 Dow 30 成分股")

    col_btn, col_hint = st.columns([1, 2])
    with col_btn:
        run_scan = st.button(
            "啟動大盤逆向掃描 (Initiate Reversal Scan)",
            type="primary",
            use_container_width=True,
            key="hunter_run_button",
        )
    with col_hint:
        st.info("偵探引擎會跳過數據缺失的個股，不會因單一 Ticker 失敗而中斷。")

    if run_scan:
        if not parsed:
            st.warning("請至少提供一個有效股票代號，或選擇可載入的指數成分股清單。")
        else:
            with st.spinner(
                f"偵探引擎正在掃描 {len(parsed)} 檔標的"
                "（六道濾網 → 🛡️ 防禦評分 → Gemini 錯殺標籤）…"
            ):
                st.session_state.hunter_results = find_turnaround_opportunities(parsed)
                st.session_state.hunter_scanned_count = len(parsed)

    results: list[TurnaroundOpportunity] = st.session_state.hunter_results

    st.markdown("---")
    st.subheader("轉機候選股結果")

    if not results:
        st.warning(
            "尚未命中，或尚未執行掃描。本雷達採六道機構級濾網"
            "（半年跌幅 > 15%、估值吸引力、FCF > 0、站上 SMA20、"
            "淨槓桿 < 3x、利息保障 > 3x），命中數偏少屬正常現象。"
        )
        return

    high_defense = sum(1 for r in results if (r.value_defense_score or 0) >= 85)
    st.success(
        f"從 {st.session_state.hunter_scanned_count} 檔標的中，"
        f"找到 {len(results)} 檔通過全部濾網的轉機候選"
        f"（其中 {high_defense} 檔防禦得分 ≥85，優先排序）。"
    )

    result_df = _turnaround_to_dataframe(results)
    _render_fx_table_card(result_df, title="Turnaround Candidates")

    st.markdown('<p class="panel-subheading">解鎖深度財報分析</p>', unsafe_allow_html=True)
    st.caption("點擊後將自動聚焦至下方「公司深度分析」並切換至該標的。")
    unlock_cols = st.columns(min(len(results), 4) or 1)
    for i, opp in enumerate(results):
        with unlock_cols[i % len(unlock_cols)]:
            if opp.symbol in st.session_state.analyzed_tickers:
                st.success(f"✓ {opp.symbol} 已解鎖")
            elif st.button(
                f"📊 解鎖 {opp.symbol} 深度財報圖表",
                key=f"unlock_{opp.symbol}",
                use_container_width=True,
            ):
                _unlock_ticker_for_analysis(opp.symbol)

    st.markdown('<p class="panel-subheading">個股快覽</p>', unsafe_allow_html=True)
    for opp in results:
        defense_line = ""
        if opp.value_defense_score is not None:
            emoji = opp.value_grade_emoji or ""
            defense_line = f"| 🛡️ {opp.value_defense_score:.1f}分 "
        tag_line = ""
        if opp.reason_tag:
            tag_line = f"| {opp.reason_tag} {opp.reason_comment or ''}"
        with st.expander(
            f"{opp.symbol} · {opp.company_name}  "
            f"|  -{opp.drawdown_pct:.1f}%  "
            f"{defense_line}"
            f"| FCF {_fmt_money_large(opp.latest_fcf)}"
            f"{tag_line}"
        ):
            if opp.value_defense_score is not None:
                st.markdown(
                    f"**🛡️ 價值防禦得分**：{opp.value_defense_score:.1f}/100 "
                    f"（{opp.value_grade_emoji or ''} {opp.value_grade_label or ''}）"
                )
            if opp.reason_tag:
                st.markdown(
                    f"**錯殺原因**：{opp.reason_tag} — {opp.reason_comment or ''}"
                )
            _render_trend_signal_block(_cached_trend_signal(opp.symbol))
            _render_fx_metric_row(
                [
                    ("相對半年高點跌幅", f"-{opp.drawdown_pct:.1f}%"),
                    ("距52週高點", (
                        f"-{(1 - opp.price_vs_52w_high) * 100:.1f}%"
                        if opp.price_vs_52w_high is not None else "—"
                    )),
                    ("PEG", f"{opp.peg_ratio:.2f}" if opp.peg_ratio is not None else "—"),
                    ("現價", f"${opp.current_price:.2f}"),
                    ("半年高點", f"${opp.six_month_high:.2f}"),
                    ("最新 FCF", _fmt_money_large(opp.latest_fcf)),
                ]
            )
            cov_value = (
                f"{opp.interest_coverage:.1f}x"
                if opp.interest_coverage is not None
                else "低負債結構"
            )
            if opp.gross_margin is not None:
                gm_value = f"{opp.gross_margin:.1f}%"
                gm_sub = (
                    f"YoY {'+' if (opp.gross_margin_yoy_change_pp or 0) >= 0 else ''}"
                    f"{opp.gross_margin_yoy_change_pp:.1f}pp"
                    if opp.gross_margin_yoy_change_pp is not None
                    else "YoY 數據不足"
                )
            else:
                gm_value, gm_sub = "—", "毛利率數據不足"
            _render_fx_metric_row(
                [
                    ("利息保障倍數", cov_value, "EBIT / 利息費用 · 門檻 > 3x"),
                    ("最新季毛利率", gm_value, gm_sub),
                    ("右側結構", "✅ 站上 SMA20", "已通過技術面右側濾網"),
                ]
            )
            if opp.rd_expense:
                st.markdown(
                    f"**科技新知儲備（R&D）**：{_fmt_money_large(opp.rd_expense)} "
                    f"（{opp.rd_fiscal_year}）"
                )
            st.caption(f"FCF 資料來源：{opp.fcf_source}")


def _render_sidebar() -> None:
    st.sidebar.header("量化評分標準")
    st.sidebar.markdown(
        """
        **Red Team Protocol · 雙軌計分（封頂 95）**
        - **企業品質分**：護城河 · 現金流 · 財務 · 營收
        - **估值安全分**：Forward P/E · PEG · FCF Yield
        - **<50 估值紅燈**：品質極優但估值過高

        **🛡️ 價值模式品質權重**：35/25/25/15 + 死亡懲罰

        **🚀 動能模式**：基本面30 + Surprise25 + PEG25 + Timing15 + 風險緩衝5

        **等級**：依企業品質分 · 紅隊 AI 強制【🩸漏洞審查】
        """
    )
    st.sidebar.header("逆向轉機股雷達")
    st.sidebar.markdown(
        """
        **七道濾網 + 防結構腐壞：**
        1. 半年跌幅 > 15% + Close > SMA20
        2. 估值吸引力（52週高點 / PEG）
        3. FCF > 0 · 淨槓桿 < 3x · 利息保障 > 3x
        4. 毛利率 YoY 穩定
        5. **3Y 營收 CAGR > 0** 或 **季毛利率 > 產業中位數/無結構崩塌**
        6. 🛡️ 100分防禦評分 · Gemini 錯殺標籤
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
    st.sidebar.markdown(
        f"**已載入深度分析**：{len(st.session_state.get('analyzed_tickers', []))} 檔"
    )
    st.sidebar.markdown("---")
    st.sidebar.markdown(
        """
        <div class="sidebar-lab-card">
            <div class="sidebar-lab-badge">COMING SOON</div>
            <div class="sidebar-lab-title">實驗性引擎：社會套利 (Social Sentiment Lab)</div>
            <p class="sidebar-lab-hint">TODO: 接入 Reddit / TikTok API</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.sidebar.button(
        "社會套利 · Social Sentiment Lab",
        disabled=True,
        help="TODO: 接入 Reddit / TikTok API — 模組二預留中",
        use_container_width=True,
        key="social_sentiment_lab_button",
    )
    if st.sidebar.button("清除快取資料"):
        load_report_for_symbol.clear()
        load_company_narrative.clear()
        clear_gemini_llm_cache()
        _validate_ticker_symbol.clear()
        _fetch_market_history.clear()
        _cached_index_constituents.clear()
        st.rerun()


def main() -> None:
    try:
        st.set_page_config(layout="wide")
    except Exception:
        pass  # full config already applied at import (before @st.cache_data)
    _inject_css()
    _init_session_state()

    main_container = st.container()
    with main_container:
        st.markdown(
            '<p class="main-title">股息安全 · 綜合分析儀表板</p>',
            unsafe_allow_html=True,
        )
        st.markdown(
            '<p class="subtitle">自訂觀察清單 · 100 分制財務評分 · 轉機股雷達 · 技術線圖</p>',
            unsafe_allow_html=True,
        )
        _render_watchlist_bar()

        tab_score, tab_hunter = st.tabs(
            [
                "📊 核心財務評分",
                "🛡️ 逆向轉機股雷達",
            ]
        )

        with tab_score:
            _render_core_scoring_tab()

        with tab_hunter:
            _render_turnaround_hunter_tab()

        _render_company_deep_analysis()

    _render_sidebar()


if __name__ == "__main__":
    main()
