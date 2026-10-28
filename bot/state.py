"""state.json: the bot's memory, committed back to the repo after every run.
Holds NO secrets."""
import json
import os

STATE_FILE = os.environ.get("STATE_FILE", "state.json")

DEFAULT = {
    "offset": 0,            # Telegram getUpdates offset
    "sites": [],            # [{url, adapter, added}]
    "sent": {},             # site url -> [item ids already in the channel]
    "big_pending": {},      # item id -> {site, name, size}  (too big, no userbot)
    "last_sync": None,
    "last_result": "",
    "files_sent_total": 0,
    "fails": {},            # item id -> failed tries
    "errors": [],           # last 20: {at, msg}
    "sync_requested": False,
}


def load():
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        data = {}
    out = json.loads(json.dumps(DEFAULT))
    out.update(data)
    return out


def save(state):
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=1, sort_keys=True)
        f.write("\n")
    os.replace(tmp, STATE_FILE)


def add_error(state, msg, at):
    state["errors"] = (state.get("errors") or [])[-19:] + [{"at": at, "msg": msg}]
