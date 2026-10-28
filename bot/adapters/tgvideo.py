"""Adapter for Aditya's own video site type (e.g. https://videoclasses.vercel.app/).

The page loads a public catalog JSON (…/api/catalog). Each video is streamed from
{stream}/v/{cid}/{msg}?t={token}. The stream server only answers when the request
carries the site's own Referer, exactly like the site's player does.
"""
import re
from urllib.parse import quote, urlparse

from .base import Item
from ..util import http, safe_name

CATALOG_RE = re.compile(r"https://[A-Za-z0-9.-]+/api/catalog")
MARKERS = ("tgvideo.sites.tab.bot", "/api/catalog")


def detect(html: str) -> bool:
    return any(m in html for m in MARKERS)


def site_referer(site_url: str) -> str:
    p = urlparse(site_url)
    return f"{p.scheme}://{p.netloc}/"


def catalog_url_from_html(html: str) -> str:
    m = CATALOG_RE.search(html)
    return m.group(0) if m else "https://tgvideo.sites.tab.bot/api/catalog"


def items_from_catalog(data: dict, referer: str, include_test: bool = False):
    stream = (data.get("stream") or "https://tgvideo-stream.sites.tab.bot").rstrip("/")
    cat = data.get("catalog") or {}
    out = []
    for course in cat.get("courses", []):
        if course.get("test") and not include_test:
            continue
        cid = course.get("cid")
        cname = course.get("name", "")
        for folder in course.get("folders", []):
            fname = folder.get("name", "")
            for v in folder.get("videos", []):
                msg = v.get("msg")
                if cid is None or msg is None:
                    continue
                title = v.get("title") or f"video {msg}"
                url = f"{stream}/v/{cid}/{msg}?t={quote(str(v.get('t') or ''), safe='')}"
                out.append(Item(
                    id=f"tgvideo:{cid}:{msg}",
                    url=url,
                    filename=safe_name(title, f"video_{msg}") + ".mp4",
                    caption=" · ".join(x for x in (cname, fname, title) if x),
                    size=v.get("size"),
                    headers={"Referer": referer},
                    kind="video",
                ))
    return out


def list_items(site_url: str, html: str = None):
    s = http()
    if html is None:
        html = s.get(site_url, timeout=30).text
    data = s.get(catalog_url_from_html(html), timeout=30, headers={"Cache-Control": "no-cache"}).json()
    return items_from_catalog(data, site_referer(site_url))
