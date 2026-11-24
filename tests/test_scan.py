import json
import os
import tempfile
import unittest
from unittest import mock

from liaowang import llm, scan, store

WATCH = {"id": 1, "name": "RAG 框架", "source": "github", "target": "topic:rag",
         "min_stars": 500, "language": "", "days": 90, "per_page": 6, "note": ""}

ITEMS = [
    {"key": "gh:infiniflow/ragflow", "title": "infiniflow/ragflow", "url": "u1",
     "summary": "RAG engine", "source": "github", "stars": 9000, "published": "2026-11-24", "extra": {}},
    {"key": "gh:foo/awesome", "title": "foo/awesome", "url": "u2",
     "summary": "awesome list", "source": "github", "stars": 300, "published": "2026-11-24", "extra": {}},
]

GOOD = json.dumps({
    "items": [
        {"n": 1, "score": 92, "tag": "RAG 引擎", "why": "对口且活跃", "keep": True},
        {"n": 2, "score": 30, "tag": "清单聚合", "why": "只是清单", "keep": True},  # keep 但分数不够，程序会压掉
    ],
    "takeaway": "只有一条真正对口",
}, ensure_ascii=False)


class TestScoreBatch(unittest.TestCase):
    def test_parse_scores(self):
        with mock.patch.object(llm, "chat", return_value=GOOD):
            r = scan.score_batch(WATCH, ITEMS)
        self.assertEqual(r["error"], "")
        self.assertEqual(r["scores"]["gh:infiniflow/ragflow"]["score"], 92)
        self.assertTrue(r["scores"]["gh:infiniflow/ragflow"]["keep"])
        # keep=true 但只有 30 分：一律当过滤，保持「分数说话」
        self.assertFalse(r["scores"]["gh:foo/awesome"]["keep"])

    def test_out_of_range_n_ignored(self):
        bad = json.dumps({"items": [{"n": 7, "score": 99, "keep": True}], "takeaway": ""})
        with mock.patch.object(llm, "chat", return_value=bad):
            r = scan.score_batch(WATCH, ITEMS)
        self.assertEqual(r["scores"], {})

    def test_score_clamped(self):
        weird = json.dumps({"items": [{"n": 1, "score": 999, "keep": True}]})
        with mock.patch.object(llm, "chat", return_value=weird):
            r = scan.score_batch(WATCH, ITEMS)
        self.assertEqual(r["scores"]["gh:infiniflow/ragflow"]["score"], 100)

    def test_llm_error_reported(self):
        with mock.patch.object(llm, "chat", side_effect=llm.LLMError("429")):
            r = scan.score_batch(WATCH, ITEMS)
        self.assertIn("429", r["error"])
        self.assertEqual(r["scores"], {})


class TestScan(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.conn = store.connect(os.path.join(self.dir, "t.db"))
        self.wid = store.add_watch(self.conn, "RAG 框架", "github", "topic:rag", min_stars=500, per_page=6)

    def tearDown(self):
        self.conn.close()

    def watch(self):
        return store.get_watch(self.conn, self.wid)

    def test_full_scan_counts(self):
        with mock.patch.object(scan.fetch, "fetch_source", return_value=ITEMS), \
             mock.patch.object(llm, "chat", return_value=GOOD):
            r = scan.scan(self.conn, self.watch(), config={"api_key": "x", "base_url": "http://x", "model": "m"})
        self.assertEqual(r["fetched"], 2)
        self.assertEqual(r["fresh"], 2)
        self.assertEqual(r["kept"], 1)
        self.assertEqual(r["skipped"], 1)
        self.assertEqual(r["takeaway"], "只有一条真正对口")
        self.assertEqual(store.stats(self.conn)["kept"], 1)

    def test_second_scan_adds_nothing(self):
        cfg = {"api_key": "x", "base_url": "http://x", "model": "m"}
        with mock.patch.object(scan.fetch, "fetch_source", return_value=ITEMS), \
             mock.patch.object(llm, "chat", return_value=GOOD):
            scan.scan(self.conn, self.watch(), config=cfg)
            second = scan.scan(self.conn, self.watch(), config=cfg)
        self.assertEqual(second["fresh"], 0)
        self.assertEqual(store.stats(self.conn)["items"], 2)

    def test_model_failure_keeps_items_unscored(self):
        cfg = {"api_key": "x", "base_url": "http://x", "model": "m"}
        with mock.patch.object(scan.fetch, "fetch_source", return_value=ITEMS), \
             mock.patch.object(llm, "chat", side_effect=llm.LLMError("timeout")):
            r = scan.scan(self.conn, self.watch(), config=cfg)
        self.assertIn("timeout", r["error"])
        self.assertEqual(r["fresh"], 2)  # 条目照样入库
        self.assertEqual(store.stats(self.conn)["items"], 2)
        self.assertEqual(store.list_items(self.conn, verdict="unscored")[0]["verdict"], "unscored")

    def test_dry_run_does_not_write(self):
        with mock.patch.object(scan.fetch, "fetch_source", return_value=ITEMS):
            r = scan.scan(self.conn, self.watch(), dry_run=True)
        self.assertEqual(r["fetched"], 2)
        self.assertEqual(r["fresh"], 0)
        self.assertEqual(store.stats(self.conn)["items"], 0)

    def test_no_model_marks_unscored(self):
        with mock.patch.object(scan.fetch, "fetch_source", return_value=ITEMS):
            r = scan.scan(self.conn, self.watch(), config=None)
        self.assertEqual(r["fresh"], 2)
        self.assertEqual(len(store.list_items(self.conn, verdict="unscored")), 2)

    def test_batches_respect_size(self):
        calls = []

        def spy(watch, items, config=None, max_tokens=8000):
            calls.append(len(items))
            return {"scores": {}, "takeaway": "", "error": ""}

        many = [{**ITEMS[0], "key": f"gh:r{i}", "title": f"repo{i}"} for i in range(7)]
        with mock.patch.object(scan.fetch, "fetch_source", return_value=many), \
             mock.patch.object(scan, "score_batch", side_effect=spy):
            scan.scan(self.conn, self.watch(), config={"api_key": "x"}, batch_size=3)
        self.assertEqual(calls, [3, 3, 1])

    def test_fetch_error_propagates(self):
        with mock.patch.object(scan.fetch, "fetch_source", side_effect=scan.fetch.FetchError("403")):
            with self.assertRaises(scan.fetch.FetchError):
                scan.scan(self.conn, self.watch())


if __name__ == "__main__":
    unittest.main()
