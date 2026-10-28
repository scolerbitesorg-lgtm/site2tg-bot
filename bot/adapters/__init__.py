"""Pick the right adapter for a site."""
from . import generic, tgvideo
from ..util import http

ADAPTERS = {"tgvideo": tgvideo, "generic": generic}


def detect(html: str) -> str:
    if tgvideo.detect(html):
        return "tgvideo"
    return "generic"


def fetch_page(url: str) -> str:
    r = http().get(url, timeout=30)
    r.raise_for_status()
    return r.text


def list_items(url: str, adapter: str = None):
    html = fetch_page(url)
    name = adapter or detect(html)
    return name, ADAPTERS[name].list_items(url, html)
