"""Minimal Telegram Bot API client (requests only). Never logs the token."""
import time

import requests

from .util import redact

BOT_UPLOAD_LIMIT = 50_000_000  # Bot API upload limit is 50 MB


class TelegramError(Exception):
    pass


class Bot:
    def __init__(self, token: str):
        self._base = f"https://api.telegram.org/bot{token}/"
        self.s = requests.Session()

    def call(self, method, data=None, files=None, timeout=60, tries=3):
        last = None
        for _ in range(tries):
            try:
                r = self.s.post(self._base + method, data=data, files=files, timeout=timeout)
                j = r.json()
            except Exception as e:  # network error: never include the URL (has token)
                last = TelegramError(f"{method}: network error {type(e).__name__}")
                time.sleep(3)
                continue
            if j.get("ok"):
                return j["result"]
            params = j.get("parameters") or {}
            if j.get("error_code") == 429 and params.get("retry_after"):
                time.sleep(min(int(params["retry_after"]) + 1, 60))
                continue
            raise TelegramError(redact(f"{method}: {j.get('error_code')} {j.get('description')}"))
        raise last or TelegramError(f"{method}: failed")

    def get_updates(self, offset):
        return self.call("getUpdates", {"offset": offset, "timeout": 0,
                                        "allowed_updates": '["message"]'}, timeout=30)

    def get_webhook_info(self):
        return self.call("getWebhookInfo", {}, timeout=20, tries=2)

    def edit_message(self, chat_id, message_id, text):
        return self.call("editMessageText", {"chat_id": chat_id, "message_id": message_id, "text": text[:4000],
                                             "disable_web_page_preview": "true"}, tries=2)

    def send_message(self, chat_id, text):
        return self.call("sendMessage", {"chat_id": chat_id, "text": text[:4000],
                                         "disable_web_page_preview": "true"})

    def send_file(self, chat_id, path, filename, caption, kind):
        method, field = ("sendVideo", "video") if kind == "video" else ("sendDocument", "document")
        data = {"chat_id": chat_id, "caption": caption[:1000]}
        if kind == "video":
            data["supports_streaming"] = "true"
        with open(path, "rb") as f:
            return self.call(method, data, files={field: (filename, f)}, timeout=600, tries=2)
