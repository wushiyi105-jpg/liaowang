import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from unittest import mock

from liaowang import scan, store, web

ITEMS = [
    {"key": "gh:infiniflow/ragflow", "title": "infiniflow/ragflow", "url": "https://github.com/infiniflow/ragflow",
     "summary": "RAG engine", "source": "github", "stars": 94645, "published": "2026-11-24", "extra": {}},
]


class TestWeb(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp()
        cls.conn = store.connect(os.path.join(cls.dir, "web.db"))
        cls.httpd = web.make_server(cls.conn, port=0)
        cls.port = cls.httpd.server_address[1]
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.conn.close()

    def url(self, path):
        return f"http://127.0.0.1:{self.port}{path}"

    def get(self, path):
        with urllib.request.urlopen(self.url(path), timeout=10) as r:
            return r.status, r.read().decode("utf-8")

    def post(self, path, payload):
        req = urllib.request.Request(
            self.url(path), data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read().decode("utf-8"))

    def test_index(self):
        status, body = self.get("/")
        self.assertEqual(status, 200)
        self.assertIn("瞭望", body)

    def test_add_watch(self):
        _, data = self.post("/api/watch", {"name": "RAG 框架", "topic": "topic:rag", "min_stars": 500})
        self.assertIsInstance(data["id"], int)
        _, body = self.get("/api/watches")
        self.assertEqual(json.loads(body)["items"][0]["name"], "RAG 框架")

    def test_add_watch_requires_fields(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.post("/api/watch", {"name": "只有名字"})
        self.assertEqual(ctx.exception.code, 400)

    def test_scan_and_items(self):
        _, data = self.post("/api/watch", {"name": "扫一次", "topic": "topic:rag"})
        wid = data["id"]
        with mock.patch.object(scan.fetch, "fetch_source", return_value=ITEMS), \
             mock.patch("liaowang.llm.default_config", return_value={"api_key": "x", "base_url": "http://x", "model": "m"}), \
             mock.patch.object(scan, "score_batch", return_value={"scores": {}, "takeaway": "", "error": ""}):
            status, payload = self.post("/api/scan", {"id": wid})
        self.assertEqual(status, 200)
        self.assertEqual(payload["fetched"], 1)
        self.assertEqual(payload["fresh"], 1)
        _, body = self.get(f"/api/items?watch={wid}")
        self.assertEqual(len(json.loads(body)["items"]), 1)

    def test_skip(self):
        _, data = self.post("/api/watch", {"name": "跳过测试", "topic": "topic:rag"})
        wid = data["id"]
        fresh = store.save_items(self.conn, wid, [{**ITEMS[0], "key": "gh:x"}])
        _, payload = self.post("/api/skip", {"id": fresh[0]["id"]})
        self.assertTrue(payload["ok"])
        _, body = self.get(f"/api/items?watch={wid}")
        self.assertEqual(json.loads(body)["items"][0]["verdict"], "skip")

    def test_skip_bad_id(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.post("/api/skip", {"id": "abc"})
        self.assertEqual(ctx.exception.code, 400)

    def test_brief(self):
        _, payload = self.post("/api/brief", {})
        self.assertIn("text", payload)
        self.assertIn("counts", payload)

    def test_unknown_path(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.get("/api/nope")
        self.assertEqual(ctx.exception.code, 404)


if __name__ == "__main__":
    unittest.main()
