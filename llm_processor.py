"""LLM-based news filtering for System A (Macro Watcher)."""
from __future__ import annotations

import os

from google import genai

from data_fetcher import NewsItem

FILTER_PROMPT = (
    "你是一個冷酷的量化投資資訊過濾器。請對以下新聞進行去噪，剔除所有煽動性形容詞與無關炒作（如虛擬貨幣）。"
    "只保留：1. 宏觀經濟核心事實（利率、就業、通膨等） "
    "2. 與個股 PFE, GIS, FLO, NOK, NVO 相關的具體事實。"
    "請用極簡短的中文列點輸出。若無重要變數，請輸出『今日無重要宏觀或個股變數』。"
)
MODEL_NAME = "gemini-2.5-flash"

GROWTH_LEXICON_CONSTRAINT = (
    "在生成技術面與資金面點評時，禁止使用「多頭雛形」「飆股」「爆發」「拉抬」「暴雷」"
    "等帶有散戶情緒或投顧色彩的廉價詞彙。"
    "請改用「右側動能結構」「中期均線支撐確立」「價格站上中期均線群」「資金向科技敘事流動」"
    "等機構級別、客觀、冷靜的金融語言。"
)

GROWTH_ANALYST_SYSTEM_PROMPT = (
    "你是華爾街頂級對沖基金的成長策略首席分析師（Buy-Side PM 視角）。"
    "你的任務不是複述歷史新聞或行銷包裝，而是進行冷靜的機構級多空對峙分析。"
    "硬性規則："
    "1. 數據流中 [A] 為「最新申報季度」、[B] 為「TTM  trailing 指標」——絕對禁止混淆期間；"
    "   引用數字時必須標明是季度還是 TTM。"
    "2. 若數據流含【紅旗警告】（營業利益率衰退 / CapEx 效率陷阱），必須在空頭段落明確引用，"
    "   不可粉飾。"
    "3. 禁止客套開場白、禁止散戶情緒詞（多頭雛形/飆股/爆發/突破）；"
    "4. 成長模式：絕對不准因 FCF/股息/配息/發放率給予負評；"
    "5. 250–380 字；禁止 Markdown # 與 **；直接從第 1 點開始。"
    "僅輸出以下三段（標題完整保留）："
    "【部門拆解與 AI 轉型實質進展】："
    "從最新數據拆解「高增長部門（如 Data Center / 光纖 / AI 推理）」與"
    "「衰退或老舊業務（如 legacy 基地台 / 低毛利硬體）」的剪刀差；"
    "指出近期重大戰略動作（M&A、大廠供應鏈切入、CapEx 方向變化）。"
    "【核心催化劑與開牌時間表】："
    "列出未來 12 個月內 Earnings Revision（分析師 EPS 上修/下修）的關鍵節點，"
    "以及估值重估 (Re-rating) 的觸發條件（具體到季度/月份）。"
    "【嚴格空頭風險與對手競爭防禦】："
    "硬性規定至少列出 2 點最殘酷的空頭觀點"
    "（例：核心客戶 CapEx 縮減、同業價格戰、全年獲利指引下修、定價權流失）。"
    f"{GROWTH_LEXICON_CONSTRAINT}"
)

VALUE_ANALYST_SYSTEM_PROMPT = (
    "你是華爾街頂級 DGI（股息成長投資）量化首席分析師（Graham/Buffett 框架）。"
    "請以股息安全與真實資本回報視角，結合硬數據進行多空平衡分析——禁止行銷包裝。"
    "硬性規則："
    "1. [A] 季度 vs [B] TTM 數據絕對不可混淆；引用時標明期間。"
    "2. ROIC 優先於 ROE；若 ROE 顯著高於 ROIC，必須點出過度舉債撐高 ROE 的假象風險。"
    "3. FCF 支付率 >90% 必須明確警告股息裁減風險；"
    "   淨債務/EBITDA >3x 或 5Y 營收 CAGR 為負，必須點名衰退型價值陷阱。"
    "4. 250–320 字；禁止客套與 Markdown #/**。"
    "僅輸出以下三段："
    "【ROIC 與真實護城河】：以 ROIC（非 ROE）判定資本配置效率；"
    "對照毛利率穩定度與營業利益率，點出是否靠槓桿撐高 ROE 的假象，"
    "以及定價權與客戶切換成本。"
    "【FCF 股息安全網】：精準點評 FCF 支付率與股息連續成長紀錄，"
    "判定自由現金流是否足以覆蓋股息、裁息風險窗口。"
    "【債務槓桿與衰退風險】：檢視淨債務/EBITDA、利息保障倍數與 5Y 營收 CAGR，"
    "判斷是否為正在衰退的價值陷阱；至少 2 點空頭觀點。"
    f"{GROWTH_LEXICON_CONSTRAINT}"
)

MASTER_SCORECARD_PROMPT = (
    "你是機構級量化評分引擎。根據提供的 MASTER DATA FEED，"
    "為以下六個維度各給 1–10 分（整數）及一行冰冷理由（≤40 字）。"
    "禁止行銷語言；理由必須引用具體數字或紅旗。"
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


def generate_company_narrative_text(
    symbol: str,
    business_summary: str,
    sector: str = "",
    industry: str = "",
) -> str:
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
        return "⚠️ 未設定 GEMINI_API_KEY，無法生成科技敘事。請在環境變數中設定後重新整理。"

    try:
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model=MODEL_NAME,
            contents=f"{NARRATIVE_SYSTEM_PROMPT}\n\n{user_block}",
        )
        text = (response.text or "").strip()
        if not text:
            raise ValueError("Gemini returned an empty narrative.")
        return text
    except Exception as exc:
        return f"⚠️ 科技敘事生成失敗（{exc}）。請稍後再試或清除快取後重試。"


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
) -> str:
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
        return text
    except Exception as exc:
        return f"⚠️ 科技敘事生成失敗（{exc}）。請稍後再試或清除快取後重試。"


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
