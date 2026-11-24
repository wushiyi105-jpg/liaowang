import json
import unittest
from unittest import mock

from liaowang import fetch

GH_JSON = {
    "total_count": 2,
    "items": [
        {"full_name": "infiniflow/ragflow", "html_url": "https://github.com/infiniflow/ragflow",
         "description": "RAG engine <b>with</b> &amp; agents", "stargazers_count": 94645,
         "pushed_at": "2026-11-24T10:00:00Z", "language": "Python", "forks_count": 8000,
         "open_issues_count": 120, "topics": ["rag", "llm"]},
        {"full_name": "Foo/Bar", "html_url": "https://github.com/Foo/Bar", "description": None,
         "stargazers_count": 12, "pushed_at": "2026-10-01T00:00:00Z", "language": None,
         "forks_count": 1, "open_issues_count": 0},
    ],
}

ATOM = """<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>示例源</title>
  <entry>
    <title>第一条 &amp; 测试</title>
    <link href="https://example.com/a"/>
    <summary>&lt;p&gt;摘要内容&lt;/p&gt;</summary>
    <published>2026-11-20T08:00:00Z</published>
  </entry>
  <entry>
    <title></title>
    <link href="https://example.com/empty"/>
  </entry>
</feed>
"""

RSS = """<?xml version="1.0"?>
<rss version="2.0"><channel>
  <item>
    <title>RSS 一条</title>
    <link>https://example.com/r1</link>
    <description>描述文字</description>
    <pubDate>Mon, 24 Nov 2026 00:00:00 +0800</pubDate>
  </item>
</channel></rss>
"""


def fake_get(payload: bytes):
    def _inner(url, timeout=30, token=None):
        return payload
    return _inner


class TestGithubSearch(unittest.TestCase):
    def test_parses_items(self):
        with mock.patch.object(fetch, "_get", fake_get(json.dumps(GH_JSON).encode("utf-8"))):
            items = fetch.github_search("topic:rag", min_stars=500, per_page=2)
        self.assertEqual(len(items), 2)
        first = items[0]
        self.assertEqual(first["key"], "gh:infiniflow/ragflow")
        self.assertEqual(first["stars"], 94645)
        self.assertEqual(first["published"], "2026-11-24")
        self.assertEqual(first["extra"]["language"], "Python")
        self.assertIn("RAG engine", first["summary"])
        self.assertNotIn("<b>", first["summary"])

    def test_missing_description_becomes_empty(self):
        with mock.patch.object(fetch, "_get", fake_get(json.dumps(GH_JSON).encode("utf-8"))):
            items = fetch.github_search("topic:rag")
        self.assertEqual(items[1]["summary"], "")

    def test_query_includes_filters(self):
        captured = {}

        def spy(url, timeout=30, token=None):
            captured["url"] = url
            return json.dumps(GH_JSON).encode("utf-8")

        with mock.patch.object(fetch, "_get", spy):
            fetch.github_search("topic:rag", min_stars=300, language="Python", days=30, per_page=5)
        url = captured["url"]
        self.assertIn("stars%3A%3E%3D300", url)
        self.assertIn("language%3APython", url)
        self.assertIn("per_page=5", url)

    def test_bad_json_raises(self):
        with mock.patch.object(fetch, "_get", fake_get(b"<html>oops</html>")):
            with self.assertRaises(fetch.FetchError):
                fetch.github_search("topic:rag")


class TestFeed(unittest.TestCase):
    def test_atom(self):
        items = fetch.parse_feed(ATOM.encode("utf-8"))
        self.assertEqual(len(items), 1)  # 第二条没有标题，丢掉
        self.assertEqual(items[0]["title"], "第一条 & 测试")
        self.assertEqual(items[0]["url"], "https://example.com/a")
        self.assertEqual(items[0]["summary"], "摘要内容")
        self.assertEqual(items[0]["published"], "2026-11-20")

    def test_rss(self):
        items = fetch.parse_feed(RSS.encode("utf-8"), source="hn")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["title"], "RSS 一条")
        self.assertEqual(items[0]["source"], "hn")

    def test_bad_xml_raises(self):
        with self.assertRaises(fetch.FetchError):
            fetch.parse_feed(b"not xml")

    def test_fetch_source_dispatch(self):
        with mock.patch.object(fetch, "github_search", return_value=[{"key": "gh:x"}]):
            self.assertEqual(fetch.fetch_source("github", "topic:rag")[0]["key"], "gh:x")
        with mock.patch.object(fetch, "fetch_feed", return_value=[{"key": "feed:y"}]):
            self.assertEqual(fetch.fetch_source("rss", "https://example.com/feed")[0]["key"], "feed:y")
        with self.assertRaises(fetch.FetchError):
            fetch.fetch_source("ftp", "whatever")


if __name__ == "__main__":
    unittest.main()
