"""YouTube routing, queues, and channel seeding (offline; all downloads mocked)."""
import os
from pathlib import Path

from bot import main as m
from bot import state as st
from bot.adapters.base import Item


class Bot:
    def __init__(self, fail_upload=False):
        self.msgs = []
        self.uploads = []
        self.fail_upload = fail_upload

    def send_message(self, chat_id, text):
        self.msgs.append((str(chat_id), text))

    def send_file(self, chat_id, path, filename, caption, kind):
        self.uploads.append((str(chat_id), path, filename, caption, kind))
        if self.fail_upload:
            raise RuntimeError("mock Telegram upload failure")

    def edit_message(self, chat_id, message_id, text):
        raise RuntimeError("no edit in this test")


def fresh(monkeypatch, tmp_path):
    monkeypatch.setattr(st, "STATE_FILE", str(tmp_path / "state.json"))
    for k, v in {"CHANNEL_ID": "-100", "OWNER_ID": "7"}.items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("CHANNEL_ID_VIDEO", raising=False)
    monkeypatch.setattr(m.time, "sleep", lambda s: None)
    return st.load()


def fake_download(monkeypatch, tmp_path):
    def download(url):
        folder = tmp_path / ("download_" + url.rsplit("=", 1)[-1])
        folder.mkdir(exist_ok=True)
        path = folder / (url.rsplit("=", 1)[-1] + ".mp4")
        path.write_bytes(b"mock video bytes")
        return path.name, str(path), path.stat().st_size
    monkeypatch.setattr(m, "download_youtube_video", download)


def test_addsite_with_youtube_video_downloads_and_uploads(monkeypatch, tmp_path):
    state, bot = fresh(monkeypatch, tmp_path), Bot()
    fake_download(monkeypatch, tmp_path)
    monkeypatch.setattr(m.adapters, "list_items", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no crawl")))
    m.run_command(bot, state, "/addsite https://youtu.be/mWlmcjwV44o?si=Rz", "7")
    assert state["sites"] == []
    assert len(bot.uploads) == 1
    assert bot.uploads[0][0] == "-100"
    assert bot.uploads[0][2] == "mWlmcjwV44o.mp4"
    assert "upload kar di" in bot.msgs[-1][1]
    # The manual video is recorded only after upload succeeds.
    assert "mWlmcjwV44o" in state["youtube_seen"]["manual"]


def test_addyoutube_video_and_playlist_routing(monkeypatch, tmp_path):
    state, bot = fresh(monkeypatch, tmp_path), Bot()
    fake_download(monkeypatch, tmp_path)
    m.run_command(bot, state, "/addyoutube https://youtu.be/mWlmcjwV44o", "7")
    assert state["youtube_sources"] == []
    assert len(bot.uploads) == 1 and bot.uploads[0][0] == "-100"
    m.run_command(bot, state, "/addsite https://www.youtube.com/playlist?list=PL1234567890abcd", "7")
    assert [(s["kind"], s["id"]) for s in state["youtube_sources"]] == [("playlist", "PL1234567890abcd")]
    assert state["sites"] == [] and "playlist" in bot.msgs[-1][1]
    m.run_command(bot, state, "/removeyoutube PL1234567890abcd", "7")
    assert state["youtube_sources"] == []
    m.run_command(bot, state, "/removeyoutube a", "7")
    assert "nahi mili" in bot.msgs[-1][1]


def test_site_youtube_queue_uploads_a_few_per_run(monkeypatch, tmp_path):
    state, bot = fresh(monkeypatch, tmp_path), Bot()
    fake_download(monkeypatch, tmp_path)
    monkeypatch.setenv("MAX_YOUTUBE_VIDEOS_PER_RUN", "2")
    url = "https://ex.am/p/7/videos"
    state["sites"] = [{"url": url, "adapter": "generic", "depth": 5, "limit": 3}]
    state["sent"][url] = []
    yt = [Item(id=f"yt:{c * 11}", url=f"https://www.youtube.com/watch?v={c * 11}", filename=c * 11,
               caption=f"Lecture {c}", kind="youtube") for c in "abc"]
    monkeypatch.setattr(m.adapters, "list_items", lambda *a, **k: ("generic", list(yt)))
    sent, failed, big = m.sync(bot, state, "-100")
    assert (sent, failed, big) == (2, 0, 0)
    assert len(bot.uploads) == 2
    assert [u[2] for u in bot.uploads] == ["aaaaaaaaaaa.mp4", "bbbbbbbbbbb.mp4"]
    assert "YouTube links: 2" in state["last_result"]
    m.sync(bot, state, "-100")
    assert [u[2] for u in bot.uploads] == ["aaaaaaaaaaa.mp4", "bbbbbbbbbbb.mp4", "ccccccccccc.mp4"]
    m.sync(bot, state, "-100")
    assert len(bot.uploads) == 3 and "site:ex.am/p/7/videos" not in state["youtube_pending"]
    assert "YouTube videos: 3 upload" in m.cmd_sites(state, "")


def test_empty_site_gets_a_plain_reason_in_status_and_sync_reply(monkeypatch, tmp_path):
    state, bot = fresh(monkeypatch, tmp_path), Bot()
    url = "https://spidy.app/course/1"
    state["sites"] = [{"url": url, "adapter": "generic", "depth": 5, "limit": 3}]
    state["sent"][url] = []
    shell = '<div>Videos (0)</div><script>self.__next_f.push([1,""])</script>'
    monkeypatch.setattr(m.adapters, "fetch_page", lambda u: shell)
    monkeypatch.setattr(m.adapters.generic, "_robots", lambda *a: None)
    m.sync(bot, state, "-100")
    assert "JavaScript" in state["site_notes"][url]
    assert "0 kyun" in m.cmd_status(state, "") and "JavaScript" in m.cmd_sites(state, "")
    m.cmd_removesite(state, url)
    assert url not in state["site_notes"]


def test_new_channel_posts_only_its_latest_three_as_files(monkeypatch, tmp_path):
    state, bot = fresh(monkeypatch, tmp_path), Bot()
    fake_download(monkeypatch, tmp_path)
    state["youtube_sources"] = [{"kind": "channel", "id": "UC" + "a" * 22, "url": "https://www.youtube.com/channel/x"}]
    entries = [{"id": f"{i:011d}", "title": f"v{i}", "url": f"https://www.youtube.com/watch?v={i:011d}"} for i in range(10)]
    monkeypatch.setattr(m.youtube_tracker, "fetch_entries", lambda s: list(entries))
    m.sync_youtube_links(bot, state, "-100")
    assert [u[3].split("\n")[0] for u in bot.uploads] == ["▶️ v7", "▶️ v8"]
    # Default queue limit is two videos per run.
    m.sync_youtube_links(bot, state, "-100")
    assert [u[3].split("\n")[0] for u in bot.uploads] == ["▶️ v7", "▶️ v8", "▶️ v9"]
    entries.append({"id": "00000000010", "title": "new upload", "url": "https://www.youtube.com/watch?v=00000000010"})
    m.sync_youtube_links(bot, state, "-100")
    assert [u[3].split("\n")[0] for u in bot.uploads][3:] == ["▶️ new upload"]


def test_youtube_fetch_error_is_recorded_once_and_does_not_count_as_failed(monkeypatch, tmp_path):
    state, bot = fresh(monkeypatch, tmp_path), Bot()
    state["youtube_sources"] = [{"kind": "playlist", "id": "PL1234567890abcd", "url": "u"}]
    def boom(s):
        raise RuntimeError("YouTube page HTTP 429")
    monkeypatch.setattr(m.youtube_tracker, "fetch_entries", boom)
    assert m.sync_youtube_links(bot, state, "-100") == (0, 0)
    m.sync_youtube_links(bot, state, "-100")
    assert len(state["errors"]) == 1


def test_a_new_video_on_a_site_jumps_the_backlog(monkeypatch, tmp_path):
    state = fresh(monkeypatch, tmp_path)
    url = "https://ex.am/list"
    mk = lambda c: Item(id=f"yt:{c * 11}", url=f"https://www.youtube.com/watch?v={c * 11}", filename="", caption=c, kind="youtube")
    m.queue_site_youtube(state, url, [mk("b"), mk("c")])
    m.queue_site_youtube(state, url, [mk("a"), mk("b"), mk("c")])
    assert [e["id"][0] for e in state["youtube_pending"]["site:ex.am/list"]] == ["a", "b", "c"]
