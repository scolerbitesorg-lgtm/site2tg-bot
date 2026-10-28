"""Offline test of one full bot run with a fake Telegram and fake websites."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bot import main as m  # noqa: E402
from bot import state as st  # noqa: E402
from bot.adapters.base import Item  # noqa: E402


class FakeBot:
    def __init__(self, updates):
        self.updates, self.sent, self.msgs = updates, [], []

    def get_updates(self, offset):
        return [u for u in self.updates if u["update_id"] >= offset]

    def send_message(self, chat_id, text):
        self.msgs.append((chat_id, text))

    def send_file(self, chat_id, path, filename, caption, kind):
        assert os.path.getsize(path) > 0
        self.sent.append((chat_id, filename, caption, kind))


def upd(i, text, uid=111):
    return {"update_id": i, "message": {"text": text, "from": {"id": uid}, "chat": {"id": uid}}}


def test_full_run(tmp_path, monkeypatch):
    monkeypatch.setattr(st, "STATE_FILE", str(tmp_path / "state.json"))
    small = Item(id="x:1", url="https://s/1.mp4", filename="1.mp4", caption="c1", size=1000, kind="video")
    big = Item(id="x:2", url="https://s/2.mp4", filename="2.mp4", caption="c2", size=90_000_000, kind="video")
    broken = Item(id="x:3", url="https://s/3.apk", filename="3.apk", caption="c3", size=10)

    monkeypatch.setattr(m.adapters, "list_items", lambda url, adapter=None: ("generic", [small, big, broken]))

    def fake_download(item, folder):
        if item.id == "x:3":
            raise RuntimeError("download HTTP 404")
        p = os.path.join(folder, item.filename)
        open(p, "wb").write(b"0" * 1000)
        return p, 1000

    monkeypatch.setattr(m, "download", fake_download)
    monkeypatch.setattr(m.userbot, "available", lambda: False)
    for k, v in {"BOT_TOKEN": "1:x", "CHANNEL_ID": "-100123", "OWNER_ID": "111"}.items():
        monkeypatch.setenv(k, v)

    bot = FakeBot([upd(5, "/addsite mysite.com"), upd(6, "/status", uid=999), upd(7, "/sites")])
    monkeypatch.setattr(m, "Bot", lambda token: bot)
    assert m.main() == 0

    s = st.load()
    assert s["offset"] == 8
    assert s["sites"][0]["url"] == "https://mysite.com"
    assert bot.sent == [("-100123", "1.mp4", "c1", "video")]        # small one sent
    assert "x:2" in s["big_pending"]                                  # big one held
    assert s["fails"]["x:3"] == 1 and s["errors"]                     # broken one recorded
    assert s["sent"]["https://mysite.com"] == ["x:1"]
    assert len([t for c, t in bot.msgs if c == 999]) == 0             # stranger ignored
    assert any("Site jod di" in t for _, t in bot.msgs)

    # second run: nothing new is re-sent, /status works
    bot.updates = [upd(8, "/status")]
    bot.sent.clear()
    s["last_sync"] = None
    st.save(s)
    assert m.main() == 0
    assert bot.sent == []
    assert any("Status" in t and "badi files" in t for _, t in bot.msgs)


def test_missing_secrets_exits_cleanly(monkeypatch, tmp_path):
    monkeypatch.setattr(st, "STATE_FILE", str(tmp_path / "state.json"))
    for k in ("BOT_TOKEN", "CHANNEL_ID", "OWNER_ID"):
        monkeypatch.delenv(k, raising=False)
    assert m.main() == 0


def test_setup_mode_tells_ids(monkeypatch, tmp_path):
    monkeypatch.setattr(st, "STATE_FILE", str(tmp_path / "state.json"))
    monkeypatch.setenv("BOT_TOKEN", "1:x")
    monkeypatch.delenv("CHANNEL_ID", raising=False)
    monkeypatch.delenv("OWNER_ID", raising=False)
    fwd = {"update_id": 3, "message": {"from": {"id": 42}, "chat": {"id": 42},
           "forward_origin": {"type": "channel", "chat": {"id": -1009876, "title": "Backup"}}}}
    bot = FakeBot([upd(2, "/start", uid=42), fwd])
    monkeypatch.setattr(m, "Bot", lambda token: bot)
    assert m.main() == 0
    assert "42" in bot.msgs[0][1]
    assert "-1009876" in bot.msgs[1][1]
    assert st.load()["offset"] == 4


def test_site_limit(monkeypatch, tmp_path):
    monkeypatch.setattr(st, "STATE_FILE", str(tmp_path / "state.json"))
    items = [Item(id=f"u:{i}", url=f"https://s/{i}.apk", filename=f"{i}.apk", caption="", size=10) for i in range(7)]
    monkeypatch.setattr(m.adapters, "list_items", lambda url, adapter=None: ("generic", items))

    def fake_download(item, folder):
        p = os.path.join(folder, item.filename)
        open(p, "wb").write(item.id.encode())
        return p, 1

    monkeypatch.setattr(m, "download", fake_download)
    for k, v in {"BOT_TOKEN": "1:x", "CHANNEL_ID": "-100123", "OWNER_ID": "111"}.items():
        monkeypatch.setenv(k, v)
    bot = FakeBot([upd(1, "/addsite https://s.com 2")])
    monkeypatch.setattr(m, "Bot", lambda token: bot)
    m.main()
    assert [f for _, f, _, _ in bot.sent] == ["0.apk", "1.apk"]      # only 2 per sync
    s = st.load()
    assert s["sites"][0]["limit"] == 2
    s["last_sync"] = None
    st.save(s)
    bot.updates, bot.sent = [], []
    m.main()
    assert [f for _, f, _, _ in bot.sent] == ["2.apk", "3.apk"]      # next sync continues, no repeats


def test_duplicate_content_posted_once(monkeypatch, tmp_path):
    monkeypatch.setattr(st, "STATE_FILE", str(tmp_path / "state.json"))
    items = [Item(id="u:a", url="https://s/latest.apk", filename="latest.apk", caption="", size=5),
             Item(id="u:b", url="https://s/v52.apk", filename="v52.apk", caption="", size=5)]
    monkeypatch.setattr(m.adapters, "list_items", lambda url, adapter=None: ("generic", items))

    def fake_download(item, folder):
        p = os.path.join(folder, item.filename)
        open(p, "wb").write(b"same-bytes")
        return p, 10

    monkeypatch.setattr(m, "download", fake_download)
    for k, v in {"BOT_TOKEN": "1:x", "CHANNEL_ID": "-100123", "OWNER_ID": "111"}.items():
        monkeypatch.setenv(k, v)
    bot = FakeBot([upd(1, "/addsite https://s.com")])
    monkeypatch.setattr(m, "Bot", lambda token: bot)
    m.main()
    assert [f for _, f, _, _ in bot.sent] == ["latest.apk"]
    assert st.load()["sent"]["https://s.com"] == ["u:a", "u:b"]
