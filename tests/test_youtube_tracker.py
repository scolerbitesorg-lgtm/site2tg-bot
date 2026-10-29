import pytest

from bot import youtube_tracker


def test_parse_watch_url():
    url, video_id = youtube_tracker.parse_video_url("https://www.youtube.com/watch?v=abcdefghijk&t=30")
    assert video_id == "abcdefghijk"
    assert url == "https://www.youtube.com/watch?v=abcdefghijk"


def test_parse_short_url():
    url, video_id = youtube_tracker.parse_video_url("https://youtu.be/abcdefghijk")
    assert video_id == "abcdefghijk"
    assert url.endswith("v=abcdefghijk")


def test_parse_shorts_url():
    _, video_id = youtube_tracker.parse_video_url("https://www.youtube.com/shorts/abcdefghijk")
    assert video_id == "abcdefghijk"


def test_reject_non_youtube_video_url():
    with pytest.raises(ValueError):
        youtube_tracker.parse_video_url("https://example.com/watch?v=abcdefghijk")


def test_reject_bad_video_id():
    with pytest.raises(ValueError):
        youtube_tracker.parse_video_url("https://youtube.com/watch?v=short")


def test_parse_playlist_url():
    source = youtube_tracker.parse_source(
        "https://www.youtube.com/playlist?list=PL1234567890abcd", "playlist"
    )
    assert source["kind"] == "playlist"
    assert source["id"] == "PL1234567890abcd"
    assert source["url"] == "https://www.youtube.com/playlist?list=PL1234567890abcd"


def test_parse_channel_id():
    channel_id = "UC" + "a" * 22
    source = youtube_tracker.parse_source(channel_id, "channel")
    assert source["kind"] == "channel"
    assert source["id"] == channel_id


def test_reject_non_youtube_playlist_url():
    with pytest.raises(ValueError):
        youtube_tracker.parse_source("https://example.com/playlist?list=PL1234567890", "playlist")


# ---------------------------------------------------------------- 2026-10-29 additions

def test_video_ids_from_html_finds_embeds_lite_embeds_and_links():
    html = (
        '<div class="yt-lite" data-ytid="KR_gAamao2Y" data-title="x"></div>'
        '<iframe src="https://www.youtube.com/embed/abcdefghijk?rel=0"></iframe>'
        '<iframe src="https://www.youtube.com/embed/videoseries?list=PL123"></iframe>'
        '<a href="https://youtu.be/ZZZZZZZZZZZ">x</a>'
        '<a href="https://www.youtube.com/watch?feature=share&amp;v=YYYYYYYYYYY">y</a>'
        '<img src="https://i.ytimg.com/vi/KR_gAamao2Y/hqdefault.jpg">'
    )
    assert youtube_tracker.video_ids_from_html(html) == [
        "KR_gAamao2Y", "abcdefghijk", "ZZZZZZZZZZZ", "YYYYYYYYYYY"]
    assert youtube_tracker.video_ids_from_html("<p>no video, just https://example.com/watch?v=abcdefghijk</p>") == []


def test_classify_youtube_links():
    c = youtube_tracker.classify
    assert c("https://youtu.be/mWlmcjwV44o?si=RzZuUDU05Jmr_WtF") == "video"
    assert c("https://www.youtube.com/shorts/abcdefghijk") == "video"
    assert c("https://www.youtube.com/playlist?list=PL1234567890abcd") == "playlist"
    assert c("https://www.youtube.com/watch?v=abcdefghijk&list=PL1234567890abcd") == "playlist"
    assert c("https://www.youtube.com/watch?v=abcdefghijk&list=RDabcdefghijk") == "video"  # auto "Mix"
    assert c("https://www.youtube.com/@StudyIQ") == "channel"
    assert c("youtube.com/channel/UC" + "a" * 22) == "channel"
    assert c("@StudyIQ") == "channel"
    assert c("https://example.com/watch?v=abcdefghijk") is None


def test_entries_from_page_data_keep_page_order():
    data = {"contents": [
        {"lockupViewModel": {"contentId": "aaaaaaaaaaa", "contentType": "LOCKUP_CONTENT_TYPE_VIDEO",
                             "metadata": {"lockupMetadataViewModel": {"title": {"content": "Lecture 1"}}}}},
        {"lockupViewModel": {"contentId": "PLnotavideo1", "contentType": "LOCKUP_CONTENT_TYPE_PLAYLIST"}},
        {"playlistVideoRenderer": {"videoId": "bbbbbbbbbbb", "title": {"runs": [{"text": "Lecture 2"}]}}},
        {"playlistVideoRenderer": {"videoId": "aaaaaaaaaaa", "title": {"runs": [{"text": "dup"}]}}},
    ]}
    html = "<script>var ytInitialData = " + __import__("json").dumps(data) + ";</script>"
    got = youtube_tracker.entries_from_initial_data(youtube_tracker.initial_data(html))
    assert [(e["id"], e["title"]) for e in got] == [("aaaaaaaaaaa", "Lecture 1"), ("bbbbbbbbbbb", "Lecture 2")]
    assert got[0]["url"] == "https://www.youtube.com/watch?v=aaaaaaaaaaa"


def test_channel_id_read_from_channel_page():
    cid = "UC" + "b" * 22
    assert youtube_tracker._channel_id_from_page('{"externalId":"%s"}' % cid) == cid
    assert youtube_tracker._channel_id_from_page('<link href="https://www.youtube.com/channel/%s">' % cid) == cid
    assert youtube_tracker._channel_id_from_page("nothing") == ""
