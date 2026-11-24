"""简报：把一堆条目排成一份十分钟能看完的东西。

只做两件事：挑（按分数和阈值）和排（按分数、star、时间）。文字叙述交给模型在扫描
时说，简报这里不再让模型写一遍——多一次调用就多一次跑偏的机会。
"""

from __future__ import annotations

from datetime import datetime


def pick(items: list[dict], min_score: int = 60, limit: int = 10) -> list[dict]:
    """只留 keep 且分数够的，按分数从高到低。"""
    out = [i for i in items if i.get("verdict") == "keep" and (i.get("score") or 0) >= min_score]
    out.sort(key=lambda i: (-(i.get("score") or 0), -(i.get("stars") or 0), i.get("id") or 0))
    return out[:limit]


def counts(items: list[dict]) -> dict:
    return {
        "keep": sum(1 for i in items if i.get("verdict") == "keep"),
        "skip": sum(1 for i in items if i.get("verdict") == "skip"),
        "unscored": sum(1 for i in items if i.get("verdict") == "unscored"),
    }


def render_console(items: list[dict], min_score: int = 60, limit: int = 10) -> str:
    picked = pick(items, min_score=min_score, limit=limit)
    c = counts(items)
    head = (f"共 {len(items)} 条新条目：值得看 {c['keep']}、过滤 {c['skip']}、未评分 {c['unscored']}")
    lines = [head, ""]
    if not picked:
        lines.append("这次没有过线的条目。要么主题太窄，要么阈值（--min-score）开太高。")
        return "\n".join(lines)

    for n, it in enumerate(picked, 1):
        stars = f"{it['stars']} star" if it.get("stars") else ""
        meta = " · ".join(x for x in [it.get("tag", ""), stars, it.get("published", "")] if x)
        lines.append(f"{n}. [{it.get('score')}] {it['title']}" + (f"（{meta}）" if meta else ""))
        if it.get("why"):
            lines.append(f"   {it['why']}")
        if it.get("url"):
            lines.append(f"   {it['url']}")
        lines.append("")
    return "\n".join(lines).rstrip()


def render_markdown(items: list[dict], title: str, takeaway: str = "",
                    min_score: int = 60, limit: int = 10) -> str:
    picked = pick(items, min_score=min_score, limit=limit)
    c = counts(items)
    lines = [
        f"# {title} 情报简报",
        "",
        f"{datetime.now().strftime('%Y-%m-%d %H:%M')} · 新条目 {len(items)} 条 · "
        f"值得看 {c['keep']} · 过滤 {c['skip']} · 未评分 {c['unscored']}",
        "",
    ]
    if takeaway:
        lines += [f"> {takeaway}", ""]
    if not picked:
        lines.append("这次没有过线的条目。")
    for n, it in enumerate(picked, 1):
        stars = f" · {it['stars']} star" if it.get("stars") else ""
        lines += [
            f"## {n}. {it['title']}（{it.get('score')} 分）",
            "",
            f"- 标签：{it.get('tag') or '—'}{stars} · 更新 {it.get('published') or '—'}",
            f"- 为什么：{it.get('why') or '—'}",
            f"- 链接：{it.get('url') or '—'}",
            "",
        ]
    if c["skip"]:
        lines += ["## 被过滤掉的", ""]
        for it in [i for i in items if i.get("verdict") == "skip"][:20]:
            lines.append(f"- {it['title']}（{it.get('score') or '?'} 分）{it.get('why') or ''}")
        lines.append("")
    return "\n".join(lines).rstrip()
