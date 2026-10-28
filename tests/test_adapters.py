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


def test_tgvideo_nested_catalog_any_depth():
    data = {
        "stream": "https://tgvideo-stream.sites.tab.bot",
        "catalog": {"courses": [{
            "cid": 99, "name": "Physics",
            "folders": [{"name": "Mechanics",
                         "subfolders": [{"name": "Kinematics",
                                         "children": [{"name": "Lecture 1",
                                                       "videos": [{"id": "a", "title": "Intro", "msg": 11, "t": "x y"},
                                                                  {"id": "b", "title": "Graphs", "msg": 12, "t": "z"}]}],
                                         "videos": [{"title": "Notes video", "msg": 10, "t": "q"}]}]}],
            "videos": [{"title": "Welcome", "msg": 1, "t": "w"}],
        }, {"cid": 5, "name": "Test", "test": True, "folders": [{"name": "f", "videos": [{"title": "t", "msg": 2}]}]}]},
    }
    items = tgvideo.items_from_catalog(data, "https://videoclasses.vercel.app/")
    caps = {i.id: i.caption for i in items}
    assert caps == {
        "tgvideo:99:1": "Physics · Welcome",
        "tgvideo:99:10": "Physics · Mechanics · Kinematics · Notes video",
        "tgvideo:99:11": "Physics · Mechanics · Kinematics · Lecture 1 · Intro",
        "tgvideo:99:12": "Physics · Mechanics · Kinematics · Lecture 1 · Graphs",
    }
    intro = [i for i in items if i.id == "tgvideo:99:11"][0]
    assert intro.url == "https://tgvideo-stream.sites.tab.bot/v/99/11?t=x%20y"
    assert intro.headers == {"Referer": "https://videoclasses.vercel.app/"} and intro.kind == "video"


def test_tgvideo_cycle_and_duplicates_are_safe():
    node = {"name": "loop", "videos": [{"title": "v", "msg": 3}]}
    node["folders"] = [node]          # a self-reference must not hang
    data = {"catalog": {"courses": [{"cid": 1, "name": "C", "folders": [node]}]}}
    items = tgvideo.items_from_catalog(data, "https://x/")
    assert [i.id for i in items] == ["tgvideo:1:3"]


# ---------------------------------------------------------------- same-site crawl

class _Resp:
    def __init__(self, text, status=200, ctype="text/html"):
        self.text, self.status_code, self.headers = text, status, {"Content-Type": ctype}


class FakeSite:
    """A tiny local multi-page site."""
    def __init__(self, pages, robots=None):
        self.pages, self.robots, self.got = pages, robots, []

    def get(self, url, timeout=None, headers=None):
        self.got.append(url)
        if url.endswith("/robots.txt"):
            return _Resp(self.robots, 200, "text/plain") if self.robots is not None else _Resp("", 404)
        if url in self.pages:
            return _Resp(self.pages[url])
        return _Resp("nope", 404)


ROOT = "https://my.site/files/"
SITE = {
    ROOT: '<title>Home</title><a href="a/">A</a> <a href="b/">B</a> <a href="/login">x</a> '
          '<a href="https://other.com/files/x/">o</a> <a href="/blog/">outside path</a> <a href="style.css">c</a>',
    ROOT + "a/": '<title>Topic A</title><a href="a1/">a1</a>',
    ROOT + "a/a1/": '<title>Lecture A1</title><a href="v1.mp4">v</a> <a href="deeper/">should not be followed</a>',
    ROOT + "a/a1/deeper/": '<a href="never.mp4">x</a>',
    ROOT + "b/": '<title>Topic B</title><a href="app.apk">apk</a> <a href="../a/a1/v1.mp4">same file again</a> <a href="b1/">b1</a>',
    ROOT + "b/b1/": '<a href="never2.pdf">x</a>',
    "https://my.site/blog/": '<a href="blog.pdf">x</a>',
}


def test_crawl_collects_files_from_inner_pages_and_stops_at_found_branches():
    site = FakeSite(SITE)
    items = generic.list_items(ROOT, SITE[ROOT], depth=5, session=site, sleep=lambda s: None)
    got = {i.filename: i.caption for i in items}
    # v1.mp4 is linked from Topic B (level 1) and Lecture A1 (level 2): one item, first page wins
    assert got == {"v1.mp4": "Topic B · v1.mp4", "app.apk": "Topic B · app.apk"}
    assert ROOT + "a/a1/deeper/" not in site.got and ROOT + "b/b1/" not in site.got     # smart stop
    assert all("other.com" not in u and "/login" not in u and "/blog/" not in u and not u.endswith(".css")
               for u in site.got)
    assert ROOT + "a/a1/" in site.got                                           # branch A had no files yet: went deeper
    v = [i for i in items if i.filename == "v1.mp4"][0]
    assert v.kind == "video" and v.headers["Referer"] == ROOT + "b/"


def test_crawl_depth_and_page_cap_and_delay():
    site = FakeSite(SITE)
    one = generic.list_items(ROOT, SITE[ROOT], depth=1, session=site, sleep=lambda s: None)
    assert sorted(i.filename for i in one) == ["app.apk", "v1.mp4"] and ROOT + "a/a1/" not in site.got
    site = FakeSite(SITE)
    pauses = []
    generic.list_items(ROOT, SITE[ROOT], depth=5, max_pages=2, session=site, sleep=pauses.append)
    assert len([u for u in site.got if not u.endswith("robots.txt")]) == 1      # root given + 1 fetched = cap 2
    assert pauses == [0.5]
    assert [i.id for i in generic.list_items(ROOT, '<a href="x.zip">z</a>', depth=0)] == ["url:https://my.site/files/x.zip"]


def test_crawl_respects_robots_txt():
    site = FakeSite(SITE, robots="User-agent: *\nDisallow: /files/b/\n")
    items = generic.list_items(ROOT, SITE[ROOT], depth=5, session=site, sleep=lambda s: None)
    assert [i.filename for i in items] == ["v1.mp4"]
    assert ROOT + "b/" not in site.got


def test_root_page_with_files_is_not_crawled():
    site = FakeSite({ROOT: '<a href="z.apk">z</a> <a href="a/">a</a>'})
    items = generic.list_items(ROOT, site.pages[ROOT], depth=5, session=site, sleep=lambda s: None)
    assert [i.filename for i in items] == ["z.apk"] and site.got == [ROOT.replace("/files/", "/robots.txt")]
