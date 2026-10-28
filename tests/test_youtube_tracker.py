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
