# jellyfin-github-profile

Show what you're currently watching/listening to on your self-hosted **Jellyfin**
server as a live SVG card on your GitHub profile.

Runs as a single self-hostable Docker container. No OAuth, no database, no
third-party services; it just talks to your Jellyfin server with an API key.

> [!NOTE]
> A significant portion of this project was built by Claude in an afternoon. Don't use it if you don't trust it with your Jellyfin API key.

## How it works

The app polls your Jellyfin server's `/Sessions` endpoint for the configured
user and renders a "now playing" card (audio, movies and TV episodes). When
nothing is playing it falls back to recently played history.

## Quick start

1. **Create a Jellyfin API key**
   Jellyfin dashboard → *Administration* → *API Keys* → **+**.

2. **Configure**: copy `.env.example` to `.env` and fill in:

   ```sh
   JELLYFIN_URL='https://jellyfin.example.com'
   JELLYFIN_API_KEY='your-api-key'
   JELLYFIN_USERNAME='your_username'
   JELLYFIN_SELF_SIGNED_CERT='false'   # 'true' if Jellyfin uses a self-signed cert
   ```

3. **Run**

   ```sh
   docker compose up -d --build
   ```

   The card is served at `http://localhost:8080/api/view`. `GET /healthz`
   is a health endpoint; `GET /` shows config status and the embed snippet.

4. **Embed in your GitHub profile README**

   ```md
   ![Now Playing](https://your-host.example.com/api/view?theme=default)
   ```

   (`uid` is no longer required and is ignored if present.)

## Customization

Add query parameters to the `/api/view` URL:

| Parameter | Description | Default |
|-----------|-------------|---------|
| `theme` | `default`, `compact`, `natemoo-re`, `novatorem`, `karaoke`, `spotify-embed`, `apple`, `apple-music`, `liquid-glass` | `default` |
| `background_color` | Background color (hex without #) | `121212` |
| `border_radius` | Border radius in pixels | `10` |
| `bar_color` | Equalizer bar color (hex without #) | `53b14f` |
| `bar_color_cover` | Extract bar color from cover art (`true`/`false`) | `false` |
| `cover_image` | Show cover/poster image (`true`/`false`) | `true` |
| `show_offline` | Show an offline card when nothing is playing (`true`/`false`) | `false` |
| `interchange` | Swap title and artist/series positions (`true`/`false`) | `false` |
| `mode` | Color mode for supported themes (`light`/`dark`) | `light` |
| `redirect` | `302` to the Jellyfin web detail page for the item (`true`/`false`) | `false` |

Two Jellyfin-native themes are included: **`liquid-glass`** (a translucent frosted-glass card over a blurred, saturated backdrop of the cover art, inspired by Apple's Liquid Glass design language), and **`apple-music`** (a modern Apple Music "now playing" layout with ambient art backdrop, scrubber and transport controls).

## Deploying behind a reverse proxy

`deploy/` contains an example that runs the app behind nginx:

```sh
cd deploy
cp ../.env.example .env   # fill in JELLYFIN_*
docker compose up -d --build
```

`deploy/nginx.conf` proxies to the app and passes the app's `Cache-Control`
header through unchanged. Terminate TLS at the proxy in production.

## Running locally (without Docker)

```sh
pip install -r api/requirements.txt
cp .env.example .env        # fill in JELLYFIN_*
python api/app.py           # serves on http://localhost:8080
```

## Tests

```sh
pytest tests/ -v                       # all tests
pytest tests/ --cov=api --cov-report=html
pytest tests/test_util_jellyfin.py -v  # Jellyfin client unit tests
```

## Credit

Jellyfin integration inspired by
[JustRadical/jellyfin-rpc](https://github.com/JustRadical/jellyfin-rpc).
Originally forked from
[kittinan/spotify-github-profile](https://github.com/kittinan/spotify-github-profile);
card themes inspired by https://github.com/natemoo-re.
