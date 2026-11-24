"""命令行入口。"""

from __future__ import annotations

import argparse
import json
import os

from . import brief, llm, scan, store


def _open(args):
    return store.connect(args.db)


def cmd_watch_add(args) -> int:
    conn = _open(args)
    wid = store.add_watch(
        conn, args.name, args.source, args.topic,
        min_stars=args.min_stars, language=args.language or "",
        days=args.days, per_page=args.per_page, note=args.note or "",
    )
    print(f"· 监控 [{wid}] {args.name} —— {args.source}: {args.topic}")
    print(f"  跑一次：python -m liaowang scan --id {wid}")
    return 0


def cmd_watch_list(args) -> int:
    conn = _open(args)
    rows = store.list_watches(conn)
    if not rows:
        print("还没有监控项。先看 samples/ 里的示例，或者：")
        print('  python -m liaowang watch add rag --source github --topic "topic:rag" --min-stars 200')
        return 0
    print(f"{'ID':<4}{'条目':<6}{'源':<9}{'主题':<28}名字")
    for r in rows:
        print(f"{r['id']:<4}{r['n']:<6}{r['source']:<9}{r['target'][:26]:<28}{r['name']}")
        if r["last_scan_at"]:
            print(f"    上次扫描 {r['last_scan_at']}")
    return 0


def cmd_watch_rm(args) -> int:
    conn = _open(args)
    store.delete_watch(conn, args.id)
    print(f"· 监控 [{args.id}] 已删除（含条目与扫描记录）")
    return 0


def cmd_scan(args) -> int:
    conn = _open(args)
    watches = [store.get_watch(conn, args.id)] if args.id else store.list_watches(conn)
    watches = [w for w in watches if w]
    if not watches:
        print("没有可扫的监控项。先 python -m liaowang watch add ...")
        return 1

    cfg = None if args.no_model else llm.config_from_args(args)
    total = {"fetched": 0, "fresh": 0, "kept": 0, "skipped": 0}
    for w in watches:
        print(f"\n=== 扫描 [{w['id']}] {w['name']} ===")
        try:
            result = scan.scan(conn, w, config=cfg, batch_size=args.batch, dry_run=args.dry_run, token=args.gh_token)
        except Exception as e:  # noqa: BLE001  一个源挂了不该拖垮整轮
            print(f"! 抓取失败：{e}")
            continue
        print(f"抓到 {result['fetched']} 条，新的 {result['fresh']} 条，"
              f"值得看 {result['kept']}，过滤 {result['skipped']}")
        if result["error"]:
            print(f"! 模型评分没跑成：{result['error']}（条目已入库，标成未评分）")
        if result["takeaway"]:
            print(f"一句话：{result['takeaway']}")
        for k in total:
            total[k] += result.get(k, 0)

    if len(watches) > 1:
        print(f"\n合计：抓到 {total['fetched']}，新 {total['fresh']}，值得看 {total['kept']}，过滤 {total['skipped']}")
    print("\n看简报：python -m liaowang brief")
    return 0


def cmd_brief(args) -> int:
    conn = _open(args)
    items = store.list_items(conn, watch_id=args.id, limit=200)
    if not items:
        print("库里还没有条目。先 scan 一次。")
        return 0

    if args.json:
        print(json.dumps({"items": brief.pick(items, args.min_score, args.limit)}, ensure_ascii=False, indent=2))
        return 0

    runs = store.list_runs(conn, limit=3)
    takeaway = runs[0]["takeaway"] if runs else ""
    watch = store.get_watch(conn, args.id) if args.id else None
    title = watch["name"] if watch else "全部监控"

    text = brief.render_console(items, min_score=args.min_score, limit=args.limit)
    print(f"\n=== {title} · 简报 ===\n")
    if takeaway:
        print(f"一句话：{takeaway}\n")
    print(text)

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(brief.render_markdown(items, title, takeaway, args.min_score, args.limit))
        print(f"\n简报已写到 {args.out}")
    return 0


def cmd_show(args) -> int:
    conn = _open(args)
    it = store.get_item(conn, args.id)
    if not it:
        print(f"✗ 没有 id={args.id} 的条目")
        return 1
    print(f"\n=== [{it['id']}] {it['title']} ===")
    print(f"来源：{it['source']} · {it['stars']} star · 更新时间 {it['published'] or '—'}")
    print(f"链接：{it['url']}")
    print(f"描述：{it['summary'] or '（无）'}")
    print(f"评分：{it['score'] if it['score'] is not None else '未评分'} · {it['tag'] or '—'} · {it['verdict']}")
    print(f"为什么：{it['why'] or '—'}")
    if it["extra"]:
        print(f"其它：{it['extra']}")
    return 0


def cmd_runs(args) -> int:
    conn = _open(args)
    rows = store.list_runs(conn, limit=args.limit)
    if not rows:
        print("还没有扫描记录。")
        return 0
    for r in rows:
        print(f"{r['created_at']}  监控[{r['watch_id']}]  抓 {r['fetched']} 新 {r['fresh']} "
              f"留 {r['kept']} 过滤 {r['skipped']}")
        if r["takeaway"]:
            print(f"    {r['takeaway'][:150]}")
    return 0


def cmd_stats(args) -> int:
    conn = _open(args)
    print("统计：", store.stats(conn))
    return 0


def cmd_serve(args) -> int:
    from . import web

    conn = _open(args)
    web.serve(conn, host=args.host, port=args.port)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="liaowang", description="情报简报：抓一批候选，判断哪几条值得看。")
    p.add_argument("--db", default="data/liaowang.db")
    p.add_argument("--version", action="version", version="%(prog)s 0.1.0")
    p.add_argument("--api-key")
    p.add_argument("--base-url")
    p.add_argument("--model")
    sub = p.add_subparsers(dest="cmd", required=True)

    w = sub.add_parser("watch", help="监控项管理")
    wsub = w.add_subparsers(dest="wcmd", required=True)

    wa = wsub.add_parser("add", help="加一个监控")
    wa.add_argument("name")
    wa.add_argument("--source", choices=["github", "rss"], default="github")
    wa.add_argument("--topic", required=True, help="github 传搜索词（如 topic:rag），rss 传地址")
    wa.add_argument("--min-stars", type=int, default=0)
    wa.add_argument("--language", default="")
    wa.add_argument("--days", type=int, default=90)
    wa.add_argument("--per-page", type=int, default=20)
    wa.add_argument("--note", default="")
    wa.set_defaults(func=cmd_watch_add)

    wsub.add_parser("list", help="列出监控").set_defaults(func=cmd_watch_list)

    wr = wsub.add_parser("rm", help="删一个监控")
    wr.add_argument("id", type=int)
    wr.set_defaults(func=cmd_watch_rm)

    s = sub.add_parser("scan", help="跑扫描")
    s.add_argument("--id", type=int)
    s.add_argument("--batch", type=int, default=6, help="每批交给模型多少条")
    s.add_argument("--dry-run", action="store_true", help="只抓不入库、不评分")
    s.add_argument("--no-model", action="store_true", help="只抓入库，全部标未评分")
    s.add_argument("--gh-token", default=os.environ.get("GITHUB_TOKEN"))
    s.set_defaults(func=cmd_scan)

    b = sub.add_parser("brief", help="打印简报")
    b.add_argument("--id", type=int)
    b.add_argument("--min-score", type=int, default=60)
    b.add_argument("--limit", type=int, default=10)
    b.add_argument("--json", action="store_true")
    b.add_argument("--out", help="写成 markdown")
    b.set_defaults(func=cmd_brief)

    sh = sub.add_parser("show", help="看一条的详情")
    sh.add_argument("id", type=int)
    sh.set_defaults(func=cmd_show)

    r = sub.add_parser("runs", help="扫描历史")
    r.add_argument("--limit", type=int, default=20)
    r.set_defaults(func=cmd_runs)

    sub.add_parser("stats", help="统计").set_defaults(func=cmd_stats)

    sv = sub.add_parser("serve", help="起 Web")
    sv.add_argument("--host", default="127.0.0.1")
    sv.add_argument("--port", type=int, default=8769)
    sv.set_defaults(func=cmd_serve)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)
