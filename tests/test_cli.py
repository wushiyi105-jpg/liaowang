import contextlib
import io
import os
import tempfile
import unittest
from unittest import mock

from liaowang import cli, fetch, scan

ITEMS = [
    {"key": "gh:infiniflow/ragflow", "title": "infiniflow/ragflow", "url": "https://github.com/infiniflow/ragflow",
     "summary": "RAG engine", "source": "github", "stars": 94645, "published": "2026-11-24", "extra": {}},
]


class TestCli(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.db = os.path.join(self.dir, "cli.db")

    def run_cli(self, *args):
        buf, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(err):
            code = cli.main(["--db", self.db, *args])
        return code, buf.getvalue() + err.getvalue()

    def test_watch_add_and_list(self):
        code, out = self.run_cli("watch", "add", "RAG 框架", "--topic", "topic:rag", "--min-stars", "500")
        self.assertEqual(code, 0)
        self.assertIn("监控 [1]", out)
        _, out = self.run_cli("watch", "list")
        self.assertIn("RAG 框架", out)
        self.assertIn("topic:rag", out)

    def test_watch_list_empty_hint(self):
        _, out = self.run_cli("watch", "list")
        self.assertIn("还没有监控项", out)

    def test_scan_no_model(self):
        self.run_cli("watch", "add", "RAG", "--topic", "topic:rag")
        with mock.patch.object(scan.fetch, "fetch_source", return_value=ITEMS):
            code, out = self.run_cli("scan", "--no-model")
        self.assertEqual(code, 0)
        self.assertIn("抓到 1 条", out)
        self.assertIn("新的 1 条", out)

    def test_scan_without_watch(self):
        code, out = self.run_cli("scan")
        self.assertEqual(code, 1)
        self.assertIn("没有可扫的监控项", out)

    def test_scan_fetch_error_does_not_crash(self):
        self.run_cli("watch", "add", "RAG", "--topic", "topic:rag")
        with mock.patch.object(scan.fetch, "fetch_source", side_effect=fetch.FetchError("429 rate limit")):
            code, out = self.run_cli("scan", "--no-model")
        self.assertEqual(code, 0)
        self.assertIn("抓取失败", out)
        self.assertIn("429", out)

    def test_dry_run(self):
        self.run_cli("watch", "add", "RAG", "--topic", "topic:rag")
        with mock.patch.object(scan.fetch, "fetch_source", return_value=ITEMS):
            _, out = self.run_cli("scan", "--dry-run")
        self.assertIn("抓到 1 条", out)
        _, again = self.run_cli("brief")
        self.assertIn("还没有条目", again)

    def test_brief_after_scan(self):
        self.run_cli("watch", "add", "RAG", "--topic", "topic:rag")
        with mock.patch.object(scan.fetch, "fetch_source", return_value=ITEMS):
            self.run_cli("scan", "--no-model")
        _, out = self.run_cli("brief")
        self.assertIn("共 1 条新条目", out)
        self.assertIn("未评分 1", out)

    def test_brief_markdown_out(self):
        self.run_cli("watch", "add", "RAG", "--topic", "topic:rag")
        with mock.patch.object(scan.fetch, "fetch_source", return_value=ITEMS):
            self.run_cli("scan", "--no-model")
        out_path = os.path.join(self.dir, "简报.md")
        self.run_cli("brief", "--out", out_path)
        self.assertTrue(os.path.isfile(out_path))
        with open(out_path, encoding="utf-8") as f:
            self.assertIn("情报简报", f.read())

    def test_show_and_runs(self):
        self.run_cli("watch", "add", "RAG", "--topic", "topic:rag")
        with mock.patch.object(scan.fetch, "fetch_source", return_value=ITEMS):
            self.run_cli("scan", "--no-model")
        _, out = self.run_cli("show", "1")
        self.assertIn("infiniflow/ragflow", out)
        self.assertIn("未评分", out)
        _, runs = self.run_cli("runs")
        self.assertIn("抓 1", runs)

    def test_show_missing(self):
        code, out = self.run_cli("show", "99")
        self.assertEqual(code, 1)
        self.assertIn("没有 id=99", out)

    def test_rm(self):
        self.run_cli("watch", "add", "RAG", "--topic", "topic:rag")
        _, out = self.run_cli("watch", "rm", "1")
        self.assertIn("已删除", out)
        _, listing = self.run_cli("watch", "list")
        self.assertIn("还没有监控项", listing)

    def test_stats(self):
        self.run_cli("watch", "add", "RAG", "--topic", "topic:rag")
        _, out = self.run_cli("stats")
        self.assertIn("watches", out)


if __name__ == "__main__":
    unittest.main()
