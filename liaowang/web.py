"""Web：http.server 简报页。

左边是监控项和「扫一次」，右边是按分数排过序的卡片。点卡片上的「过滤掉」可以把
一条从简报里摘出去——模型判断不一定对，留个人工口子。
"""

from __future__ import annotations

import json
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import brief, llm, scan, store

PAGE = """<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>瞭望 · 情报简报</title>
<style>
*{box-sizing:border-box}
body{margin:0;background:#0b0f14;color:#c9d1d9;font:15px/1.6 -apple-system,"Segoe UI","Microsoft YaHei",sans-serif}
header{padding:16px 24px;border-bottom:1px solid #21262d;display:flex;align-items:baseline;gap:12px}
h1{margin:0;font-size:18px;color:#79c0ff;font-weight:600}
.sub{color:#8b949e;font-size:13px}
main{display:grid;grid-template-columns:300px 1fr;min-height:calc(100vh - 60px)}
aside{border-right:1px solid #21262d;padding:16px}
section{padding:20px 24px}
input,select{width:100%;background:#161b22;color:#c9d1d9;border:1px solid #30363d;border-radius:8px;
padding:7px 10px;font:14px inherit;margin-bottom:8px}
button{background:#1f6feb;color:#fff;border:0;border-radius:6px;padding:7px 12px;font:14px inherit;cursor:pointer}
button.ghost{background:#21262d;color:#c9d1d9}
button:disabled{opacity:.5}
.item{padding:10px;border:1px solid #21262d;border-radius:8px;margin-bottom:8px;background:#0d1117;cursor:pointer}
.item:hover{border-color:#30363d}
.item .t{font-weight:600}
.item .m{color:#8b949e;font-size:12px}
.card{border:1px solid #21262d;border-radius:10px;padding:14px;margin-bottom:14px;background:#0d1117}
.card h3{margin:0 0 6px;font-size:16px;color:#e6edf3}
.score{display:inline-block;background:#15321f;color:#7ee787;border-radius:10px;padding:1px 10px;font-size:13px;margin-right:8px}
.tag{display:inline-block;background:#1c2f3d;color:#79c0ff;border-radius:10px;padding:1px 10px;font-size:12px;margin-right:6px}
.k{color:#8b949e;font-size:13px}
a{color:#79c0ff;text-decoration:none}
a:hover{text-decoration:underline}
.empty{color:#8b949e}
</style></head><body>
<header><h1>瞭望</h1><span class="sub">抓一批候选，判断哪几条值得花十分钟看</span></header>
<main>
<aside>
  <input id="name" placeholder="监控名字，比如：RAG 框架">
  <input id="topic" placeholder="GitHub 搜索词，比如 topic:rag">
  <input id="stars" placeholder="最低 star（可留空）">
  <div style="display:flex;gap:8px;margin-bottom:18px">
    <button id="add">加监控</button>
  </div>
  <div id="list"></div>
</aside>
<section>
  <div style="display:flex;gap:8px;align-items:center;margin-bottom:14px">
    <button id="scanAll" class="ghost">扫全部</button>
    <span class="k" id="status"></span>
  </div>
  <div id="cards"><p class="empty">还没有条目。</p></div>
</section>
</main>
<script>
const $ = s => document.querySelector(s);
const esc = s => (s||'').replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
let currentWatch = null;

async function loadWatches(){
  const r = await fetch('/api/watches');
  const items = (await r.json()).items;
  $('#list').innerHTML = items.length ? items.map(w =>
    `<div class="item" data-id="${w.id}">
       <div class="t">${esc(w.name)}</div>
       <div class="m">${esc(w.source)} · ${esc(w.target)} · ${w.n} 条${w.last_scan_at?' · 上次 '+esc(w.last_scan_at.slice(5,16)):''}</div>
     </div>`).join('') : '<p class="empty">还没有监控项。</p>';
  document.querySelectorAll('.item').forEach(el => el.onclick = () => {
    currentWatch = +el.dataset.id; loadItems();
  });
}

async function loadItems(){
  const q = currentWatch ? '?watch=' + currentWatch : '';
  const r = await fetch('/api/items' + q);
  const items = (await r.json()).items;
  if(!items.length){ $('#cards').innerHTML = '<p class="empty">还没有条目。</p>'; return; }
  $('#cards').innerHTML = items.map(i => `<div class="card">
      <h3><span class="score">${i.score===null?'未评分':i.score}</span>${esc(i.title)}</h3>
      <div>${i.tag?`<span class="tag">${esc(i.tag)}</span>`:''}<span class="k">${i.stars?i.stars+' star · ':''}${esc(i.published||'')} · ${esc(i.verdict)}</span></div>
      <div style="margin:8px 0">${esc(i.why||i.summary||'')}</div>
      <div><a href="${esc(i.url)}" target="_blank" rel="noreferrer">${esc(i.url)}</a>
           <button class="ghost" data-skip="${i.id}" style="float:right">过滤掉</button></div>
    </div>`).join('');
  document.querySelectorAll('[data-skip]').forEach(b => b.onclick = async () => {
    await fetch('/api/skip', {method:'POST', body: JSON.stringify({id: +b.dataset.skip})});
    loadItems();
  });
}

$('#add').onclick = async () => {
  const name = $('#name').value.trim(), topic = $('#topic').value.trim();
  if(!name || !topic) return alert('名字和搜索词都要填');
  await fetch('/api/watch', {method:'POST', body: JSON.stringify({
    name, topic, min_stars: parseInt($('#stars').value || '0', 10) || 0
  })});
  $('#name').value=''; $('#topic').value=''; $('#stars').value='';
  loadWatches();
};

$('#scanAll').onclick = async () => {
  $('#scanAll').disabled = true; $('#status').textContent = '扫着…（要调模型，慢一点）';
  const r = await fetch('/api/scan', {method:'POST', body: JSON.stringify({id: currentWatch})});
  const d = await r.json();
  $('#scanAll').disabled = false;
  $('#status').textContent = d.error ? ('出错：' + d.error) : `抓 ${d.fetched} · 新 ${d.fresh} · 留 ${d.kept}`;
  loadWatches(); loadItems();
};
loadWatches(); loadItems();
</script></body></html>"""


class Handler(BaseHTTPRequestHandler):
    conn = None

    def log_message(self, fmt, *args):
        pass

    def _send(self, code, body: bytes, ctype: str):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def _body(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        try:
            return json.loads(self.rfile.read(n) or b"{}")
        except json.JSONDecodeError:
            return {}

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        qs = urllib.parse.parse_qs(parsed.query)
        if parsed.path == "/":
            self._send(200, PAGE.encode("utf-8"), "text/html; charset=utf-8")
            return
        if parsed.path == "/api/watches":
            self._json({"items": store.list_watches(self.conn)})
            return
        if parsed.path == "/api/items":
            wid = qs.get("watch", [None])[0]
            try:
                wid = int(wid) if wid else None
            except ValueError:
                wid = None
            self._json({"items": store.list_items(self.conn, watch_id=wid, limit=60)})
            return
        self._json({"error": "not found"}, 404)

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        body = self._body()

        if parsed.path == "/api/watch":
            name = (body.get("name") or "").strip()
            topic = (body.get("topic") or "").strip()
            if not name or not topic:
                self._json({"error": "名字和搜索词都要填"}, 400)
                return
            try:
                wid = store.add_watch(self.conn, name, "github", topic,
                                      min_stars=int(body.get("min_stars") or 0))
            except Exception as e:  # noqa: BLE001
                self._json({"error": repr(e)}, 500)
                return
            self._json({"id": wid})
            return

        if parsed.path == "/api/scan":
            wid = body.get("id")
            watches = [store.get_watch(self.conn, int(wid))] if wid else store.list_watches(self.conn)
            watches = [w for w in watches if w]
            total = {"fetched": 0, "fresh": 0, "kept": 0, "skipped": 0}
            error = ""
            for w in watches:
                try:
                    r = scan.scan(self.conn, w, config=llm.default_config())
                except Exception as e:  # noqa: BLE001
                    error = str(e)
                    continue
                for k in total:
                    total[k] += r.get(k, 0)
                error = error or r.get("error", "")
            self._json({**total, "error": error})
            return

        if parsed.path == "/api/skip":
            try:
                iid = int(body.get("id"))
            except (TypeError, ValueError):
                self._json({"error": "id 不合法"}, 400)
                return
            item = store.get_item(self.conn, iid)
            if item:
                store.set_verdict(self.conn, iid, item["score"], item["tag"], item["why"], "skip")
            self._json({"ok": True})
            return

        if parsed.path == "/api/brief":
            items = store.list_items(self.conn, limit=200)
            self._json({
                "text": brief.render_console(items),
                "counts": brief.counts(items),
            })
            return

        self._json({"error": "not found"}, 404)


def make_server(conn, host: str = "127.0.0.1", port: int = 8769) -> ThreadingHTTPServer:
    handler = type("BoundHandler", (Handler,), {"conn": conn})
    return ThreadingHTTPServer((host, port), handler)


def serve(conn, host: str = "127.0.0.1", port: int = 8769):
    httpd = make_server(conn, host, port)
    print(f"瞭望已起：http://{host}:{port}  （Ctrl+C 退出）")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n再见。")
    finally:
        httpd.server_close()
