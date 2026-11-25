"""抓取：GitHub 搜索 + 通用 Atom/RSS。

为什么主源选 GitHub：它公开、返回结构化 JSON、不需要登录，而且"某个技术话题最近
冒出来什么"这件事，仓库列表比新闻更耐看。RSS 是备选，给愿意自己配源的人用。

这里只负责抓，不做判断——判断是 score.py 的事，规则是 store 的事。
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

UA = "liaowang/0.1 (+https://github.com/wushiyi105-jpg/liaowang)"


class FetchError(Exception):
    """抓取失败。"""


def _get(url: str, timeout: int = 30, token: str | None = None) -> bytes:
    headers = {"User-Agent": UA, "Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode("utf-8")[:200]
        except Exception:  # noqa: BLE001
            pass
        raise FetchError(f"接口返回 {e.code}: {detail or e.reason}") from e
    except urllib.error.URLError as e:
        raise FetchError(f"连不上 {url}: {e.reason}") from e


def _clean(text: str | None) -> str:
    """压掉多余空白，去掉 HTML 标签。"""
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", " ", text)
    text = text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"')
    return re.sub(r"\s+", " ", text).strip()


def github_search(topic: str, min_stars: int = 0, language: str | None = None,
                  days: int = 90, per_page: int = 20, token: str | None = None) -> list[dict]:
    """按话题搜仓库，只要最近 pushed 过的。返回统一结构的条目。"""
    since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
    q = f"{topic} stars:>={min_stars} pushed:>{since}"
    if language:
        q += f" language:{language}"
    url = "https://api.github.com/search/repositories?" + urllib.parse.urlencode({
        "q": q, "sort": "stars", "order": "desc", "per_page": min(per_page, 50),
    })
    raw = _get(url, token=token)
    try:
        data = json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as e:
        raise FetchError(f"返回不是 JSON: {raw[:120]!r}") from e

    items = []
    for repo in data.get("items") or []:
        full = repo.get("full_name") or ""
        items.append({
            "key": "gh:" + full.lower(),
            "title": full,
            "url": repo.get("html_url") or "",
            "summary": _clean(repo.get("description")),
            "source": "github",
            "stars": int(repo.get("stargazers_count") or 0),
            "published": (repo.get("pushed_at") or "")[:10],
            "extra": {
                "language": repo.get("language") or "",
                "forks": int(repo.get("forks_count") or 0),
                "open_issues": int(repo.get("open_issues_count") or 0),
                "topics": repo.get("topics") or [],
            },
        })
    return items


def parse_feed(xml_bytes: bytes, source: str = "rss") -> list[dict]:
    """解析 Atom 或 RSS 2.0。两种都当成「标题 + 链接 + 摘要 + 时间」。"""
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as e:
        raise FetchError(f"XML 解析失败: {e}") from e

    items = []

    for entry in root.iter():
        tag = entry.tag.split("}")[-1]
        if tag not in ("entry", "item"):
            continue
        title = link = summary = published = ""
        for child in entry:
            name = child.tag.split("}")[-1]
            if name == "title":
                title = _clean(child.text)
            elif name == "link":
                link = (child.text or "").strip() or child.attrib.get("href", "")
            elif name in ("summary", "description", "content"):
                summary = summary or _clean(child.text)
            elif name in ("published", "updated", "pubDate"):
                published = (child.text or "").strip()[:10]
        if not title:
            continue
        items.append({
            "key": "feed:" + re.sub(r"\W+", "", (link or title))[:60].lower(),
            "title": title,
            "url": link,
            "summary": summary[:400],
            "source": source,
            "stars": 0,
            "published": published,
            "extra": {},
        })
    return items


def fetch_feed(url: str, source: str = "rss", timeout: int = 30) -> list[dict]:
    return parse_feed(_get(url, timeout=timeout), source=source)


def fetch_source(source_type: str, target: str, **kw) -> list[dict]:
    """统一入口：source_type 是 github / rss。"""
    if source_type == "github":
        return github_search(
            target,
            min_stars=int(kw.get("min_stars") or 0),
            language=kw.get("language"),
            days=int(kw.get("days") or 90),
            per_page=int(kw.get("per_page") or 20),
            token=kw.get("token"),
        )
    if source_type == "rss":
        return fetch_feed(target, source=kw.get("source_name") or "rss")
    raise FetchError(f"不认识的数据源类型：{source_type}")
