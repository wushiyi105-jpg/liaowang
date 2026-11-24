"""扫描与评分：抓一批，去掉见过的，剩下的交给模型判断值不值得看。

模型在这里只做一件事：给每条打分并说一句为什么。不写简报、不下结论、不排序——
排序和阈值都在程序这边，方便你自己改。

失败策略很明确：模型挂了，条目照样入库，标成 unscored。情报工具最怕的不是没评分，
是抓到了却因为一次接口 429 把它扔了。
"""

from __future__ import annotations

from . import fetch, llm, store

SYSTEM = """你在帮一个做产品的人整理技术情报，他要的是"这条值不值得花十分钟看"。

对每条候选，给：
- n：编号，和输入一致
- score：0–100 的相关度与信息价值。跟主题不沾边、只是名字撞词的，给 20 以下
- tag：两到四个字，说明它是什么（如「RAG 框架」「数据处理」「教程聚合」「噪音」）
- why：一句话，说清为什么值得看或者不值得看，不要复述标题
- keep：true 表示值得进简报，false 表示过滤掉

判断标准：
- 教程合集、awesome 清单、纯目录站，keep=false，tag 写「清单聚合」
- 描述为空、说不清做什么的，分数压低
- 跟主题只是字面相近、实际不相关的，keep=false
- 真正能解决具体问题、最近还在更新的，给高分

只输出 JSON：
{"items": [{"n": 1, "score": 0, "tag": "", "why": "", "keep": false}], "takeaway": "三句话以内，说这批候选整体什么情况"}
不要把没见过的条目凑数，也不要给所有条目同一个分数。"""


def _clip(s: str, n: int) -> str:
    return s if len(s) <= n else s[: n - 1] + "…"


def score_batch(watch: dict, items: list[dict], config=None, max_tokens: int = 8000) -> dict:
    """给一批（建议 ≤8 条）打分。返回 {scores: {key: {...}}, takeaway, error}。"""
    lines = []
    for i, it in enumerate(items, 1):
        meta = ""
        if it.get("stars"):
            meta += f"，{it['stars']} star"
        if it.get("published"):
            meta += f"，最近更新 {it['published']}"
        lines.append(f"{i}. {it['title']}（{meta.lstrip('，') or '无元信息'}）\n   {_clip(it.get('summary','') or '（没有描述）', 120)}")

    user = (
        f"【监控主题】{watch['name']}｜{watch['target']}"
        + (f"｜说明：{watch['note']}" if watch.get("note") else "")
        + "\n\n【候选】\n" + "\n".join(lines) + "\n\n按要求输出 JSON。"
    )
    try:
        raw = llm.chat(
            [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}],
            config=config, temperature=0.2, max_tokens=max_tokens,
        )
        data = llm.extract_json(raw)
        if not isinstance(data, dict):
            raise llm.LLMError("返回不是对象")
    except llm.LLMError as e:
        return {"scores": {}, "takeaway": "", "error": str(e)}

    scores: dict[str, dict] = {}
    for row in data.get("items") or []:
        try:
            n = int(row.get("n"))
        except (TypeError, ValueError):
            continue
        if not (1 <= n <= len(items)):
            continue  # 编号越界：模型自己编的，不认
        try:
            value = max(0, min(100, int(float(row.get("score")))))
        except (TypeError, ValueError):
            value = None
        scores[items[n - 1]["key"]] = {
            "score": value,
            "tag": str(row.get("tag") or "")[:8],
            "why": str(row.get("why") or "")[:200],
            "keep": bool(row.get("keep")) and value is not None and value >= 60,
        }
    return {"scores": scores, "takeaway": str(data.get("takeaway") or "")[:300], "error": ""}


def scan(conn, watch: dict, config=None, batch_size: int = 6, dry_run: bool = False,
         token: str | None = None) -> dict:
    """跑一次扫描：抓 → 去重入库 → 分批打分 → 写记录。"""
    items = fetch.fetch_source(
        watch["source"], watch["target"],
        min_stars=watch["min_stars"], language=watch["language"] or None,
        days=watch["days"], per_page=watch["per_page"], token=token,
    )
    if dry_run:
        return {"fetched": len(items), "fresh": 0, "kept": 0, "skipped": 0, "takeaway": "", "items": items, "error": ""}

    fresh = store.save_items(conn, watch["id"], items)
    kept = skipped = 0
    takeaways: list[str] = []
    error = ""

    if fresh and config is not None:
        for start in range(0, len(fresh), batch_size):
            chunk = fresh[start:start + batch_size]
            result = score_batch(watch, chunk, config=config)
            if result["error"]:
                error = result["error"]
                for it in chunk:
                    store.set_verdict(conn, it["id"], None, "", "", "unscored")
                continue
            if result["takeaway"] and not takeaways:
                # 只留第一批的说法。分批时每批各说各的，拼起来会自相矛盾——
                # 一批说"真正对口的是 ragflow"，另一批说"没有一个是纯 RAG 框架"。
                # 按 star 排序，第一批就是最重要的那批候选。
                takeaways.append(result["takeaway"])
            for it in chunk:
                s = result["scores"].get(it["key"])
                if not s or s["score"] is None:
                    store.set_verdict(conn, it["id"], None, "", "", "unscored")
                    continue
                verdict = "keep" if s["keep"] else "skip"
                if verdict == "keep":
                    kept += 1
                else:
                    skipped += 1
                store.set_verdict(conn, it["id"], s["score"], s["tag"], s["why"], verdict)
    else:
        for it in fresh:
            store.set_verdict(conn, it["id"], None, "", "", "unscored")

    takeaway = " / ".join(takeaways)[:600]
    store.save_run(conn, watch["id"], len(items), len(fresh), kept, skipped, takeaway)
    store.mark_scanned(conn, watch["id"])
    return {
        "fetched": len(items),
        "fresh": len(fresh),
        "kept": kept,
        "skipped": skipped,
        "takeaway": takeaway,
        "error": error,
        "items": fresh,
    }
