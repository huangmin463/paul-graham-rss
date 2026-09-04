#!/usr/bin/env python3
"""Build an RSS feed from Paul Graham's public essay index.

The scraper intentionally uses only the Python standard library so it can run
unchanged on a local machine or in GitHub Actions.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import format_datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterable
from urllib.parse import urljoin, urlsplit, urlunsplit
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET


SOURCE_URL = "https://paulgraham.com/articles.html"
SITE_URL = "https://paulgraham.com/"
DEFAULT_USER_AGENT = "paul-graham-rss/1.0 (+self-use feed scraper)"
ATOM_NS = "http://www.w3.org/2005/Atom"

# These are site-navigation pages rather than essays. The article index uses
# simple .html links, so filtering these known navigation links is reliable.
EXCLUDED_PATHS = {
    "/",
    "/index.html",
    "/articles.html",
    "/rss.html",
    "/bio.html",
    "/books.html",
    "/arc.html",
    "/bel.html",
    "/lisp.html",
    "/antispam.html",
    "/kedrosky.html",
    "/faq.html",
    "/raq.html",
    "/quo.html",
}


@dataclass(frozen=True)
class Article:
    title: str
    url: str


class AnchorParser(HTMLParser):
    """Collect anchor text without interpreting commented-out old markup."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.anchors: list[tuple[str, str]] = []
        self._href: str | None = None
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a" or self._href is not None:
            return
        attributes = dict(attrs)
        self._href = attributes.get("href")
        self._text = []

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() != "a" or self._href is None:
            return
        self.anchors.append((self._href, " ".join("".join(self._text).split())))
        self._href = None
        self._text = []


def canonical_article_url(href: str, base_url: str = SOURCE_URL) -> str | None:
    """Return a stable HTTPS URL for a Paul Graham essay, or None."""

    absolute = urljoin(base_url, href.strip())
    parts = urlsplit(absolute)
    host = parts.netloc.lower().split(":", 1)[0]
    path = parts.path or "/"

    if host not in {"paulgraham.com", "www.paulgraham.com"}:
        return None
    if not path.lower().endswith(".html") or path.lower() in EXCLUDED_PATHS:
        return None

    # Query strings and fragments are not part of the essay identity.
    return urlunsplit(("https", "paulgraham.com", path, "", ""))


def parse_articles(index_html: str, base_url: str = SOURCE_URL) -> list[Article]:
    """Extract unique essay links in the order shown on the source page."""

    parser = AnchorParser()
    parser.feed(index_html)

    articles: list[Article] = []
    seen_urls: set[str] = set()
    for href, title in parser.anchors:
        url = canonical_article_url(href, base_url)
        if not url or not title or url in seen_urls:
            continue
        seen_urls.add(url)
        articles.append(Article(title=title, url=url))
    return articles


def fetch_text(url: str, timeout: int = 30) -> str:
    request = Request(
        url,
        headers={
            "Accept": "text/html,application/xhtml+xml",
            "User-Agent": os.environ.get("RSS_USER_AGENT", DEFAULT_USER_AGENT),
        },
    )
    with urlopen(request, timeout=timeout) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset, errors="replace")


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def iso_timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def load_state(path: Path) -> dict[str, dict[str, str]]:
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        items = raw.get("items", raw)
        if not isinstance(items, dict):
            raise ValueError("state items must be an object")
        return {
            str(url): dict(record)
            for url, record in items.items()
            if isinstance(record, dict) and record.get("first_seen")
        }
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Cannot read state file {path}: {exc}") from exc


def save_state(path: Path, items: dict[str, dict[str, str]]) -> None:
    payload = {
        "version": 1,
        "source": SOURCE_URL,
        "items": items,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def update_state(
    articles: Iterable[Article],
    state: dict[str, dict[str, str]],
    seen_at: datetime,
) -> tuple[dict[str, dict[str, str]], int]:
    """Record first-seen timestamps while retaining stable item identities."""

    timestamp = iso_timestamp(seen_at)
    new_count = 0
    for article in articles:
        record = state.get(article.url)
        if record is None:
            state[article.url] = {
                "title": article.title,
                "first_seen": timestamp,
            }
            new_count += 1
            continue

        # Keep the URL/GUID stable, but reflect a title correction if the
        # source page changes it.
        if record.get("title") != article.title:
            record["title"] = article.title
            record["updated_at"] = timestamp
    return state, new_count


def feed_datetime(record: dict[str, str]) -> datetime:
    # The source index does not expose publication dates. First-seen time is a
    # truthful, stable fallback: it means “detected by this feed.”
    try:
        return parse_timestamp(record["first_seen"])
    except (KeyError, ValueError):
        return utc_now()


def build_feed(
    articles: Iterable[Article],
    state: dict[str, dict[str, str]],
    feed_url: str | None = None,
    built_at: datetime | None = None,
) -> bytes:
    """Build UTF-8 RSS 2.0 XML from current source items."""

    built_at = built_at or utc_now()
    root = ET.Element("rss", {"version": "2.0"})
    channel = ET.SubElement(root, "channel")
    ET.SubElement(channel, "title").text = "Paul Graham: Essays"
    ET.SubElement(channel, "link").text = SITE_URL
    ET.SubElement(channel, "description").text = (
        "A self-use feed generated from Paul Graham's public essays index."
    )
    ET.SubElement(channel, "language").text = "en-us"
    ET.SubElement(channel, "lastBuildDate").text = format_datetime(built_at, usegmt=True)
    ET.SubElement(channel, "generator").text = "paul-graham-rss"
    if feed_url:
        self_link = ET.SubElement(channel, f"{{{ATOM_NS}}}link")
        self_link.attrib.update(
            {"href": feed_url, "rel": "self", "type": "application/rss+xml"}
        )

    for article in articles:
        record = state[article.url]
        item = ET.SubElement(channel, "item")
        ET.SubElement(item, "title").text = article.title
        ET.SubElement(item, "link").text = article.url
        guid = ET.SubElement(item, "guid", {"isPermaLink": "true"})
        guid.text = article.url
        ET.SubElement(item, "pubDate").text = format_datetime(
            feed_datetime(record), usegmt=True
        )
        ET.SubElement(item, "description").text = (
            f"{article.title} — read the essay at {article.url}"
        )

    ET.register_namespace("atom", ATOM_NS)
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_bytes(data)
    temporary.replace(path)


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source-url",
        default=os.environ.get("RSS_SOURCE_URL", SOURCE_URL),
        help="HTML index to scrape",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(os.environ.get("RSS_OUTPUT", "feed.xml")),
        help="RSS XML output path",
    )
    parser.add_argument(
        "--state",
        type=Path,
        default=Path(os.environ.get("RSS_STATE", "feed-state.json")),
        help="Persistent state JSON path",
    )
    parser.add_argument(
        "--feed-url",
        default=os.environ.get("RSS_FEED_URL", "").strip() or None,
        help="Public feed URL for the Atom self link (optional)",
    )
    parser.add_argument("--timeout", type=int, default=30, help="HTTP timeout in seconds")
    return parser


def main() -> int:
    args = build_argument_parser().parse_args()
    try:
        index_html = fetch_text(args.source_url, timeout=args.timeout)
        articles = parse_articles(index_html, base_url=args.source_url)
        if not articles:
            raise RuntimeError("No essay links found; refusing to overwrite the feed")

        state = load_state(args.state)
        state, new_count = update_state(articles, state, utc_now())
        save_state(args.state, state)
        write_bytes(args.output, build_feed(articles, state, args.feed_url))
    except Exception as exc:  # A concise error is friendlier in scheduled logs.
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(
        f"wrote {len(articles)} items to {args.output} "
        f"({new_count} newly discovered; state: {args.state})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
