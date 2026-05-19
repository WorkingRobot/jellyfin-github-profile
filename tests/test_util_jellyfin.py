import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from util import jellyfin  # noqa: E402


@pytest.fixture(autouse=True)
def env(monkeypatch):
    """Configure env and reset the per-process user-id cache for each test."""
    monkeypatch.setenv("JELLYFIN_URL", "https://jf.example.com/")
    monkeypatch.setenv("JELLYFIN_API_KEY", "secret")
    monkeypatch.setenv("JELLYFIN_USERNAME", "alice")
    monkeypatch.setenv("JELLYFIN_SELF_SIGNED_CERT", "false")
    jellyfin._USER_ID_CACHE = None
    jellyfin._now_cache.update(ts=0.0, value=None)
    yield
    jellyfin._USER_ID_CACHE = None
    jellyfin._now_cache.update(ts=0.0, value=None)


def _resp(payload):
    m = MagicMock()
    m.json.return_value = payload
    m.raise_for_status.return_value = None
    return m


def test_ticks_to_ms():
    assert jellyfin._ticks_to_ms(None) is None
    assert jellyfin._ticks_to_ms(0) is None
    # 100 ns ticks -> ms; 2,400,000,000 ticks = 240,000 ms
    assert jellyfin._ticks_to_ms(2_400_000_000) == 240_000


def test_missing_config(monkeypatch):
    monkeypatch.delenv("JELLYFIN_API_KEY", raising=False)
    with pytest.raises(jellyfin.InvalidConfigError):
        jellyfin._config()


def test_self_signed_cert_toggles_verify(monkeypatch):
    assert jellyfin._verify() is True
    monkeypatch.setenv("JELLYFIN_SELF_SIGNED_CERT", "true")
    assert jellyfin._verify() is False


def test_resolve_user_id_and_cache():
    with patch("util.jellyfin._SESSION.get") as g:
        g.return_value = _resp([
            {"Name": "bob", "Id": "b1"},
            {"Name": "Alice", "Id": "a1"},
        ])
        assert jellyfin.resolve_user_id() == "a1"
        # cached: no second HTTP call
        assert jellyfin.resolve_user_id() == "a1"
        assert g.call_count == 1


def test_resolve_user_id_not_found():
    with patch("util.jellyfin._SESSION.get") as g:
        g.return_value = _resp([{"Name": "bob", "Id": "b1"}])
        with pytest.raises(jellyfin.InvalidConfigError):
            jellyfin.resolve_user_id()


def test_get_image_url_audio_uses_album():
    item = {"Type": "Audio", "Id": "i1", "AlbumId": "al1",
            "ImageTags": {"Primary": "x"}}
    url = jellyfin.get_image_url(item)
    assert "/Items/al1/Images/Primary" in url
    assert "api_key=secret" in url


def test_get_image_url_none_without_tag():
    assert jellyfin.get_image_url({"Type": "Movie", "Id": "m1"}) is None


def test_get_now_playing_audio():
    sessions = [
        {"UserName": "someone", "NowPlayingItem": None},
        {
            "UserName": "alice",
            "PlayState": {"PositionTicks": 1_200_000_000},
            "NowPlayingItem": {
                "Type": "Audio",
                "Id": "s1",
                "AlbumId": "al1",
                "Name": "Song A",
                "Artists": ["Artist A"],
                "RunTimeTicks": 2_400_000_000,
                "ImageTags": {"Primary": "t"},
            },
        },
    ]
    with patch("util.jellyfin._SESSION.get") as g:
        g.side_effect = [
            _resp([{"Name": "alice", "Id": "a1"}]),  # /Users
            _resp(sessions),                         # /Sessions
        ]
        item = jellyfin.get_now_playing()

    assert item["media_type"] == "audio"
    assert item["artist_name"] == "Artist A"
    assert item["song_name"] == "Song A"
    assert item["duration_ms"] == 240_000
    assert item["progress_ms"] == 120_000
    assert "details?id=s1" in item["detail_url"]


def test_get_now_playing_episode():
    sessions = [{
        "UserId": "a1",
        "PlayState": {"PositionTicks": 0},
        "NowPlayingItem": {
            "Type": "Episode", "Id": "e1", "SeriesId": "ser1",
            "SeriesName": "My Show", "Name": "Pilot",
            "ParentIndexNumber": 1, "IndexNumber": 2,
            "ImageTags": {}, "SeriesPrimaryImageTag": "z",
        },
    }]
    with patch("util.jellyfin._SESSION.get") as g:
        g.side_effect = [
            _resp([{"Name": "alice", "Id": "a1"}]),
            _resp(sessions),
        ]
        item = jellyfin.get_now_playing()

    assert item["media_type"] == "episode"
    assert item["artist_name"] == "My Show"
    assert item["song_name"] == "S1E2 · Pilot"


def test_get_now_playing_movie_none_when_nobody_playing():
    with patch("util.jellyfin._SESSION.get") as g:
        g.side_effect = [
            _resp([{"Name": "alice", "Id": "a1"}]),
            _resp([{"UserName": "alice", "NowPlayingItem": None}]),
        ]
        assert jellyfin.get_now_playing() is None


def test_get_recently_played():
    with patch("util.jellyfin._SESSION.get") as g:
        g.side_effect = [
            _resp([{"Name": "alice", "Id": "a1"}]),
            _resp({"Items": [
                {"Type": "Movie", "Id": "m1", "Name": "A Film",
                 "ProductionYear": 1999, "ImageTags": {"Primary": "p"},
                 "RunTimeTicks": 6_000_000_000},
            ]}),
        ]
        items = jellyfin.get_recently_played()

    assert len(items) == 1
    assert items[0]["media_type"] == "movie"
    assert items[0]["song_name"] == "A Film"
    assert items[0]["artist_name"] == "1999"


def test_request_failure_raises_invalid_config():
    import requests as _requests
    with patch("util.jellyfin._SESSION.get",
               side_effect=_requests.exceptions.ConnectionError("boom")):
        with pytest.raises(jellyfin.InvalidConfigError):
            jellyfin.resolve_user_id()
