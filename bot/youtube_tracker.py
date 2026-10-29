"""Public YouTube channel/playlist link tracker.

This module deliberately tracks public metadata and posts watch links only. It
does not download YouTube media, extract stream URLs, or bypass DRM/access
controls. No YouTube Data API key is required: it reads the public playlist /
channel page (the list YouTube itself shows) and falls back to the public RSS
feed. YouTube may change or rate-limit those pages.
"""
import json
import re
import xml.etree.ElementTree as ET
from urllib.parse import parse_qs, urlparse

from .util import http
from .security import safe_request

YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com",
                 "youtube-nocookie.com", "www.youtube-nocookie.com"}
VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
CHANNEL_ID_RE = re.compile(r"^UC[A-Za-z0-9_-]{22}$")
LIST_ID_RE = re.compile(r"^[A-Za-z0-9_-]{10,}$")
YT_NS = {"atom": "http://www.w3.org/2005/Atom", "yt": "http://www.youtube.com/xml/schemas/2015"}
# YouTube sends the full list (ytInitialData) to a desktop browser; the mobile
# page and the RSS feed carry less (measured 2026-10-29: the RSS feeds answered
# 404/500 while the desktop pages listed the videos)
DESKTOP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/130.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.8",
}

# a YouTube video referenced inside some other web page (embeds, lite-embeds,
# watch links, thumbnails); used by the website crawler to hand links over
_PAGE_VIDEO_PATTERNS = [
    re.compile(r"youtube(?:-nocookie)?\.com/(?:embed|shorts|live|v)/([A-Za-z0-9_-]{11})(?![A-Za-z0-9_-])"),
    re.compile(r"youtube\.com/watch\?(?:[^\"'<>\s]*?(?:&amp;|&))?v=([A-Za-z0-9_-]{11})(?![A-Za-z0-9_-])"),
    re.compile(r"youtu\.be/([A-Za-z0-9_-]{11})(?![A-Za-z0-9_-])"),
    re.compile(r"""data-(?:ytid|yt-id|youtube-id|youtube|yt)\s*=\s*["']([A-Za-z0-9_-]{11})["']"""),
    re.compile(r"i\.ytimg\.com/vi(?:_webp)?/([A-Za-z0-9_-]{11})/"),
]


def video_ids_from_html(html):
    """YouTube video IDs referenced in a web page, in page order, no repeats."""
    found = []
    for pat in _PAGE_VIDEO_PATTERNS:
        for m in pat.finditer(html or ""):
            found.append((m.start(), m.group(1)))
    out = []
    for _, vid in sorted(found):
        if vid not in out and vid != "videoseries":
            out.append(vid)
    return out


def _is_youtube_host(host):
    host = (host or "").lower().split(":")[0]
    return host in YOUTUBE_HOSTS or host == "youtu.be"


def is_youtube_url(value):
    try:
        p = urlparse(value.strip() if "://" in value else "https://" + value.strip())
        return _is_youtube_host(p.hostname)
    except Exception:
        return False


def classify(value):
    """'playlist', 'channel', 'video' or None for a YouTube link/ID.
    A watch link that also carries a real playlist (list=PL…) counts as the
    playlist; YouTube's auto "Mix" lists (list=RD…) don't."""
    value = (value or "").strip()
    if CHANNEL_ID_RE.fullmatch(value):
        return "channel"
    if value.startswith("@") and len(value) > 1:
        return "channel"
    if not is_youtube_url(value):
        return None
    p = urlparse(value if "://" in value else "https://" + value)
    q = parse_qs(p.query)
    lst = q.get("list", [""])[0]
    if lst and not lst.startswith("RD") and LIST_ID_RE.fullmatch(lst):
        return "playlist"
    if (p.hostname or "").lower() == "youtu.be" or p.path == "/watch":
        return "video"
    parts = [x for x in p.path.split("/") if x]
    if parts and parts[0] in ("shorts", "live", "embed"):
        return "video"
    if parts and (parts[0].startswith("@") or parts[0] in ("channel", "c", "user")):
        return "channel"
    return None

def parse_video_url(value):
    """Return a canonical public watch URL, or raise ValueError."""
    p = urlparse(value.strip())
    if p.scheme not in ("http", "https") or not _is_youtube_host(p.hostname):
        raise ValueError("YouTube ka valid public video link do.")
    video_id = ""
    if (p.hostname or "").lower() == "youtu.be":
        video_id = p.path.strip("/").split("/")[0]
    elif p.path == "/watch":
        video_id = parse_qs(p.query).get("v", [""])[0]
    else:
        parts = [x for x in p.path.split("/") if x]
        if len(parts) >= 2 and parts[0] in ("shorts", "live", "embed"):
            video_id = parts[1]
    if not VIDEO_ID_RE.fullmatch(video_id):
        raise ValueError("Is link mein valid YouTube video ID nahi mili.")
    return f"https://www.youtube.com/watch?v={video_id}", video_id


def parse_source(value, kind):
    """Normalize a channel or playlist URL/ID to a safe source record."""
    value = value.strip()
    if kind == "playlist":
        if "://" in value:
            p = urlparse(value)
            if p.scheme not in ("http", "https") or not _is_youtube_host(p.hostname):
                raise ValueError("Public YouTube playlist URL do.")
            list_id = parse_qs(p.query).get("list", [""])[0]
        else:
            list_id = value
        if not LIST_ID_RE.fullmatch(list_id):
            raise ValueError("Playlist ID/link sahi nahi. /addplaylist https://www.youtube.com/playlist?list=...")
        return {"kind": "playlist", "id": list_id,
                "url": f"https://www.youtube.com/playlist?list={list_id}"}

    if CHANNEL_ID_RE.fullmatch(value):
        channel_id = value
    else:
        if value.startswith("@"):
            value = "https://www.youtube.com/" + value
        p = urlparse(value if "://" in value else "https://" + value)
        if p.scheme not in ("http", "https") or not _is_youtube_host(p.hostname):
            raise ValueError("Public YouTube channel URL ya UC... channel ID do.")
        m = re.search(r"/channel/(UC[A-Za-z0-9_-]{22})(?:/|$)", p.path)
        channel_id = m.group(1) if m else ""
        if not channel_id:
            parts = [x for x in p.path.split("/") if x]
            if not parts:
                raise ValueError("Channel ka link do, jaise https://www.youtube.com/@channelname")
            r = safe_request("https://www.youtube.com/" + "/".join(parts[:2]), session=http(),
                             timeout=25, headers=DESKTOP_HEADERS)
            if r.status_code != 200:
                raise ValueError("Channel page nahi khul rahi. UC... channel ID try karo.")
            channel_id = _channel_id_from_page(r.text)
        if not CHANNEL_ID_RE.fullmatch(channel_id or ""):
            raise ValueError("Channel ID resolve nahi hui. YouTube channel ka UC... ID do.")
    return {"kind": "channel", "id": channel_id,
            "url": f"https://www.youtube.com/channel/{channel_id}"}


def _channel_id_from_page(text):
    for pat in (r'"externalId"\s*:\s*"(UC[A-Za-z0-9_-]{22})"',
                r'<meta itemprop="identifier" content="(UC[A-Za-z0-9_-]{22})"',
                r'"channelId"\s*:\s*"(UC[A-Za-z0-9_-]{22})"',
                r'youtube\.com/channel/(UC[A-Za-z0-9_-]{22})'):
        m = re.search(pat, text)
        if m:
            return m.group(1)
    return ""


def _feed_entries(kind, source_id):
    param = "playlist_id" if kind == "playlist" else "channel_id"
    feed_url = f"https://www.youtube.com/feeds/videos.xml?{param}={source_id}"
    r = safe_request(feed_url, session=http(), timeout=25,
                     headers={"Accept": "application/atom+xml,application/xml;q=0.9,*/*;q=0.5"})
    if r.status_code != 200:
        raise RuntimeError(f"YouTube feed HTTP {r.status_code}")
    root = ET.fromstring(r.text)
    entries = []
    for entry in root.findall("atom:entry", YT_NS):
        video_id = (entry.findtext("yt:videoId", default="", namespaces=YT_NS) or "").strip()
        title = (entry.findtext("atom:title", default="YouTube video", namespaces=YT_NS) or "YouTube video").strip()
        published = (entry.findtext("atom:published", default="", namespaces=YT_NS) or "").strip()
        if VIDEO_ID_RE.fullmatch(video_id):
            entries.append(_entry(video_id, title, published))
    return entries


def _entry(video_id, title="", published=""):
    return {"id": video_id, "title": (title or "YouTube video").strip()[:180], "published": published,
            "url": f"https://www.youtube.com/watch?v={video_id}"}


def initial_data(html):
    """The ytInitialData JSON a YouTube page carries, or None."""
    m = re.search(r'(?:var\s+ytInitialData|window\["ytInitialData"\])\s*=\s*(\{.*?\});\s*</script>', html or "", re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except ValueError:
        return None


def _text(t):
    if isinstance(t, str):
        return t
    if isinstance(t, dict):
        return t.get("simpleText") or t.get("content") or "".join(x.get("text", "") for x in t.get("runs", []))
    return ""


def entries_from_initial_data(data):
    """Videos listed on a playlist/channel page, in page order."""
    out, seen = [], set()

    def add(video_id, title):
        if isinstance(video_id, str) and VIDEO_ID_RE.fullmatch(video_id) and video_id not in seen:
            seen.add(video_id)
            out.append(_entry(video_id, title))

    def walk(o):
        if isinstance(o, dict):
            for k in ("playlistVideoRenderer", "videoRenderer", "gridVideoRenderer"):
                v = o.get(k)
                if isinstance(v, dict) and "videoId" in v:
                    add(v["videoId"], _text(v.get("title")))
            v = o.get("lockupViewModel")
            if isinstance(v, dict) and v.get("contentType") in (None, "LOCKUP_CONTENT_TYPE_VIDEO"):
                meta = ((v.get("metadata") or {}).get("lockupMetadataViewModel") or {})
                add(v.get("contentId"), _text(meta.get("title")))
            for x in o.values():
                walk(x)
        elif isinstance(o, list):
            for x in o:
                walk(x)

    walk(data)
    return out


def _page_entries(url):
    r = safe_request(url, session=http(), timeout=25, headers=DESKTOP_HEADERS)
    if r.status_code != 200:
        raise RuntimeError(f"YouTube page HTTP {r.status_code}")
    entries = entries_from_initial_data(initial_data(r.text))
    if not entries:
        raise RuntimeError("YouTube page mein video list nahi mili (private/khali ya YouTube ne page badla)")
    return entries


def fetch_entries(source):
    """Public video entries oldest-first for sequential delivery (a playlist
    keeps its own order). Page first, RSS feed as fallback."""
    if source["kind"] == "playlist":
        page_url = f"https://www.youtube.com/playlist?list={source['id']}"
    else:
        page_url = f"https://www.youtube.com/channel/{source['id']}/videos"
    try:
        entries = _page_entries(page_url)
    except Exception as page_err:
        try:
            entries = _feed_entries(source["kind"], source["id"])
        except Exception:
            raise page_err
    if source["kind"] == "channel":
        entries.reverse()  # the channel page lists newest first
    return entries
