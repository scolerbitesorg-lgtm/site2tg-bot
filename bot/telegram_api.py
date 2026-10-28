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
        for attempt in range(max(1, tries)):
            try:
                # requests consumes upload streams. Rewind them before every retry
                # or a transient failure would send an empty file on the next try.
                for entry in (files or {}).values():
                    if isinstance(entry, (tuple, list)) and len(entry) >= 2:
                        stream = entry[1]
                        if hasattr(stream, "seek"):
                            stream.seek(0)
                r = self.s.post(self._base + method, data=data, files=files, timeout=timeout)
                j = r.json()
            except Exception as e:  # never include the URL (it contains the token)
                last = TelegramError(f"{method}: network/response error {type(e).__name__}")
                if attempt + 1 < max(1, tries):
                    time.sleep(min(2 ** attempt, 8))
                    continue
                break
            if j.get("ok"):
                return j["result"]
            params = j.get("parameters") or {}
            code = j.get("error_code") or getattr(r, "status_code", None)
            if code == 429:
                wait = params.get("retry_after", 2 ** attempt)
                if attempt + 1 < max(1, tries):
                    time.sleep(min(max(1, int(wait)), 60))
                    continue
            if isinstance(code, int) and code >= 500 and attempt + 1 < max(1, tries):
                last = TelegramError(f"{method}: Telegram server error {code}")
                time.sleep(min(2 ** attempt, 8))
                continue
            raise TelegramError(redact(f"{method}: {code} {j.get('description')}"))
        raise last or TelegramError(f"{method}: failed after retries")

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
