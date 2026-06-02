"""LLM-based news filtering for System A (Macro Watcher)."""
from __future__ import annotations

import logging
import os
import re
import time

from google import genai

from data_fetcher import NewsItem

logger = logging.getLogger(__name__)

_HTML_FENCE_RE = re.compile(r"```(?:html)?\n?", re.IGNORECASE)
_LLM_ERROR_MARKERS = (
    "429",
    "resource_exhausted",
    "rate limit",
    "too many requests",
    "quota exceeded",
    "科技敘事生成失敗",
    "生成失敗",
)


def _strip_llm_fences(text: str) -> str:
    return _HTML_FENCE_RE.sub("", text or "").replace("```", "").strip()


def is_poisoned_llm_output(text: str | None) -> bool:
    """True when text looks like an API failure — must not be cached or rendered."""
    if text is None:
        return True
    raw = str(text).strip()
    if not raw:
        return True
    if raw.startswith("⚠️"):
        return True
    lower = raw.lower()
    if any(marker in lower or marker in raw for marker in _LLM_ERROR_MARKERS):
        return True
    return False


def accept_llm_cache_result(text: str | None) -> str | None:
    """Return sanitized LLM text safe to cache, or None to avoid cache poisoning."""
    if is_poisoned_llm_output(text):
        return None
    cleaned = _strip_llm_fences(str(text).strip())
    return cleaned or None

FILTER_PROMPT = (
    "你是一個冷酷的量化投資資訊過濾器。請對以下新聞進行去噪，剔除所有煽動性形容詞與無關炒作（如虛擬貨幣）。"
    "只保留：1. 宏觀經濟核心事實（利率、就業、通膨等） "
    "2. 與個股 PFE, GIS, FLO, NOK, NVO 相關的具體事實。"
    "請用極簡短的中文列點輸出。若無重要變數，請輸出『今日無重要宏觀或個股變數』。"
)
MODEL_NAME = "gemini-2.5-flash"
_GEMINI_MAX_RETRIES = 3
_GEMINI_RETRY_SLEEP_SEC = 10


def _is_rate_limit_error(exc: BaseException) -> bool:
    msg = str(exc).lower()
    return any(
        token in msg
        for token in ("429", "rate limit", "resource_exhausted", "quota", "too many requests")
    )


def _generate_content_with_backoff(client: genai.Client, *, model: str, contents: str) -> str:
    """Call Gemini with exponential-style backoff on 429 / transient failures."""
    last_exc: Exception | None = None
    for attempt in range(1, _GEMINI_MAX_RETRIES + 1):
        try:
            response = client.models.generate_content(model=model, contents=contents)
            text = (response.text or "").strip()
            if not text:
                raise ValueError("Gemini returned an empty response.")
            return text
        except Exception as exc:
            last_exc = exc
            kind = "429/rate-limit" if _is_rate_limit_error(exc) else "API"
            logger.warning(
                "Gemini %s error (attempt %d/%d): %s",
                kind,
                attempt,
                _GEMINI_MAX_RETRIES,
                exc,
            )
            print(
                f"Warning: Gemini {kind} error (attempt {attempt}/{_GEMINI_MAX_RETRIES}): {exc}"
            )
            if attempt < _GEMINI_MAX_RETRIES:
                time.sleep(_GEMINI_RETRY_SLEEP_SEC)
    if last_exc is not None:
        raise last_exc
    raise RuntimeError("Gemini API failed after retries")


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
    "Red Team Protocol：禁止為高分找藉口，專責證偽與拆穿估值泡沫。"
    "硬性規則："
    "1. [A] 季度 vs [B] TTM 絕對不可混淆；引用數字必須標明期間。"
    "2. 嚴禁合理化包裝；Business Quality 高但 Valuation Safety <50 時，"
    "   必須優先攻擊「偉大公司買太貴」陷阱。"
    "3. CapEx 激增必須質問：若無法轉化為毛利，估值下修風險多大？"
    "4. 禁止客套、禁止散戶情緒詞、禁止 Markdown #/**；"
    f"5. {CAPEX_DIALECTIC_CONSTRAINT}"
    "6. 250–380 字；直接從第 1 點開始。"
    "僅輸出以下四段（標題完整保留）："
    "【部門拆解與 AI 轉型實質進展】：冷靜拆解剪刀差，禁止行銷。"
    "【核心催化劑與開牌時間表】：若催化劑已被定價，必須點明。"
    "【🩸 紅隊漏洞審查 (Red Team Attack)】："
    "硬性 2–3 點最殘酷證偽：估值透支、CapEx 轉換失敗、競爭/定價權流失；"
    "每點須引用具體數字，禁止粉飾。"
    "【嚴格空頭風險與對手競爭防禦】：至少 2 點空頭觀點。"
    f"{GROWTH_LEXICON_CONSTRAINT}"
)

VALUE_ANALYST_SYSTEM_PROMPT = (
    "你是華爾街頂級做空機構的首席紅隊審查員（Short-Side Red Team Commander）。"
    "Red Team Protocol：剝離「好公司」與「好價格」，禁止啦啦隊式分析。"
    "硬性規則："
    "1. [A] 季度 vs [B] TTM 絕對不可混淆。"
    "2. ROIC 優先於 ROE；槓桿撐高 ROE 必須點破。"
    "3. Business Quality 高但 Valuation Safety <50 → 必須亮紅燈攻擊估值。"
    "4. FCF 支付率 >90%、淨債務/EBITDA >3x、營收衰退 → 點名價值陷阱。"
    f"5. {CAPEX_DIALECTIC_CONSTRAINT}"
    "6. 250–360 字；禁止客套與 Markdown #/**。"
    "僅輸出以下四段："
    "【ROIC 與真實護城河】：資本配置效率；禁止粉飾。"
    "【FCF 股息安全網】：裁息風險；禁止粉飾。"
    "【🩸 紅隊漏洞審查 (Red Team Attack)】："
    "硬性 2–3 點：Forward P/E/PEG/FCF Yield 透支、CapEx 轉毛利失敗、"
    "衰退型陷阱；每點引用數字。"
    "【債務槓桿與衰退風險】：至少 2 點空頭觀點。"
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

NARRATIVE_GROWTH_LIVE_PROMPT = (
    "你現在是矽谷頂級科技風投 (VC) 兼對沖基金的首席產業分析師。"
    "你手上有【官方長期業務摘要】【過去兩週即時市場與技術新聞】，以及一組"
    "【前瞻硬指標】（trailingPEG、CapEx 擴張率、Earnings Surprise、毛利率）。"
    "請以『期望值與風險溢價』的前瞻視角揉合上述資訊，提煉成 3 點冰冷、機構級的繁體中文報告，"
    "嚴格遵守以下結構，絕對禁止任何客套廢話："
    "1. 【前瞻核心壁壘與定價權】：結合毛利率與業務摘要，點穿其核心技術護城河與轉嫁通膨的定價權。"
    "2. 【未來 12 個月核心催化劑與預期管理】：結合即時新聞與 CapEx 乘數效應，"
    "指出最關鍵的研發投入、法說會指引、訂單兌現或分析師預期修正節點（具體到季度）。"
    "3. 【前瞻期望值與不對稱勝率】：結合 PEG 剪刀差、Surprise 趨勢與技術面結構，"
    "分析資金配置邏輯，判斷目前價格是否已提前反應利多，評估其不對稱風險報酬。"
    "注意：字數嚴格控制在 220 字內，語氣客觀、機構級、不帶情緒渲染。"
    "禁止 Markdown 符號（**、#、```），禁止客套開場白，直接從第 1 點開始輸出。"
    f"{GROWTH_LEXICON_CONSTRAINT}"
)

NARRATIVE_SYSTEM_PROMPT = (
    "你現在是頂級科技產業分析師。請無視任何財經媒體的股價看好或看壞噪音。"
    "請根據這段官方公司業務摘要，用 2-3 點極精鍊的繁體中文大白話，告訴用戶："
    "1. 這家公司底層到底是靠什麼科技/業務賺錢？ "
    "2. 他們最近在嘗試或投入什麼新研發/新方向？ "
    "3. 他們的競爭對手是誰？"
    "字數控制在 150 字內。"
    "嚴格禁止："
    "禁止輸出任何客套開場白（如「好的，分析師報告如下：」「以下是分析」）；"
    "禁止 Markdown 符號（**、#、```）；"
    "直接從第一點列點輸出，讓完全不懂股票的大學 CS 學生一讀就秒懂。"
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
        return _generate_content_with_backoff(
            client,
            model=MODEL_NAME,
            contents=f"{FILTER_PROMPT}\n\n{raw_text}",
        )
    except Exception as exc:
        print(f"Warning: Gemini API call failed ({exc}). Returning raw news.")
        return raw_text


def generate_company_narrative_text(
    symbol: str,
    business_summary: str,
    sector: str = "",
    industry: str = "",
) -> str | None:
    """Summarize official business summary into concise Traditional Chinese tech narrative."""
    context_parts = [f"Ticker: {symbol.upper()}"]
    if sector:
        context_parts.append(f"Sector: {sector}")
    if industry:
        context_parts.append(f"Industry: {industry}")
    context_parts.append(f"\nOfficial longBusinessSummary:\n{business_summary.strip()}")
    user_block = "\n".join(context_parts)

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return None

    try:
        client = genai.Client(api_key=api_key)
        text = _generate_content_with_backoff(
            client,
            model=MODEL_NAME,
            contents=f"{NARRATIVE_SYSTEM_PROMPT}\n\n{user_block}",
        )
        return accept_llm_cache_result(text)
    except Exception as exc:
        print(f"Warning: company narrative failed for {symbol}: {exc}")
        return None


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
    live_news_text: str = "",
    trend_signal: dict | None = None,
    master_text: str = "",
) -> str | None:
    """Growth-mode narrative: fuse static summary + live news + master metrics + technical catalyst."""
    context_parts = [f"Ticker: {symbol.upper()}"]
    if sector:
        context_parts.append(f"Sector: {sector}")
    if industry:
        context_parts.append(f"Industry: {industry}")
    context_parts.append(
        f"\n【官方長期業務摘要 longBusinessSummary】\n{(business_summary or '（無）').strip()}"
    )
    if live_news_text.strip():
        context_parts.append(f"\n【過去兩週即時市場與技術新聞】\n{live_news_text.strip()}")
    else:
        context_parts.append("\n【過去兩週即時市場與技術新聞】\n（即時新聞流暫不可用，請僅依靜態摘要與技術面推論。）")
    if master_text.strip():
        context_parts.append(f"\n【前瞻硬指標 Master Variables】\n{master_text.strip()}")
    context_parts.append(f"\n{_format_trend_context(trend_signal)}")
    user_block = "\n".join(context_parts)

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return None

    try:
        client = genai.Client(api_key=api_key)
        text = _generate_content_with_backoff(
            client,
            model=MODEL_NAME,
            contents=f"{NARRATIVE_GROWTH_LIVE_PROMPT}\n\n{user_block}",
        )
        return accept_llm_cache_result(text)
    except Exception as exc:
        print(f"Warning: growth narrative failed for {symbol}: {exc}")
        return None


def _call_gemini(system_prompt: str, context: str) -> str | None:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return None
    try:
        client = genai.Client(api_key=api_key)
        text = _generate_content_with_backoff(
            client,
            model=MODEL_NAME,
            contents=f"{system_prompt}\n\n{context.strip()}",
        )
        return accept_llm_cache_result(text)
    except Exception as exc:
        print(f"Warning: Gemini commentary failed after retries: {exc}")
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
