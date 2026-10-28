"""Small helpers: secret redaction, time, HTTP session, safe filenames."""
import os
import re
import time
from datetime import datetime, timezone

import requests

UA = "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Mobile Safari/537.36 site2tg-bot/1"

_SECRET_ENV = ("BOT_TOKEN", "API_HASH", "SESSION_STRING", "API_ID")


def redact(text) -> str:
    """Remove secrets and long query strings from any text before it is logged,
    stored in state.json, or sent to Telegram."""
    s = str(text)
    for name in _SECRET_ENV:
        val = os.environ.get(name, "")
        if val and len(val) >= 4:
            s = s.replace(val, "***")
    # bot tokens look like 123456:ABC-xyz...
    s = re.sub(r"\b\d{6,}:[A-Za-z0-9_-]{30,}\b", "***", s)
    # strip query strings from URLs (signed tokens etc.)
    s = re.sub(r"(https?://[^\s?#'\"]+)\?[^\s'\"]*", r"\1?…", s)
    return s[:500]


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(s):
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def ist(s) -> str:
    """Show a stored UTC time in India time for humans."""
    d = parse_iso(s)
    if not d:
        return "kabhi nahi"
    t = d.timestamp() + 5.5 * 3600
    return time.strftime("%d %b %I:%M %p IST", time.gmtime(t))


def http() -> requests.Session:
    s = requests.Session()
    s.headers["User-Agent"] = UA
    return s


def safe_name(name: str, default: str = "file") -> str:
    name = re.sub(r"[\\/:*?\"<>|\x00-\x1f]+", "_", name or "").strip(" ._")
    return (name or default)[:120]


def human_size(n) -> str:
    if n is None:
        return "?"
    n = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"
