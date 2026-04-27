"""App settings — persistence and rendering helpers."""

from __future__ import annotations

import html as html_lib
import json
import re
import secrets
import time
from pathlib import Path

import db as _db

DEFAULT_APP_SETTINGS = {
    "app_name": "Replay",
    "nav_matches_label": "Matches",
    "nav_admin_label": "Admin",
    "season_title": "U12 GIRLS STEEL",
    "season_intro": "Missed a game? You can find all our match replays right here! (Subject to my attendance and the battery life of my camera.)",
    "main_team_name": "OSU Steel",
    "filter_all_label": "All Matches",
    "filter_home_label": "Home",
    "filter_away_label": "Away",
    "stat_matches_label": "Matches",
    "stat_ready_label": "Ready",
    "stat_processing_label": "Processing",
    "game_back_label": "Back to Matches",
    "game_replay_label": "Match Replay",
    "game_video_status_label": "Video Status",
    "download_label": "Download",
    "downloads_enabled": "1",
    "live_enabled": "1",
    "live_offline_message": "No live stream right now. Check back at kick-off.",
    "live_rtmp_public_url": "",
    "app_logo_filename": "",
    "favicon_filename": "",
}

# Keys that are private — never returned in the public settings payload, and
# only writable through dedicated admin endpoints (not the generic settings PUT).
PRIVATE_SETTING_KEYS = {"live_stream_key"}

EDITABLE_APP_SETTING_KEYS = {
    key for key in DEFAULT_APP_SETTINGS.keys()
    if key not in {"app_logo_filename", "favicon_filename"}
}

APP_ASSET_CONFIG = {
    "logo": {
        "setting_key": "app_logo_filename",
        "allowed_exts": {".png", ".jpg", ".jpeg", ".svg", ".webp"},
        "max_size": 20 * 1024 * 1024,
    },
    "favicon": {
        "setting_key": "favicon_filename",
        "allowed_exts": {".ico", ".png", ".svg"},
        "max_size": 5 * 1024 * 1024,
    },
}

# Set by server at startup
APP_ASSETS_DIR: Path = Path("app_assets")
STATIC_DIR: Path = Path(".")


def init(app_assets_dir: Path, static_dir: Path):
    global APP_ASSETS_DIR, STATIC_DIR
    APP_ASSETS_DIR = app_assets_dir
    STATIC_DIR = static_dir


def load_unlocked() -> dict[str, str]:
    settings = DEFAULT_APP_SETTINGS.copy()
    with _db.connect() as conn:
        rows = conn.execute("SELECT key, value FROM settings").fetchall()
    for row in rows:
        settings[row["key"]] = row["value"]
    return settings


def save_unlocked(updates: dict[str, str]) -> dict[str, str]:
    if not updates:
        return load_unlocked()
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    with _db.connect() as conn:
        conn.executemany(
            """
            INSERT INTO settings (key, value, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at
            """,
            [(key, value, now) for key, value in updates.items()],
        )
        conn.commit()
    return load_unlocked()


def normalize_value(key: str, value) -> str:
    if value is None:
        return DEFAULT_APP_SETTINGS.get(key, "")
    if key in {"downloads_enabled", "live_enabled"}:
        if isinstance(value, bool):
            return "1" if value else "0"
        return "1" if str(value).strip().lower() in {"1", "true", "yes", "on"} else "0"
    return str(value).strip()


# ---------------------------------------------------------------------------
# Live stream key management
# ---------------------------------------------------------------------------

def _generate_stream_key() -> str:
    """24 chars of url-safe entropy — enough to make brute force infeasible."""
    return secrets.token_urlsafe(18)


def get_or_create_stream_key_unlocked() -> str:
    """Return the configured live stream key, generating one on first access."""
    with _db.connect() as conn:
        row = conn.execute(
            "SELECT value FROM settings WHERE key = 'live_stream_key'"
        ).fetchone()
        if row and row["value"]:
            return row["value"]
        key = _generate_stream_key()
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        conn.execute(
            "INSERT INTO settings (key, value, updated_at) VALUES (?, ?, ?)"
            " ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
            ("live_stream_key", key, now),
        )
        conn.commit()
        return key


def rotate_stream_key_unlocked() -> str:
    """Generate and persist a new stream key, returning the new value."""
    key = _generate_stream_key()
    save_unlocked({"live_stream_key": key})
    return key


def _asset_version(filename: str) -> str:
    path = STATIC_DIR / filename
    try:
        return str(path.stat().st_mtime_ns)
    except FileNotFoundError:
        return "0"


def _versioned_static_path(filename: str) -> str:
    return f"/static/{filename}?v={_asset_version(filename)}"


def app_asset_url(kind: str, settings: dict[str, str]) -> str:
    config = APP_ASSET_CONFIG[kind]
    filename = settings.get(config["setting_key"], "")
    if filename:
        asset_path = APP_ASSETS_DIR / filename
        if asset_path.is_file():
            return f"/api/app-assets/{kind}?v={asset_path.stat().st_mtime_ns}"
    if kind == "logo":
        return _versioned_static_path("logo.png")
    return _versioned_static_path("logo.png")


def public_payload(settings: dict[str, str]) -> dict:
    public_settings = {k: v for k, v in settings.items() if k not in PRIVATE_SETTING_KEYS}
    return {
        "settings": public_settings,
        "assets": {
            "logo_url": app_asset_url("logo", settings),
            "favicon_url": app_asset_url("favicon", settings),
        },
    }


def render_index_html(settings_payload: dict) -> str:
    html = (STATIC_DIR / "index.html").read_text()
    app_name = html_lib.escape(settings_payload["settings"]["app_name"] or DEFAULT_APP_SETTINGS["app_name"])
    favicon_url = html_lib.escape(settings_payload["assets"]["favicon_url"], quote=True)
    html = re.sub(r'/static/styles\.css(?:\?v=[^"\']*)?', _versioned_static_path("styles.css"), html)
    html = re.sub(r'/static/script\.js(?:\?v=[^"\']*)?', _versioned_static_path("script.js"), html)
    html = re.sub(r'/static/logo\.png(?:\?v=[^"\']*)?', app_asset_url("logo", settings_payload["settings"]), html)
    html = re.sub(r"<title>.*?</title>", f"<title>{app_name}</title>", html, count=1)
    favicon_link = f'<link rel="icon" href="{favicon_url}">'
    if 'rel="icon"' in html:
        html = re.sub(r'<link rel="icon"[^>]*>', favicon_link, html, count=1)
    else:
        html = html.replace("</head>", f"    {favicon_link}\n</head>")
    bootstrap = "<script>window.__APP_SETTINGS__ = " + json.dumps(settings_payload).replace("</", "<\\/") + ";</script>"
    if "window.__APP_SETTINGS__" not in html:
        html = html.replace("</head>", f"    {bootstrap}\n</head>")
    return html
