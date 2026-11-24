import unittest

from liaowang import brief

ITEMS = [
    {"id": 1, "title": "A", "score": 95, "verdict": "keep", "stars": 9000, "tag": "RAG 引擎", "why": "对口", "url": "u1", "published": "2026-11-24"},
    {"id": 2, "title": "B", "score": 60, "verdict": "keep", "stars": 500, "tag": "工具", "why": "还行", "url": "u2", "published": ""},
    {"id": 3, "title": "C", "score": 30, "verdict": "skip", "stars": 100, "tag": "清单聚合", "why": "只是清单", "url": "u3", "published": ""},
    {"id": 4, "title": "D", "score": None, "verdict": "unscored", "stars": 0, "tag": "", "why": "", "url": "u4", "published": ""},
]


class TestPick(unittest.TestCase):
    def test_filters_by_verdict_and_score(self):
        picked = brief.pick(ITEMS, min_score=60)
        self.assertEqual([p["title"] for p in picked], ["A", "B"])

    def test_threshold_excludes_low(self):
        self.assertEqual([p["title"] for p in brief.pick(ITEMS, min_score=90)], ["A"])

    def test_limit(self):
        self.assertEqual(len(brief.pick(ITEMS, min_score=0, limit=1)), 1)

    def test_star_breaks_tie(self):
        tie = [
            {"id": 1, "title": "少星", "score": 80, "verdict": "keep", "stars": 100},
            {"id": 2, "title": "多星", "score": 80, "verdict": "keep", "stars": 900},
        ]
        self.assertEqual([p["title"] for p in brief.pick(tie)], ["多星", "少星"])

    def test_unscored_never_picked(self):
        self.assertNotIn("D", [p["title"] for p in brief.pick(ITEMS, min_score=0)])


class TestCounts(unittest.TestCase):
    def test_counts(self):
        c = brief.counts(ITEMS)
        self.assertEqual(c, {"keep": 2, "skip": 1, "unscored": 1})


class TestRender(unittest.TestCase):
    def test_console(self):
        text = brief.render_console(ITEMS)
        self.assertIn("值得看 2", text)
        self.assertIn("[95] A", text)
        self.assertIn("RAG 引擎", text)
        self.assertNotIn("C", text.split("值得看")[1][:200])  # skip 的不进正文

    def test_console_empty_hint(self):
        text = brief.render_console([i for i in ITEMS if i["verdict"] == "unscored"])
        self.assertIn("没有过线", text)

    def test_markdown_has_sections(self):
        md = brief.render_markdown(ITEMS, "RAG 框架", "只有一条对口")
        self.assertIn("# RAG 框架 情报简报", md)
        self.assertIn("> 只有一条对口", md)
        self.assertIn("## 1. A（95 分）", md)
        self.assertIn("## 被过滤掉的", md)
        self.assertIn("只是清单", md)


if __name__ == "__main__":
    unittest.main()
