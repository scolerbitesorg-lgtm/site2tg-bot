"""Offline tests for yt-dlp config, retries, locking, queue and Telegram cleanup."""
import os
import sys
import threading
import time
import types
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from bot import main as m


class FakeYoutubeDL:
    instances = []
    error = None
    active = 0
    max_active = 0
    active_lock = threading.Lock()

    def __init__(self, opts):
        self.opts = opts
        self.info = None
        type(self).instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def extract_info(self, url, download=True):
        if type(self).error:
            raise type(self).error
        with type(self).active_lock:
            type(self).active += 1
            type(self).max_active = max(type(self).max_active, type(self).active)
        try:
            time.sleep(0.02)
            self.info = {"id": url.rsplit("=", 1)[-1], "ext": "mp4"}
            path = self.prepare_filename(self.info)
            Path(path).write_bytes(b"video-data")
            return self.info
        finally:
            with type(self).active_lock:
                type(self).active -= 1

    def prepare_filename(self, info):
        template = self.opts["outtmpl"]
        return template.replace("%(id)s", info["id"]).replace("%(ext)s", info["ext"])


def fake_yt_dlp(monkeypatch, error=None):
    FakeYoutubeDL.instances = []
    FakeYoutubeDL.error = error
    FakeYoutubeDL.active = 0
    FakeYoutubeDL.max_active = 0
    monkeypatch.setitem(sys.modules, "yt_dlp", types.SimpleNamespace(YoutubeDL=FakeYoutubeDL))


def test_configured_cookie_file_is_passed_to_yt_dlp(monkeypatch, tmp_path):
    cookie_file = tmp_path / "cookies.txt"
    cookie_file.write_text("# Netscape HTTP Cookie File\n", encoding="utf-8")
    monkeypatch.setenv("YTDLP_COOKIES_FILE", str(cookie_file))
    fake_yt_dlp(monkeypatch)
    name, path, size = m.download_youtube_video("https://www.youtube.com/watch?v=abc123")
    assert FakeYoutubeDL.instances[0].opts["cookiefile"] == str(cookie_file)
    assert name == "abc123.mp4" and Path(path).is_file() and size == len(b"video-data")
    Path(path).unlink()
    Path(path).parent.rmdir()


def test_missing_configured_cookie_file_fails_closed(monkeypatch, tmp_path):
    monkeypatch.setenv("YTDLP_COOKIES_FILE", str(tmp_path / "does-not-exist.txt"))
    fake_yt_dlp(monkeypatch)
    with pytest.raises(RuntimeError, match="cookies file nahi mili"):
        m.download_youtube_video("https://www.youtube.com/watch?v=abc123")
    assert FakeYoutubeDL.instances == []


def test_youtube_auth_error_is_not_retried_or_bypassed(monkeypatch, tmp_path):
    monkeypatch.delenv("YTDLP_COOKIES_FILE", raising=False)
    fake_yt_dlp(monkeypatch, RuntimeError("Sign in to confirm you’re not a bot. Use --cookies-from-browser"))
    with pytest.raises(RuntimeError, match="authentication required"):
        m.download_youtube_video("https://www.youtube.com/watch?v=abc123")
    assert len(FakeYoutubeDL.instances) == 1


def test_normal_download_failure_has_bounded_attempts(monkeypatch, tmp_path):
    monkeypatch.delenv("YTDLP_COOKIES_FILE", raising=False)
    monkeypatch.setattr(m.time, "sleep", lambda _: None)
    fake_yt_dlp(monkeypatch, RuntimeError("temporary network failure"))
    with pytest.raises(RuntimeError, match="failed after 3 attempts"):
        m.download_youtube_video("https://www.youtube.com/watch?v=abc123")
    assert len(FakeYoutubeDL.instances) == m.YTDLP_MAX_ATTEMPTS


class UploadBot:
    def __init__(self, fail=False):
        self.fail = fail
        self.uploads = []

    def send_file(self, *args):
        self.uploads.append(args)
        if self.fail:
            raise RuntimeError("mock Telegram upload failure")


def make_state(tmp_path):
    return {"youtube_seen": {}, "youtube_pending": {}, "youtube_sources": [], "errors": []}


def test_telegram_upload_failure_keeps_video_file(monkeypatch, tmp_path):
    path = tmp_path / "owned.mp4"
    path.write_bytes(b"video")
    monkeypatch.setattr(m, "download_youtube_video", lambda url: (path.name, str(path), path.stat().st_size))
    bot = UploadBot(fail=True)
    result = m.cmd_yt(bot, "https://www.youtube.com/watch?v=abc123", "-100", make_state(tmp_path))
    assert "upload nahi hui" in result
    assert path.exists(), "failed upload must preserve the downloaded file for retry"


def test_telegram_upload_success_deletes_video_file(monkeypatch, tmp_path):
    path = tmp_path / "owned.mp4"
    path.write_bytes(b"video")
    monkeypatch.setattr(m, "download_youtube_video", lambda url: (path.name, str(path), path.stat().st_size))
    bot = UploadBot()
    state = make_state(tmp_path)
    result = m.cmd_yt(bot, "https://www.youtube.com/watch?v=abc123", "-100", state)
    assert "upload kar di" in result
    assert len(bot.uploads) == 1
    assert not path.exists(), "successful upload should clean up the local video"
    assert "abc123" in state["youtube_seen"]["manual"]


def test_queue_retries_are_bounded_and_item_stays_until_limit(monkeypatch, tmp_path):
    state = make_state(tmp_path)
    source = {"kind": "playlist", "id": "PL1234567890abcd", "url": "https://www.youtube.com/playlist?list=PL1234567890abcd"}
    state["youtube_sources"] = [source]
    entry = {"id": "abc123", "title": "owned video", "url": "https://www.youtube.com/watch?v=abc123"}
    monkeypatch.setattr(m.youtube_tracker, "fetch_entries", lambda _: [entry])
    monkeypatch.setattr(m, "download_youtube_video", lambda _: (_ for _ in ()).throw(RuntimeError("mock download failure")))
    monkeypatch.setattr(m.time, "sleep", lambda _: None)
    bot = UploadBot()
    for attempt in range(1, m.YTDLP_MAX_ATTEMPTS + 1):
        m.sync_youtube_links(bot, state, "-100")
        if attempt < m.YTDLP_MAX_ATTEMPTS:
            assert state["youtube_pending"]["playlist:PL1234567890abcd"][0]["attempts"] == attempt
        else:
            assert not state["youtube_pending"]["playlist:PL1234567890abcd"]
    m.sync_youtube_links(bot, state, "-100")
    assert len(state["errors"]) >= m.YTDLP_MAX_ATTEMPTS
    assert bot.uploads == []


def test_downloads_are_serialized_inside_one_process(monkeypatch):
    monkeypatch.delenv("YTDLP_COOKIES_FILE", raising=False)
    fake_yt_dlp(monkeypatch)
    monkeypatch.setattr(m.time, "sleep", lambda _: None)
    urls = [f"https://www.youtube.com/watch?v=video{i}" for i in range(4)]
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(m.download_youtube_video, urls))
    assert FakeYoutubeDL.max_active == 1
    for _, path, _ in results:
        Path(path).unlink()
        Path(path).parent.rmdir()
