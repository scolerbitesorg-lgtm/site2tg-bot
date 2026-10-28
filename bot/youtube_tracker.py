"""Public YouTube channel/playlist link tracker.

This module deliberately tracks public metadata and posts watch links only. It
does not download YouTube media, extract stream URLs, or bypass DRM/access
controls. No YouTube Data API key is required for the public feeds/pages used
here, though YouTube may change or rate-limit those endpoints.
"""
import re
import xml.etree.ElementTree as ET
from urllib.parse import parse_qs, urlparse

from .util import http
from .security import safe_request

YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com"}
VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
CHANNEL_ID_RE = re.compile(r"^UC[A-Za-z0-9_-]{22}$")
LIST_ID_RE = re.compile(r"^[A-Za-z0-9_-]{10,}$")
YT_NS = {"atom": "http://www.w3.org/2005/Atom", "yt": "http://www.youtube.com/xml/schemas/2015"}


def _is_youtube_host(host):
    host = (host or "").lower().split(":")[0]
    return host in YOUTUBE_HOSTS or host == "youtu.be"


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
        p = urlparse(value if "://" in value else "https://" + value)
        if p.scheme not in ("http", "https") or not _is_youtube_host(p.hostname):
            raise ValueError("Public YouTube channel URL ya UC... channel ID do.")
        m = re.search(r"/channel/(UC[A-Za-z0-9_-]{22})(?:/|$)", p.path)
        channel_id = m.group(1) if m else ""
        if not channel_id:
            r = safe_request("https://www.youtube.com" + (p.path or "/"), session=http(),
                             timeout=25, headers={"Accept-Language": "en-US,en;q=0.8"})
            if r.status_code != 200:
                raise ValueError("Channel page nahi khul rahi. UC... channel ID try karo.")
            match = re.search(r'"channelId"\s*:\s*"(UC[A-Za-z0-9_-]{22})"', r.text)
            if not match:
                match = re.search(r'<link[^>]+itemprop=["\']url["\'][^>]+content=["\']https://www\\.youtube\\.com/channel/(UC[A-Za-z0-9_-]{22})', r.text)
            channel_id = match.group(1) if match else ""
        if not CHANNEL_ID_RE.fullmatch(channel_id):
            raise ValueError("Channel ID resolve nahi hui. YouTube channel ka UC... ID do.")
    return {"kind": "channel", "id": channel_id,
            "url": f"https://www.youtube.com/channel/{channel_id}"}


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
            entries.append({"id": video_id, "title": title[:180], "published": published,
                            "url": f"https://www.youtube.com/watch?v={video_id}"})
    return entries


def fetch_entries(source):
    """Return public video entries oldest-first for sequential delivery."""
    try:
        entries = _feed_entries(source["kind"], source["id"])
    except Exception:
        if source["kind"] != "playlist":
            raise
        entries = []

    if source["kind"] == "playlist":
        # Prefer the public playlist page as it can expose more than the
        # latest 15 feed entries. Keep feed titles when available and merge
        # any additional IDs from the page into the durable queue.
        try:
            r = safe_request(source["url"], session=http(), timeout=25,
                             headers={"Accept-Language": "en-US,en;q=0.8"})
            if r.status_code != 200:
                raise RuntimeError(f"YouTube playlist page HTTP {r.status_code}")
            ids = list(dict.fromkeys(re.findall(r'"videoId"\s*:\s*"([A-Za-z0-9_-]{11})"', r.text)))
            by_id = {entry["id"]: entry for entry in entries}
            for video_id in ids:
                by_id.setdefault(video_id, {
                    "id": video_id, "title": "YouTube playlist video", "published": "",
                    "url": f"https://www.youtube.com/watch?v={video_id}"
                })
            entries = list(by_id.values())
        except Exception:
            if not entries:
                raise

    # RSS feed is newest-first. Reverse to keep posts in chronological order.
    entries.reverse()
    return entries
