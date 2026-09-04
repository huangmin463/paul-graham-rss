import sys
import unittest
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from scrape_feed import Article, build_feed, parse_articles, update_state


class ScraperTests(unittest.TestCase):
    def test_parse_articles_ignores_comments_navigation_and_duplicates(self):
        html = """
        <!-- <a href='old.html'>Commented old essay</a> -->
        <map><area href='faq.html'></map>
        <a href='articles.html'>Essays</a>
        <a href='prepare.html'>How Universities Should Prepare Founders</a>
        <a href='/prepare.html#top'>Duplicate</a>
        <a href='https://www.paulgraham.com/earn.html'>How to Earn a Billion Dollars</a>
        <a href='https://example.com/no.html'>External page</a>
        """
        articles = parse_articles(html)
        self.assertEqual(
            articles,
            [
                Article(
                    "How Universities Should Prepare Founders",
                    "https://paulgraham.com/prepare.html",
                ),
                Article("How to Earn a Billion Dollars", "https://paulgraham.com/earn.html"),
            ],
        )

    def test_state_and_feed_have_stable_guid_and_valid_xml(self):
        articles = [Article("Example Essay", "https://paulgraham.com/example.html")]
        state, new_count = update_state(
            articles,
            {},
            datetime(2026, 9, 4, 0, 0, tzinfo=timezone.utc),
        )
        self.assertEqual(new_count, 1)
        xml_bytes = build_feed(
            articles,
            state,
            feed_url="https://example.github.io/feed.xml",
            built_at=datetime(2026, 9, 4, 0, 0, tzinfo=timezone.utc),
        )
        root = ET.fromstring(xml_bytes)
        item = root.find("./channel/item")
        self.assertIsNotNone(item)
        self.assertEqual(item.findtext("guid"), "https://paulgraham.com/example.html")
        self.assertEqual(item.findtext("link"), "https://paulgraham.com/example.html")
        self.assertIn("Paul Graham: Essays", root.findtext("./channel/title"))


if __name__ == "__main__":
    unittest.main()
