"""Webhook mode: Telegram webhook is set (Vercel), so the run must NOT call
getUpdates and must answer only the command the webhook dispatched."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bot import main as m  # noqa: E402
from bot import state as st  # noqa: E402
from bot.adapters.base import Item  # noqa: E402


class HookBot:
    def __init__(self, hook_url="https://x.vercel.app/api/telegram"):
        self.hook_url, self.msgs, self.sent, self.polled = hook_url, [], [], 0

    def get_webhook_info(self):
        return {"url": self.hook_url}

    def get_updates(self, offset):
        self.polled += 1
        return [{"update_id": 9, "message": {"text": "/sites", "from": {"id": 111}, "chat": {"id": 111}}}]

    def send_message(self, chat_id, text):
        self.msgs.append((chat_id, text))

    def edit_message(self, chat_id, message_id, text):
        if message_id == 666:
            raise RuntimeError("message to edit not found")
        self.msgs.append((chat_id, f"EDIT#{message_id}:" + text))

    def send_file(self, chat_id, path, filename, caption, kind):
        self.sent.append((chat_id, filename))


def _env(monkeypatch, tmp_path, **extra):
    monkeypatch.setattr(st, "STATE_FILE", str(tmp_path / "state.json"))
    for k, v in {"BOT_TOKEN": "1:x", "CHANNEL_ID": "-100123", "OWNER_ID": "111"}.items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("WEBHOOK_MODE", raising=False)
    monkeypatch.delenv("INJECTED_COMMAND", raising=False)
    monkeypatch.delenv("ACK_MESSAGE_ID", raising=False)
    monkeypatch.delenv("CHANNEL_ID_VIDEO", raising=False)
    monkeypatch.delenv("CHANNEL_ID_FILES", raising=False)
    for k, v in extra.items():
        monkeypatch.setenv(k, v)


def test_webhook_mode_uses_injected_command_only(monkeypatch, tmp_path):
    _env(monkeypatch, tmp_path, INJECTED_COMMAND="/addsite mysite.com 2")
    item = Item(id="a:1", url="https://s/1.apk", filename="1.apk", caption="c", size=10)
    monkeypatch.setattr(m.adapters, "list_items", lambda url, adapter=None, **kw: ("generic", [item]))

    def fake_download(it, folder):
        p = os.path.join(folder, it.filename)
        open(p, "wb").write(b"x")
        return p, 1

    monkeypatch.setattr(m, "download", fake_download)
    bot = HookBot()
    monkeypatch.setattr(m, "Bot", lambda token: bot)
    assert m.main() == 0
    assert bot.polled == 0                                   # no getUpdates (would be 409)
    s = st.load()
    assert s["offset"] == 0
    assert s["sites"][0]["url"] == "https://mysite.com" and s["sites"][0]["limit"] == 2
    assert bot.msgs[0][0] == "111" and "Site jod di" in bot.msgs[0][1]   # reply goes to owner
    assert bot.sent == [("-100123", "1.apk")]


def test_webhook_mode_sync_command_always_reports(monkeypatch, tmp_path):
    _env(monkeypatch, tmp_path, INJECTED_COMMAND="/sync")
    s = st.load()
    s["sites"] = [{"url": "https://e.com", "adapter": "generic", "added": "x", "limit": 3}]
    s["last_sync"] = "2099-01-01T00:00:00Z"   # not due by time
    st.save(s)
    monkeypatch.setattr(m.adapters, "list_items", lambda url, adapter=None, **kw: ("generic", []))
    bot = HookBot()
    monkeypatch.setattr(m, "Bot", lambda token: bot)
    m.main()
    texts = [t for _, t in bot.msgs]
    assert texts[0].startswith("🔄 Sync shuru")
    assert any(t.startswith("🔄 Sync: 0 bheji") for t in texts)   # result even when nothing new


def test_no_webhook_keeps_polling_and_also_runs_injected(monkeypatch, tmp_path):
    _env(monkeypatch, tmp_path, INJECTED_COMMAND="/status")
    bot = HookBot(hook_url="")
    monkeypatch.setattr(m, "Bot", lambda token: bot)
    m.main()
    assert bot.polled == 1
    assert st.load()["offset"] == 10
    texts = [t for _, t in bot.msgs]
    assert any("websites" in t.lower() or "site" in t.lower() for t in texts)
    assert any("Status" in t for t in texts)


def test_webhook_mode_env_override(monkeypatch, tmp_path):
    _env(monkeypatch, tmp_path, WEBHOOK_MODE="1")
    bot = HookBot(hook_url="")
    monkeypatch.setattr(m, "Bot", lambda token: bot)
    m.main()
    assert bot.polled == 0
    _env(monkeypatch, tmp_path, WEBHOOK_MODE="0")
    bot2 = HookBot()
    monkeypatch.setattr(m, "Bot", lambda token: bot2)
    m.main()
    assert bot2.polled == 1


def test_non_command_injection_ignored(monkeypatch, tmp_path):
    _env(monkeypatch, tmp_path, INJECTED_COMMAND="hello")
    bot = HookBot()
    monkeypatch.setattr(m, "Bot", lambda token: bot)
    m.main()
    assert bot.msgs == []


def test_setup_mode_with_webhook_does_not_poll(monkeypatch, tmp_path):
    monkeypatch.setattr(st, "STATE_FILE", str(tmp_path / "state.json"))
    monkeypatch.setenv("BOT_TOKEN", "1:x")
    monkeypatch.delenv("CHANNEL_ID", raising=False)
    monkeypatch.delenv("OWNER_ID", raising=False)
    monkeypatch.delenv("WEBHOOK_MODE", raising=False)
    monkeypatch.setenv("INJECTED_COMMAND", "/status")
    bot = HookBot()
    monkeypatch.setattr(m, "Bot", lambda token: bot)
    assert m.main() == 0
    assert bot.polled == 0 and bot.msgs == []


def test_offset_survives_save_and_load(monkeypatch, tmp_path):
    """The getUpdates offset must be written to state.json and read back
    (else every run re-answers old messages)."""
    path = tmp_path / "state.json"
    monkeypatch.setattr(st, "STATE_FILE", str(path))
    s = st.load()
    assert s["offset"] == 0
    s["offset"] = 959581372
    st.save(s)
    assert '"offset": 959581372' in path.read_text()
    assert st.load()["offset"] == 959581372


def test_setup_mode_offset_persisted_across_runs(monkeypatch, tmp_path):
    monkeypatch.setattr(st, "STATE_FILE", str(tmp_path / "state.json"))
    monkeypatch.setenv("BOT_TOKEN", "1:x")
    monkeypatch.delenv("CHANNEL_ID", raising=False)
    monkeypatch.delenv("OWNER_ID", raising=False)
    monkeypatch.delenv("WEBHOOK_MODE", raising=False)
    monkeypatch.delenv("INJECTED_COMMAND", raising=False)
    bot = HookBot(hook_url="")
    monkeypatch.setattr(m, "Bot", lambda token: bot)
    m.main()
    assert st.load()["offset"] == 10 and len(bot.msgs) == 1
    bot.msgs.clear()
    bot.get_updates = lambda offset: [] if offset >= 10 else [{"update_id": 9, "message": {}}]
    m.main()                                   # next run asks from offset 10: no re-reply
    assert bot.msgs == [] and st.load()["offset"] == 10


def test_injected_command_edits_the_ack_message(monkeypatch, tmp_path):
    _env(monkeypatch, tmp_path, INJECTED_COMMAND="/sites", ACK_MESSAGE_ID="77")
    bot = HookBot()
    monkeypatch.setattr(m, "Bot", lambda token: bot)
    m.main()
    assert bot.msgs and bot.msgs[0][1].startswith("EDIT#77:")


def test_failed_edit_falls_back_to_new_message(monkeypatch, tmp_path):
    _env(monkeypatch, tmp_path, INJECTED_COMMAND="/sites", ACK_MESSAGE_ID="666")
    bot = HookBot()
    monkeypatch.setattr(m, "Bot", lambda token: bot)
    m.main()
    assert len(bot.msgs) == 1 and not bot.msgs[0][1].startswith("EDIT")


def test_same_site_typed_differently_is_not_added_twice(monkeypatch, tmp_path):
    _env(monkeypatch, tmp_path)
    monkeypatch.setattr(m.adapters, "list_items", lambda url, adapter=None, **kw: ("tgvideo", []))
    s = st.load()
    for u in ("https://videoclasses.vercel.app/", "videoclasses.vercel.app", "http://www.VideoClasses.vercel.app"):
        reply = m.cmd_addsite(s, u)
    assert len(s["sites"]) == 1
    assert "pehle se" in reply
    assert m.site_key("https://x.com/a/") == m.site_key("x.com/a") == m.site_key("http://www.X.com/a")
    assert m.site_key("https://x.com/a") != m.site_key("https://x.com/b")
    assert "Hata di" in m.cmd_removesite(s, "videoclasses.vercel.app")   # no exact slash needed
    assert s["sites"] == []


def test_old_duplicate_entries_are_merged_and_nothing_is_posted_twice(monkeypatch, tmp_path):
    _env(monkeypatch, tmp_path)
    s = st.load()
    s["sites"] = [{"url": "https://v.app/", "adapter": "tgvideo", "added": "x", "limit": 5},
                  {"url": "https://v.app", "adapter": "tgvideo", "added": "y", "limit": 5}]
    s["sent"] = {"https://v.app/": ["tgvideo:1:4"], "https://v.app": ["tgvideo:1:5"]}
    s["hashes"] = {"https://v.app/": ["h4"], "https://v.app": ["h5"]}
    s["last_sync"] = None
    st.save(s)
    items = [Item(id=f"tgvideo:1:{i}", url=f"https://s/{i}.mp4", filename=f"{i}.mp4", caption="", size=10, kind="video")
             for i in (4, 5, 6)]
    monkeypatch.setattr(m.adapters, "list_items", lambda url, adapter=None, **kw: ("tgvideo", items))

    def fake_download(it, folder):
        p = os.path.join(folder, it.filename)
        open(p, "wb").write(it.id.encode())
        return p, 1

    monkeypatch.setattr(m, "download", fake_download)
    bot = HookBot()
    monkeypatch.setattr(m, "Bot", lambda token: bot)
    m.main()
    s = st.load()
    assert [x["url"] for x in s["sites"]] == ["https://v.app/"]
    assert sorted(s["sent"]["https://v.app/"]) == ["tgvideo:1:4", "tgvideo:1:5", "tgvideo:1:6"]
    assert [f for _, f in bot.sent] == ["6.mp4"]                      # only the new one, once


def test_same_file_listed_by_two_different_sites_goes_once(monkeypatch, tmp_path):
    _env(monkeypatch, tmp_path)
    s = st.load()
    s["sites"] = [{"url": "https://a.com", "adapter": "generic", "added": "x", "limit": 5},
                  {"url": "https://b.com", "adapter": "generic", "added": "x", "limit": 5}]
    s["sent"] = {"https://a.com": [], "https://b.com": []}
    st.save(s)
    same = Item(id="url:https://cdn/app.apk", url="https://cdn/app.apk", filename="app.apk", caption="", size=10)
    monkeypatch.setattr(m.adapters, "list_items", lambda url, adapter=None, **kw: ("generic", [same]))

    def fake_download(it, folder):
        p = os.path.join(folder, it.filename)
        open(p, "wb").write(b"apk")
        return p, 3

    monkeypatch.setattr(m, "download", fake_download)
    bot = HookBot()
    monkeypatch.setattr(m, "Bot", lambda token: bot)
    m.main()
    assert [f for _, f in bot.sent] == ["app.apk"]


def test_videos_and_files_go_to_their_own_channels(monkeypatch, tmp_path):
    _env(monkeypatch, tmp_path, CHANNEL_ID_VIDEO="-100777", CHANNEL_ID_FILES="-100888")
    monkeypatch.delenv("CHANNEL_ID")                       # optional when both are set
    s = st.load()
    s["sites"] = [{"url": "https://a.com", "adapter": "generic", "added": "x", "limit": 5}]
    st.save(s)
    items = [Item(id="1", url="https://a/v.mp4", filename="v.mp4", caption="", size=10, kind="video"),
             Item(id="2", url="https://a/x.apk", filename="x.apk", caption="", size=10),
             Item(id="3", url="https://a/c.mkv", filename="c.mkv", caption="", size=10)]
    monkeypatch.setattr(m.adapters, "list_items", lambda url, adapter=None, **kw: ("generic", items))

    def fake_download(it, folder):
        p = os.path.join(folder, it.filename)
        open(p, "wb").write(it.id.encode())
        return p, 1

    monkeypatch.setattr(m, "download", fake_download)
    bot = HookBot()
    monkeypatch.setattr(m, "Bot", lambda token: bot)
    assert m.main() == 0
    assert sorted(bot.sent) == [("-100777", "c.mkv"), ("-100777", "v.mp4"), ("-100888", "x.apk")]
    assert st.load()["routing"] == "videos → alag video channel, baaki files → alag files channel"


def test_only_video_channel_set_files_fall_back(monkeypatch, tmp_path):
    _env(monkeypatch, tmp_path, CHANNEL_ID_VIDEO="-100777")
    it = Item(id="2", url="https://a/x.apk", filename="x.apk", caption="", size=10)
    assert m.pick_channel(it, "-100123") == "-100123"
    it2 = Item(id="1", url="https://a/v.MP4", filename="v.MP4", caption="", size=10)
    assert m.pick_channel(it2, "-100123") == "-100777"


def _get_env(monkeypatch, tmp_path, content=b"PK\x03\x04apk-bytes", **extra):
    _env(monkeypatch, tmp_path, **extra)

    def fake_download(it, folder):
        p = os.path.join(folder, it.filename)
        open(p, "wb").write(content)
        return p, len(content)

    monkeypatch.setattr(m, "download", fake_download)
    bot = HookBot()
    return bot


def test_get_downloads_one_link_and_posts_it(monkeypatch, tmp_path):
    bot = _get_env(monkeypatch, tmp_path, CHANNEL_ID_FILES="-100888")
    s = st.load()
    reply = m.cmd_get(bot, s, "https://cdn.site.com/apps/My%20App.apk?x=1", "-100123")
    assert reply.startswith("✅ Bhej di: My App.apk") and "files channel" in reply
    assert bot.sent == [("-100888", "My App.apk")]
    assert s["files_sent_total"] == 1 and s["last_get"]["name"] == "My App.apk"
    again = m.cmd_get(bot, s, "https://mirror.other.com/My-App.apk", "-100123")   # same bytes
    assert "pehle se channel mein" in again and len(bot.sent) == 1


def test_get_mp4_without_extension_is_detected_as_video(monkeypatch, tmp_path):
    bot = _get_env(monkeypatch, tmp_path, content=b"\x00\x00\x00\x18ftypmp42rest", CHANNEL_ID_VIDEO="-100777")
    reply = m.cmd_get(bot, st.load(), "https://cdn.site.com/download/123", "-100123")
    assert bot.sent == [("-100777", "123.mp4")] and "video channel" in reply


def test_get_refuses_streams_pages_and_bad_links(monkeypatch, tmp_path):
    bot = _get_env(monkeypatch, tmp_path)
    s = st.load()
    assert "stream/YouTube" in m.cmd_get(bot, s, "https://x.com/live/index.m3u8", "-1")
    assert "stream/YouTube" in m.cmd_get(bot, s, "https://www.youtube.com/watch?v=abc", "-1")
    assert "stream/YouTube" in m.cmd_get(bot, s, "https://youtu.be/abc", "-1")
    assert "sahi nahi" in m.cmd_get(bot, s, "ftp://x.com/a.apk", "-1")
    assert "Aise likho" in m.cmd_get(bot, s, "", "-1")
    assert bot.sent == []

    def page(it, folder):
        raise RuntimeError("download gave a web page, not a file")

    monkeypatch.setattr(m, "download", page)
    assert "web page" in m.cmd_get(bot, s, "https://x.com/file", "-1")
    bot2 = _get_env(monkeypatch, tmp_path, content=b"#EXTM3U\n#EXT-X-VERSION:3")
    assert "m3u8" in m.cmd_get(bot2, st.load(), "https://x.com/playlist", "-1")
    assert bot2.sent == []


def test_get_big_file_without_userbot_is_explained(monkeypatch, tmp_path):
    bot = _get_env(monkeypatch, tmp_path)
    monkeypatch.setattr(m, "BOT_UPLOAD_LIMIT", 5)
    monkeypatch.setattr(m.userbot, "available", lambda: False)
    reply = m.cmd_get(bot, st.load(), "https://x.com/big.zip", "-1")
    assert "50 MB se badi" in reply and bot.sent == []


def test_get_via_dispatch_edits_ack(monkeypatch, tmp_path):
    bot = _get_env(monkeypatch, tmp_path, INJECTED_COMMAND="/get https://x.com/a.pdf", ACK_MESSAGE_ID="55")
    monkeypatch.setattr(m, "Bot", lambda token: bot)
    m.main()
    assert bot.sent == [("-100123", "a.pdf")]
    assert bot.msgs[0][1].startswith("EDIT#55:✅ Bhej di: a.pdf")


def test_addsite_depth_option(monkeypatch, tmp_path):
    _env(monkeypatch, tmp_path)
    seen = {}

    def fake_list(url, adapter=None, depth=0):
        seen["depth"] = depth
        return ("generic", [])

    monkeypatch.setattr(m.adapters, "list_items", fake_list)
    s = st.load()
    assert "5 level" in m.cmd_addsite(s, "https://a.com") and seen["depth"] == 5 and s["sites"][0]["depth"] == 5
    assert "Depth 0 se 5" in m.cmd_addsite(s, "https://b.com 3 9")
    assert "2 level" in m.cmd_addsite(s, "a.com/ 4 2") and s["sites"][0] == {**s["sites"][0], "limit": 4, "depth": 2}
    assert "2 level andar" in m.cmd_sites(s, "")


def test_parallel_downloads_upload_in_order(monkeypatch, tmp_path):
    import threading
    import time as _t
    _env(monkeypatch, tmp_path, PARALLEL_DOWNLOADS="4")
    monkeypatch.setattr(m, "UPLOAD_GAP_SECONDS", 0)
    monkeypatch.setattr(m, "PARALLEL_DOWNLOADS", 4)
    s = st.load()
    s["sites"] = [{"url": "https://a.com", "adapter": "generic", "added": "x", "limit": 6}]
    st.save(s)
    items = [Item(id=f"i{n}", url=f"https://a/{n}.mp4", filename=f"{n}.mp4", caption="", size=10, kind="video")
             for n in range(6)]
    monkeypatch.setattr(m.adapters, "list_items", lambda url, adapter=None, **kw: ("generic", items))
    live, peak, lock = [0], [0], threading.Lock()

    def slow_download(it, folder):
        with lock:
            live[0] += 1
            peak[0] = max(peak[0], live[0])
        _t.sleep(0.3 if it.id == "i0" else 0.05)      # first file is the slowest
        p = os.path.join(folder, it.filename)
        open(p, "wb").write(it.id.encode())
        with lock:
            live[0] -= 1
        return p, 2

    monkeypatch.setattr(m, "download", slow_download)
    bot = HookBot()
    monkeypatch.setattr(m, "Bot", lambda token: bot)
    t0 = _t.time()
    m.main()
    assert [f for _, f in bot.sent] == [f"{n}.mp4" for n in range(6)]   # posted in order
    assert peak[0] > 1                                                  # downloads overlapped
    assert _t.time() - t0 < 1.0                                         # not 0.3 + 5*0.05 sequential + gaps
