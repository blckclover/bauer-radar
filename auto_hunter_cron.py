"""Automated cron: System A news brain + System B turnaround radar → dual Discord channels."""
from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass
from datetime import datetime

import requests
from google import genai

from analyzer_core import (
    TICKERS,
    TurnaroundOpportunity,
    detect_trend_signals,
    find_turnaround_opportunities,
)
from data_fetcher import NewsItem, fetch_yahoo_finance_rss

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# Default scan universe: portfolio tickers + large-cap watchlist (matches Streamlit UI).
LARGE_CAP_EXTRAS: tuple[str, ...] = ("INTC", "BA", "DIS", "AAPL", "MSFT", "GOOGL", "AMZN")

GEMINI_MODEL = "gemini-2.5-flash"
DISCORD_MAX_CONTENT = 2000

DEEP_DIVE_DELIMITER = "---DEEP_DIVE---"

HUNTER_PROMPT = (
    "你是一個冷酷的量化投資資訊過濾器。請閱讀以下財經/科技新聞標題，"
    "並「必須以繁體中文」一次產出「兩份」內容，中間以恰好一行 "
    f"`{DEEP_DIVE_DELIMITER}` 分隔。\n\n"
    "【第一份：短戰情報摘要】\n"
    "## 宏觀硬事實\n"
    "列出 2-3 點去除噪音的核心硬事實（利率、就業、通膨、產業政策、龍頭財報等）。"
    "剔除煽動性形容詞、無關炒作（如虛擬貨幣短炒）。每點一行，以「- 」開頭。\n\n"
    "## 每日產業知識點\n"
    "用 1 段大白話（80 字以內）解讀一個與今日新聞相關的產業概念，"
    "讓非專業投資人也能理解。\n\n"
    f"{DEEP_DIVE_DELIMITER}\n\n"
    "【第二份：深度大白話解析】\n"
    "## 今日深度解析\n"
    "從今日新聞中挑選「最重要的一則」事件或硬事實，撰寫約 400 字的大白話深度解析。"
    "重點說明：這件事對「美股防禦型板塊」（如公用事業、必需消費、醫療保健、食品飲料）"
    "或「科技板塊」（半導體、雲端、AI 基礎建設）的底層邏輯與資金流向有何影響。"
    "禁止空泛口號，需具體、可驗證。\n\n"
    "若確實無重要宏觀或產業變數，第一份請在「宏觀硬事實」寫：今日無重要宏觀變數，"
    "並在「每日產業知識點」簡述一個通用投資概念；"
    "第二份則選一個通用但具教育性的市場機制作為解析主題。"
)

TREND_LABELS: dict[str, str] = {
    "Buy": "🟢 **BUY** · 右側動能確認（建議進場）",
    "Sell": "🔴 **SELL** · 動能衰竭（建議出場）",
    "Wait": "🔵 **WAIT** · 底部觀察中（請勿接刀）",
    "Hold": "🟡 **HOLD** · 趨勢穩定持有",
}


def _format_news_block(news_list: list[NewsItem]) -> str:
    if not news_list:
        return "（無法取得今日 RSS 新聞標題）"
    lines: list[str] = []
    for index, item in enumerate(news_list, start=1):
        lines.append(f"{index}. {item['title']}")
        lines.append(f"   發布：{item['published']}")
    return "\n".join(lines)


def _fmt_money_large(value: float | None) -> str:
    if value is None:
        return "N/A"
    v = float(value)
    if abs(v) >= 1e9:
        return f"${v / 1e9:.2f}B"
    if abs(v) >= 1e6:
        return f"${v / 1e6:.0f}M"
    return f"${v:,.0f}"


def build_scan_universe() -> list[str]:
    """Merge portfolio TICKERS with large-cap extras; dedupe while preserving order."""
    seen: set[str] = set()
    universe: list[str] = []
    for sym in (*TICKERS, *LARGE_CAP_EXTRAS):
        token = sym.upper().strip()
        if token and token not in seen:
            seen.add(token)
            universe.append(token)
    return universe


@dataclass
class SystemAIntel:
    alerts_brief: str
    deep_dive: str


def _fallback_alerts_brief(reason: str, raw_block: str) -> str:
    return (
        "## 宏觀硬事實\n"
        f"- （{reason}）\n\n"
        "## 每日產業知識點\n"
        "（略）\n\n"
        f"---\n{raw_block}"
    )


def _parse_system_a_response(text: str) -> tuple[str, str]:
    """Split Gemini output into alerts brief and deep-dive sections."""
    if DEEP_DIVE_DELIMITER in text:
        alerts_part, deep_part = text.split(DEEP_DIVE_DELIMITER, 1)
        return alerts_part.strip(), deep_part.strip()

    logger.warning("Gemini response missing %s delimiter; treating full text as alerts.", DEEP_DIVE_DELIMITER)
    return text.strip(), "（Gemini 未產出深度解析區塊，請稍後重試。）"


def run_system_a_news() -> SystemAIntel:
    """Fetch RSS headlines and distill alerts brief + deep dive via Gemini."""
    news_items = fetch_yahoo_finance_rss()
    raw_block = _format_news_block(news_items)

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        logger.warning("GEMINI_API_KEY not set; returning raw headlines.")
        return SystemAIntel(
            alerts_brief=_fallback_alerts_brief("未設定 GEMINI_API_KEY，以下為原始標題", raw_block),
            deep_dive="（未設定 GEMINI_API_KEY，無法產出深度解析。）",
        )

    try:
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=f"{HUNTER_PROMPT}\n\n---\n今日新聞標題：\n{raw_block}",
        )
        text = (response.text or "").strip()
        if not text:
            raise ValueError("Gemini returned empty response.")
        alerts_brief, deep_dive = _parse_system_a_response(text)
        return SystemAIntel(alerts_brief=alerts_brief, deep_dive=deep_dive)
    except Exception as exc:
        logger.warning("Gemini call failed (%s); falling back to raw headlines.", exc)
        return SystemAIntel(
            alerts_brief=_fallback_alerts_brief(f"Gemini 處理失敗：{exc}", raw_block),
            deep_dive=f"（Gemini 處理失敗：{exc}）",
        )


@dataclass
class TurnaroundHit:
    opportunity: TurnaroundOpportunity
    trend_signal: str
    trend_detail: str


def run_system_b_scan(universe: list[str]) -> tuple[list[TurnaroundHit], int]:
    """Screen universe for turnaround candidates and attach trend signals."""
    hits: list[TurnaroundHit] = []

    try:
        opportunities = find_turnaround_opportunities(universe)
    except Exception as exc:
        logger.error("Turnaround scan failed: %s", exc)
        return [], len(universe)

    for opp in opportunities:
        signal = "N/A"
        detail = "⚪ **N/A** · 無法取得均線資料"
        try:
            trend = detect_trend_signals(opp.symbol)
            if trend and trend.get("current_signal"):
                signal = str(trend["current_signal"])
                detail = TREND_LABELS.get(signal, f"⚪ **{signal}**")
        except Exception as exc:
            logger.warning("Trend signal failed for %s: %s", opp.symbol, exc)

        hits.append(
            TurnaroundHit(
                opportunity=opp,
                trend_signal=signal,
                trend_detail=detail,
            )
        )

    return hits, len(universe)


def _format_turnaround_section(hits: list[TurnaroundHit], scanned: int) -> str:
    lines = [
        f"掃描 **{scanned}** 檔標的 | 命中 **{len(hits)}** 檔（半年跌幅 >15% 且 FCF > 0）",
        "",
    ]

    if not hits:
        lines.append("_今日未命中轉機候選股。市場可能尚未出現「恐慌但現金流仍穩」的標的。_")
        return "\n".join(lines)

    for hit in hits:
        opp = hit.opportunity
        fcf_year = f"（{opp.latest_fcf_fiscal_year}）" if opp.latest_fcf_fiscal_year else ""
        lines.extend(
            [
                f"### {opp.symbol} · {opp.company_name}",
                f"- 跌幅：**-{opp.drawdown_pct:.1f}%**（相對半年高點 ${opp.six_month_high:.2f}）",
                f"- 現價：${opp.current_price:.2f}",
                f"- 最新 FCF：**{_fmt_money_large(opp.latest_fcf)}** {fcf_year}",
                f"- 均線訊號：{hit.trend_detail}",
                "",
            ]
        )

    return "\n".join(lines).rstrip()


def build_war_room_card(
    news_intel: str,
    hits: list[TurnaroundHit],
    scanned: int,
    generated_at: datetime,
) -> str:
    """Assemble the full Discord Markdown payload."""
    timestamp = generated_at.strftime("%Y-%m-%d %H:%M:%S")
    turnaround_block = _format_turnaround_section(hits, scanned)

    sections = [
        "# 📡 每日戰情簡報",
        f"**生成時間：** {timestamp}",
        "",
        "## 🧠 宏觀情報（System A）",
        news_intel.strip(),
        "",
        "## 🎯 轉機股雷達（System B）",
        turnaround_block,
    ]
    return "\n".join(sections)


def build_deep_dive_message(deep_dive: str, generated_at: datetime) -> str:
    """Assemble the Deep Dive channel Markdown payload."""
    timestamp = generated_at.strftime("%Y-%m-%d %H:%M:%S")
    sections = [
        "# 🔬 每日深度解析（Deep Dive）",
        f"**生成時間：** {timestamp}",
        "",
        deep_dive.strip(),
    ]
    return "\n".join(sections)


def split_discord_messages(text: str, max_len: int = DISCORD_MAX_CONTENT) -> list[str]:
    """Split long text into Discord-safe chunks (≤2000 chars), preferring line breaks."""
    if len(text) <= max_len:
        return [text]

    chunks: list[str] = []
    remaining = text

    while remaining:
        if len(remaining) <= max_len:
            chunks.append(remaining)
            break

        split_at = remaining.rfind("\n\n", 0, max_len)
        if split_at < max_len // 2:
            split_at = remaining.rfind("\n", 0, max_len)
        if split_at < max_len // 2:
            split_at = max_len

        chunk = remaining[:split_at].rstrip()
        if not chunk:
            chunk = remaining[:max_len]
            split_at = max_len

        suffix = f"\n\n_（續 {len(chunks) + 1}）_"
        if len(chunk) + len(suffix) <= max_len:
            chunk += suffix

        chunks.append(chunk)
        remaining = remaining[split_at:].lstrip("\n")

    return chunks


def send_discord_webhook(message: str, webhook_url: str) -> bool:
    """Post a single message chunk to Discord. Returns True on HTTP 200/204."""
    try:
        response = requests.post(
            webhook_url,
            json={"content": message},
            timeout=30,
        )
        if response.status_code in (200, 204):
            return True
        logger.warning(
            "Discord webhook HTTP %s: %s",
            response.status_code,
            response.text.strip()[:500],
        )
        return False
    except requests.RequestException as exc:
        logger.warning("Discord webhook request failed: %s", exc)
        return False


def send_discord_payload(text: str, webhook_url: str, channel_label: str = "Discord") -> bool:
    """Send full payload, splitting into multiple messages if needed."""
    parts = split_discord_messages(text)
    all_ok = True
    for index, part in enumerate(parts, start=1):
        ok = send_discord_webhook(part, webhook_url)
        if not ok:
            all_ok = False
            logger.error(
                "[%s] Failed to send chunk %d/%d.",
                channel_label,
                index,
                len(parts),
            )
    return all_ok


def dispatch_alerts_channel(payload: str) -> bool:
    """Send war-room card to DISCORD_WEBHOOK_ALERTS (independent pipeline)."""
    webhook_url = os.environ.get("DISCORD_WEBHOOK_ALERTS")
    if not webhook_url:
        logger.warning("DISCORD_WEBHOOK_ALERTS not set; printing alerts payload to stdout.")
        print("=== ALERTS CHANNEL ===")
        print(payload)
        return True

    try:
        ok = send_discord_payload(payload, webhook_url, channel_label="Alerts")
        if ok:
            logger.info(
                "Alerts delivered (%d part(s)).",
                len(split_discord_messages(payload)),
            )
        return ok
    except Exception as exc:
        logger.error("Alerts channel delivery error: %s", exc)
        return False


def dispatch_deepdive_channel(payload: str) -> bool:
    """Send deep-dive analysis to DISCORD_WEBHOOK_DEEPDIVE (independent pipeline)."""
    webhook_url = os.environ.get("DISCORD_WEBHOOK_DEEPDIVE")
    if not webhook_url:
        logger.warning("DISCORD_WEBHOOK_DEEPDIVE not set; printing deep dive to stdout.")
        print("=== DEEP DIVE CHANNEL ===")
        print(payload)
        return True

    try:
        ok = send_discord_payload(payload, webhook_url, channel_label="Deep Dive")
        if ok:
            logger.info(
                "Deep Dive delivered (%d part(s)).",
                len(split_discord_messages(payload)),
            )
        return ok
    except Exception as exc:
        logger.error("Deep Dive channel delivery error: %s", exc)
        return False


def main() -> int:
    """Run the full auto-hunter pipeline. Returns 0 on success, 1 on fatal error."""
    generated_at = datetime.now()
    logger.info("Auto Hunter cron started.")

    try:
        system_a = run_system_a_news()
        logger.info("System A complete (alerts + deep dive).")
    except Exception as exc:
        logger.error("System A fatal error: %s", exc)
        system_a = SystemAIntel(
            alerts_brief=f"（System A 執行失敗：{exc}）",
            deep_dive=f"（System A 執行失敗：{exc}）",
        )

    try:
        universe = build_scan_universe()
        hits, scanned = run_system_b_scan(universe)
        logger.info("System B complete: %d hits from %d tickers.", len(hits), scanned)
    except Exception as exc:
        logger.error("System B fatal error: %s", exc)
        hits, scanned = [], 0

    try:
        alerts_payload = build_war_room_card(system_a.alerts_brief, hits, scanned, generated_at)
        deep_dive_payload = build_deep_dive_message(system_a.deep_dive, generated_at)
        logger.info(
            "Payloads assembled (alerts: %d chars, deep dive: %d chars).",
            len(alerts_payload),
            len(deep_dive_payload),
        )
    except Exception as exc:
        logger.error("Failed to build payloads: %s", exc)
        return 1

    alerts_ok = dispatch_alerts_channel(alerts_payload)
    deepdive_ok = dispatch_deepdive_channel(deep_dive_payload)

    if not alerts_ok:
        logger.error("Alerts channel delivery failed.")
    if not deepdive_ok:
        logger.error("Deep Dive channel delivery failed.")

    if not alerts_ok and not deepdive_ok:
        has_any_webhook = bool(
            os.environ.get("DISCORD_WEBHOOK_ALERTS") or os.environ.get("DISCORD_WEBHOOK_DEEPDIVE")
        )
        if has_any_webhook:
            return 1

    logger.info("Auto Hunter cron finished.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
