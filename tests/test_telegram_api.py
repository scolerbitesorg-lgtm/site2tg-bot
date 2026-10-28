import io

from bot.telegram_api import Bot, TelegramError


class FakeResponse:
    def __init__(self, payload, status=200):
        self.payload = payload
        self.status_code = status

    def json(self):
        return self.payload


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.positions = []

    def post(self, url, data=None, files=None, timeout=None):
        stream = next(iter(files.values()))[1] if files else None
        if stream is not None:
            self.positions.append(stream.read(1))
        return self.responses.pop(0)


def test_upload_retry_rewinds_file(monkeypatch):
    monkeypatch.setattr("bot.telegram_api.time.sleep", lambda _: None)
    bot = Bot("123:secret")
    bot.s = FakeSession([
        FakeResponse({"ok": False, "error_code": 500, "description": "temporary"}, 500),
        FakeResponse({"ok": True, "result": {"message_id": 7}}),
    ])
    result = bot.call("sendDocument", files={"document": ("x.pdf", io.BytesIO(b"abc"))}, tries=2)
    assert result["message_id"] == 7
    assert bot.s.positions == [b"a", b"a"]


def test_permanent_telegram_error_does_not_retry(monkeypatch):
    monkeypatch.setattr("bot.telegram_api.time.sleep", lambda _: None)
    bot = Bot("123:secret")
    bot.s = FakeSession([FakeResponse({"ok": False, "error_code": 400, "description": "bad request"}, 400)])
    try:
        bot.call("sendMessage", data={"text": "x"}, tries=3)
    except TelegramError as exc:
        assert "400" in str(exc)
        assert "secret" not in str(exc)
    else:
        raise AssertionError("expected TelegramError")
