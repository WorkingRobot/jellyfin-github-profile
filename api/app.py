"""Single-container entrypoint.

One Flask app, one port. Configured entirely by JELLYFIN_* env vars
(see .env.example). No login/callback/OAuth and no database.
"""

import os
import sys

from flask import Flask, Response, request

# Ensure the api/ directory is on sys.path so sibling modules resolve.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import view as view_module  # noqa: E402

app = Flask(__name__)

EMBED_HINT = (
    "![Now playing](http://localhost:8080/api/view?theme=default)"
)

THEMES = [
    "default",
    "compact",
    "natemoo-re",
    "novatorem",
    "karaoke",
    "spotify-embed",
    "apple",
    "apple-music",
    "liquid-glass",
]


@app.route("/")
def index():
    configured = all(
        os.getenv(k)
        for k in ("JELLYFIN_URL", "JELLYFIN_API_KEY", "JELLYFIN_USERNAME")
    )
    status = "configured" if configured else "NOT configured (set JELLYFIN_* env)"
    body = (
        "jellyfin-github-profile\n\n"
        f"Status: {status}\n\n"
        "Embed in your README:\n"
        f"{EMBED_HINT}\n\n"
        "See all themes at /gallery\n"
    )
    return Response(body, mimetype="text/plain")


@app.route("/gallery")
def gallery():
    """Live preview of every theme (extra query params are passed through)."""
    extra = "".join(
        f"&{k}={v}"
        for k, v in request.args.items(multi=True)
        if k != "theme"
    )
    cards = "\n".join(
        f"""<figure>
              <figcaption>{t}</figcaption>
              <object type="image/svg+xml"
                      data="/api/view?theme={t}{extra}"></object>
            </figure>"""
        for t in THEMES
    )
    html = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>jellyfin-github-profile - themes</title>
<style>
  body {{ margin: 0; padding: 32px; background: #0d1117; color: #c9d1d9;
         font-family: ui-sans-serif, system-ui, -apple-system, sans-serif; }}
  h1 {{ font-size: 18px; font-weight: 600; margin: 0 0 4px; }}
  p {{ color: #8b949e; margin: 0 0 28px; font-size: 13px; }}
  code {{ color: #c9d1d9; background: #161b22; padding: 1px 5px;
          border-radius: 4px; }}
  .grid {{ display: flex; flex-wrap: wrap; gap: 28px; align-items: flex-start; }}
  figure {{ margin: 0; }}
  figcaption {{ font-size: 12px; color: #8b949e; margin-bottom: 8px;
               font-family: ui-monospace, monospace; }}
  object {{ display: block; border: 1px solid #30363d; border-radius: 10px;
           background: #161b22; }}
</style>
</head>
<body>
  <h1>jellyfin-github-profile</h1>
  <p>Live theme previews. Append params (e.g.
     <code>/gallery?mode=dark&amp;cover_image=false</code>) to apply to all.</p>
  <div class="grid">
    {cards}
  </div>
</body>
</html>"""
    return Response(html, mimetype="text/html")


@app.route("/healthz")
def healthz():
    return Response("ok", mimetype="text/plain")


@app.route("/api/view", defaults={"path": ""})
@app.route("/api/view/<path:path>")
def view(path):
    return view_module.catch_all(path)


@app.route("/api/view.svg", defaults={"path": ""})
@app.route("/api/view.svg/<path:path>")
def view_svg(path):
    return view_module.catch_all(path)


if __name__ == "__main__":
    app.run(debug=True, port=int(os.getenv("PORT", "8080")))
