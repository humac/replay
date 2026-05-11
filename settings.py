"""App settings — persistence and rendering helpers."""

from __future__ import annotations

import html as html_lib
import json
import os
import re
import secrets
import time
from pathlib import Path

import db as _db

# Default presets reused by tuning UI; kept in sync with server.py HLS_VARIANT_PRESETS.
_DEFAULT_HLS_VARIANT_PRESETS = [
    {"name": "1440p", "height": 1440, "width": 2560,
     "video_bitrate": "9000k", "maxrate": "10000k", "bufsize": "18000k",
     "audio_bitrate": "192k", "bandwidth": 10000000, "enabled": False},
    {"name": "1080p", "height": 1080, "width": 1920,
     "video_bitrate": "6000k", "maxrate": "6800k", "bufsize": "12000k",
     "audio_bitrate": "192k", "bandwidth": 7000000, "enabled": True},
    {"name": "720p", "height": 720, "width": 1280,
     "video_bitrate": "3200k", "maxrate": "3600k", "bufsize": "7200k",
     "audio_bitrate": "128k", "bandwidth": 3800000, "enabled": True},
    {"name": "480p", "height": 480, "width": 854,
     "video_bitrate": "1400k", "maxrate": "1600k", "bufsize": "3200k",
     "audio_bitrate": "128k", "bandwidth": 1800000, "enabled": True},
]

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
    # Performance tuning (formerly env vars). Stored as strings; coerced via TUNING_KNOBS.
    "transcode_concurrency": "2",
    "replay_hwaccel": "auto",
    "hls_segment_duration": "6",
    "min_free_disk_bytes": str(20 * 1024 * 1024 * 1024),
    "upload_disk_headroom_multiplier": "2.2",
    "stale_upload_session_seconds": str(6 * 60 * 60),
    "video_stream_chunk_bytes": str(1024 * 1024),
    "upload_chunk_size_bytes": str(16 * 1024 * 1024),
    "max_upload_size_bytes": str(12 * 1024 * 1024 * 1024),
    "hls_variant_presets": json.dumps(_DEFAULT_HLS_VARIANT_PRESETS),
    # Live streaming knobs (require MediaMTX restart)
    "live_hls_variant": "mpegts",
    "live_record_enabled": "0",
    "live_transcode_enabled": "0",
}

# Keys that are private — never returned in the public settings payload, and
# only writable through dedicated admin endpoints (not the generic settings PUT).
PRIVATE_SETTING_KEYS = {"live_stream_key"}

# Tuning knobs — admin-only in the public payload, but editable through the
# regular settings PUT. Each entry: type, range, optional env-var fallback for
# first-boot migration, and whether changes require a process restart.
#
# `kind`:
#   int   — integer with [min, max] clamp
#   float — float with [min, max] clamp
#   bool  — accepts "1"/"0"/true/false/yes/no/on/off; stored as "1"/"0"
#   enum  — one of `choices`
#   json  — opaque JSON blob, validated elsewhere
#
# `restart`: True means the value is read at startup or during MediaMTX boot —
# the UI shows a "Restart required" pill and the change still persists.
TUNING_KNOBS: dict[str, dict] = {
    "transcode_concurrency": {
        "kind": "int", "min": 1, "max": 8,
        "env": "TRANSCODE_CONCURRENCY", "restart": False,
        "label": "Transcode concurrency",
        "help": "Max simultaneous transcode jobs. Iris Xe + 12 threads handles 4 comfortably; bump to 6 with QSV.",
    },
    "replay_hwaccel": {
        "kind": "enum", "choices": ["auto", "qsv", "vaapi", "nvenc", "cpu"],
        "env": "REPLAY_HWACCEL", "restart": False,
        "label": "Hardware acceleration",
        "help": "qsv is fastest on Intel iGPU; auto picks the best available.",
    },
    "hls_segment_duration": {
        "kind": "int", "min": 2, "max": 10,
        "env": "HLS_SEGMENT_DURATION", "restart": True,
        "label": "HLS segment duration (s)",
        "help": "Shorter = snappier seek but more files. Existing HLS keeps its old duration until re-transcoded.",
    },
    "min_free_disk_bytes": {
        "kind": "int", "min": 1 * 1024 * 1024 * 1024, "max": 1024 * 1024 * 1024 * 1024,
        "env": "MIN_FREE_DISK_BYTES", "restart": False,
        "label": "Min free disk (bytes)",
        "help": "Refuse new uploads when free space falls below this floor.",
    },
    "upload_disk_headroom_multiplier": {
        "kind": "float", "min": 1.0, "max": 5.0,
        "env": "UPLOAD_DISK_HEADROOM_MULTIPLIER", "restart": False,
        "label": "Upload disk headroom",
        "help": "Required free bytes = upload_size × this. Covers raw + transcode + HLS.",
    },
    "stale_upload_session_seconds": {
        "kind": "int", "min": 600, "max": 7 * 24 * 60 * 60,
        "env": "STALE_UPLOAD_SESSION_SECONDS", "restart": False,
        "label": "Stale upload session timeout (s)",
        "help": "Idle upload sessions older than this are cancelled and their raw files removed.",
    },
    "video_stream_chunk_bytes": {
        "kind": "int", "min": 64 * 1024, "max": 8 * 1024 * 1024,
        "env": "VIDEO_STREAM_CHUNK_BYTES", "restart": False,
        "label": "Video stream chunk (bytes)",
        "help": "Read size per iteration when serving MP4 ranges. Larger = higher per-stream throughput.",
    },
    "upload_chunk_size_bytes": {
        "kind": "int", "min": 1 * 1024 * 1024, "max": 64 * 1024 * 1024,
        "env": "UPLOAD_CHUNK_SIZE_BYTES", "restart": False,
        "label": "Upload chunk size (bytes)",
        "help": "Suggested chunk size for new resumable upload sessions. In-flight sessions keep their old size.",
    },
    "max_upload_size_bytes": {
        "kind": "int", "min": 1 * 1024 * 1024 * 1024, "max": 64 * 1024 * 1024 * 1024,
        "env": "MAX_UPLOAD_SIZE_BYTES", "restart": False,
        "label": "Max upload size (bytes)",
        "help": "Largest single video allowed. Reverse-proxy body limit must be at least this.",
    },
    "hls_variant_presets": {
        "kind": "json", "restart": True,
        "label": "HLS variant ladder",
        "help": "ABR ladder used for new transcodes. Existing HLS unchanged until regenerated.",
    },
    "live_hls_variant": {
        "kind": "enum", "choices": ["mpegts", "lowLatency"],
        "restart": True,
        "label": "Live HLS variant",
        "help": "lowLatency is ~3× snappier on LAN but requires stable encoder timing.",
    },
    "live_record_enabled": {
        "kind": "bool", "restart": True,
        "label": "Record live to disk",
        "help": "MediaMTX records each publish to fMP4 segments — enables auto-promote-to-VOD.",
    },
    "live_transcode_enabled": {
        "kind": "bool", "restart": True,
        "label": "Live ABR transcode",
        "help": "Spawns a sidecar ffmpeg that produces 1080/720/480 renditions for live viewers.",
    },
}

EDITABLE_APP_SETTING_KEYS = {
    key for key in DEFAULT_APP_SETTINGS.keys()
    if key not in {"app_logo_filename", "favicon_filename"}
}

# Keys excluded from the public (unauthenticated) `/api/settings` payload.
# Tuning knobs leak nothing sensitive but are noise for non-admin clients.
PUBLIC_HIDDEN_KEYS = set(TUNING_KNOBS.keys()) | PRIVATE_SETTING_KEYS

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


def _seed_env_fallbacks_unlocked(conn) -> None:
    """First-boot migration: for any TUNING_KNOBS key with no DB row yet, seed
    from the matching env var if it is set. This lets existing deployments keep
    their `.env.local` values on first upgrade; subsequent saves come from the
    UI and the env var is ignored thereafter."""
    existing = {row["key"] for row in conn.execute("SELECT key FROM settings").fetchall()}
    rows = []
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    for key, spec in TUNING_KNOBS.items():
        if key in existing:
            continue
        env_var = spec.get("env")
        if not env_var:
            continue
        env_val = os.environ.get(env_var)
        if env_val is None or env_val == "":
            continue
        try:
            normalized = normalize_value(key, env_val)
        except ValueError:
            continue
        rows.append((key, normalized, now))
    if rows:
        conn.executemany(
            "INSERT INTO settings (key, value, updated_at) VALUES (?, ?, ?)"
            " ON CONFLICT(key) DO NOTHING",
            rows,
        )


def load_unlocked() -> dict[str, str]:
    settings = DEFAULT_APP_SETTINGS.copy()
    with _db.connect() as conn:
        _seed_env_fallbacks_unlocked(conn)
        rows = conn.execute("SELECT key, value FROM settings").fetchall()
    for row in rows:
        settings[row["key"]] = row["value"]
    return settings


def save_unlocked(updates: dict[str, str], *, actor: str | None = None) -> dict[str, str]:
    if not updates:
        return load_unlocked()
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    with _db.connect() as conn:
        prior = {
            row["key"]: row["value"]
            for row in conn.execute(
                "SELECT key, value FROM settings WHERE key IN (%s)"
                % ",".join("?" * len(updates)),
                list(updates.keys()),
            ).fetchall()
        }
        conn.executemany(
            """
            INSERT INTO settings (key, value, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at
            """,
            [(key, value, now) for key, value in updates.items()],
        )
        # Audit only changes that actually flipped a value, and only for keys
        # we actively tune (avoids cluttering the log with label edits).
        audit_rows = []
        for key, new_value in updates.items():
            if key not in TUNING_KNOBS:
                continue
            old_value = prior.get(key)
            if old_value == new_value:
                continue
            audit_rows.append((now, key, old_value, new_value, actor or ""))
        if audit_rows:
            conn.executemany(
                "INSERT INTO settings_audit (ts, key, old_value, new_value, actor)"
                " VALUES (?, ?, ?, ?, ?)",
                audit_rows,
            )
        conn.commit()
    return load_unlocked()


def list_audit_entries(limit: int = 50) -> list[dict]:
    with _db.connect() as conn:
        rows = conn.execute(
            "SELECT ts, key, old_value, new_value, actor FROM settings_audit"
            " ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [
        {
            "ts": r["ts"],
            "key": r["key"],
            "old_value": r["old_value"],
            "new_value": r["new_value"],
            "actor": r["actor"] or "",
        }
        for r in rows
    ]


def _coerce_bool(value) -> str:
    if isinstance(value, bool):
        return "1" if value else "0"
    return "1" if str(value).strip().lower() in {"1", "true", "yes", "on"} else "0"


def _coerce_int(value, *, lo: int, hi: int) -> str:
    try:
        n = int(float(str(value).strip()))
    except (TypeError, ValueError):
        raise ValueError(f"expected integer, got {value!r}")
    n = max(lo, min(hi, n))
    return str(n)


def _coerce_float(value, *, lo: float, hi: float) -> str:
    try:
        n = float(str(value).strip())
    except (TypeError, ValueError):
        raise ValueError(f"expected number, got {value!r}")
    if n < lo: n = lo
    if n > hi: n = hi
    return f"{n:g}"


def _coerce_enum(value, *, choices: list[str]) -> str:
    s = str(value).strip()
    if s not in choices:
        raise ValueError(f"must be one of: {', '.join(choices)}")
    return s


def _coerce_json(value) -> str:
    """Round-trip JSON to validate shape; reject anything that isn't a list/dict."""
    if isinstance(value, (list, dict)):
        return json.dumps(value)
    s = str(value).strip()
    if not s:
        raise ValueError("empty JSON")
    try:
        parsed = json.loads(s)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON: {exc.msg}")
    if not isinstance(parsed, (list, dict)):
        raise ValueError("JSON value must be an object or array")
    return json.dumps(parsed)


def normalize_value(key: str, value) -> str:
    if value is None:
        return DEFAULT_APP_SETTINGS.get(key, "")
    if key in {"downloads_enabled", "live_enabled"}:
        return _coerce_bool(value)
    spec = TUNING_KNOBS.get(key)
    if spec is not None:
        kind = spec["kind"]
        if kind == "int":
            return _coerce_int(value, lo=spec["min"], hi=spec["max"])
        if kind == "float":
            return _coerce_float(value, lo=spec["min"], hi=spec["max"])
        if kind == "bool":
            return _coerce_bool(value)
        if kind == "enum":
            return _coerce_enum(value, choices=spec["choices"])
        if kind == "json":
            return _coerce_json(value)
    return str(value).strip()


# ---------------------------------------------------------------------------
# Typed read helpers (used by hot-path code that needs the live setting value)
# ---------------------------------------------------------------------------

def get_int(settings: dict[str, str], key: str, default: int | None = None) -> int:
    raw = settings.get(key, DEFAULT_APP_SETTINGS.get(key, ""))
    try:
        return int(float(raw))
    except (TypeError, ValueError):
        return default if default is not None else 0


def get_float(settings: dict[str, str], key: str, default: float | None = None) -> float:
    raw = settings.get(key, DEFAULT_APP_SETTINGS.get(key, ""))
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default if default is not None else 0.0


def get_bool(settings: dict[str, str], key: str) -> bool:
    raw = settings.get(key, DEFAULT_APP_SETTINGS.get(key, ""))
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def get_str(settings: dict[str, str], key: str, default: str = "") -> str:
    return settings.get(key, DEFAULT_APP_SETTINGS.get(key, default))


def get_hls_variant_presets(settings: dict[str, str]) -> list[dict]:
    """Parsed + filtered HLS variant ladder. Falls back to default if the stored
    JSON is corrupt; only enabled rows are returned."""
    raw = settings.get("hls_variant_presets") or DEFAULT_APP_SETTINGS["hls_variant_presets"]
    try:
        rows = json.loads(raw)
    except (TypeError, ValueError):
        rows = _DEFAULT_HLS_VARIANT_PRESETS
    if not isinstance(rows, list):
        rows = _DEFAULT_HLS_VARIANT_PRESETS
    return [r for r in rows if isinstance(r, dict) and r.get("enabled", True)]


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
    public_settings = {k: v for k, v in settings.items() if k not in PUBLIC_HIDDEN_KEYS}
    return {
        "settings": public_settings,
        "assets": {
            "logo_url": app_asset_url("logo", settings),
            "favicon_url": app_asset_url("favicon", settings),
        },
    }


def admin_payload(settings: dict[str, str]) -> dict:
    """Same shape as `public_payload` but exposes tuning knobs (still hides
    PRIVATE_SETTING_KEYS like `live_stream_key`). Admin-only callers."""
    admin_settings = {k: v for k, v in settings.items() if k not in PRIVATE_SETTING_KEYS}
    return {
        "settings": admin_settings,
        "assets": {
            "logo_url": app_asset_url("logo", settings),
            "favicon_url": app_asset_url("favicon", settings),
        },
        "tuning_knobs": {
            key: {k: v for k, v in spec.items()}
            for key, spec in TUNING_KNOBS.items()
        },
    }


def render_index_html(settings_payload: dict) -> str:
    html = (STATIC_DIR / "index.html").read_text()
    app_name = html_lib.escape(settings_payload["settings"]["app_name"] or DEFAULT_APP_SETTINGS["app_name"])
    favicon_url = html_lib.escape(settings_payload["assets"]["favicon_url"], quote=True)
    html = re.sub(r'/static/styles\.css(?:\?v=[^"\']*)?', _versioned_static_path("styles.css"), html)
    html = re.sub(r'/static/styles/coaching-engagement\.css(?:\?v=[^"\']*)?', _versioned_static_path("styles/coaching-engagement.css"), html)
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
