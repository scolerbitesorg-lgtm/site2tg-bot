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
    for k, v in extra.items():
        monkeypatch.setenv(k, v)


def test_webhook_mode_uses_injected_command_only(monkeypatch, tmp_path):
    _env(monkeypatch, tmp_path, INJECTED_COMMAND="/addsite mysite.com 2")
    item = Item(id="a:1", url="https://s/1.apk", filename="1.apk", caption="c", size=10)
    monkeypatch.setattr(m.adapters, "list_items", lambda url, adapter=None: ("generic", [item]))

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
    monkeypatch.setattr(m.adapters, "list_items", lambda url, adapter=None: ("generic", []))
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
