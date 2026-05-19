from flask import Flask, Response, jsonify, render_template, redirect, request
from base64 import b64decode, b64encode
from dotenv import load_dotenv, find_dotenv

from util.profanity import profanity_check
from util.remaster import remove_remaster

load_dotenv(find_dotenv())

from PIL import Image, ImageFile

import io
from util import jellyfin
import random
import requests
import functools
import colorgram
import math
import html
import re

ImageFile.LOAD_TRUNCATED_IMAGES = True

print("Starting Server")

app = Flask(__name__)


@functools.lru_cache(maxsize=128)
def generate_css_bar(num_bar=75):
    css_bar = ""
    left = 1
    for i in range(1, num_bar + 1):

        anim = random.randint(350, 500)
        css_bar += (
            ".bar:nth-child({})  {{ left: {}px; animation-duration: {}ms; }}".format(
                i, left, anim
            )
        )
        left += 4

    return css_bar


_IMG_SESSION = requests.Session()


@functools.lru_cache(maxsize=128)
def load_image(url):
    try:
        response = _IMG_SESSION.get(url, timeout=10)
        response.raise_for_status()
        return response.content
    except requests.exceptions.RequestException as e:
        print(f"Error loading image from {url}: {e}")
        # Return a placeholder or None to handle gracefully
        return None
    except Exception as e:
        print(f"Unexpected error loading image: {e}")
        return None


def to_img_b64(content):
    if content is None:
        return ""
    return b64encode(content).decode("ascii")


def load_image_b64(url):
    return to_img_b64(load_image(url))


def isLightOrDark(rgbColor=[0, 128, 255], threshold=127.5):
    # https://stackoverflow.com/a/58270890
    [r, g, b] = rgbColor
    hsp = math.sqrt(0.299 * (r * r) + 0.587 * (g * g) + 0.114 * (b * b))
    if hsp > threshold:
        return "light"
    else:
        return "dark"


def encode_html_entities(text):
    return html.escape(text)


def format_time_ms(milliseconds):
    """Convert milliseconds to MM:SS format"""
    if milliseconds is None or milliseconds < 0:
        return "0:00"

    seconds = milliseconds // 1000
    minutes = seconds // 60
    seconds = seconds % 60

    return f"{minutes}:{seconds:02d}"


def calculate_progress_data(progress_ms, duration_ms):
    """Calculate progress percentage and formatted times.

    Only a valid duration is required: when progress is unknown/zero (e.g. a
    recently-played item) we still report the real track length and remaining
    time instead of collapsing to 0:00 / 0:00.
    """
    if not duration_ms or duration_ms <= 0:
        return {
            "progress_percentage": 0,
            "current_time": "0:00",
            "remaining_time": "0:00",
            "total_time": "0:00",
            "remaining_seconds": 0,
        }

    # Clamp progress into [0, duration]
    progress_ms = min(max(progress_ms or 0, 0), duration_ms)

    progress_percentage = (progress_ms / duration_ms) * 100
    remaining_ms = duration_ms - progress_ms

    return {
        "progress_percentage": progress_percentage,
        "current_time": format_time_ms(progress_ms),
        # Apple-style countdown (negative). Spotify-style themes use total_time.
        "remaining_time": f"-{format_time_ms(remaining_ms)}",
        "total_time": format_time_ms(duration_ms),
        # Seconds left in the track; used to animate the progress bar in
        # real time for the currently-playing card.
        "remaining_seconds": max(int(remaining_ms / 1000), 0),
    }


# @functools.lru_cache(maxsize=128)
def make_svg(
    artist_name,
    song_name,
    img,
    is_now_playing,
    cover_image,
    theme,
    bar_color,
    show_offline,
    background_color,
    mode,
    border_radius="10",
    progress_ms=None,
    duration_ms=None,
    is_paused=False,
):
    height = 0
    num_bar = 75

    # Sanitize input
    artist_name = encode_html_entities(artist_name)
    song_name = encode_html_entities(song_name)

    if theme == "compact":
        if cover_image:
            height = 400
        else:
            height = 100
    elif theme == "natemoo-re":
        height = 84
        num_bar = 100
    elif theme == "novatorem":
        height = 100
        num_bar = 100
    elif theme == "apple":
        height = 534
        num_bar = 0
    elif theme == "apple-music":
        height = 470
        num_bar = 0
    elif theme == "liquid-glass":
        height = 460
        num_bar = 0
    elif theme == "spotify-embed":
        height = 152
        num_bar = 0
    else:
        if cover_image:
            height = 445
        else:
            height = 145

    if is_now_playing:
        title_text = "Paused" if is_paused else "Now playing"
        content_bar = "".join(["<div class='bar'></div>" for i in range(num_bar)])
        css_bar = generate_css_bar(num_bar)
    elif show_offline:
        title_text = "Not playing"
        content_bar = ""
        css_bar = None
    else:
        title_text = "Recently played"
        content_bar = ""
        css_bar = generate_css_bar(num_bar)

    # Calculate progress data for Apple and Spotify Embed themes
    progress_data = {}
    if (
        theme in ["apple", "apple-music", "liquid-glass", "spotify-embed"]
        and duration_ms is not None
    ):
        if is_now_playing and progress_ms is not None:
            # Currently playing - show real progress
            progress_data = calculate_progress_data(progress_ms, duration_ms)
        else:
            # Recently played - show 0 progress but real duration
            progress_data = calculate_progress_data(0, duration_ms)

    rendered_data = {
        "height": height,
        "num_bar": num_bar,
        "content_bar": content_bar,
        "css_bar": css_bar,
        "title_text": title_text,
        "artist_name": artist_name,
        "song_name": song_name,
        "img": img,
        "cover_image": cover_image,
        "bar_color": bar_color,
        "background_color": background_color,
        "mode": mode,
        "is_now_playing": is_now_playing,
        "is_paused": is_paused,
        "progress_data": progress_data,
        "border_radius": border_radius,
    }

    return render_template(f"jellyfin.{theme}.html.j2", **rendered_data)


def get_song_info(show_offline):
    """Return (normalized_item, is_now_playing).

    Item shape comes from util.jellyfin (provider-agnostic). Falls back to
    recently played history when nothing is currently playing.
    """
    item = jellyfin.get_now_playing()
    if item:
        return item, True

    if show_offline:
        return None, False

    recent = jellyfin.get_recently_played()
    if not recent:
        return None, False

    return random.choice(recent), False


@app.route("/", defaults={"path": ""})
@app.route("/<path:path>")
def catch_all(path):
    # uid is accepted for README backward-compat but ignored (single-user).
    cover_image = request.args.get("cover_image", default="true") == "true"
    is_redirect = request.args.get("redirect", default="false") == "true"
    theme = request.args.get("theme", default="default")
    bar_color = request.args.get("bar_color", default="00a4dc")
    background_color = request.args.get("background_color", default="121212")
    is_bar_color_from_cover = (
        request.args.get("bar_color_cover", default="false") == "true"
    )
    show_offline = request.args.get("show_offline", default="false") == "true"
    interchange = request.args.get("interchange", default="false") == "true"
    mode = request.args.get("mode", default="light")
    border_radius = request.args.get("border_radius", default="10")
    is_enable_profanity = request.args.get("profanity", default="false") == "true"
    hide_remaster = request.args.get("hide_remaster", default="false") == "true"

    if not re.match(r'^\d+$', border_radius):
        border_radius = "10"

    try:
        item, is_now_playing = get_song_info(show_offline)
    except jellyfin.InvalidConfigError as e:
        return Response(f"Error: {e}")

    if (show_offline and not is_now_playing) or (item is None):
        if interchange:
            artist_name = "Currently not playing on Jellyfin"
            song_name = "Offline"
        else:
            artist_name = "Offline"
            song_name = "Currently not playing on Jellyfin"
        progress_ms = None
        duration_ms = None
        img_b64 = ""
        cover_image = False
        svg = make_svg(
            artist_name,
            song_name,
            img_b64,
            is_now_playing,
            cover_image,
            theme,
            bar_color,
            show_offline,
            background_color,
            mode,
            border_radius,
            progress_ms,
            duration_ms,
        )
        resp = Response(svg, mimetype="image/svg+xml")
        resp.headers["Cache-Control"] = "s-maxage=1"
        return resp

    progress_ms = item.get("progress_ms")
    duration_ms = item.get("duration_ms")

    if is_redirect and item.get("detail_url"):
        return redirect(item["detail_url"], code=302)

    img = None
    img_b64 = ""
    if cover_image and item.get("image_url"):
        img = load_image(item["image_url"])

        # Only convert to base64 if image was successfully loaded
        if img is not None:
            img_b64 = to_img_b64(img)

    # Extract cover image color
    if is_bar_color_from_cover and img is not None:

        is_skip_dark = False
        if theme in ["default"]:
            is_skip_dark = True

        try:
            pil_img = Image.open(io.BytesIO(img))
            colors = colorgram.extract(pil_img, 5)
        except Exception as e:
            print(f"Error extracting colors from image: {e}")
            colors = []

        for color in colors:

            rgb = color.rgb

            light_or_dark = isLightOrDark([rgb.r, rgb.g, rgb.b], threshold=80)

            if light_or_dark == "dark" and is_skip_dark:
                # Skip to use bar in dark color
                continue

            bar_color = "%02x%02x%02x" % (rgb.r, rgb.g, rgb.b)
            break

    # Artist/song come pre-normalized from the Jellyfin layer for audio,
    # movie and episode items, so the card layout is provider-agnostic.
    artist_name = item["artist_name"]
    song_name = item["song_name"]

    # Handle profanity filtering
    if is_enable_profanity:
        artist_name = profanity_check(artist_name)
        song_name = profanity_check(song_name)

    # Strip remaster annotations from song title
    if hide_remaster:
        song_name = remove_remaster(song_name)

    if interchange:
        x = artist_name
        artist_name = song_name
        song_name = x

    svg = make_svg(
        artist_name,
        song_name,
        img_b64,
        is_now_playing,
        cover_image,
        theme,
        bar_color,
        show_offline,
        background_color,
        mode,
        border_radius,
        progress_ms,
        duration_ms,
        item.get("is_paused", False),
    )

    resp = Response(svg, mimetype="image/svg+xml")
    resp.headers["Cache-Control"] = "s-maxage=1"

    return resp


if __name__ == "__main__":

    app.run(debug=True, port=5003)
