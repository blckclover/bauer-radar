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

NARRATIVE_SYSTEM_PROMPT = (
    "你現在是頂級科技產業分析師。請無視任何財經媒體的股價看好或看壞噪音。"
    "請根據這段官方公司業務摘要，用 2-3 點極精鍊的繁體中文大白話，告訴用戶："
    "1. 這家公司底層到底是靠什麼科技/業務賺錢？ "
    "2. 他們最近在嘗試或投入什麼新研發/新方向？ "
    "3. 他們的競爭對手是誰？"
    "字數控制在 150 字內，要讓完全不懂股票的大學 CS 學生一讀就秒懂該公司的科技敘事。"
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
