"""System A main entry point: generate a daily market news briefing."""
from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

import requests

from data_fetcher import fetch_yahoo_finance_rss
from llm_processor import crush_and_filter_news

OUTPUT_FILE = Path(__file__).resolve().parent / "daily_market_brief.txt"


def _format_briefing(body: str, generated_at: datetime) -> str:
    """Wrap filtered content with a generation timestamp header."""
    lines = [
        "Daily Market Briefing",
        f"Generated at: {generated_at.strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        body,
    ]
    return "\n".join(lines).rstrip() + "\n"


def send_discord_webhook(message: str, webhook_url: str) -> bool:
    """Send a message to a Discord webhook. Returns True on success."""
    try:
        response = requests.post(
            webhook_url,
            json={"content": message},
            timeout=30,
        )
        if response.status_code in (200, 204):
            return True
        print(
            f"Warning: Discord webhook returned HTTP {response.status_code}: "
            f"{response.text.strip()}"
        )
        return False
    except requests.RequestException as exc:
        print(f"Warning: Discord webhook delivery failed ({exc}).")
        return False


def _push_briefing_to_discord(output_path: Path) -> None:
    """Read the briefing file and push it to Discord if a webhook URL is configured."""
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL")
    if not webhook_url:
        return

    try:
        with open(output_path, "r", encoding="utf-8") as briefing_file:
            content = briefing_file.read()
    except OSError as exc:
        print(f"Warning: Failed to read briefing file for Discord ({exc}).")
        return

    if send_discord_webhook(content, webhook_url):
        print("Daily briefing sent to Discord.")


def write_daily_briefing(output_path: Path = OUTPUT_FILE) -> Path:
    """Fetch news, filter via LLM, and write the daily briefing file."""
    generated_at = datetime.now()
    news_items = fetch_yahoo_finance_rss()
    filtered_content = crush_and_filter_news(news_items)
    content = _format_briefing(filtered_content, generated_at)
    with open(output_path, "w", encoding="utf-8") as briefing_file:
        briefing_file.write(content)
    return output_path


def main() -> None:
    output_path = write_daily_briefing()
    print(f"Daily briefing written to: {output_path}")
    _push_briefing_to_discord(output_path)


if __name__ == "__main__":
    main()
