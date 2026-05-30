"""Idempotent seed script for documentation screenshots.

Inserts ~12 placeholder matches and 2 demo users (uploader1, viewer1)
directly into the SQLite database via the project's own ``db`` and ``auth``
helpers, and attaches one committed mock video to a single match so the
player/VOD surfaces are screenshot-ready.

No HTTP / no running server required.

Safety: aborts if the target ``matches`` table already contains rows with
non-empty ``videos_json`` (i.e. real uploaded videos). This is a guard against
running the script against the user's real ``~/replay-data`` archive.

Usage:

    export REPLAY_DATA_DIR=/tmp/replay-docs-data
    export ADMIN_PASS=admin
    python docs/_seed/seed.py

``ADMIN_PASS`` is required because importing ``auth`` validates it at module
import time (the env-admin break-glass path). Use any non-empty value for
documentation captures.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import time
import uuid
from pathlib import Path

# Make the repo root importable
_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT))

import asyncio
import shutil as _shutil

import db as _db
import auth as _auth
import media as _media
import settings as _settings


SEEDED_USERS = ("uploader1", "viewer1")
DEMO_PASSWORD = "Replay!Demo123"

LOGO_DIR = Path(__file__).parent / "logos"


def _resolve_data_dir() -> Path:
    raw = os.environ.get("REPLAY_DATA_DIR")
    if not raw:
        print(
            "REPLAY_DATA_DIR is not set. Refusing to seed against an unspecified data dir.\n"
            "  Recommended: export REPLAY_DATA_DIR=/tmp/replay-docs-data",
            file=sys.stderr,
        )
        sys.exit(2)
    return Path(raw).expanduser().resolve()


def _abort_if_real_archive(conn) -> None:
    try:
        rows = conn.execute(
            "SELECT id, videos_json FROM matches WHERE videos_json NOT IN ('', '{}')"
        ).fetchall()
    except Exception:
        return
    # Re-running the seed must be idempotent. The mock-video step
    # populates `videos_json = {"first_half": "first_half.mp4"}` (or
    # similar single-slot mock shape), so the bare check above would
    # flag the script's OWN previous output as "looks like a real
    # archive." Treat any row whose only filenames are the seed-known
    # mock filenames (and whose other slots are null/missing) as
    # seed-produced output, not user uploads.
    real = []
    for row in rows:
        try:
            videos = json.loads(row["videos_json"] or "{}")
        except Exception:
            real.append(row)
            continue
        seed_only = True
        for slot, fname in videos.items():
            if fname is None:
                continue
            if slot != MOCK_VIDEO_SLOT or fname != f"{MOCK_VIDEO_SLOT}.mp4":
                seed_only = False
                break
        if not seed_only:
            real.append(row)
    if real:
        print(
            f"\nABORT: The matches table at this data dir contains {len(real)} match(es) "
            "with uploaded videos.\nThis looks like a real archive. Refusing to wipe it.\n"
            "Re-run against an isolated dir, e.g.\n"
            "  export REPLAY_DATA_DIR=/tmp/replay-docs-data",
            file=sys.stderr,
        )
        sys.exit(3)


_PALETTE = [
    ("#1f6feb", "#0b3d91"),
    ("#d62828", "#7d1414"),
    ("#0a8754", "#04361f"),
    ("#9b59b6", "#5b347a"),
    ("#e67e22", "#7d3a0a"),
    ("#16a085", "#0a4a3d"),
    ("#c0392b", "#5e1810"),
    ("#2c3e50", "#0d1822"),
    ("#f39c12", "#7d4f06"),
    ("#27ae60", "#114a25"),
    ("#8e44ad", "#3f1f55"),
    ("#34495e", "#16222e"),
]


def _initials(team: str) -> str:
    parts = [p for p in team.split() if p]
    if len(parts) >= 2:
        return (parts[0][0] + parts[1][0]).upper()
    return team[:2].upper()


def _make_logo_svg(team: str, fg: str, bg: str) -> str:
    initials = _initials(team)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 120" width="120" height="120">'
        f'<circle cx="60" cy="60" r="56" fill="{fg}" stroke="{bg}" stroke-width="6"/>'
        '<text x="60" y="74" text-anchor="middle" font-family="Helvetica, Arial, sans-serif" '
        f'font-size="42" font-weight="700" fill="white">{initials}</text>'
        '</svg>'
    )


def _ensure_logo_files(teams: list[str]) -> dict[str, Path]:
    LOGO_DIR.mkdir(parents=True, exist_ok=True)
    by_team: dict[str, Path] = {}
    for idx, team in enumerate(teams):
        fg, bg = _PALETTE[idx % len(_PALETTE)]
        slug = team.lower().replace(" ", "-").replace(".", "")
        path = LOGO_DIR / f"{slug}.svg"
        path.write_text(_make_logo_svg(team, fg, bg))
        by_team[team] = path
    return by_team


# 12 matches across 2 seasons. videos_json={} so cards render in "no video yet" state.
SEED_MATCHES = [
    # 2025-26 season — completed (with scores)
    {"home": "Riverside FC",      "away": "Northgate United", "date": "2025-09-14", "time": "15:00", "loc": "Riverside Park",      "sh": 2, "sa": 1, "fmt": "two_halves"},
    {"home": "Eastside Rovers",   "away": "Riverside FC",     "date": "2025-09-21", "time": "15:00", "loc": "Eastside Stadium",    "sh": 0, "sa": 0, "fmt": "two_halves"},
    {"home": "Riverside FC",      "away": "Highbridge Town",  "date": "2025-09-28", "time": "14:30", "loc": "Riverside Park",      "sh": 4, "sa": 2, "fmt": "two_halves"},
    {"home": "Marsh Lane Athletic","away": "Riverside FC",    "date": "2025-10-05", "time": "13:00", "loc": "Marsh Lane Ground",   "sh": 1, "sa": 3, "fmt": "two_halves"},
    {"home": "Riverside FC",      "away": "Westwood Albion",  "date": "2025-10-12", "time": "15:00", "loc": "Riverside Park",      "sh": 1, "sa": 1, "fmt": "full"},
    {"home": "Coastal United",    "away": "Riverside FC",     "date": "2025-10-19", "time": "16:00", "loc": "Coastal Arena",       "sh": 2, "sa": 2, "fmt": "two_halves"},
    {"home": "Riverside FC",      "away": "Pinehurst Rangers","date": "2025-11-02", "time": "15:00", "loc": "Riverside Park",      "sh": 3, "sa": 0, "fmt": "two_halves"},
    {"home": "Bridgewater FC",    "away": "Riverside FC",     "date": "2025-11-09", "time": "14:00", "loc": "Bridgewater Field",   "sh": 0, "sa": 1, "fmt": "two_halves"},
    {"home": "Riverside FC",      "away": "Eastside Rovers",  "date": "2025-11-23", "time": "15:00", "loc": "Riverside Park",      "sh": 2, "sa": 2, "fmt": "two_halves"},
    {"home": "Northgate United",  "away": "Riverside FC",     "date": "2025-12-07", "time": "13:30", "loc": "Northgate Field",     "sh": 1, "sa": 4, "fmt": "two_halves"},
    # 2026 — upcoming (no scores)
    {"home": "Riverside FC",      "away": "Marsh Lane Athletic","date": "2026-05-02","time": "15:00","loc": "Riverside Park",      "sh": None, "sa": None, "fmt": "two_halves"},
    {"home": "Highbridge Town",   "away": "Riverside FC",     "date": "2026-05-16", "time": "14:00", "loc": "Highbridge Stadium",  "sh": None, "sa": None, "fmt": "two_halves"},
]


def _all_teams() -> list[str]:
    seen: list[str] = []
    for m in SEED_MATCHES:
        for t in (m["home"], m["away"]):
            if t not in seen:
                seen.append(t)
    return seen


def _seed_matches(data_dir: Path, logos: dict[str, Path]) -> dict[tuple[str, str, str], str]:
    """Insert the demo matches and return a {(home, away, date): match_id} map.

    The map lets the mock-video step bind to a specific match without
    re-querying.
    """
    videos_dir = data_dir / "videos"
    videos_dir.mkdir(parents=True, exist_ok=True)

    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    by_key: dict[tuple[str, str, str], str] = {}
    with _db.connect() as conn:
        _abort_if_real_archive(conn)
        conn.execute("DELETE FROM matches")
        for entry in SEED_MATCHES:
            match_id = str(uuid.uuid4())
            slug_base = _db.generate_slug(entry["home"], entry["away"], entry["date"])
            slug = _db.ensure_unique_slug(conn, slug_base)

            match_dir = videos_dir / match_id
            match_dir.mkdir(parents=True, exist_ok=True)
            home_logo_dest = match_dir / "home_logo.svg"
            away_logo_dest = match_dir / "away_logo.svg"
            shutil.copyfile(logos[entry["home"]], home_logo_dest)
            shutil.copyfile(logos[entry["away"]], away_logo_dest)

            _db.upsert_match(conn, {
                "id": match_id,
                "home_team": entry["home"],
                "away_team": entry["away"],
                "date": entry["date"],
                "time": entry["time"],
                "location": entry["loc"],
                "score_home": entry["sh"],
                "score_away": entry["sa"],
                "format": entry["fmt"],
                "videos": {},
                "video_status": {},
                "home_logo": home_logo_dest.name,
                "away_logo": away_logo_dest.name,
                "created_at": now,
                "slug": slug,
                "updated_at": now,
            })
            by_key[(entry["home"], entry["away"], entry["date"])] = match_id
        conn.commit()
    return by_key


def _seed_users() -> dict[str, str]:
    """Create the demo users and return a {username: user_id} map."""
    with _db.connect() as conn:
        placeholders = ",".join("?" for _ in SEEDED_USERS)
        conn.execute(f"DELETE FROM users WHERE username IN ({placeholders})", SEEDED_USERS)
        conn.commit()

    pwd_hash = _auth.hash_password(DEMO_PASSWORD)
    spec = [
        ("uploader1", "uploader", "Uploader Demo"),
        ("viewer1",   "viewer",   "Viewer Demo"),
    ]
    by_username: dict[str, str] = {}
    for username, role, display in spec:
        user = _db.create_user(username, pwd_hash, role, display_name=display)
        by_username[username] = user["id"]
    return by_username


# ---------------------------------------------------------------------------
# Mock video — committed alongside the seed script so a fresh seed always has
# at least one playable match. The committed file is a 30-second 1280x720
# h.264/aac SMPTE-bars clip (~420 KB) generated with ffmpeg lavfi. We attach
# it to the first 2025 Riverside FC home match's `first_half` slot, run the
# real HLS variant ladder + match thumbnail through `media.py`, and persist
# `videos`/`video_status` directly so the surfaces that depend on a real
# playable video (player view) work end-to-end.
#
# Idempotent: skips re-transcoding if the HLS master already exists.
# ---------------------------------------------------------------------------

MOCK_VIDEO_SOURCE = Path(__file__).parent / "videos" / "mock_first_half.mp4"
MOCK_VIDEO_TARGET = ("Riverside FC", "Northgate United", "2025-09-14")
MOCK_VIDEO_SLOT = "first_half"


def _seed_mock_video(
    data_dir: Path,
    matches_by_key: dict[tuple[str, str, str], str],
) -> str:
    """Copy the committed mock mp4 into the slot path, build HLS variants,
    generate the match thumbnail, and update the match record so playback
    surfaces work. Returns a one-line status string for the seed summary.

    Note on idempotence: `_seed_matches` deletes and re-inserts every
    match each run (new UUIDs), so on a re-seed the previous run's
    `<old_id>/first_half.mp4` is orphaned and this function transcodes
    fresh into `<new_id>/`. The skip-if-exists branch only fires if
    the seed runs twice without `_seed_matches` having reset the
    table — for example if a future change makes match seeding
    upsert-by-key. The skip path is kept for that future case and
    for safety against partial runs."""
    if not MOCK_VIDEO_SOURCE.is_file():
        return f"  skipped (mock source missing: {MOCK_VIDEO_SOURCE})"

    match_id = matches_by_key.get(MOCK_VIDEO_TARGET)
    if not match_id:
        return f"  skipped (target match {MOCK_VIDEO_TARGET} not found)"

    videos_dir = data_dir / "videos"
    originals_dir = data_dir / "videos"  # un-tiered single-volume layout
    final_mp4 = originals_dir / match_id / f"{MOCK_VIDEO_SLOT}.mp4"
    hls_master = _media.slot_hls_master_path(videos_dir, match_id, MOCK_VIDEO_SLOT)

    # Idempotent: a previous seed in the same data dir already produced
    # everything. Re-running shouldn't re-transcode.
    if final_mp4.is_file() and hls_master.is_file():
        return f"  reused existing HLS for {MOCK_VIDEO_TARGET[0]} vs {MOCK_VIDEO_TARGET[1]}"

    final_mp4.parent.mkdir(parents=True, exist_ok=True)
    _shutil.copyfile(MOCK_VIDEO_SOURCE, final_mp4)

    # Pull the live HLS preset list from settings — same source the
    # admin tuning panel + transcode pipeline use, so the seed produces
    # whatever variant ladder the dev's environment is configured for.
    settings_snapshot = _settings.load_unlocked()
    hls_segment_duration = _settings.get_int(
        settings_snapshot, "hls_segment_duration", 4,
    )
    hls_variant_presets = _settings.get_hls_variant_presets(settings_snapshot)

    async def _run_pipeline() -> None:
        ok = await _media.build_hls_assets(
            final_mp4, match_id, MOCK_VIDEO_SLOT,
            videos_dir=videos_dir,
            hls_segment_duration=hls_segment_duration,
            hls_variant_presets=hls_variant_presets,
        )
        if not ok:
            raise RuntimeError("build_hls_assets returned False")
        thumb_path = videos_dir / match_id / "thumb.jpg"
        if not thumb_path.exists():
            await _media.generate_thumbnail(final_mp4, thumb_path)

    asyncio.run(_run_pipeline())

    # Persist videos[slot] + video_status[slot] = "ready" so the match
    # row reflects a real playable asset. Mirrors what
    # `_set_video_status(..., "ready", filename)` does at runtime, but
    # we don't need the activity-feed write or the async lock here —
    # we're seeding, not racing concurrent uploads.
    matches = _db.load_matches_unlocked()
    match = _db.find_match(matches, match_id)
    if match is None:
        return f"  skipped (match record vanished mid-seed: {match_id})"
    match.setdefault("videos", {})
    match.setdefault("video_status", {})
    match["videos"][MOCK_VIDEO_SLOT] = f"{MOCK_VIDEO_SLOT}.mp4"
    match["video_status"][MOCK_VIDEO_SLOT] = "ready"
    _db.save_matches_unlocked(matches)

    return f"  seeded mock {MOCK_VIDEO_SLOT} for {MOCK_VIDEO_TARGET[0]} vs {MOCK_VIDEO_TARGET[1]}"


def main() -> None:
    data_dir = _resolve_data_dir()
    db_file = data_dir / "replay.db"
    app_assets_dir = data_dir / "app_assets"

    print(f"[seed] data dir: {data_dir}")
    _db.init(data_dir, db_file, app_assets_dir)

    teams = _all_teams()
    logos = _ensure_logo_files(teams)
    print(f"[seed] generated {len(logos)} placeholder team logos in {LOGO_DIR}")

    matches_by_key = _seed_matches(data_dir, logos)
    users = _seed_users()
    mock_video_status = _seed_mock_video(data_dir, matches_by_key)

    print()
    print("=" * 60)
    print(" Seed complete")
    print("=" * 60)
    print(f"  Matches:    {len(matches_by_key)}")
    print(f"  Users:      {len(users)}")
    print(f"  Mock video:")
    print(mock_video_status)
    print()
    print("  Demo accounts (password: %s):" % DEMO_PASSWORD)
    print("    uploader1  — uploader  (manages the match library)")
    print("    viewer1    — viewer    (read-only)")
    print()
    print("  Next:  python server.py")
    print(f"         (uses REPLAY_DATA_DIR={data_dir})")
    print()


if __name__ == "__main__":
    main()
