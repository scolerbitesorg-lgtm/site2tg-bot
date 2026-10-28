"""Offline tests (no network): run with  python -m pytest -q"""
import os
import sys
from urllib.parse import unquote

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bot import adapters  # noqa: E402
from bot.adapters import generic, tgvideo  # noqa: E402
from bot.util import redact  # noqa: E402

CATALOG = {
    "stream": "https://tgvideo-stream.sites.tab.bot",
    "catalog": {"courses": [
        {"name": "Video Saver", "cid": 3723101547, "folders": [
            {"name": "Sabhi", "videos": [
                {"id": "a", "title": "वीडियो 1", "msg": 4, "size": 10160166, "t": "1793188943.K9I+Q/x="},
                {"id": "b", "title": "x/y", "msg": 5, "size": 60_000_000, "t": "z"},
            ]}]},
        {"name": "Test", "cid": 1, "test": True, "folders": [
            {"name": "f", "videos": [{"id": "c", "title": "t", "msg": 1, "t": "q"}]}]},
    ]},
}


def test_tgvideo_detect():
    html = '<script>fetch("https://tgvideo.sites.tab.bot/api/catalog")</script>'
    assert tgvideo.detect(html)
    assert adapters.detect(html) == "tgvideo"
    assert adapters.detect("<a href='x.apk'>") == "generic"
    assert tgvideo.catalog_url_from_html(html) == "https://tgvideo.sites.tab.bot/api/catalog"


def test_tgvideo_items():
    items = tgvideo.items_from_catalog(CATALOG, "https://videoclasses.vercel.app/")
    assert len(items) == 2  # test course skipped
    a = items[0]
    assert a.id == "tgvideo:3723101547:4"
    assert a.url.startswith("https://tgvideo-stream.sites.tab.bot/v/3723101547/4?t=")
    assert unquote(a.url.split("?t=")[1]) == "1793188943.K9I+Q/x="  # token fully url-encoded
    assert "+" not in a.url.split("?t=")[1] and "/" not in a.url.split("?t=")[1]
    assert a.headers == {"Referer": "https://videoclasses.vercel.app/"}
    assert a.caption == "Video Saver · Sabhi · वीडियो 1"
    assert a.filename == "वीडियो 1.mp4"
    assert a.kind == "video" and a.size == 10160166
    assert items[1].filename == "x_y.mp4"  # slash removed


def test_referer_from_any_page():
    assert tgvideo.site_referer("https://videoclasses.vercel.app/course/abc?x=1") == "https://videoclasses.vercel.app/"


def test_generic_links():
    html = """
    <a href="/apps/My%20App.apk">app</a>
    <a href="https://cdn.example.com/v/clip.MP4?x=1#t">vid</a>
    <video src="media/song.mp3"></video>
    <a href="/about.html">about</a>
    <a href="javascript:void(0)">x</a>
    <a href="/apps/My%20App.apk">dup</a>
    <a data-url="//img.example.com/p.pdf">pdf</a>
    <img src="/shot.png"><link rel="icon" href="/fav.png"><a href="/x.log.gz">log</a>
    """
    items = generic.items_from_html(html, "https://mysite.com/files/")
    urls = [i.url for i in items]
    assert urls == [
        "https://mysite.com/apps/My%20App.apk",
        "https://cdn.example.com/v/clip.MP4?x=1",
        "https://mysite.com/files/media/song.mp3",
        "https://img.example.com/p.pdf",
    ]
    assert items[0].filename == "My App.apk" and items[0].kind == "document"
    assert items[1].kind == "video"
    assert items[0].id == "url:https://mysite.com/apps/My%20App.apk"


def test_redact_hides_secrets(monkeypatch):
    monkeypatch.setenv("BOT_TOKEN", "123456789:AAH-secretsecretsecretsecretsecret12")
    s = redact("POST https://api.telegram.org/bot123456789:AAH-secretsecretsecretsecretsecret12/sendVideo failed")
    assert "secret" not in s
    s2 = redact("bad https://x.com/v/1/2?t=SIGNEDTOKEN here")
    assert "SIGNEDTOKEN" not in s2


def test_fdroid_style_page():
    html = """
    <link rel="apple-touch-icon" href="/assets/icon.png">
    <a href="https://f-droid.org/F-Droid.apk">Download</a>
    <a href="https://f-droid.org/repo/org.fdroid.fdroid_2000052.apk">apk</a>
    <a href="https://f-droid.org/repo/org.fdroid.fdroid_2000052.apk.asc">sig</a>
    <a href="https://f-droid.org/repo/org.fdroid.fdroid_2000052_src.tar.gz">src</a>
    <a href="https://f-droid.org/repo/org.fdroid.fdroid_2000052.log.gz">log</a>
    <img src="https://f-droid.org/repo/org.fdroid.fdroid/en-US/phoneScreenshots/01-latest.png">
    """
    urls = [i.url for i in generic.items_from_html(html, "https://f-droid.org/en/packages/org.fdroid.fdroid/")]
    assert urls == ["https://f-droid.org/F-Droid.apk", "https://f-droid.org/repo/org.fdroid.fdroid_2000052.apk"]
