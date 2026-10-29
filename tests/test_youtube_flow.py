"""YouTube routing, link queues from websites, channel seeding, per-site "why 0"
notes (offline: fake Telegram, fake sites)."""
from bot import main as m
from bot import state as st
from bot.adapters.base import Item


class Bot:
    def __init__(self):
        self.msgs = []

    def send_message(self, chat_id, text):
        self.msgs.append((str(chat_id), text))

    def edit_message(self, chat_id, message_id, text):
        raise RuntimeError("no edit in this test")


def fresh(monkeypatch, tmp_path):
    monkeypatch.setattr(st, "STATE_FILE", str(tmp_path / "state.json"))
    for k, v in {"CHANNEL_ID": "-100", "OWNER_ID": "7"}.items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("CHANNEL_ID_VIDEO", raising=False)
    monkeypatch.setattr(m.time, "sleep", lambda s: None)
    return st.load()


def test_addsite_with_a_youtube_video_posts_the_link_instead(monkeypatch, tmp_path):
    state, bot = fresh(monkeypatch, tmp_path), Bot()
    monkeypatch.setattr(m.adapters, "list_items", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no crawl")))
    m.run_command(bot, state, "/addsite https://youtu.be/mWlmcjwV44o?si=Rz", "7")
    assert state["sites"] == []
    assert bot.msgs[0] == ("-100", "▶️ YouTube video link\nhttps://www.youtube.com/watch?v=mWlmcjwV44o")
    assert "single video" in bot.msgs[1][1] and bot.msgs[1][0] == "7"
    # same video again: not posted twice
    m.run_command(bot, state, "/yt https://www.youtube.com/watch?v=mWlmcjwV44o", "7")
    assert len([x for x in bot.msgs if x[0] == "-100"]) == 1 and "pehle hi" in bot.msgs[-1][1]


def test_addyoutube_with_video_or_playlist_link_goes_to_the_right_place(monkeypatch, tmp_path):
    state, bot = fresh(monkeypatch, tmp_path), Bot()
    m.run_command(bot, state, "/addyoutube https://youtu.be/mWlmcjwV44o", "7")
    assert state["youtube_sources"] == [] and bot.msgs[0][0] == "-100"
    m.run_command(bot, state, "/addsite https://www.youtube.com/playlist?list=PL1234567890abcd", "7")
    assert [(s["kind"], s["id"]) for s in state["youtube_sources"]] == [("playlist", "PL1234567890abcd")]
    assert state["sites"] == [] and "playlist" in bot.msgs[-1][1]
    m.run_command(bot, state, "/removeyoutube PL1234567890abcd", "7")
    assert state["youtube_sources"] == []
    m.run_command(bot, state, "/removeyoutube a", "7")      # too short to match anything
    assert "nahi mili" in bot.msgs[-1][1]


def test_site_youtube_videos_are_queued_and_posted_a_few_per_run(monkeypatch, tmp_path):
    state, bot = fresh(monkeypatch, tmp_path), Bot()
    monkeypatch.setenv("MAX_YOUTUBE_LINKS_PER_RUN", "2")
    url = "https://ex.am/p/7/videos"
    state["sites"] = [{"url": url, "adapter": "generic", "depth": 5, "limit": 3}]
    state["sent"][url] = []
    yt = [Item(id=f"yt:{c * 11}", url=f"https://www.youtube.com/watch?v={c * 11}", filename=c * 11,
               caption=f"Lecture {c}", kind="youtube") for c in "abc"]
    monkeypatch.setattr(m.adapters, "list_items", lambda *a, **k: ("generic", list(yt)))
    sent, failed, big = m.sync(bot, state, "-100")
    assert (sent, failed) == (2, 0)
    assert [t.split("\n")[1] for _, t in bot.msgs] == [
        "https://www.youtube.com/watch?v=aaaaaaaaaaa", "https://www.youtube.com/watch?v=bbbbbbbbbbb"]
    assert "YouTube links: 2" in state["last_result"]
    m.sync(bot, state, "-100")                          # next run: the last one, nothing twice
    assert [t.split("\n")[1] for _, t in bot.msgs][2:] == ["https://www.youtube.com/watch?v=ccccccccccc"]
    m.sync(bot, state, "-100")
    assert len(bot.msgs) == 3 and "site:ex.am/p/7/videos" not in state["youtube_pending"]
    assert "YouTube links: 3 post" in m.cmd_sites(state, "")


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


def test_new_channel_posts_only_its_latest_three(monkeypatch, tmp_path):
    state, bot = fresh(monkeypatch, tmp_path), Bot()
    state["youtube_sources"] = [{"kind": "channel", "id": "UC" + "a" * 22, "url": "https://www.youtube.com/channel/x"}]
    entries = [{"id": f"{i:011d}", "title": f"v{i}", "url": f"https://www.youtube.com/watch?v={i:011d}"} for i in range(10)]
    monkeypatch.setattr(m.youtube_tracker, "fetch_entries", lambda s: list(entries))
    m.sync_youtube_links(bot, state, "-100")
    assert [t.split("\n")[0] for _, t in bot.msgs] == ["▶️ v7", "▶️ v8", "▶️ v9"]
    entries.append({"id": "00000000010", "title": "new upload", "url": "https://www.youtube.com/watch?v=00000000010"})
    m.sync_youtube_links(bot, state, "-100")
    assert [t.split("\n")[0] for _, t in bot.msgs][3:] == ["▶️ new upload"]


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
