import os
import tempfile
import unittest

from liaowang import store

WATCH = {"name": "RAG 框架", "source": "github", "target": "topic:rag", "min_stars": 500,
         "language": "", "days": 90, "per_page": 20, "note": ""}

ITEM = {"key": "gh:infiniflow/ragflow", "title": "infiniflow/ragflow", "url": "https://github.com/infiniflow/ragflow",
        "summary": "RAG engine", "source": "github", "stars": 94645, "published": "2026-11-24",
        "extra": {"language": "Python"}}


class TestWatch(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.conn = store.connect(os.path.join(self.dir, "t.db"))

    def tearDown(self):
        self.conn.close()

    def test_add_and_list(self):
        wid = store.add_watch(self.conn, **{k: v for k, v in WATCH.items()})
        self.assertEqual(wid, 1)
        rows = store.list_watches(self.conn)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["name"], "RAG 框架")
        self.assertEqual(rows[0]["n"], 0)

    def test_delete_cascades(self):
        wid = store.add_watch(self.conn, **WATCH)
        store.save_items(self.conn, wid, [ITEM])
        store.save_run(self.conn, wid, 1, 1, 1, 0, "一句话")
        store.delete_watch(self.conn, wid)
        self.assertIsNone(store.get_watch(self.conn, wid))
        self.assertEqual(store.list_items(self.conn), [])
        self.assertEqual(store.list_runs(self.conn), [])

    def test_mark_scanned(self):
        wid = store.add_watch(self.conn, **WATCH)
        store.mark_scanned(self.conn, wid)
        self.assertTrue(store.get_watch(self.conn, wid)["last_scan_at"])


class TestItems(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.conn = store.connect(os.path.join(self.dir, "t.db"))
        self.wid = store.add_watch(self.conn, **WATCH)

    def tearDown(self):
        self.conn.close()

    def test_save_returns_fresh(self):
        fresh = store.save_items(self.conn, self.wid, [ITEM])
        self.assertEqual(len(fresh), 1)
        self.assertIn("id", fresh[0])

    def test_same_key_not_twice(self):
        store.save_items(self.conn, self.wid, [ITEM])
        again = store.save_items(self.conn, self.wid, [ITEM])
        self.assertEqual(again, [])
        self.assertEqual(len(store.list_items(self.conn)), 1)

    def test_same_key_different_watch_allowed(self):
        wid2 = store.add_watch(self.conn, **{**WATCH, "name": "别的主题"})
        store.save_items(self.conn, self.wid, [ITEM])
        store.save_items(self.conn, wid2, [ITEM])
        self.assertEqual(len(store.list_items(self.conn)), 2)

    def test_verdict_and_order(self):
        items = [
            {**ITEM, "key": "gh:a", "title": "A"},
            {**ITEM, "key": "gh:b", "title": "B"},
        ]
        fresh = store.save_items(self.conn, self.wid, items)
        store.set_verdict(self.conn, fresh[0]["id"], 40, "教程聚合", "清单而已", "skip")
        store.set_verdict(self.conn, fresh[1]["id"], 90, "RAG 引擎", "值得看", "keep")
        rows = store.list_items(self.conn)
        self.assertEqual([r["title"] for r in rows], ["B", "A"])

    def test_filter_by_watch_and_verdict(self):
        fresh = store.save_items(self.conn, self.wid, [{**ITEM, "key": "gh:a"}])
        store.set_verdict(self.conn, fresh[0]["id"], 90, "x", "y", "keep")
        self.assertEqual(len(store.list_items(self.conn, verdict="keep")), 1)
        self.assertEqual(len(store.list_items(self.conn, verdict="skip")), 0)
        self.assertEqual(len(store.list_items(self.conn, watch_id=999)), 0)

    def test_extra_json_roundtrip(self):
        store.save_items(self.conn, self.wid, [ITEM])
        row = store.list_items(self.conn)[0]
        self.assertEqual(row["extra"]["language"], "Python")

    def test_get_item(self):
        fresh = store.save_items(self.conn, self.wid, [ITEM])
        self.assertEqual(store.get_item(self.conn, fresh[0]["id"])["title"], "infiniflow/ragflow")
        self.assertIsNone(store.get_item(self.conn, 999))

    def test_stats(self):
        fresh = store.save_items(self.conn, self.wid, [{**ITEM, "key": "gh:a"}, {**ITEM, "key": "gh:b"}])
        store.set_verdict(self.conn, fresh[0]["id"], 90, "x", "y", "keep")
        store.save_run(self.conn, self.wid, 2, 2, 1, 0, "t")
        s = store.stats(self.conn)
        self.assertEqual(s["watches"], 1)
        self.assertEqual(s["items"], 2)
        self.assertEqual(s["kept"], 1)
        self.assertEqual(s["runs"], 1)

    def test_runs_list(self):
        store.save_run(self.conn, self.wid, 5, 3, 2, 1, "第一批")
        runs = store.list_runs(self.conn)
        self.assertEqual(runs[0]["fetched"], 5)
        self.assertEqual(runs[0]["takeaway"], "第一批")


if __name__ == "__main__":
    unittest.main()
