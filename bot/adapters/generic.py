"""Generic adapter: read one web page and collect direct file links."""
import os
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse, unquote, urldefrag

from .base import Item
from ..util import http, safe_name

# file types the bot picks up (page icons/screenshots/logs are deliberately not included)
EXTS = {
    ".apk", ".apks", ".xapk", ".aab",
    ".mp4", ".mkv", ".webm", ".mov", ".avi", ".3gp",
    ".mp3", ".m4a", ".aac", ".wav", ".ogg", ".flac",
    ".pdf", ".zip", ".rar", ".7z",
    ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".epub",
}
# only these tags count as "a file on the page" (not <img>, <link rel=icon>, <script>)
FILE_TAGS = {"a", "video", "audio", "source", "embed", "object", "iframe", "button", "div", "span", "li"}
VIDEO_EXTS = {".mp4", ".mov", ".webm", ".mkv"}


class _LinkParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []

    def handle_starttag(self, tag, attrs):
        if tag not in FILE_TAGS:
            return
        for k, v in attrs:
            if k in ("href", "src", "data-src", "data-href", "data-url") and v:
                self.links.append(v.strip())


def file_ext(url: str) -> str:
    path = unquote(urlparse(url).path).lower()
    _, ext = os.path.splitext(path)
    return ext


def extract_links(html: str, page_url: str):
    p = _LinkParser()
    p.feed(html)
    seen, out = set(), []
    for raw in p.links:
        if raw.startswith(("javascript:", "mailto:", "data:", "#")):
            continue
        absu, _ = urldefrag(urljoin(page_url, raw))
        if urlparse(absu).scheme not in ("http", "https"):
            continue
        if file_ext(absu) not in EXTS:
            continue
        if absu in seen:
            continue
        seen.add(absu)
        out.append(absu)
    return out


def items_from_html(html: str, page_url: str):
    items = []
    for u in extract_links(html, page_url):
        ext = file_ext(u)
        base = os.path.basename(unquote(urlparse(u).path)) or "file" + ext
        items.append(Item(
            id="url:" + u,
            url=u,
            filename=safe_name(base),
            caption=base,
            headers={"Referer": page_url},
            kind="video" if ext in VIDEO_EXTS else "document",
        ))
    return items


def list_items(site_url: str, html: str = None):
    if html is None:
        html = http().get(site_url, timeout=30).text
    return items_from_html(html, site_url)
