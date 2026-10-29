"""Generic adapter: read a web page (and, if asked, its inner pages on the same
site) and collect direct file links, plus YouTube videos the pages embed
(those become watch LINKS for the link tracker, never downloads). Plain HTML
only: links that a page builds with JavaScript are not seen; `explain()` says
in plain words why a site gave nothing."""
import os
import re
import time
from html.parser import HTMLParser
from urllib import robotparser
from urllib.parse import urljoin, urlparse, unquote, urldefrag

from .base import Item
from ..util import UA, http, safe_name
from ..security import safe_request
from .. import youtube_tracker

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


def youtube_items(html: str, page_url: str, title: str = ""):
    """YouTube videos a page embeds, as link-only items (kind "youtube")."""
    return [Item(id="yt:" + vid, url=f"https://www.youtube.com/watch?v={vid}", filename=vid,
                 caption=title or "YouTube video", kind="youtube")
            for vid in youtube_tracker.video_ids_from_html(html)]


def has_content(html: str, page_url: str) -> bool:
    return bool(extract_links(html, page_url) or youtube_tracker.video_ids_from_html(html))


def items_from_html(html: str, page_url: str, title: str = ""):
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
    return items + youtube_items(html, page_url, title)


# ------------------------------------------------------------------ same-site crawl

MAX_DEPTH = 5
DEFAULT_MAX_PAGES = 60
SKIP_EXTS = {".css", ".js", ".mjs", ".json", ".xml", ".rss", ".atom", ".txt", ".ico", ".png", ".jpg", ".jpeg",
             ".gif", ".svg", ".webp", ".avif", ".bmp", ".woff", ".woff2", ".ttf", ".otf", ".eot", ".map", ".m3u8", ".mpd"}
SKIP_WORDS = re.compile(r"(log-?in|log-?out|sign-?in|sign-?up|signout|register|auth|account|password|cart|checkout|"
                        r"wp-admin|wp-login|admin|feed|share|print)", re.I)


CHROME_TAGS = {"nav", "header", "footer", "aside"}


class _PageParser(HTMLParser):
    """<a href> links (each marked: inside the page's menu/header/footer or in
    its main content) and the <title>."""
    def __init__(self):
        super().__init__()
        self.hrefs, self.title, self._in_title, self._chrome = [], "", False, 0

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            for k, v in attrs:
                if k == "href" and v:
                    self.hrefs.append((v.strip(), self._chrome > 0))
        elif tag == "title":
            self._in_title = True
        elif tag in CHROME_TAGS:
            self._chrome += 1

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
        elif tag in CHROME_TAGS and self._chrome:
            self._chrome -= 1

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


def page_links(html: str, page_url: str, site_url: str, prefixes=None, content_only=False):
    """Inner pages to visit: <a href> on the same host, under one of the
    allowed path prefixes (default: the added URL's folder), not
    files/assets/login pages. prefixes=() + content_only=True: any path on the
    host, but only links in the page's main content (not menu/header/footer)."""
    p = _PageParser()
    p.feed(html)
    host = _host(site_url)
    if prefixes is None:
        prefixes = (scope_prefix(site_url),)
    out, seen = [], set()
    for raw, in_chrome in p.hrefs:
        if raw.startswith(("javascript:", "mailto:", "tel:", "data:", "#")):
            continue
        if content_only and in_chrome:
            continue
        u, _ = urldefrag(urljoin(page_url, raw))
        pu = urlparse(u)
        if pu.scheme not in ("http", "https") or _host(u) != host:
            continue
        path = pu.path or "/"
        if prefixes and not any(path.startswith(px) or path + "/" == px for px in prefixes):
            continue
        ext = file_ext(u)
        if ext in EXTS or ext in SKIP_EXTS or SKIP_WORDS.search(pu.path + "?" + pu.query):
            continue
        if u not in seen and u != urldefrag(page_url)[0]:
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
    obey robots.txt. Smart stop: a page that already has files (or YouTube
    videos) is a finished branch, its links are not followed; only branches
    with nothing yet go deeper.
    Scope: pages under the added URL's folder. When the added page links to
    nothing in its folder (a listing page like /p/7/videos whose lectures live
    at /video-lectures/...), the links in its main content are followed
    instead (menu/header/footer links are not), and their folders join the
    scope."""
    depth = max(0, min(int(depth or 0), MAX_DEPTH))
    s = session or http()
    _, title0 = page_links(first_html, site_url, site_url)
    pages = [(site_url, first_html, title0)]
    if depth == 0:
        return pages
    rp = _robots(site_url, s)
    seen = {urldefrag(site_url)[0]}
    prefixes = [scope_prefix(site_url)]
    frontier = [(site_url, first_html)]
    for level in range(depth):
        nxt = []
        for page_url, html in frontier:
            if has_content(html, page_url):
                continue  # this branch found its files: don't go deeper here
            links, _ = page_links(html, page_url, site_url, prefixes)
            if level == 0 and not [u for u in links if u not in seen]:
                links, _ = page_links(html, page_url, site_url, (), content_only=True)
                for u in links:
                    px = scope_prefix(u)
                    if px != "/" and px not in prefixes:
                        prefixes.append(px)
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


# ------------------------------------------------------------------ "why 0?"

def explain(pages) -> str:
    """One plain Hinglish line on why these pages gave no file and no YouTube
    video. pages: [(url, html, title)]."""
    html = " ".join(h for _, h, _ in pages)[:3_000_000]
    low = html.lower()
    n_links = sum(len(_PageParser_hrefs(h)) for _, h, _ in pages[:1])
    if ".m3u8" in low or ".mpd" in low or "application/x-mpegurl" in low:
        return ("is site pe videos stream (m3u8/HLS) ke roop mein hain, file nahi. "
                "Bot streams download nahi karta, isliye 0.")
    js_app = ("self.__next_f" in html or 'id="__next"' in html or 'id="root"></div>' in html
              or 'id="app"></div>' in html or "__nuxt" in low or "ng-version" in low)
    if js_app and n_links < 15:
        return ("ye site JavaScript app hai: videos/PDF ki list page khulne ke baad JS se aati hai, "
                "HTML mein koi link nahi hota. Bot sirf seedhe HTML links padhta hai, isliye 0.")
    if re.search(r'type=["\']password["\']', low) or "please login" in low or "please log in" in low:
        return "content login ke peeche lagta hai. Bot login nahi karta, isliye 0."
    return (f"{len(pages)} page(s) dekhe, kisi pe seedha file link (.mp4/.pdf/.apk/.zip…) "
            "ya YouTube video nahi mila.")


def _PageParser_hrefs(html):
    p = _PageParser()
    try:
        p.feed(html)
    except Exception:
        return []
    return p.hrefs


# why the last list_items() of a site gave nothing (site url -> line), read by main.py
LAST_NOTES = {}


def list_items(site_url: str, html: str = None, depth: int = 0, max_pages: int = DEFAULT_MAX_PAGES, **kw):
    if html is None:
        html = http().get(site_url, timeout=30).text
    if not depth:
        pages = [(site_url, html, page_links(html, site_url, site_url)[1])]
    else:
        pages = crawl(site_url, html, depth, max_pages, **kw)
    out, seen = [], set()
    for page_url, body, title in pages:
        for it in items_from_html(body, page_url, title if page_url != site_url else ""):
            if it.id in seen:
                continue
            seen.add(it.id)
            if page_url != site_url and title and it.kind != "youtube":
                it.caption = f"{title[:80]} · {it.caption}"
            out.append(it)
    if out:
        LAST_NOTES.pop(site_url, None)
    else:
        LAST_NOTES[site_url] = explain(pages)
    return out
