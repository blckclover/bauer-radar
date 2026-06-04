"""LLM-based news filtering for System A (Macro Watcher)."""
from __future__ import annotations

import os
import re

from google import genai

from data_fetcher import NewsItem

FILTER_PROMPT = (
    "你是一個冷酷的量化投資資訊過濾器。請對以下新聞進行去噪，剔除所有煽動性形容詞與無關炒作（如虛擬貨幣）。"
    "只保留：1. 宏觀經濟核心事實（利率、就業、通膨等） "
    "2. 與個股 PFE, GIS, FLO, NOK, NVO 相關的具體事實。"
    "請用極簡短的中文列點輸出。若無重要變數，請輸出『今日無重要宏觀或個股變數』。"
)
MODEL_NAME = "gemini-2.5-flash"


def is_narrative_error_payload(text: str) -> bool:
    """檢查 LLM 回傳的字串是否為底層 API 的 JSON 錯誤代碼 (如 429 資源耗盡)"""
    if not text:
        return False
    upper_text = text.upper()
    if "RESOURCE_EXHAUSTED" in upper_text or "QUOTA EXCEEDED" in upper_text:
        return True
    if "429" in upper_text and "ERROR" in upper_text:
        return True
    if text.strip().startswith("{") and "'ERROR':" in upper_text:
        return True
    return False


GROWTH_LEXICON_CONSTRAINT = (
    "在生成技術面與資金面點評時，禁止使用「多頭雛形」「飆股」「爆發」「拉抬」「暴雷」"
    "等帶有散戶情緒或投顧色彩的廉價詞彙。"
    "請改用「右側動能結構」「中期均線支撐確立」「價格站上中期均線群」「資金向科技敘事流動」"
    "等機構級別、客觀、冷靜的金融語言。"
)

CAPEX_DIALECTIC_CONSTRAINT = (
    "當偵察到該公司的資本支出（CapEx YoY）大幅下滑時，AI 點評禁止單純將其解讀為利多或利空。"
    "必須客觀陳述雙面刃效應：一方面短期可美化並提升自由現金流（FCF Reality），"
    "另一方面代表公司正在縮減未來成長性投資，可能導致中長期科技敘事（Tech Narrative）失去動能。"
    "請用冰冷、中性的機構語言進行此項前瞻預期管理。"
)

GROWTH_ANALYST_SYSTEM_PROMPT = (
    "你是華爾街頂級做空機構的首席紅隊審查員（Short-Side Red Team Commander）。"
    "你的任務不是為高分找藉口，而是無情拆解財報與估值中最脆弱的環節。"
    "硬性規則："
    "1. [A] 季度 vs [B] TTM 絕對不可混淆；引用數字必須標明期間。"
    "2. 嚴禁對高分進行合理化包裝；若 Business Quality 高但 Valuation Safety <50，"
    "   必須優先攻擊「偉大公司買太貴」陷阱，質問當前價格已透支多少未來完美預期。"
    "3. CapEx 激增時必須質問：若投入無法轉化為毛利，估值面臨多大下修風險？"
    "4. 禁止客套、禁止散戶情緒詞、禁止 Markdown #/**；"
    f"5. {CAPEX_DIALECTIC_CONSTRAINT}"
    "6. 280–400 字；直接從第 1 點開始。"
    "僅輸出以下四段（標題完整保留）："
    "【部門拆解與 AI 轉型實質進展】："
    "冷靜拆解高增長 vs 衰退業務剪刀差；禁止行銷包裝。"
    "【核心催化劑與開牌時間表】："
    "未來 12 個月預期修正節點；若催化劑已被定價，必須點明。"
    "【🩸 紅隊漏洞審查 (Red Team Attack)】："
    "硬性列出 2–3 個最殘酷的證偽風險與質疑（估值透支、CapEx 轉換失敗、"
    "財報弱點或分析師下修）；每點須引用具體數字；禁止粉飾。"
    "【嚴格空頭風險與對手競爭防禦】："
    "至少 2 點最殘酷的空頭觀點。"
    f"{GROWTH_LEXICON_CONSTRAINT}"
)

VALUE_ANALYST_SYSTEM_PROMPT = (
    "你是華爾街頂級做空機構的首席紅隊審查員（Short-Side Red Team Commander）。"
    "你以 Graham/Buffett 框架審查，但核心任務是剝離「好公司」與「好價格」。"
    "硬性規則："
    "1. [A] 季度 vs [B] TTM 絕對不可混淆。"
    "2. ROIC 優先於 ROE；ROE 顯著高於 ROIC 必須點出槓桿假象。"
    "3. 嚴禁對高分合理化；Business Quality 高且 Valuation Safety <50 時，"
    "   必須亮紅燈：品質極優但估值過高，質問安全邊際何在。"
    "4. FCF 支付率 >90%、淨債務/EBITDA >3x、5Y 營收 CAGR 為負 → 必須點名價值陷阱。"
    f"5. {CAPEX_DIALECTIC_CONSTRAINT}"
    "6. 280–380 字；禁止客套與 Markdown #/**。"
    "僅輸出以下四段："
    "【ROIC 與真實護城河】：以 ROIC 判定資本配置；指出槓桿撐高 ROE 假象。"
    "【FCF 股息安全網】：FCF 支付率與裁息風險；禁止粉飾。"
    "【🩸 紅隊漏洞審查 (Red Team Attack)】："
    "硬性 2–3 個最殘酷證偽風險：估值透支（Forward P/E/PEG/FCF Yield）、"
    "CapEx 無法轉化毛利、衰退型價值陷阱或財報弱點；每點引用數字；禁止粉飾。"
    "【債務槓桿與衰退風險】：淨槓桿、利息保障、營收 CAGR；至少 2 點空頭觀點。"
    f"{GROWTH_LEXICON_CONSTRAINT}"
)

TURNAROUND_REASON_TAG_PROMPT = (
    "你是對沖基金量化分析師。根據最近新聞標題與跌幅數據，判斷該股大跌核心原因。"
    "嚴格歸類為以下三種標籤之一（必須完全一致，含方括號）："
    "[產業週期下行] · [短期利空/公關危機] · [成長放緩但護城河存]"
    "禁止 Markdown、禁止客套、禁止多於兩行。"
    "僅輸出："
    "TAG: <三選一標籤>"
    "COMMENT: <15字以內繁體中文短評>"
)

TURNAROUND_REASON_TAGS: tuple[str, ...] = (
    "[產業週期下行]",
    "[短期利空/公關危機]",
    "[成長放緩但護城河存]",
)

MASTER_SCORECARD_PROMPT = (
    "你是機構級量化評分引擎。根據提供的 MASTER DATA FEED，"
    "為以下六個維度各給 1–10 分（整數）及一行冰冷理由（≤40 字）。"
    "禁止行銷語言；理由必須引用具體數字或紅旗。"
    f"{CAPEX_DIALECTIC_CONSTRAINT}"
    "僅輸出以下區塊（不要其他任何文字）："
    "===SCORECARD==="
    "1. 財務安全 (Financial Runway)|<1-10>|<理由>"
    "2. 現金流健康度 (FCF Reality)|<1-10>|<理由>"
    "3. 核心成長性 (Growth Momentum)|<1-10>|<理由>"
    "4. 科技/AI 題材含金量 (Tech Narrative Catalyst)|<1-10>|<理由>"
    "5. 產業定價權與競爭優勢 (Moat Stability)|<1-10>|<理由>"
    "6. 前瞻估值吸引力 (Valuation Safety Margin)|<1-10>|<理由>"
    "===END==="
)

# Legacy alias
MASTER_ANALYST_SYSTEM_PROMPT = VALUE_ANALYST_SYSTEM_PROMPT

NARRATIVE_BUY_SIDE_ROLE = (
    "你是華爾街頂級對沖基金的資深研究員 (Buy-side Equity Analyst)。"
    "你的任務是撰寫精準、犀利且具備前瞻性的投資論述 (Investment Thesis)。"
    "嚴禁提供維基百科式的公司簡介，必須直接切入核心驅動力與風險。"
)

NARRATIVE_THESIS_STRUCTURE = (
    "【深度敘事結構 — 硬性規定】"
    "輸出必須且僅能包含以下三個 Markdown 標題區塊（標題逐字保留含 **，每段限 2-3 句話，禁止羅列廢話）："
    "**【🛡️ 商業模式與護城河】** (Business Model & Moat)："
    "公司真正賺錢的引擎是什麼？定價權是否穩固？面對 Private Label 或競爭對手的壓力如何？"
    "**【🔥 營運趨勢與利潤動能】** (Margin & Revenue Drivers)："
    "未來的成長是靠漲價、銷量、還是併購？毛利率是在擴張還是被通膨/競爭壓縮？"
    "**【⚡ 催化劑與多空情境】** (Catalysts & Bull/Bear Cases)："
    "未來半年有無改變股價的催化劑？"
    "Bull Case：錯殺反轉的理由；Bear Case：價值陷阱或成長透支的死法。"
    "禁止 # 標題與 ``` 程式碼區塊；禁止客套開場白；全文繁體中文，總字數 280–420 字。"
)

NARRATIVE_QUANT_GROUNDING_RULE = (
    "【量化錨定】必須引用使用者提供的「量化特徵」與 MASTER DATA 中的數字進行定性推論。"
    "若模式為價值防禦 (value)，側重現金流、配息安全、ROIC、估值邊際；"
    "若模式為動能成長 (growth)，側重 TAM、CapEx 轉換率、PEG 剪刀差、預期修正與技術催化。"
)

NARRATIVE_THESIS_SYSTEM_PROMPT = (
    f"{NARRATIVE_BUY_SIDE_ROLE}\n"
    f"{NARRATIVE_THESIS_STRUCTURE}\n"
    f"{NARRATIVE_QUANT_GROUNDING_RULE}"
)

NARRATIVE_GROWTH_LIVE_ADDENDUM = (
    "【成長模式增量指令】你已獲得官方摘要、過去兩週即時新聞、MASTER DATA 與技術面事實。"
    "在「催化劑與多空情境」段落必須融入至少一項可驗證的近期新聞或技術結構（禁止空泛預測）。"
    f"{GROWTH_LEXICON_CONSTRAINT}"
)

# Legacy aliases
NARRATIVE_SYSTEM_PROMPT = NARRATIVE_THESIS_SYSTEM_PROMPT
NARRATIVE_GROWTH_LIVE_PROMPT = f"{NARRATIVE_THESIS_SYSTEM_PROMPT}\n{NARRATIVE_GROWTH_LIVE_ADDENDUM}"


def _fmt_narrative_metric(value: float | None, *, as_pct: bool = False) -> str:
    if value is None:
        return "N/A"
    if as_pct:
        return f"{value * 100:.1f}%"
    return f"{value:.2f}"


def build_narrative_quant_context(
    *,
    strategy_mode: str = "value",
    revenue_cagr: float | None = None,
    gross_margin: float | None = None,
    fcf_yield: float | None = None,
    peg_ratio: float | None = None,
    forward_pe: float | None = None,
    payout_ratio: float | None = None,
    beta: float | None = None,
    business_quality_score: float | None = None,
    valuation_margin_score: float | None = None,
) -> str:
    """Compact quant block for narrative LLM grounding (avoids analyzer_core import cycle)."""
    mode_code = (strategy_mode or "value").strip().lower()
    if mode_code in ("growth", "momentum") or "成長" in strategy_mode or "動能" in strategy_mode:
        mode_label = "動能成長"
    else:
        mode_label = "價值防禦"

    payout_str = _fmt_narrative_metric(payout_ratio, as_pct=True) if payout_ratio is not None else "N/A"
    beta_str = _fmt_narrative_metric(beta)

    return (
        "【量化特徵 — Data-Driven Grounding】\n"
        f"請基於以下量化特徵進行定性分析：當前模式={mode_label} ({mode_code}), "
        f"營收成長(CAGR)={_fmt_narrative_metric(revenue_cagr, as_pct=True)}, "
        f"毛利率={_fmt_narrative_metric(gross_margin, as_pct=True)}, "
        f"FCF Yield={_fmt_narrative_metric(fcf_yield, as_pct=True)}, "
        f"PEG={_fmt_narrative_metric(peg_ratio)}, "
        f"估值(Forward P/E)={_fmt_narrative_metric(forward_pe)}, "
        f"配息發放率={payout_str}, Beta={beta_str}, "
        f"企業品質分={_fmt_narrative_metric(business_quality_score)}, "
        f"估值安全分={_fmt_narrative_metric(valuation_margin_score)}。\n"
        "若模式為『價值防禦』，請側重現金流與配息安全；若為『動能成長』，請側重 TAM 與資本支出轉換率。"
    )


def build_narrative_quant_context_from_report(report) -> str:
    """Build quant grounding from StockReport or dict-like session objects."""
    if not report:
        return ""
    mode = getattr(report, "strategy_mode", "value")
    master = getattr(report, "master", None)
    revenue_cagr = getattr(report, "revenue_cagr", None)
    if revenue_cagr is None and master is not None:
        revenue_cagr = getattr(master, "revenue_cagr_5y", None)
    gross_margin = None
    if master is not None:
        gross_margin = getattr(master, "ttm_gross_margin", None) or getattr(
            master, "gross_margins", None
        )
    fcf_yield = getattr(master, "fcf_yield", None) if master is not None else None
    peg_ratio = getattr(master, "peg_ratio", None) if master is not None else None
    forward_pe = getattr(master, "forward_pe", None) if master is not None else None
    return build_narrative_quant_context(
        strategy_mode=mode,
        revenue_cagr=revenue_cagr,
        gross_margin=gross_margin,
        fcf_yield=fcf_yield,
        peg_ratio=peg_ratio,
        forward_pe=forward_pe,
        payout_ratio=getattr(report, "payout_ratio", None),
        beta=getattr(report, "beta", None),
        business_quality_score=getattr(report, "business_quality_score", None)
        or getattr(report, "total_score", None),
        valuation_margin_score=getattr(report, "valuation_margin_score", None),
    )


def build_narrative_quant_context_from_master(
    strategy_mode: str,
    master,
    *,
    payout_ratio: float | None = None,
    beta: float | None = None,
) -> str:
    """Build quant block when only MasterMetrics + mode are available (narrative-only fetch path)."""
    if master is None:
        return build_narrative_quant_context(strategy_mode=strategy_mode)
    return build_narrative_quant_context(
        strategy_mode=strategy_mode,
        revenue_cagr=getattr(master, "revenue_cagr_5y", None),
        gross_margin=getattr(master, "ttm_gross_margin", None)
        or getattr(master, "gross_margins", None),
        fcf_yield=getattr(master, "fcf_yield", None),
        peg_ratio=getattr(master, "peg_ratio", None),
        forward_pe=getattr(master, "forward_pe", None),
        payout_ratio=payout_ratio,
        beta=beta,
    )


def _format_news_list(news_list: list[NewsItem]) -> str:
    """Convert news items into a readable plain-text block."""
    if not news_list:
        return "No news items available. The RSS feed could not be retrieved."

    lines: list[str] = []
    for index, item in enumerate(news_list, start=1):
        lines.append(f"{index}. {item['title']}")
        lines.append(f"   Published: {item['published']}")
    return "\n".join(lines)


def crush_and_filter_news(news_list: list[NewsItem]) -> str:
    """Filter RSS headlines via Gemini; fall back to raw formatted text on failure."""
    raw_text = _format_news_list(news_list)

    api_key = os.environ.get("GEMINI_API_KEY")
    if api_key is None:
        print("Warning: GEMINI_API_KEY is not set. Returning raw news without LLM filtering.")
        return raw_text

    try:
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model=MODEL_NAME,
            contents=f"{FILTER_PROMPT}\n\n{raw_text}",
        )
        filtered_text = (response.text or "").strip()
        if not filtered_text:
            raise ValueError("Gemini returned an empty response.")
        return filtered_text
    except Exception as exc:
        print(f"Warning: Gemini API call failed ({exc}). Returning raw news.")
        return raw_text


def _build_narrative_user_block(
    symbol: str,
    business_summary: str,
    sector: str = "",
    industry: str = "",
    *,
    quant_context: str = "",
    master_text: str = "",
    live_news_text: str = "",
    trend_context: str = "",
) -> str:
    context_parts = [f"Ticker: {symbol.upper()}"]
    if sector:
        context_parts.append(f"Sector: {sector}")
    if industry:
        context_parts.append(f"Industry: {industry}")
    if quant_context.strip():
        context_parts.append(f"\n{quant_context.strip()}")
    if master_text.strip():
        context_parts.append(f"\n{master_text.strip()}")
    context_parts.append(
        f"\n【官方業務摘要 longBusinessSummary — 僅供事實錨定，禁止逐句改寫為百科介紹】\n"
        f"{business_summary.strip()}"
    )
    if live_news_text.strip():
        context_parts.append(f"\n【過去兩週即時市場與技術新聞】\n{live_news_text.strip()}")
    if trend_context.strip():
        context_parts.append(f"\n{trend_context.strip()}")
    return "\n".join(context_parts)


def generate_company_narrative_text(
    symbol: str,
    business_summary: str,
    sector: str = "",
    industry: str = "",
    *,
    strategy_mode: str = "value",
    quant_context: str = "",
    master_text: str = "",
) -> str:
    """Buy-side investment thesis from summary + quant grounding."""
    if not quant_context.strip():
        quant_context = build_narrative_quant_context(strategy_mode=strategy_mode)
    user_block = _build_narrative_user_block(
        symbol,
        business_summary,
        sector,
        industry,
        quant_context=quant_context,
        master_text=master_text,
    )

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return "⚠️ 未設定 GEMINI_API_KEY，無法生成科技敘事。請在環境變數中設定後重新整理。"

    try:
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model=MODEL_NAME,
            contents=f"{NARRATIVE_THESIS_SYSTEM_PROMPT}\n\n{user_block}",
        )
        text = (response.text or "").strip()
        if not text:
            raise ValueError("Gemini returned an empty narrative.")
        if is_narrative_error_payload(text):
            return ""
        return text
    except Exception:
        return ""


def _format_trend_context(trend_signal: dict | None) -> str:
    if not trend_signal:
        return "Technical trend: unavailable."
    try:
        price = float(trend_signal.get("current_price", 0))
        sma_20 = float(trend_signal.get("sma_20", 0))
        sma_50 = float(trend_signal.get("sma_50", 0))
        above_both = price > sma_20 and price > sma_50
    except (TypeError, ValueError):
        above_both = False
    lines = [
        "Technical trend facts:",
        f"- Signal: {trend_signal.get('current_signal')}",
        f"- Close: {trend_signal.get('current_price')}",
        f"- SMA20: {trend_signal.get('sma_20')}",
        f"- SMA50: {trend_signal.get('sma_50')}",
        f"- Price above BOTH SMA20 & SMA50: {above_both}",
        f"- As of: {trend_signal.get('as_of_date')}",
    ]
    if above_both:
        lines.append(
            "- Note: 價格已站上中期均線群，呈現右側打底結構（右側結構確立，禁用「突破」等通俗詞）。"
        )
    lines.append(f"- Lexicon: {GROWTH_LEXICON_CONSTRAINT}")
    return "\n".join(lines)


def generate_growth_narrative_text(
    symbol: str,
    business_summary: str,
    sector: str = "",
    industry: str = "",
    *,
    strategy_mode: str = "growth",
    quant_context: str = "",
    live_news_text: str = "",
    trend_signal: dict | None = None,
    master_text: str = "",
) -> str:
    """Growth-mode investment thesis: summary + live news + master metrics + technical catalyst."""
    if not quant_context.strip():
        quant_context = build_narrative_quant_context(strategy_mode=strategy_mode)
    news_block = live_news_text.strip()
    if not news_block:
        news_block = "（即時新聞流暫不可用，請僅依靜態摘要、量化特徵與技術面推論。）"
    user_block = _build_narrative_user_block(
        symbol,
        (business_summary or "（無）").strip(),
        sector,
        industry,
        quant_context=quant_context,
        master_text=master_text,
        live_news_text=news_block,
        trend_context=_format_trend_context(trend_signal),
    )

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return "⚠️ 未設定 GEMINI_API_KEY，無法生成科技敘事。請在環境變數中設定後重新整理。"

    try:
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model=MODEL_NAME,
            contents=f"{NARRATIVE_GROWTH_LIVE_PROMPT}\n\n{user_block}",
        )
        text = (response.text or "").strip()
        if not text:
            raise ValueError("Gemini returned an empty narrative.")
        if is_narrative_error_payload(text):
            return ""
        return text
    except Exception:
        return ""


def _call_gemini(system_prompt: str, context: str) -> str | None:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return None
    try:
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model=MODEL_NAME,
            contents=f"{system_prompt}\n\n{context.strip()}",
        )
        text = (response.text or "").strip()
        return text or None
    except Exception:
        return None


def generate_growth_analyst_commentary(context: str) -> str | None:
    """Growth-mode bull/bear institutional commentary."""
    return _call_gemini(GROWTH_ANALYST_SYSTEM_PROMPT, context)


def generate_value_analyst_commentary(context: str) -> str | None:
    """Value-mode moat / catalyst / bear-risk commentary."""
    return _call_gemini(VALUE_ANALYST_SYSTEM_PROMPT, context)


def generate_master_analyst_commentary(context: str) -> str | None:
    """Backward-compatible — defaults to value prompt."""
    return generate_value_analyst_commentary(context)


def _parse_scorecard_block(text: str) -> list[dict[str, object]] | None:
    """Parse ===SCORECARD=== ... ===END=== block into row dicts."""
    import re

    if not text:
        return None
    match = re.search(r"===SCORECARD===(.*?)===END===", text, re.DOTALL | re.IGNORECASE)
    if not match:
        return None
    body = match.group(1).strip()
    rows: list[dict[str, object]] = []
    for line in body.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("|", 2)
        if len(parts) < 3:
            continue
        dim, score_raw, rationale = parts[0].strip(), parts[1].strip(), parts[2].strip()
        try:
            score = int(re.sub(r"[^\d]", "", score_raw))
        except ValueError:
            continue
        score = max(1, min(10, score))
        rows.append({"dimension": dim, "score": score, "rationale": rationale})
    return rows if len(rows) >= 4 else None


def generate_investment_scorecard(context: str, *, growth: bool = False) -> list[dict[str, object]] | None:
    """Return six-dimension Master Investment Scorecard rows (1–10 each)."""
    raw = _call_gemini(MASTER_SCORECARD_PROMPT, context)
    if not raw:
        return None
    return _parse_scorecard_block(raw)


def _parse_turnaround_reason_tag(text: str) -> tuple[str, str] | None:
    import re

    if not text:
        return None
    tag_match = re.search(
        r"TAG:\s*(\[[^\]]+\])",
        text,
        re.IGNORECASE,
    )
    comment_match = re.search(
        r"COMMENT:\s*(.+)",
        text,
        re.IGNORECASE,
    )
    if not tag_match:
        return None
    tag = tag_match.group(1).strip()
    if tag not in TURNAROUND_REASON_TAGS:
        for candidate in TURNAROUND_REASON_TAGS:
            if candidate in tag or candidate in text:
                tag = candidate
                break
        else:
            return None
    comment = comment_match.group(1).strip() if comment_match else ""
    comment = comment.replace("**", "").replace("#", "").strip()
    if len(comment) > 15:
        comment = comment[:15]
    return tag, comment


def _fallback_turnaround_reason_tag(context: str) -> tuple[str, str]:
    """Heuristic tag when Gemini is unavailable."""
    blob = context.lower()
    if any(k in blob for k in ("訴訟", "scandal", "召回", "調查", "裁員", "layoff", "probe")):
        return "[短期利空/公關危機]", "突發事件衝擊情緒"
    if any(k in blob for k in ("recession", "cycle", "demand", "週期", "景氣", "庫存")):
        return "[產業週期下行]", "景氣循環壓抑估值"
    return "[成長放緩但護城河存]", "成長放緩錯殺"


def generate_turnaround_reason_tag(context: str) -> tuple[str, str]:
    """
    Classify mispricing reason into one of three institutional tags.

    Returns (tag, comment≤15 chars). Never raises.
    """
    raw = _call_gemini(TURNAROUND_REASON_TAG_PROMPT, context)
    if raw:
        parsed = _parse_turnaround_reason_tag(raw)
        if parsed:
            return parsed
    return _fallback_turnaround_reason_tag(context)
