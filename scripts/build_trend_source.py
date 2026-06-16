#!/usr/bin/env python3
from __future__ import annotations

import email.utils
import json
import os
import re
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = Path(os.environ.get("TREND_SOURCE_CONFIG", ROOT / "config" / "sources.json"))
OUT = ROOT / "public" / "trendradar_source.json"
UA = "zhibo-trend-source/1.0 (+https://github.com/servagent-ai/zhibo-trend-source)"


def http_get(url: str, headers: dict[str, str] | None = None) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=20) as resp:  # noqa: S310
        return resp.read().decode("utf-8", errors="replace")


def parse_time(raw: str | None) -> int:
    if not raw:
        return int(time.time())
    try:
        return int(email.utils.parsedate_to_datetime(raw).timestamp())
    except Exception:
        return int(time.time())


def clean_html(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", value or "")).strip()


def child_text(item: ET.Element, tag: str) -> str:
    text = item.findtext(tag)
    if text:
        return text
    for child in list(item):
        if child.tag.rsplit("}", 1)[-1] == tag:
            return child.text or child.get("href") or ""
    return ""


def make_row(title: str, url: str, summary: str, platform: str, hot: int, rank: int, ts: int):
    title = " ".join((title or "").split())
    if not title:
        return None
    return {
        "title": title[:220],
        "url": (url or "").strip(),
        "summary": " ".join((summary or "").split())[:1500],
        "platform": platform,
        "hot": int(hot or 0),
        "rank": int(rank or 0),
        "timestamp": int(ts or time.time()),
    }


def fetch_rss(source_id: str, url: str):
    try:
        root = ET.fromstring(http_get(url))
    except Exception as exc:
        print(f"WARN rss {source_id}: {exc}")
        return []
    entries = list(root.iterfind(".//item")) or list(root.iterfind(".//{http://www.w3.org/2005/Atom}entry"))
    out = []
    for idx, item in enumerate(entries[:40], 1):
        title = child_text(item, "title")
        link = child_text(item, "link") or child_text(item, "id")
        desc = child_text(item, "description") or child_text(item, "summary") or child_text(item, "content")
        published = child_text(item, "pubDate") or child_text(item, "published") or child_text(item, "updated")
        row = make_row(title, link, clean_html(desc), source_id, max(1, 50 - idx), idx, parse_time(published))
        if row:
            out.append(row)
    return out


def fetch_google_news(query: str):
    q = urllib.parse.quote(query)
    rows = fetch_rss("googlenews", f"https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en")
    for item in rows:
        item["summary"] = f"{query} · {item.get('summary', '')}".strip(" ·")
    return rows


def fetch_hackernews(query: str):
    q = urllib.parse.quote(query)
    url = f"https://hn.algolia.com/api/v1/search?tags=story&query={q}&hitsPerPage=30"
    try:
        data = json.loads(http_get(url))
    except Exception as exc:
        print(f"WARN hn {query}: {exc}")
        return []
    out = []
    for hit in data.get("hits", []) or []:
        points = int(hit.get("points") or 0)
        if points < 50:
            continue
        row = make_row(
            hit.get("title") or "",
            hit.get("url") or f"https://news.ycombinator.com/item?id={hit.get('objectID')}",
            clean_html(hit.get("story_text") or ""),
            "hackernews",
            points,
            int(hit.get("num_comments") or 0),
            int(hit.get("created_at_i") or time.time()),
        )
        if row:
            out.append(row)
    return out


def fetch_github(query: str):
    q = urllib.parse.quote(query)
    headers = {"Accept": "application/vnd.github+json"}
    if os.environ.get("GITHUB_TOKEN"):
        headers["Authorization"] = f"Bearer {os.environ['GITHUB_TOKEN']}"
    url = f"https://api.github.com/search/repositories?q={q}&sort=stars&order=desc&per_page=30"
    try:
        data = json.loads(http_get(url, headers=headers))
    except Exception as exc:
        print(f"WARN github {query}: {exc}")
        return []
    out = []
    for repo in data.get("items", []) or []:
        row = make_row(
            repo.get("full_name") or "",
            repo.get("html_url") or "",
            repo.get("description") or "",
            "github",
            int(repo.get("stargazers_count") or 0),
            int(repo.get("forks_count") or 0),
            parse_time(repo.get("pushed_at")),
        )
        if row:
            out.append(row)
    return out


def dedupe(items):
    seen = set()
    out = []
    for item in sorted(items, key=lambda x: int(x.get("hot") or 0), reverse=True):
        key = (item.get("title") or "", item.get("url") or "")
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def main() -> int:
    cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
    items = []
    for query in cfg.get("google_news_queries", []):
        items.extend(fetch_google_news(query))
    for src in cfg.get("rss", []):
        items.extend(fetch_rss(src["id"], src["url"]))
    for query in cfg.get("github_queries", []):
        items.extend(fetch_github(query))
    for query in cfg.get("hackernews_queries", []):
        items.extend(fetch_hackernews(query))
    payload = {"generated_at": int(time.time()), "items": dedupe(items)[:500]}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {OUT} items={len(payload['items'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
