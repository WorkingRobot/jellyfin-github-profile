import os
import sys
from unittest.mock import MagicMock, patch

import pytest

# Add the parent directory to the path to import the api module
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))


def _item(**overrides):
    """A normalized Jellyfin item as produced by util.jellyfin."""
    base = {
        "media_type": "audio",
        "artist_name": "Test Artist",
        "song_name": "Test Song",
        "image_url": "http://example.com/image.jpg",
        "duration_ms": 240000,
        "progress_ms": 120000,
        "detail_url": "https://jf.example.com/web/#/details?id=abc",
    }
    base.update(overrides)
    return base


@pytest.fixture
def client():
    """Create a test client for the view Flask application."""
    from api.view import app
    app.config.update({"TESTING": True})

    with app.test_client() as client:
        yield client


@patch('api.view.get_song_info')
@patch('api.view.make_svg')
def test_offline(mock_make_svg, mock_get_song_info, client):
    """User is offline -> offline card, no uid required."""
    mock_get_song_info.return_value = (None, False)
    mock_make_svg.return_value = '<svg>offline</svg>'

    response = client.get('/?show_offline=true')

    assert response.status_code == 200
    assert response.mimetype == 'image/svg+xml'
    assert response.headers['Cache-Control'] == 's-maxage=1'
    args, _ = mock_make_svg.call_args
    assert args[0] in ["Currently not playing on Jellyfin", "Offline"]
    assert args[1] in ["Offline", "Currently not playing on Jellyfin"]


@patch('api.view.get_song_info')
@patch('api.view.make_svg')
def test_now_playing_audio(mock_make_svg, mock_get_song_info, client):
    mock_get_song_info.return_value = (_item(), True)
    mock_make_svg.return_value = '<svg>now playing</svg>'

    with patch('api.view.load_image', return_value=b'fake_image_data'):
        response = client.get('/')

        assert response.status_code == 200
        assert response.mimetype == 'image/svg+xml'
        args, _ = mock_make_svg.call_args
        assert args[0] == "Test Artist"
        assert args[1] == "Test Song"


@patch('api.view.get_song_info')
@patch('api.view.make_svg')
def test_video_episode(mock_make_svg, mock_get_song_info, client):
    """Episode items render through the same card via normalized fields."""
    mock_get_song_info.return_value = (
        _item(media_type="episode", artist_name="The Series",
              song_name="S1E2 · Pilot"),
        True,
    )
    mock_make_svg.return_value = '<svg></svg>'

    with patch('api.view.load_image', return_value=b'fake_image_data'):
        response = client.get('/')

        assert response.status_code == 200
        args, _ = mock_make_svg.call_args
        assert args[0] == "The Series"
        assert args[1] == "S1E2 · Pilot"


@patch('api.view.get_song_info')
def test_redirect(mock_get_song_info, client):
    mock_get_song_info.return_value = (_item(), True)

    response = client.get('/?redirect=true')

    assert response.status_code == 302
    assert response.headers['Location'] == 'https://jf.example.com/web/#/details?id=abc'


@patch('api.view.get_song_info')
def test_invalid_config_error(mock_get_song_info, client):
    from util.jellyfin import InvalidConfigError
    mock_get_song_info.side_effect = InvalidConfigError("Missing config: set JELLYFIN_URL")

    response = client.get('/')

    assert response.status_code == 200
    assert b'Missing config' in response.data


ALL_THEMES = [
    "default", "compact", "natemoo-re", "novatorem", "karaoke",
    "apple", "spotify-embed", "apple-music", "liquid-glass",
]


@pytest.mark.parametrize("theme", ALL_THEMES)
@patch('api.view.get_song_info')
@patch('api.view.make_svg')
def test_different_themes(mock_make_svg, mock_get_song_info, client, theme):
    mock_get_song_info.return_value = (_item(), True)
    mock_make_svg.return_value = '<svg></svg>'

    with patch('api.view.load_image', return_value=b'fake_image_data'):
        response = client.get(f'/?theme={theme}')
        assert response.status_code == 200
        mock_make_svg.assert_called_once()


@pytest.mark.parametrize("theme", ALL_THEMES)
@patch('api.view.get_song_info')
def test_theme_templates_render(mock_get_song_info, client, theme):
    """Render each Jinja template for real to catch template syntax errors."""
    mock_get_song_info.return_value = (_item(), True)

    with patch('api.view.load_image', return_value=b'fake_image_data'):
        response = client.get(f'/?theme={theme}&cover_image=true')
        assert response.status_code == 200
        assert response.mimetype == 'image/svg+xml'
        assert b'<svg' in response.data


@pytest.mark.parametrize("cover_image,expected_call", [
    ("true", True),
    ("false", False),
    ("", True),
])
@patch('api.view.get_song_info')
@patch('api.view.make_svg')
@patch('api.view.load_image')
def test_cover_image_parameter(mock_load_image, mock_make_svg, mock_get_song_info,
                               client, cover_image, expected_call):
    mock_get_song_info.return_value = (_item(), False)
    mock_make_svg.return_value = '<svg></svg>'
    mock_load_image.return_value = b'fake_image_data'

    if cover_image:
        response = client.get(f'/?cover_image={cover_image}')
    else:
        response = client.get('/')

    assert response.status_code == 200
    if expected_call:
        mock_load_image.assert_called_once()
    else:
        mock_load_image.assert_not_called()


@patch('api.view.get_song_info')
@patch('api.view.make_svg')
@patch('api.view.load_image')
def test_interchange_parameter(mock_load_image, mock_make_svg, mock_get_song_info, client):
    mock_get_song_info.return_value = (_item(), True)
    mock_make_svg.return_value = '<svg></svg>'
    mock_load_image.return_value = b'fake_image_data'

    response = client.get('/?interchange=true&cover_image=false')

    assert response.status_code == 200
    args, _ = mock_make_svg.call_args
    assert args[0] == "Test Song"
    assert args[1] == "Test Artist"


@pytest.mark.parametrize("show_offline,interchange,expected_artist,expected_song", [
    (True, False, "Offline", "Currently not playing on Jellyfin"),
    (True, True, "Currently not playing on Jellyfin", "Offline"),
    (False, False, "Offline", "Currently not playing on Jellyfin"),
    (False, True, "Currently not playing on Jellyfin", "Offline"),
])
@patch('api.view.get_song_info')
@patch('api.view.make_svg')
def test_offline_text_with_interchange(mock_make_svg, mock_get_song_info, client,
                                       show_offline, interchange,
                                       expected_artist, expected_song):
    mock_get_song_info.return_value = (None, False)
    mock_make_svg.return_value = '<svg></svg>'

    params = (f'show_offline={str(show_offline).lower()}'
              f'&interchange={str(interchange).lower()}')
    response = client.get(f'/?{params}')

    assert response.status_code == 200
    args, _ = mock_make_svg.call_args
    assert args[0] == expected_artist
    assert args[1] == expected_song


@patch('api.view.get_song_info')
@patch('api.view.make_svg')
@patch('api.view.load_image')
@patch('PIL.Image.open')
@patch('api.view.colorgram.extract')
def test_bar_color_from_cover(mock_extract, mock_pil_open, mock_load_image,
                              mock_make_svg, mock_get_song_info, client):
    mock_pil_open.return_value = MagicMock()
    mock_color = MagicMock()
    mock_color.rgb.r, mock_color.rgb.g, mock_color.rgb.b = 255, 100, 100
    mock_extract.return_value = [mock_color]

    mock_get_song_info.return_value = (_item(), True)
    mock_make_svg.return_value = '<svg></svg>'
    mock_load_image.return_value = b'fake_image_data'

    response = client.get('/?bar_color_cover=true')

    assert response.status_code == 200
    mock_extract.assert_called_once()


def test_helper_function_format_time_ms():
    from api.view import format_time_ms

    assert format_time_ms(0) == "0:00"
    assert format_time_ms(30000) == "0:30"
    assert format_time_ms(90000) == "1:30"
    assert format_time_ms(3600000) == "60:00"
    assert format_time_ms(None) == "0:00"
    assert format_time_ms(-1000) == "0:00"


def test_helper_function_calculate_progress_data():
    from api.view import calculate_progress_data

    result = calculate_progress_data(60000, 180000)
    assert result["progress_percentage"] == pytest.approx(33.33, rel=1e-2)
    assert result["current_time"] == "1:00"
    assert result["remaining_time"] == "-2:00"

    assert calculate_progress_data(None, 180000)["progress_percentage"] == 0
    assert calculate_progress_data(60000, None)["progress_percentage"] == 0
    assert calculate_progress_data(200000, 180000)["progress_percentage"] == 100


def test_helper_function_isLightOrDark():
    from api.view import isLightOrDark

    assert isLightOrDark([255, 255, 255]) == "light"
    assert isLightOrDark([0, 0, 0]) == "dark"


def test_helper_function_encode_html_entities():
    from api.view import encode_html_entities

    assert encode_html_entities("text & more") == "text &amp; more"
    assert encode_html_entities("<script>") == "&lt;script&gt;"


def test_to_img_b64_handles_none():
    from api.view import to_img_b64
    assert to_img_b64(None) == ""


def test_generate_css_bar():
    from api.view import generate_css_bar

    css = generate_css_bar(5)
    assert 'bar:nth-child(' in css
    assert 'animation-duration:' in css
    assert len(generate_css_bar(20)) > len(generate_css_bar(10))
