"""Jellyfin data layer.

Single-user, env-configured client for a self-hosted Jellyfin server. Reads the
currently playing item from the /Sessions endpoint (like JustRadical/jellyfin-rpc)
and falls back to play history. No OAuth, no token refresh, no persistence.
"""

import os

import requests
from dotenv import find_dotenv, load_dotenv

load_dotenv(find_dotenv())

import threading
import time

# 1 tick = 100 nanoseconds; Jellyfin reports durations/positions in ticks.
TICKS_PER_MS = 10_000

_USER_ID_CACHE = None

# Reuse one connection pool (keep-alive) instead of a fresh TLS handshake
# per call, the Jellyfin server is hit several times per page render.
_SESSION = requests.Session()

# Very short cache of the resolved "now playing" item: just long enough to
# collapse simultaneous bursts (the /gallery page fires ~9 requests at once,
# GitHub's camo refetches in bursts) without making a manual reload feel
# stale, the position stays effectively real-time.
_NOW_CACHE_TTL = 1.0
_now_cache = {"ts": 0.0, "value": None}
_now_lock = threading.Lock()


class InvalidConfigError(Exception):
    """Raised when JELLYFIN_* env is missing or the server is unreachable."""


def _config():
    url = os.getenv("JELLYFIN_URL")
    api_key = os.getenv("JELLYFIN_API_KEY")
    username = os.getenv("JELLYFIN_USERNAME")
    if not url or not api_key or not username:
        raise InvalidConfigError(
            "Missing config: set JELLYFIN_URL, JELLYFIN_API_KEY and JELLYFIN_USERNAME."
        )
    return url.rstrip("/"), api_key, username


def _verify():
    return os.getenv("JELLYFIN_SELF_SIGNED_CERT", "false").lower() != "true"


def _get(path, params=None):
    url, api_key, _ = _config()
    headers = {"X-Emby-Token": api_key, "Accept": "application/json"}
    try:
        resp = _SESSION.get(
            f"{url}{path}",
            headers=headers,
            params=params,
            timeout=10,
            verify=_verify(),
        )
        resp.raise_for_status()
    except requests.exceptions.RequestException as e:
        raise InvalidConfigError(f"Jellyfin request to {path} failed: {e}")
    return resp.json()


def _ticks_to_ms(ticks):
    if not ticks:
        return None
    return int(ticks) // TICKS_PER_MS


def resolve_user_id():
    """Return the Jellyfin user Id for JELLYFIN_USERNAME (cached per process)."""
    global _USER_ID_CACHE
    if _USER_ID_CACHE is not None:
        return _USER_ID_CACHE

    _, _, username = _config()
    users = _get("/Users")
    for user in users:
        if user.get("Name", "").lower() == username.lower():
            _USER_ID_CACHE = user["Id"]
            return _USER_ID_CACHE

    raise InvalidConfigError(f"Jellyfin user '{username}' not found.")


def get_image_url(item):
    """Build a Primary image URL for the item, or None when it has no artwork."""
    if not item:
        return None

    url, api_key, _ = _config()
    item_type = item.get("Type")
    image_tags = item.get("ImageTags") or {}

    if item_type == "Audio":
        image_item_id = item.get("AlbumId") or item.get("Id")
        if not item.get("AlbumPrimaryImageTag") and not image_tags.get("Primary"):
            return None
    elif item_type == "Episode":
        image_item_id = item.get("SeriesId") or item.get("Id")
        if not item.get("SeriesPrimaryImageTag") and not image_tags.get("Primary"):
            return None
    else:  # Movie and everything else
        image_item_id = item.get("Id")
        if not image_tags.get("Primary"):
            return None

    return (
        f"{url}/Items/{image_item_id}/Images/Primary"
        f"?maxHeight=300&api_key={api_key}"
    )


def _normalize(item, progress_ms=None, is_paused=False):
    """Convert a raw Jellyfin item into the provider-agnostic card shape."""
    url, _, _ = _config()
    item_type = item.get("Type")

    if item_type == "Audio":
        media_type = "audio"
        artists = item.get("Artists") or []
        artist_name = artists[0] if artists else item.get("AlbumArtist", "")
        song_name = item.get("Name", "")
    elif item_type == "Episode":
        media_type = "episode"
        artist_name = item.get("SeriesName", "")
        season = item.get("ParentIndexNumber")
        episode = item.get("IndexNumber")
        name = item.get("Name", "")
        if season is not None and episode is not None:
            song_name = f"S{season}E{episode} · {name}"
        else:
            song_name = name
    else:  # Movie / other
        media_type = "movie"
        year = item.get("ProductionYear")
        artist_name = str(year) if year else ""
        song_name = item.get("Name", "")

    return {
        "media_type": media_type,
        "artist_name": artist_name,
        "song_name": song_name,
        "image_url": get_image_url(item),
        "duration_ms": _ticks_to_ms(item.get("RunTimeTicks")),
        "progress_ms": progress_ms,
        "is_paused": bool(is_paused),
        "detail_url": f"{url}/web/#/details?id={item.get('Id')}",
    }


def get_now_playing():
    """Normalized currently-playing item (or None), cached for a few seconds.

    Collapses bursts of concurrent requests (the /gallery page, GitHub camo)
    into a single upstream fetch.
    """
    if time.monotonic() - _now_cache["ts"] < _NOW_CACHE_TTL:
        return _now_cache["value"]
    with _now_lock:
        if time.monotonic() - _now_cache["ts"] < _NOW_CACHE_TTL:
            return _now_cache["value"]
        value = _fetch_now_playing()
        _now_cache["value"] = value
        _now_cache["ts"] = time.monotonic()
        return value


def _fetch_now_playing():
    """Return the normalized item the configured user is playing, else None."""
    _, _, username = _config()
    user_id = resolve_user_id()

    sessions = _get("/Sessions")
    candidates = [
        s
        for s in sessions
        if s.get("NowPlayingItem")
        and (
            s.get("UserId") == user_id
            or s.get("UserName", "").lower() == username.lower()
        )
    ]
    if not candidates:
        return None

    def rank(session):
        play_state = session.get("PlayState") or {}
        # Prefer the session that is actually playing (not paused), then the
        # one with real playback progress, then the most recent check-in.
        return (
            0 if play_state.get("IsPaused") else 1,
            play_state.get("PositionTicks") or 0,
            session.get("LastPlaybackCheckIn") or "",
            session.get("LastActivityDate") or "",
        )

    session = max(candidates, key=rank)
    play_state = session.get("PlayState") or {}
    # Jellyfin's PositionTicks is already extrapolated server-side (it
    # advances in real time, not just on client check-ins), so trust it
    # directly. When paused it stops, which is exactly what we want.
    return _normalize(
        session["NowPlayingItem"],
        progress_ms=_ticks_to_ms(play_state.get("PositionTicks")),
        is_paused=play_state.get("IsPaused", False),
    )


def get_recently_played(limit=10):
    """Return up to `limit` normalized recently played items (newest first)."""
    user_id = resolve_user_id()
    data = _get(
        f"/Users/{user_id}/Items",
        params={
            "SortBy": "DatePlayed",
            "SortOrder": "Descending",
            "Filters": "IsPlayed",
            "Recursive": "true",
            "Limit": limit,
            "IncludeItemTypes": "Audio,Movie,Episode",
        },
    )
    return [_normalize(item) for item in data.get("Items", [])]
