"""One run of the bot (GitHub Actions calls this on a schedule, or right away
when the Vercel webhook dispatches a command):
1. read new Telegram commands from the owner and answer them
   - polling mode: via getUpdates
   - webhook mode (Vercel front-end set as the Telegram webhook): getUpdates is
     disabled by Telegram, so the only command is the one the webhook passed in
     as the workflow_dispatch input `command` (env INJECTED_COMMAND)
2. if a sync is due (or /sync was sent), find new files on every site,
   download each one to disk, post it to the channel, delete it
3. save state.json (the workflow commits it)
"""
import hashlib
import os
import shutil
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import unquote, urlparse

from . import adapters, state as st, userbot, youtube_tracker
from .adapters.base import Item
from .telegram_api import BOT_UPLOAD_LIMIT, Bot, TelegramError
from .util import http, human_size, ist, now_iso, parse_iso, redact, safe_name
from .security import safe_request, validate_url_shape

USERBOT_LIMIT = 2_000_000_000
SYNC_EVERY_MIN = int(os.environ.get("SYNC_EVERY_MIN") or 10)
MAX_FILES_PER_RUN = int(os.environ.get("MAX_FILES_PER_RUN") or 15)
MAX_RUN_SECONDS = int(os.environ.get("MAX_RUN_MINUTES") or 40) * 60
DEFAULT_SITE_LIMIT = 3  # max new files per site per sync (change per site: /addsite <url> <limit>)
MAX_TRIES = 3  # after 3 failed tries a file is skipped (use /retry to try again)
START = time.time()

HELP = """🤖 site2tg-bot commands

/addsite <url> [limit] [depth] — nayi website jodo (limit = ek sync mein max nayi files, default 3; depth = andar ke pages kitne level, 0-5, default 5)
/removesite <url> — website hatao
/sites — saari websites ki list
/sync — abhi sync karo (agle run pe)
/status — kitni files gayi, last sync, errors
/retry — jo files 3 baar fail hui, unhe dobara try karo
/id — aapka OWNER_ID aur CHANNEL_ID
/get <link> — ek direct file link (…/video.mp4, .apk, .pdf) turant download karke channel mein
/addplaylist <YouTube playlist URL/ID> — public playlist ko one-by-one link queue mein jodo
/addyoutube <channel URL/UC... ID> — public channel ke naye uploads track karo
/youtubes — tracked YouTube playlists/channels dekho
/removeyoutube <URL/ID> — tracker hatao
/yt <YouTube video URL> — video ka watch link channel mein post karo (media download nahi)
/help — ye message

Note: Vercel webhook laga hai toh /menu, /status, /sites turant; add/remove/sync/retry ka "⏳ chal raha hai" turant aur result ~1-2 min mein. Webhook nahi laga toh bot har ~1 ghante pe jaagta hai."""


VIDEO_EXTS = {".mp4", ".mkv", ".webm", ".mov", ".m4v", ".avi", ".3gp"}
STREAM_HINTS = (".m3u8", ".mpd")
STREAM_HOSTS = ("youtube.com", "youtu.be")


def is_video(item) -> bool:
    return item.kind == "video" or os.path.splitext(item.filename.lower())[1] in VIDEO_EXTS


def pick_channel(item, default):
    """Videos -> CHANNEL_ID_VIDEO, everything else -> CHANNEL_ID_FILES; each
    falls back to CHANNEL_ID when not set."""
    if is_video(item):
        return os.environ.get("CHANNEL_ID_VIDEO") or default
    return os.environ.get("CHANNEL_ID_FILES") or default


def routing_note():
    v = "alag video channel" if os.environ.get("CHANNEL_ID_VIDEO") else "main channel"
    f = "alag files channel" if os.environ.get("CHANNEL_ID_FILES") else "main channel"
    return f"videos → {v}, baaki files → {f}"


def log(msg):
    print(redact(msg), flush=True)


def norm_url(u: str) -> str:
    u = u.strip().strip("<>")
    if not u.startswith(("http://", "https://")):
        u = "https://" + u
    return u


def site_key(u: str) -> str:
    """Same site, however it was typed: http/https, www., trailing slash and
    host case don't matter (https://x.com/a/ == x.com/a == http://www.X.com/a)."""
    p = urlparse(norm_url(u))
    host = p.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    path = p.path.rstrip("/")
    return host + path + (("?" + p.query) if p.query else "")


def find_site(state, url):
    key = site_key(url)
    for s in state["sites"]:
        if site_key(s["url"]) == key:
            return s
    return None


def dedupe_sites(state):
    """Merge site entries that are the same site (older state could hold
    https://x.com/ and https://x.com both, which sent every file twice)."""
    seen, keep = {}, []
    for s in state["sites"]:
        k = site_key(s["url"])
        if k not in seen:
            seen[k] = s
            keep.append(s)
            continue
        first = seen[k]["url"]
        for field in ("sent", "hashes"):
            merged = state[field].setdefault(first, [])
            for v in state[field].pop(s["url"], []):
                if v not in merged:
                    merged.append(v)
        for v in state["big_pending"].values():
            if v.get("site") == s["url"]:
                v["site"] = first
        log(f"merged duplicate site entry: {s['url']} -> {first}")
    state["sites"] = keep


def valid_url(u: str) -> bool:
    try:
        validate_url_shape(u)
        return True
    except (TypeError, ValueError):
        return False


# ---------------------------------------------------------------- commands

NEW_SITE_DEPTH = 5  # inner-page levels for a newly added normal site (0-5)


def cmd_addsite(state, arg):
    if not arg:
        return ("Aise likho: /addsite https://meri-site.com 3 2\n"
                "(3 = ek sync mein max nayi files, default 3; 2 = andar ke kitne level ke pages bhi dekhe, 0-5, default 5. Dono optional)")
    parts = arg.split()
    url = norm_url(parts[0])
    limit, depth = DEFAULT_SITE_LIMIT, NEW_SITE_DEPTH
    if len(parts) > 1:
        if not parts[1].isdigit() or int(parts[1]) < 1:
            return "Limit ek number hona chahiye, jaise: /addsite https://meri-site.com 5"
        limit = int(parts[1])
    if len(parts) > 2:
        if not parts[2].isdigit() or int(parts[2]) > 5:
            return "Depth 0 se 5 tak ka number hona chahiye, jaise: /addsite https://meri-site.com 5 2"
        depth = int(parts[2])
    if not valid_url(url):
        return "Ye URL sahi nahi lag raha."
    s = find_site(state, url)
    if s:
        if len(parts) > 1:
            s["limit"] = limit
            if len(parts) > 2:
                s["depth"] = depth
            return (f"Ye site pehle se hai ({s['url']}). Ab: max {s['limit']} files per sync, "
                    f"andar ke pages: {s.get('depth', 0)} level.")
        return f"Ye site pehle se list mein hai: {s['url']}"
    try:
        name, items = adapters.list_items(url, depth=depth)
    except Exception as e:
        return f"Site khul nahi rahi: {redact(e)}"
    site = {"url": url, "adapter": name, "added": now_iso(), "limit": limit}
    if name == "generic":
        site["depth"] = depth
    state["sites"].append(site)
    state["sent"].setdefault(url, [])
    state["sync_requested"] = True
    kind = "video catalog site" if name == "tgvideo" else f"normal page + andar ke pages ({depth} level)"
    return (f"✅ Site jod di: {url}\nType: {kind}\nAbhi {len(items)} files mili. "
            f"Har sync mein max {limit} nayi files jayengi. Sync isi run mein shuru ho raha hai.")


def cmd_removesite(state, arg):
    site = find_site(state, arg) if arg else None
    if not site:
        return "Ye site list mein nahi mili. /sites se URL dekho."
    url = site["url"]
    state["sites"] = [s for s in state["sites"] if s is not site]
    state["sent"].pop(url, None)
    state["hashes"].pop(url, None)
    state["big_pending"] = {k: v for k, v in state["big_pending"].items() if v.get("site") != url}
    # ids of this site's items in "fails" are harmless; they are cleared on /retry
    return f"🗑 Hata di: {url}"


def cmd_sites(state, _):
    if not state["sites"]:
        return "Abhi koi site nahi hai. /addsite <url> se jodo."
    lines = [f"{i}. {s['url']} ({s['adapter']}, max {s.get('limit', DEFAULT_SITE_LIMIT)}/sync"
             + (f", {s['depth']} level andar" if s.get("depth") else "") + ") — "
             f"{len(state['sent'].get(s['url'], []))} files bheji"
             for i, s in enumerate(state["sites"], 1)]
    return "🌐 Websites:\n" + "\n".join(lines)


def cmd_status(state, _):
    big = state.get("big_pending") or {}
    lines = [
        "📊 Status",
        f"Websites: {len(state['sites'])}",
        f"Total files bheji: {state.get('files_sent_total', 0)}",
        f"Last sync: {ist(state.get('last_sync'))}",
        f"Last result: {state.get('last_result') or '-'}",
        f"Channels: {routing_note()}",
        f"Badi files (>50 MB) ke liye userbot: {'ON ✅' if userbot.available() else 'OFF (secrets nahi hain)'}",
    ]
    if big:
        lines.append(f"\n⚠️ {len(big)} badi files ruki hui hain (userbot secrets daalo):")
        for v in list(big.values())[:10]:
            lines.append(f"• {v.get('name')} ({human_size(v.get('size'))})")
    gave_up = sum(1 for v in (state.get("fails") or {}).values() if v >= MAX_TRIES)
    if gave_up:
        lines.append(f"\n⛔ {gave_up} files 3 baar fail hui, skip ho rahi hain (/retry)")
    errs = state.get("errors") or []
    if errs:
        lines.append("\n❌ Last errors:")
        for e in errs[-5:]:
            lines.append(f"• {ist(e['at'])}: {e['msg']}")
    return "\n".join(lines)


def cmd_retry(state, _):
    n = sum(1 for v in state["fails"].values() if v >= MAX_TRIES)
    state["fails"] = {}
    state["sync_requested"] = True
    return f"🔁 {n} fail hui files dobara try hongi, sync shuru."


def cmd_id(state, _):
    return f"OWNER_ID: {os.environ.get('OWNER_ID')}\nCHANNEL_ID: {os.environ.get('CHANNEL_ID')}"


def cmd_sync(state, _):
    state["sync_requested"] = True
    return "🔄 Sync shuru ho raha hai (isi run mein). Khatam hote hi result bhejunga."


def _youtube_source_key(source):
    return f"{source['kind']}:{source['id']}"


def cmd_add_youtube_source(state, arg, kind):
    if not arg:
        example = "/addplaylist https://www.youtube.com/playlist?list=PLAYLIST_ID" if kind == "playlist" else "/addyoutube https://www.youtube.com/@channel"
        return f"Aise likho: {example}"
    try:
        source = youtube_tracker.parse_source(arg.split()[0], kind)
    except Exception as e:
        return f"Link/ID sahi nahi: {redact(e)}"
    state.setdefault("youtube_sources", [])
    state.setdefault("youtube_seen", {})
    state.setdefault("youtube_pending", {})
    key = _youtube_source_key(source)
    if any(_youtube_source_key(s) == key for s in state["youtube_sources"]):
        return f"Ye {kind} pehle se track ho rahi hai: {source['url']}"
    source["added"] = now_iso()
    state["youtube_sources"].append(source)
    state["youtube_seen"].setdefault(key, [])
    state["youtube_pending"].setdefault(key, [])
    state["sync_requested"] = True
    return ("✅ Public YouTube source add ho gaya. Available links next sync mein queue honge, "
            "phir ek-ek karke channel par post honge. Ye watch links hain, video files nahi.\n" + source["url"])


def cmd_addplaylist(state, arg):
    return cmd_add_youtube_source(state, arg, "playlist")


def cmd_addyoutube(state, arg):
    return cmd_add_youtube_source(state, arg, "channel")


def cmd_youtubes(state, _):
    sources = state.get("youtube_sources") or []
    if not sources:
        return "Koi YouTube source track nahi ho raha. /addplaylist ya /addyoutube use karo."
    lines = ["📺 Tracked YouTube sources:"]
    for i, source in enumerate(sources, 1):
        key = _youtube_source_key(source)
        pending = len((state.get("youtube_pending") or {}).get(key, []))
        seen = len((state.get("youtube_seen") or {}).get(key, []))
        lines.append(f"{i}. {source['kind']} — {source['url']}\n   Posted links: {seen}; queue: {pending}")
    return "\n".join(lines)


def cmd_removeyoutube(state, arg):
    if not arg:
        return "Aise likho: /removeyoutube <playlist/channel URL ya ID>"
    value = arg.strip()
    sources = state.get("youtube_sources") or []
    match = None
    for source in sources:
        if value in (source.get("id"), source.get("url")) or value in source.get("url", ""):
            match = source
            break
    if not match:
        return "Ye YouTube source nahi mili. /youtubes dekho."
    state["youtube_sources"] = [s for s in sources if s is not match]
    key = _youtube_source_key(match)
    (state.get("youtube_seen") or {}).pop(key, None)
    (state.get("youtube_pending") or {}).pop(key, None)
    return f"🗑 YouTube tracker hata diya: {match['url']}"


def cmd_yt(bot, arg, default_channel):
    if not arg:
        return "Aise likho: /yt https://www.youtube.com/watch?v=VIDEO_ID"
    try:
        url, video_id = youtube_tracker.parse_video_url(arg.split()[0])
        channel = os.environ.get("CHANNEL_ID_VIDEO") or default_channel
        bot.send_message(channel, f"▶️ YouTube video link\n{url}")
        return f"✅ Watch link channel par post kar diya: {video_id}\nNote: YouTube media download nahi hua."
    except Exception as e:
        return f"Link post nahi hua: {redact(e)}"


def sync_youtube_links(bot, state, channel_id):
    """Queue public watch links and post them one at a time; never downloads media."""
    sources = state.get("youtube_sources") or []
    if not sources:
        return 0, 0
    state.setdefault("youtube_seen", {})
    state.setdefault("youtube_pending", {})
    max_links = max(1, int(os.environ.get("MAX_YOUTUBE_LINKS_PER_RUN") or 5))
    posted, failed = 0, 0
    target = os.environ.get("CHANNEL_ID_VIDEO") or channel_id
    for source in sources:
        key = _youtube_source_key(source)
        seen = state["youtube_seen"].setdefault(key, [])
        pending = state["youtube_pending"].setdefault(key, [])
        try:
            entries = youtube_tracker.fetch_entries(source)
            known = set(seen) | {v.get("id") for v in pending}
            for entry in entries:
                if entry["id"] not in known:
                    pending.append(entry)
                    known.add(entry["id"])
        except Exception as e:
            failed += 1
            st.add_error(state, f"YouTube {source['url']}: {redact(e)}", now_iso())
            log(f"YouTube tracker fetch failed: {redact(e)}")
        # Preserve order and a durable queue across scheduled workflow runs.
        batch = pending[:max_links]
        for entry in batch:
            try:
                title = (entry.get("title") or "YouTube video").replace("\n", " ")[:180]
                bot.send_message(target, f"▶️ {title}\n{entry['url']}\nSource: {source['url']}")
                seen.append(entry["id"])
                pending.remove(entry)
                posted += 1
                time.sleep(1.0)
            except Exception as e:
                failed += 1
                st.add_error(state, f"YouTube post {entry.get('id')}: {redact(e)}", now_iso())
                log(f"YouTube link post failed: {redact(e)}")
                break
    return posted, failed


def cmd_get(bot, state, arg, default_channel):
    """/get <direct file URL>: download that one file and post it."""
    if not arg:
        return "Aise likho: /get https://site.com/file.mp4\n(sirf direct file link: .mp4 .apk .pdf .zip …)"
    url = arg.split()[0].strip("<>")
    p = urlparse(url)
    if not valid_url(url):
        return "Ye link sahi nahi lag raha. Sirf public http:// ya https:// file link chalega; local/private addresses allowed nahi hain."
    host = p.netloc.lower()
    if p.path.lower().endswith(STREAM_HINTS) or any(host == h or host.endswith("." + h) for h in STREAM_HOSTS):
        return "Ye stream/YouTube link hai. Ye bot sirf direct file links download karta hai (jaise …/video.mp4, …/app.apk)."
    name = safe_name(unquote(os.path.basename(p.path)), "file")
    ext = os.path.splitext(name.lower())[1]
    item = Item(id=f"get:{p.netloc}{p.path}", url=url, filename=name, caption=name,
                kind="video" if ext in VIDEO_EXTS else "document")
    tmp = tempfile.mkdtemp(prefix="site2tg-get-")
    try:
        try:
            path, real = download(item, tmp)
        except Exception as e:
            msg = str(e)
            if "web page" in msg:
                return "Ye link file nahi, web page khol raha hai. Direct file link chahiye (jo browser mein kholte hi download ho)."
            return f"Download nahi hua: {redact(e)}"
        with open(path, "rb") as f:
            head = f.read(16)
        if head.startswith(b"#EXTM3U"):
            return "Ye m3u8 stream playlist hai, file nahi. Ye bot streams download nahi karta."
        if not ext and head[4:8] == b"ftyp":  # mp4 without a name
            item.filename = item.caption = name + ".mp4"
            item.kind = "video"
            os.rename(path, path + ".mp4")
            path += ".mp4"
        digest = file_hash(path)
        if any(digest in hs for hs in state["hashes"].values()):
            return f"Ye file pehle se channel mein hai, dobara nahi bheji: {item.filename}"
        channel = pick_channel(item, default_channel)
        if real <= BOT_UPLOAD_LIMIT:
            bot.send_file(channel, path, item.filename, item.caption, item.kind)
        elif userbot.available():
            userbot.send_big(channel, path, item.caption, item.kind)
        else:
            return (f"File {human_size(real)} ki hai, 50 MB se badi. Iske liye API_ID, API_HASH, SESSION_STRING "
                    "secrets chahiye (README dekho).")
        state["hashes"].setdefault("/get", []).append(digest)
        state["files_sent_total"] = state.get("files_sent_total", 0) + 1
        where = "video channel" if is_video(item) and os.environ.get("CHANNEL_ID_VIDEO") else (
            "files channel" if not is_video(item) and os.environ.get("CHANNEL_ID_FILES") else "channel")
        state["last_get"] = {"at": now_iso(), "name": item.filename, "size": real}
        log(f"/get sent {item.filename}")
        return f"✅ Bhej di: {item.filename} ({human_size(real)}) → {where}"
    except Exception as e:
        st.add_error(state, f"/get {item.filename}: {redact(e)}", now_iso())
        return f"Bhej nahi paya: {redact(e)}"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


COMMANDS = {
    "/addsite": cmd_addsite, "/removesite": cmd_removesite, "/sites": cmd_sites,
    "/status": cmd_status, "/sync": cmd_sync, "/retry": cmd_retry, "/id": cmd_id, "/addplaylist": cmd_addplaylist, "/addyoutube": cmd_addyoutube, "/youtubes": cmd_youtubes, "/removeyoutube": cmd_removeyoutube, "/help": lambda s, a: HELP, "/start": lambda s, a: HELP,
}


def run_command(bot, state, text, chat_id, edit_message_id=None):
    """Answer one owner command (already checked to be from the owner).
    edit_message_id: the webhook's "⏳ chal raha hai…" message; it is edited
    into the result (a new message is sent if the edit fails)."""
    parts = text.split(maxsplit=1)
    cmd = parts[0].split("@")[0].lower()
    arg = parts[1].strip() if len(parts) > 1 else ""
    if cmd == "/get":
        reply = cmd_get(bot, state, arg, os.environ.get("CHANNEL_ID"))
    elif cmd == "/yt":
        reply = cmd_yt(bot, arg, os.environ.get("CHANNEL_ID"))
    else:
        fn = COMMANDS.get(cmd)
        reply = fn(state, arg) if fn else "Ye command nahi pata. /help dekho."
    if edit_message_id:
        try:
            bot.edit_message(chat_id, edit_message_id, reply)
            return
        except Exception as e:
            log(f"edit failed, sending instead: {e}")
    try:
        bot.send_message(chat_id, reply)
    except TelegramError as e:
        log(f"reply failed: {e}")


def handle_updates(bot, state, owner_id):
    try:
        updates = bot.get_updates(state["offset"])
    except TelegramError as e:
        log(f"getUpdates failed: {e}")
        st.add_error(state, f"getUpdates: {e}", now_iso())
        return
    for u in updates:
        state["offset"] = u["update_id"] + 1
        msg = u.get("message") or {}
        text = (msg.get("text") or "").strip()
        sender = (msg.get("from") or {}).get("id")
        if not text.startswith("/"):
            continue
        if str(sender) != str(owner_id):
            log("ignored command from non-owner user")
            continue
        log(f"command: {text.split()[0]}")
        run_command(bot, state, text, msg["chat"]["id"])


def injected_command():
    """The command the Vercel webhook passed in (workflow_dispatch input), if any.
    Only the owner can cause one: the webhook checks OWNER_ID and dispatching
    needs a GitHub token for this repo."""
    text = (os.environ.get("INJECTED_COMMAND") or "").strip()
    return text if text.startswith("/") else ""


def ack_message_id():
    v = (os.environ.get("ACK_MESSAGE_ID") or "").strip()
    return int(v) if v.isdigit() else None


def webhook_active(bot):
    """True when a Telegram webhook is set (then getUpdates answers 409).
    WEBHOOK_MODE=1 / 0 (repo variable) forces it; otherwise ask Telegram."""
    forced = (os.environ.get("WEBHOOK_MODE") or "").strip().lower()
    if forced in ("1", "true", "yes", "on"):
        return True
    if forced in ("0", "false", "no", "off"):
        return False
    try:
        info = bot.get_webhook_info()
    except Exception as e:  # can't tell: fall back to polling (old behaviour)
        log(f"getWebhookInfo failed: {e}")
        return False
    return bool((info or {}).get("url"))


# ---------------------------------------------------------------- sync

def download(item, folder):
    """Stream the file to disk. Returns (path, size) or raises."""
    path = os.path.join(folder, item.filename)
    s = http()
    with safe_request(item.url, session=s, headers=item.headers, stream=True, timeout=(20, 120)) as r:
        if r.status_code != 200:
            raise RuntimeError(f"download HTTP {r.status_code}")
        ctype = r.headers.get("Content-Type", "").lower()
        if ctype.startswith(("text/html", "application/xhtml+xml")):
            raise RuntimeError("download gave a web page, not a file")
        declared = r.headers.get("Content-Length")
        if declared and declared.isdigit() and int(declared) > USERBOT_LIMIT:
            raise RuntimeError("file bigger than 2 GB")
        size = 0
        with open(path, "wb") as f:
            for chunk in r.iter_content(1024 * 256):
                if not chunk:
                    continue
                size += len(chunk)
                if size > USERBOT_LIMIT:
                    raise RuntimeError("file bigger than 2 GB")
                f.write(chunk)
    if size == 0:
        raise RuntimeError("empty file")
    return path, size


def file_hash(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()[:20]


def remote_size(item):
    if item.size:
        return int(item.size)
    try:
        r = safe_request(item.url, session=http(), method="HEAD", headers=item.headers, timeout=20)
        n = r.headers.get("Content-Length")
        return int(n) if n and r.status_code == 200 else None
    except Exception:
        return None


PARALLEL_DOWNLOADS = max(1, int(os.environ.get("PARALLEL_DOWNLOADS") or 4))
UPLOAD_GAP_SECONDS = 1.0  # small pause between channel posts (Telegram flood limits)


def _fetch(item, folder, size_limit):
    """Runs in a worker thread: size check, then download. Never raises."""
    try:
        size = remote_size(item)
        if size and size > size_limit:
            return ("big", size)
        sub = tempfile.mkdtemp(dir=folder)  # own folder: same filenames can't clash
        path, real = download(item, sub)
        return ("ok", path, real)
    except Exception as e:
        return ("err", e)


def sync(bot, state, channel_id):
    sent_now, failed, big_now = 0, 0, 0
    has_userbot = userbot.available()
    size_limit = USERBOT_LIMIT if has_userbot else BOT_UPLOAD_LIMIT
    # never post the same file twice, even if two site entries list it
    all_ids = {i for ids in state["sent"].values() for i in ids}
    all_hashes = {h for hs in state["hashes"].values() for h in hs}
    tmp = tempfile.mkdtemp(prefix="site2tg-")
    pool = ThreadPoolExecutor(max_workers=PARALLEL_DOWNLOADS)
    last_upload = 0.0
    try:
        for site in list(state["sites"]):
            url = site["url"]
            done = set(state["sent"].setdefault(url, []))
            site_limit = int(site.get("limit") or DEFAULT_SITE_LIMIT)
            try:
                name, items = adapters.list_items(url, site.get("adapter"), depth=int(site.get("depth") or 0))
            except Exception as e:
                failed += 1
                st.add_error(state, f"{url}: list failed: {redact(e)}", now_iso())
                continue
            # pick this sync's new files for the site
            todo = []
            for item in items:
                if item.id in done:
                    continue
                if item.id in all_ids:  # already posted for another site entry
                    state["sent"][url].append(item.id)
                    done.add(item.id)
                    continue
                if state["fails"].get(item.id, 0) >= MAX_TRIES:
                    continue  # gave up on this file; shown in /status
                if len(todo) >= site_limit:
                    break  # rest of this site's new files go in later syncs
                if sent_now + len(todo) >= MAX_FILES_PER_RUN or time.time() - START > MAX_RUN_SECONDS:
                    state["sync_requested"] = True  # continue on next run
                    break
                todo.append(item)
            if not todo:
                continue
            # download in parallel, post to Telegram one by one in the original order
            futures = [(item, pool.submit(_fetch, item, tmp, size_limit)) for item in todo]
            for item, fut in futures:
                res = fut.result()
                path = res[1] if res[0] == "ok" else None
                try:
                    if res[0] == "big":
                        if item.id not in state["big_pending"]:
                            big_now += 1
                        state["big_pending"][item.id] = {"site": url, "name": item.filename, "size": res[1]}
                        continue
                    if res[0] == "err":
                        raise res[1]
                    real = res[2]
                    log(f"downloaded {item.filename} ({human_size(real)})")
                    digest = file_hash(path)
                    hashes = state["hashes"].setdefault(url, [])
                    if digest in hashes or digest in all_hashes:  # same file under another link: don't post twice
                        state["sent"][url].append(item.id)
                        done.add(item.id)
                        log(f"duplicate of an already sent file, skipped: {item.filename}")
                        continue
                    if real > BOT_UPLOAD_LIMIT and not has_userbot:
                        state["big_pending"][item.id] = {"site": url, "name": item.filename, "size": real}
                        big_now += 1
                        continue
                    wait = UPLOAD_GAP_SECONDS - (time.time() - last_upload)
                    if wait > 0:
                        time.sleep(wait)
                    if real <= BOT_UPLOAD_LIMIT:
                        bot.send_file(pick_channel(item, channel_id), path, item.filename, item.caption, item.kind)
                    else:
                        userbot.send_big(pick_channel(item, channel_id), path, item.caption, item.kind)
                    last_upload = time.time()
                    state["sent"][url].append(item.id)
                    hashes.append(digest)
                    done.add(item.id)
                    all_ids.add(item.id)
                    all_hashes.add(digest)
                    state["big_pending"].pop(item.id, None)
                    state["fails"].pop(item.id, None)
                    state["files_sent_total"] = state.get("files_sent_total", 0) + 1
                    sent_now += 1
                    log(f"sent {item.filename}")
                except Exception as e:
                    failed += 1
                    state["fails"][item.id] = state["fails"].get(item.id, 0) + 1
                    st.add_error(state, f"{item.filename}: {redact(e)}", now_iso())
                    log(f"failed {item.filename}: {e}")
                finally:
                    if path and os.path.exists(path):
                        os.remove(path)
    finally:
        pool.shutdown(wait=True)
        shutil.rmtree(tmp, ignore_errors=True)
    yt_sent, yt_failed = sync_youtube_links(bot, state, channel_id)
    failed += yt_failed
    state["last_sync"] = now_iso()
    state["last_result"] = f"{sent_now} files bheji, {yt_sent} YouTube links bheje, {failed} fail, {big_now} badi files ruki"
    return sent_now + yt_sent, failed, big_now


def sync_due(state):
    if state.get("sync_requested"):
        return True
    last = parse_iso(state.get("last_sync"))
    return last is None or (time.time() - last.timestamp()) >= SYNC_EVERY_MIN * 60


def setup_mode(bot, state):
    """Only BOT_TOKEN is set: help the owner find their user id and channel id.
    In webhook mode the Vercel function does this instantly, nothing to poll."""
    if webhook_active(bot):
        log("setup mode: webhook is set, Vercel replies with the ids; not polling")
        if injected_command():
            log("setup mode: dispatched command received but ignored until OWNER_ID and CHANNEL_ID are set: "
                + injected_command().split()[0])
        return
    if injected_command():
        log("setup mode: dispatched command received but ignored until OWNER_ID and CHANNEL_ID are set: "
            + injected_command().split()[0])
    try:
        updates = bot.get_updates(state["offset"])
    except TelegramError as e:
        log(f"getUpdates failed: {e}")
        return
    for u in updates:
        state["offset"] = u["update_id"] + 1
        msg = u.get("message") or {}
        if not msg.get("chat"):
            continue
        lines = [f"👤 Aapka user id (OWNER_ID): {(msg.get('from') or {}).get('id')}"]
        origin = msg.get("forward_origin") or {}
        chat = origin.get("chat") or msg.get("forward_from_chat") or {}
        if chat.get("id"):
            lines.append(f"📢 Channel id (CHANNEL_ID): {chat['id']}  ({chat.get('title', '')})")
        else:
            lines.append("Channel id ke liye: apne channel ki koi bhi post is bot ko forward karo.")
        lines.append("Ye dono GitHub Secrets mein daal do, phir bot normal chalega.")
        try:
            bot.send_message(msg["chat"]["id"], "\n".join(lines))
        except TelegramError as e:
            log(f"reply failed: {e}")


def main():
    token = os.environ.get("BOT_TOKEN")
    channel_id = os.environ.get("CHANNEL_ID")
    owner_id = os.environ.get("OWNER_ID")
    # CHANNEL_ID is optional only when both per-type channels are set
    has_channels = bool(channel_id or (os.environ.get("CHANNEL_ID_VIDEO") and os.environ.get("CHANNEL_ID_FILES")))
    missing = [k for k, v in (("BOT_TOKEN", token), ("CHANNEL_ID", has_channels), ("OWNER_ID", owner_id)) if not v]
    if token and missing:
        print("::warning::Setup mode (missing " + ", ".join(missing) + "): replying with ids only.")
        state = st.load()
        try:
            setup_mode(Bot(token), state)
        finally:
            st.save(state)
        return 0
    if missing:
        # exit 0 so GitHub doesn't email a failure every 30 min before setup is done
        print("::warning::Missing secrets: " + ", ".join(missing)
              + " (repo Settings -> Secrets and variables -> Actions). Bot did nothing.")
        return 0
    bot = Bot(token)
    state = st.load()
    dedupe_sites(state)
    state["routing"] = routing_note()
    try:
        if webhook_active(bot):
            log("webhook mode: not polling getUpdates")
        else:
            handle_updates(bot, state, owner_id)
        cmd = injected_command()
        if cmd:
            log(f"dispatched command: {cmd.split()[0]}")
            run_command(bot, state, cmd, owner_id, ack_message_id())
        if (state["sites"] or state.get("youtube_sources")) and sync_due(state):
            asked = bool(state.get("sync_requested"))
            state["sync_requested"] = False
            sent, failed, big = sync(bot, state, channel_id)
            log(f"sync: {state['last_result']}")
            if sent or failed or big or asked:
                try:
                    bot.send_message(owner_id, f"🔄 Sync: {state['last_result']}. /status se details dekho.")
                except TelegramError as e:
                    log(f"notify failed: {e}")
    finally:
        st.save(state)
    return 0


if __name__ == "__main__":
    sys.exit(main())
