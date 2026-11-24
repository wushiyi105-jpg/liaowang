"""SQLite：监控项、抓到过的条目、每次扫描的记录。

去重是这里的核心：同一个仓库第二次被搜到，不该在简报里出现第二次。
键是 key（gh:owner/name 或 feed:归一化后的链接），跟 watch 绑在一起建唯一索引。
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from datetime import datetime

_LOCK = threading.Lock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS watches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'github',
    target TEXT NOT NULL,
    min_stars INTEGER NOT NULL DEFAULT 0,
    language TEXT NOT NULL DEFAULT '',
    days INTEGER NOT NULL DEFAULT 90,
    per_page INTEGER NOT NULL DEFAULT 20,
    note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    last_scan_at TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    watch_id INTEGER NOT NULL,
    key TEXT NOT NULL,
    title TEXT NOT NULL,
    url TEXT NOT NULL DEFAULT '',
    summary TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT '',
    stars INTEGER NOT NULL DEFAULT 0,
    published TEXT NOT NULL DEFAULT '',
    extra TEXT NOT NULL DEFAULT '{}',
    score INTEGER,
    tag TEXT NOT NULL DEFAULT '',
    why TEXT NOT NULL DEFAULT '',
    verdict TEXT NOT NULL DEFAULT 'new',
    seen_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_item_watch_key ON items(watch_id, key);
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    watch_id INTEGER NOT NULL,
    fetched INTEGER NOT NULL,
    fresh INTEGER NOT NULL,
    kept INTEGER NOT NULL,
    skipped INTEGER NOT NULL,
    takeaway TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
"""


def now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def connect(path: str = "data/liaowang.db") -> sqlite3.Connection:
    parent = os.path.dirname(os.path.abspath(path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


# ---------- 监控项 ----------
def add_watch(conn, name: str, source: str, target: str, min_stars: int = 0,
              language: str = "", days: int = 90, per_page: int = 20, note: str = "") -> int:
    with _LOCK:
        cur = conn.execute(
            """INSERT INTO watches(name, source, target, min_stars, language, days, per_page, note, created_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (name, source, target, min_stars, language, days, per_page, note, now()),
        )
        conn.commit()
        return cur.lastrowid


def list_watches(conn) -> list[dict]:
    rows = conn.execute(
        """SELECT w.*, (SELECT COUNT(*) FROM items i WHERE i.watch_id=w.id) n
           FROM watches w ORDER BY w.id"""
    ).fetchall()
    return [dict(r) for r in rows]


def get_watch(conn, watch_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM watches WHERE id=?", (watch_id,)).fetchone()
    return dict(row) if row else None


def delete_watch(conn, watch_id: int) -> None:
    with _LOCK:
        conn.execute("DELETE FROM items WHERE watch_id=?", (watch_id,))
        conn.execute("DELETE FROM runs WHERE watch_id=?", (watch_id,))
        conn.execute("DELETE FROM watches WHERE id=?", (watch_id,))
        conn.commit()


def mark_scanned(conn, watch_id: int) -> None:
    conn.execute("UPDATE watches SET last_scan_at=? WHERE id=?", (now(), watch_id))
    conn.commit()


# ---------- 条目 ----------
def save_items(conn, watch_id: int, items: list[dict]) -> list[dict]:
    """写入新条目，返回真正是新的那批（老的直接忽略）。"""
    fresh = []
    with _LOCK:
        for it in items:
            try:
                conn.execute(
                    """INSERT INTO items(watch_id, key, title, url, summary, source, stars, published, extra, seen_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?)""",
                    (
                        watch_id, it["key"], it["title"], it.get("url", ""), it.get("summary", ""),
                        it.get("source", ""), int(it.get("stars") or 0), it.get("published", ""),
                        json.dumps(it.get("extra") or {}, ensure_ascii=False), now(),
                    ),
                )
            except sqlite3.IntegrityError:
                continue  # 见过，跳过
            fresh.append({**it, "id": conn.execute("SELECT last_insert_rowid() i").fetchone()["i"]})
        conn.commit()
    return fresh


def set_verdict(conn, item_id: int, score: int | None, tag: str, why: str, verdict: str) -> None:
    conn.execute(
        "UPDATE items SET score=?, tag=?, why=?, verdict=? WHERE id=?",
        (score, tag, why, verdict, item_id),
    )
    conn.commit()


def list_items(conn, watch_id: int | None = None, verdict: str | None = None, limit: int = 100) -> list[dict]:
    sql = "SELECT * FROM items WHERE 1=1"
    args: list = []
    if watch_id is not None:
        sql += " AND watch_id=?"
        args.append(watch_id)
    if verdict:
        sql += " AND verdict=?"
        args.append(verdict)
    sql += " ORDER BY COALESCE(score, -1) DESC, stars DESC, id DESC LIMIT ?"
    args.append(limit)
    rows = conn.execute(sql, args).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["extra"] = json.loads(d["extra"] or "{}")
        out.append(d)
    return out


def get_item(conn, item_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()
    if not row:
        return None
    d = dict(row)
    d["extra"] = json.loads(d["extra"] or "{}")
    return d


# ---------- 扫描记录 ----------
def save_run(conn, watch_id: int, fetched: int, fresh: int, kept: int, skipped: int, takeaway: str = "") -> int:
    with _LOCK:
        cur = conn.execute(
            """INSERT INTO runs(watch_id, fetched, fresh, kept, skipped, takeaway, created_at)
               VALUES (?,?,?,?,?,?,?)""",
            (watch_id, fetched, fresh, kept, skipped, takeaway, now()),
        )
        conn.commit()
        return cur.lastrowid


def list_runs(conn, limit: int = 20) -> list[dict]:
    rows = conn.execute("SELECT * FROM runs ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]


def stats(conn) -> dict:
    w = conn.execute("SELECT COUNT(*) n FROM watches").fetchone()["n"]
    i = conn.execute("SELECT COUNT(*) n FROM items").fetchone()["n"]
    kept = conn.execute("SELECT COUNT(*) n FROM items WHERE verdict='keep'").fetchone()["n"]
    skipped = conn.execute("SELECT COUNT(*) n FROM items WHERE verdict='skip'").fetchone()["n"]
    runs = conn.execute("SELECT COUNT(*) n FROM runs").fetchone()["n"]
    return {"watches": w, "items": i, "kept": kept, "skipped": skipped, "runs": runs}
