"""RSS data fetcher for System A market news ingestion."""
from __future__ import annotations

import logging
from datetime import datetime
from typing import TypedDict

import feedparser

logger = logging.getLogger(__name__)

YAHOO_FINANCE_RSS_URL = "https://finance.yahoo.com/news/rssindex"
MAX_ITEMS = 10


class NewsItem(TypedDict):
    title: str
    published: str


def _format_published(entry: feedparser.FeedParserDict) -> str:
    """Return a human-readable published date from an RSS entry."""
    if entry.get("published"):
        return str(entry["published"])
    if entry.get("updated"):
        return str(entry["updated"])
    published_parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if published_parsed:
        return datetime(*published_parsed[:6]).strftime("%Y-%m-%d %H:%M:%S UTC")
    return "Unknown"


def fetch_yahoo_finance_rss() -> list[NewsItem]:
    """Fetch the latest Yahoo Finance RSS headlines.

    Returns up to 10 items with title and published date.
    On network or parsing failure, returns an empty list.
    """
    try:
        feed = feedparser.parse(YAHOO_FINANCE_RSS_URL)
        if feed.bozo and not feed.entries:
            logger.warning("RSS feed parse error: %s", feed.bozo_exception)
            return []

        items: list[NewsItem] = []
        for entry in feed.entries[:MAX_ITEMS]:
            title = entry.get("title", "").strip()
            if not title:
                continue
            items.append(
                {
                    "title": title,
                    "published": _format_published(entry),
                }
            )
        return items
    except Exception as exc:
        logger.exception("Failed to fetch Yahoo Finance RSS: %s", exc)
        return []
