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
    "你現在是頂級風險投資家 (VC) 與趨勢交易員的雙面首席分析師。"
    "請根據提供的量化評分與技術面物理事實，用繁體中文撰寫決策點評。"
    "強制約束："
    "1. 絕對不准提及 FCF、自由現金流、股息、配息、發放率，也不准因這些項目給負評；"
    "2. 若 Price above BOTH SMA20 and SMA50 為 true，"
    "必須客觀指出「價格站上中期均線群 · 右側結構確立」，"
    "並描述為確認價格轉入中期上升軌道的動能標的；"
    "3. 聚焦營收/R&D 孵化潛力、Beta 彈性、中期均線動能結構；"
    "4. 結構：① 綜合得分解讀 ② 技術面結構 ③ 成長敘事 ④ 風險邊界（各 1-2 句）；"
    "5. 150–250 字，禁止 Markdown 標題與 ** 符號，用列點或短段落。"
    f"6. {GROWTH_LEXICON_CONSTRAINT}"
)

NARRATIVE_GROWTH_LIVE_PROMPT = (
    "你現在是矽谷頂級科技風投 (VC) 的首席產業分析師。"
    "你手上有一份該公司的【官方長期業務摘要】以及【過去兩週的即時市場與技術新聞】。"
    "請幫我揉合這兩者，提煉成 3 點極具洞察力的繁體中文報告，嚴格遵守以下結構，絕對禁止任何客套廢話："
    "1. 【核心商業基因】：用一句話點穿這家公司底層靠什麼核心技術/業務賺錢（來自靜態摘要）。"
    "2. 【最新科技嘗試與技術動態】：結合【即時新聞】，指出最近數週的研發投入、"
    "新產品、法說會指引或重大商業合作。"
    "3. 【右側動能催化劑 (Catalyst)】：結合技術面結構與最新消息，"
    "分析資金配置邏輯（例如：板塊輪動、競爭格局變化、訂單能見度提升）。"
    "注意：字數嚴格控制在 200 字內，語氣客觀、機構級、不帶情緒渲染。"
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
) -> str:
    """Growth-mode narrative: fuse static summary + live news + technical catalyst."""
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


def generate_growth_analyst_commentary(context: str) -> str | None:
    """VC / trend-trader commentary for growth strategy mode; None triggers fallback."""
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return None

    try:
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model=MODEL_NAME,
            contents=f"{GROWTH_ANALYST_SYSTEM_PROMPT}\n\n{context.strip()}",
        )
        text = (response.text or "").strip()
        return text or None
    except Exception:
        return None
