"""Generic adapter: read a web page (and, if asked, its inner pages on the same
site) and collect direct file links. Plain HTML only: links that a page builds
with JavaScript are not seen."""
import os
import re
import time
from html.parser import HTMLParser
from urllib import robotparser
from urllib.parse import urljoin, urlparse, unquote, urldefrag

from .base import Item
from ..util import UA, http, safe_name
from ..security import safe_request

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


# ------------------------------------------------------------------ same-site crawl

MAX_DEPTH = 5
DEFAULT_MAX_PAGES = 60
SKIP_EXTS = {".css", ".js", ".mjs", ".json", ".xml", ".rss", ".atom", ".txt", ".ico", ".png", ".jpg", ".jpeg",
             ".gif", ".svg", ".webp", ".avif", ".bmp", ".woff", ".woff2", ".ttf", ".otf", ".eot", ".map", ".m3u8", ".mpd"}
SKIP_WORDS = re.compile(r"(log-?in|log-?out|sign-?in|sign-?up|signout|register|auth|account|password|cart|checkout|"
                        r"wp-admin|wp-login|admin|feed|share|print)", re.I)


class _PageParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.hrefs, self.title, self._in_title = [], "", False

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            for k, v in attrs:
                if k == "href" and v:
                    self.hrefs.append(v.strip())
        elif tag == "title":
            self._in_title = True

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._in_title and len(self.title) < 200:
            self.title += data


def _host(u):
    h = urlparse(u).netloc.lower()
    return h[4:] if h.startswith("www.") else h


def scope_prefix(site_url: str) -> str:
    """Inner pages must be under this path ("/" = whole site)."""
    path = urlparse(site_url).path or "/"
    return path if path.endswith("/") else path.rsplit("/", 1)[0] + "/"


def page_links(html: str, page_url: str, site_url: str):
    """Inner pages to visit: <a href> on the same host, under the added URL's
    path, not files/assets/login pages."""
    p = _PageParser()
    p.feed(html)
    host, prefix = _host(site_url), scope_prefix(site_url)
    out, seen = [], set()
    for raw in p.hrefs:
        if raw.startswith(("javascript:", "mailto:", "tel:", "data:", "#")):
            continue
        u, _ = urldefrag(urljoin(page_url, raw))
        pu = urlparse(u)
        if pu.scheme not in ("http", "https") or _host(u) != host:
            continue
        if not (pu.path or "/").startswith(prefix) and (pu.path or "/") + "/" != prefix:
            continue
        ext = file_ext(u)
        if ext in EXTS or ext in SKIP_EXTS or SKIP_WORDS.search(pu.path + "?" + pu.query):
            continue
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out, " ".join(p.title.split())


def _robots(site_url, session):
    rp = robotparser.RobotFileParser()
    pu = urlparse(site_url)
    try:
        r = safe_request(f"{pu.scheme}://{pu.netloc}/robots.txt", session=session, timeout=15)
        if r.status_code >= 400:
            return None  # no robots.txt: allowed
        rp.parse(r.text.splitlines())
        return rp
    except Exception:
        return None


def crawl(site_url: str, first_html: str, depth: int, max_pages: int = DEFAULT_MAX_PAGES,
          delay: float = 0.5, session=None, sleep=time.sleep):
    """Breadth-first visit of inner pages. Returns [(page_url, html, title)].
    The added URL itself is always read (the owner asked for it); inner pages
    obey robots.txt. Smart stop: a page that already has file links is a
    finished branch, its links are not followed; only branches with no files
    yet go deeper."""
    depth = max(0, min(int(depth or 0), MAX_DEPTH))
    s = session or http()
    _, title0 = page_links(first_html, site_url, site_url)
    pages = [(site_url, first_html, title0)]
    if depth == 0:
        return pages
    rp = _robots(site_url, s)
    seen = {urldefrag(site_url)[0]}
    frontier = [(site_url, first_html)]
    for _level in range(depth):
        nxt = []
        for page_url, html in frontier:
            if extract_links(html, page_url):
                continue  # this branch found its files: don't go deeper here
            links, _ = page_links(html, page_url, site_url)
            for u in links:
                if u in seen or len(pages) >= max_pages:
                    continue
                seen.add(u)
                if rp is not None and not rp.can_fetch(UA, u):
                    continue
                sleep(delay)
                try:
                    r = safe_request(u, session=s, timeout=20, headers={"Referer": page_url})
                except Exception:
                    continue
                if r.status_code != 200 or "html" not in r.headers.get("Content-Type", "text/html"):
                    continue
                body = r.text
                pages.append((u, body, page_links(body, u, site_url)[1]))
                nxt.append((u, body))
        frontier = nxt
        if not frontier or len(pages) >= max_pages:
            break
    return pages


def list_items(site_url: str, html: str = None, depth: int = 0, max_pages: int = DEFAULT_MAX_PAGES, **kw):
    if html is None:
        html = http().get(site_url, timeout=30).text
    if not depth:
        return items_from_html(html, site_url)
    out, seen = [], set()
    for page_url, body, title in crawl(site_url, html, depth, max_pages, **kw):
        for it in items_from_html(body, page_url):
            if it.id in seen:
                continue
            seen.add(it.id)
            if page_url != site_url and title:
                it.caption = f"{title[:80]} · {it.caption}"
            out.append(it)
    return out
