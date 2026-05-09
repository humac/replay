"""Idempotent seed script for documentation screenshots.

Inserts ~12 placeholder matches and 5 demo users (uploader1, viewer1, coach1,
family1, family2) directly into the SQLite database via the project's own
``db`` and ``auth`` helpers. Also seeds a 12-player roster, six coaching
notes (one with a multi-player formation overlay), and two playlists so the
``/coach`` and ``/feedback`` surfaces are screenshot-ready.

No HTTP / no running server required.

Safety: aborts if the target ``matches`` table already contains rows with
non-empty ``videos_json`` (i.e. real uploaded videos). This is a guard against
running the script against the user's real ``~/replay-data`` archive.

Usage:

    export REPLAY_DATA_DIR=/tmp/replay-docs-data
    python docs/_seed/seed.py
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


SEEDED_USERS = ("uploader1", "viewer1", "coach1", "family1", "family2")
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

    The map lets the coaching seed bind notes to specific matches without
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
    """Create the demo users and return a {username: user_id} map.

    The map is needed so the coaching seed can build player_user_links without
    re-querying the users table, and so coaching_notes.created_by can be set to
    a stable username (the same value the runtime sets via actor=user["username"]).
    """
    with _db.connect() as conn:
        placeholders = ",".join("?" for _ in SEEDED_USERS)
        conn.execute(f"DELETE FROM users WHERE username IN ({placeholders})", SEEDED_USERS)
        conn.commit()

    pwd_hash = _auth.hash_password(DEMO_PASSWORD)
    spec = [
        ("uploader1", "uploader",       "Uploader Demo"),
        ("viewer1",   "viewer",         "Viewer Demo"),
        ("coach1",    "coach,uploader", "Coach Demo"),
        ("family1",   "viewer",         "Alex Parent"),
        ("family2",   "viewer",         "Jordan Family"),
    ]
    by_username: dict[str, str] = {}
    for username, role, display in spec:
        user = _db.create_user(username, pwd_hash, role, display_name=display)
        by_username[username] = user["id"]
    return by_username


# ---------------------------------------------------------------------------
# Coaching workspace seed
# ---------------------------------------------------------------------------

# 12 roster players. Jersey #13 skipped (common superstition); #9 is inactive
# so the active filter on the Roster tab has something to hide.
SEED_ROSTER = [
    ("1",  "Maya Chen",       True),
    ("2",  "Liam O'Connor",   True),
    ("3",  "Theo Bauer",      True),
    ("4",  "Noor Hassan",     True),
    ("5",  "Diego Alvarez",   True),
    ("6",  "Anders Holm",     True),
    ("7",  "Alex Park",       True),    # linked to family1
    ("8",  "Jonah Reyes",     True),
    ("9",  "Sam Whitlock",    False),   # inactive — demos the active filter
    ("10", "Jordan Vega",     True),    # linked to family2
    ("11", "Kai Nakamura",    True),
    ("14", "Riley Park",      True),    # linked to family1 (sibling case)
]


def _seed_roster() -> dict[str, str]:
    """Replace the demo roster and return a {jersey_number: player_id} map."""
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    by_jersey: dict[str, str] = {}
    with _db.connect() as conn:
        # Children with FK ON DELETE CASCADE are wiped automatically when
        # players is cleared — but we clear them too to keep the seed fully
        # explicit and avoid leaving orphan rows from any prior schema state.
        # Phase 6e follow-up: include coaching_clips + coaching_clip_players
        # in the wipe. `coaching_clips.match_id` has no FK declaration and
        # the project doesn't enable PRAGMA foreign_keys, so re-running
        # the seed against the same data dir would otherwise pile up clip
        # rows whose `match_id` references the previous run's matches
        # (which `_seed_matches` rewrites with fresh UUIDs every run).
        conn.execute("DELETE FROM coaching_reviews")
        conn.execute("DELETE FROM player_goal_reflections")
        conn.execute("DELETE FROM player_goal_status_history")
        conn.execute("DELETE FROM player_goals")
        conn.execute("DELETE FROM coaching_match_summary_playlists")
        conn.execute("DELETE FROM coaching_match_summary_clips")
        conn.execute("DELETE FROM coaching_match_summary_notes")
        conn.execute("DELETE FROM coaching_match_summaries")
        conn.execute("DELETE FROM coaching_clip_players")
        conn.execute("DELETE FROM coaching_clips")
        conn.execute("DELETE FROM coaching_playlist_players")
        conn.execute("DELETE FROM coaching_playlist_items")
        conn.execute("DELETE FROM coaching_playlists")
        conn.execute("DELETE FROM coaching_note_tags")
        conn.execute("DELETE FROM coaching_note_players")
        conn.execute("DELETE FROM coaching_notes")
        conn.execute("DELETE FROM player_user_links")
        conn.execute("DELETE FROM players")
        for jersey, name, active in SEED_ROSTER:
            pid = uuid.uuid4().hex
            conn.execute(
                "INSERT INTO players (id, display_name, jersey_number, active, notes, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (pid, name, jersey, 1 if active else 0, "", now, now),
            )
            by_jersey[jersey] = pid
        conn.commit()
    return by_jersey


def _seed_player_user_links(roster: dict[str, str], users: dict[str, str]) -> int:
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    links = [
        (roster["7"],  users["family1"], "guardian"),
        (roster["14"], users["family1"], "guardian"),
        (roster["10"], users["family2"], "parent"),
    ]
    with _db.connect() as conn:
        for player_id, user_id, relationship in links:
            conn.execute(
                "INSERT INTO player_user_links (player_id, user_id, relationship, created_at)"
                " VALUES (?, ?, ?, ?)",
                (player_id, user_id, relationship, now),
            )
        conn.commit()
    return len(links)


# Drawing builders — produce JSON v2 objects that conform to the validator at
# models.py validate_drawing_payload(). All coordinates are normalized 0..1.
def _drawing_arrow_zone() -> dict:
    return {
        "version": 2,
        "objects": [
            {"type": "zone",  "color": "#facc15", "width": 3,
             "x": 0.10, "y": 0.55, "w": 0.30, "h": 0.30},
            {"type": "arrow", "color": "#38bdf8", "width": 4,
             "x1": 0.50, "y1": 0.20, "x2": 0.25, "y2": 0.65},
        ],
    }


def _drawing_back_four_formation(roster: dict[str, str]) -> dict:
    """Five anchors: a four-back line plus one central anchor at (0.50, 0.45).
    The hull is the four corners; the central anchor sits inside the polygon
    so Andrew's monotone-chain hull (used by the runtime painter) returns
    exactly four points. Hand-computed here because the seed runs without JS.
    """
    anchors = [
        {"x": 0.20, "y": 0.62, "player_id": roster["3"], "label": "3"},
        {"x": 0.40, "y": 0.65, "player_id": roster["4"], "label": "4"},
        {"x": 0.60, "y": 0.65, "player_id": roster["5"], "label": "5"},
        {"x": 0.80, "y": 0.62, "player_id": roster["2"], "label": "2"},
        {"x": 0.50, "y": 0.45, "player_id": roster["6"], "label": "6"},
    ]
    # CCW hull of the four corner anchors (central anchor is interior).
    hull = [
        {"x": 0.20, "y": 0.62},
        {"x": 0.80, "y": 0.62},
        {"x": 0.60, "y": 0.65},
        {"x": 0.40, "y": 0.65},
    ]
    return {
        "version": 2,
        "objects": [
            {"type": "formation", "color": "#38bdf8", "width": 3,
             "anchors": anchors, "hull_points": hull},
        ],
    }


def _drawing_circle_label() -> dict:
    return {
        "version": 2,
        "objects": [
            {"type": "circle", "color": "#22c55e", "width": 3,
             "x": 0.45, "y": 0.50, "w": 0.10, "h": 0.10},
            {"type": "label", "color": "#22c55e", "x": 0.46, "y": 0.45, "text": "control"},
        ],
    }


def _drawing_freehand_arrow() -> dict:
    return {
        "version": 2,
        "objects": [
            {"type": "freehand", "color": "#f97316", "width": 3,
             "points": [
                 {"x": 0.62, "y": 0.40}, {"x": 0.58, "y": 0.48},
                 {"x": 0.52, "y": 0.55}, {"x": 0.46, "y": 0.60},
                 {"x": 0.40, "y": 0.62},
             ]},
            {"type": "arrow", "color": "#f97316", "width": 4,
             "x1": 0.40, "y1": 0.62, "x2": 0.30, "y2": 0.70},
        ],
    }


def _drawing_spotlight_dim() -> dict:
    return {
        "version": 2,
        "objects": [
            {"type": "dim", "opacity": 0.45},
            {"type": "spotlight", "color": "#facc15", "width": 3,
             "x": 0.55, "y": 0.30, "w": 0.18, "h": 0.18},
        ],
    }


# Notes: (home, away, date) selects a seeded match. Coordinates and content
# are tuned so each note demonstrates a distinct telestrator tool combination.
#
# Each spec carries a stable `key` (e.g. "press_trigger", "p7_recovery") so
# downstream seeders (`_seed_clips`, `_seed_playlists`) can look notes up by
# name instead of by positional index. Adding/reordering notes in this list
# now no longer silently rebinds clip `source_note_id`s or playlist items.
def _seed_coaching_notes(
    matches: dict[tuple[str, str, str], str],
    roster: dict[str, str],
) -> dict[str, int]:
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    m1 = matches[("Riverside FC", "Northgate United", "2025-09-14")]
    m2 = matches[("Riverside FC", "Highbridge Town",  "2025-09-28")]
    m3 = matches[("Riverside FC", "Pinehurst Rangers","2025-11-02")]

    # Each entry is a dict with a stable `key`. Phase 1 structured fields
    # are optional — empty strings render the legacy `body`-only path,
    # populated values render the full tone-pill + summary + structured
    # <dl> stack in My Feedback.
    specs: list[dict] = [
        {
            "key": "press_trigger",
            "match_id": m1, "slot": "first_half", "timestamp_seconds": 312.5,
            "title": "Pressing trigger on goal-kick",
            "body": (
                "When their #1 plants the ball, our front three step up together. Watch the angle "
                "the wide forward takes — body shape forces the keeper to go long."
            ),
            "category": "pressing", "visibility": "team",
            "drawing": _drawing_arrow_zone(),
            "jerseys": [], "tags": ["pressing", "shape"],
            "note_type": "team_concept",
            "player_summary": "When their keeper plants the ball, step up together — angle the press so the keeper has to go long.",
            "what_happened": "Their goal kick at 5:12. Our front three drifted apart, the keeper had a free short pass to the centre-back, and we lost ten yards of pressure.",
            "why_it_matters": "If we time the trigger together we force long balls into our centre-backs' headers — that's a 70% recovery rate for us.",
            "what_to_do_next": "Watch your wide partner's first step. When they go, you go. Body shape closes the inside lane, not the keeper directly.",
            "coach_private_note": "Coach note: drilled this on Tuesday with the front three only — second unit still drifting late.",
        },
        {
            "key": "back_four_shape",
            "match_id": m1, "slot": "second_half", "timestamp_seconds": 1820.0,
            "title": "Back-four shape during Northgate spell",
            "body": (
                "The line stayed compact for ten minutes here. Notice how the holding mid drops in "
                "to make a five when Northgate worked the wide channel."
            ),
            "category": "shape", "visibility": "team",
            "drawing": _drawing_back_four_formation(roster),
            "jerseys": ["3", "4", "5", "2", "6"], "tags": ["shape", "defending"],
            "note_type": "positive",
            "player_summary": "Best ten-minute defensive spell of the half — line stayed compact and the #6 dropped to make a five in the wide channel.",
            "what_happened": "", "why_it_matters": "", "what_to_do_next": "",
            "coach_private_note": "",
        },
        {
            "key": "phase8_private_summary_source",
            "match_id": m1, "slot": "second_half", "timestamp_seconds": 1900.0,
            "title": "PHASE8_PRIVATE_SOURCE_CANARY title",
            "body": "PHASE8_PRIVATE_SOURCE_CANARY body must not leak through team-visible summary links.",
            "category": "other", "visibility": "private",
            "drawing": {"version": 2, "objects": []},
            "jerseys": [], "tags": ["phase8-private-source"],
            "note_type": "correction",
            "player_summary": "", "what_happened": "", "why_it_matters": "", "what_to_do_next": "",
            "coach_private_note": "PHASE8_PRIVATE_SOURCE_CANARY coach-private text",
        },
        {
            "key": "first_touch_pressure",
            "match_id": m2, "slot": "full", "timestamp_seconds": 642.0,
            "title": "First-touch under pressure",
            "body": (
                "Receive across the body, open the hips, and you're already facing forward. "
                "Compare this clip with the turnover at 14:30."
            ),
            "category": "build_up", "visibility": "team",
            "drawing": _drawing_circle_label(),
            "jerseys": [], "tags": ["technique"],
            "note_type": "individual_goal",
            "player_summary": "Receive across your body — open hips, take the touch into space, and you're facing forward already.",
            "what_happened": "Ball came from the keeper. You took it facing your own goal, had to turn under pressure, and lost it.",
            "why_it_matters": "One extra touch backwards is one extra second for their press to set. Open the body once and you skip that whole sequence.",
            "what_to_do_next": "On reception: plant the back foot, point the front foot toward the opponent's goal, take the touch with your far foot.",
            "coach_private_note": "PHASE7_SECRET: seeded source-note canary that must never appear in viewer goal payloads or UI.",
        },
        {
            "key": "p7_recovery",
            "match_id": m2, "slot": "full", "timestamp_seconds": 1430.0,
            "title": "Player #7 — defensive recovery",
            "body": (
                "Strong recovery run from the far side. Track the angle: cut across the passing "
                "lane, don't chase the ball."
            ),
            "category": "defending", "visibility": "player",
            "drawing": _drawing_freehand_arrow(),
            "jerseys": ["7"], "tags": ["recovery", "1v1"],
            "note_type": "positive",
            "player_summary": "Beautiful recovery run — you cut across the passing lane instead of chasing the ball. That's the model.",
            "what_happened": "", "why_it_matters": "", "what_to_do_next": "",
            "coach_private_note": "",
        },
        {
            "key": "p10_early_run",
            "match_id": m3, "slot": "first_half", "timestamp_seconds": 215.0,
            "title": "Player #10 — early run",
            "body": (
                "Read the trigger off the keeper and break early. Spotlight is the gap you should "
                "be attacking before the centre-back closes."
            ),
            "category": "transition", "visibility": "player",
            "drawing": _drawing_spotlight_dim(),
            "jerseys": ["10"], "tags": ["transition"],
            "note_type": "correction",
            "player_summary": "Break earlier on the keeper's release — attack the gap before the centre-back can close it.",
            "what_happened": "Keeper rolled it out at 3:35. You started moving 1.5 seconds late and the gap had already shut.",
            "why_it_matters": "If you read the trigger off the keeper's body shape (not the ball), you get a 5–8 yard head start on the centre-back. That's the difference between a chance and a recycle.",
            "what_to_do_next": "Two cues: (1) keeper's plant foot turns sideways → release is coming, (2) centre-back's eyes go to the ball → blind side opens. Move on cue 1, finish on cue 2.",
            "coach_private_note": "Coach note: pulled #10 at 18' for a debrief on this; he saw it. Repeat in next session's possession game.",
        },
        {
            "key": "private_sub_rationale",
            "match_id": m3, "slot": "second_half", "timestamp_seconds": 1100.0,
            "title": "PRIVATE CANARY — internal substitution rationale",
            "body": (
                "PRIVATE CANARY coaching note only — context for the staff. Subbing for energy in the press, not "
                "punishing the player."
            ),
            "category": "other", "visibility": "private",
            "drawing": {"version": 2, "objects": []},
            "jerseys": [], "tags": [],
            "note_type": "correction",
            "player_summary": "", "what_happened": "", "why_it_matters": "", "what_to_do_next": "",
            "coach_private_note": "Sub at 65' was for energy in the press, NOT punishment. Make sure the player hears that on Tuesday — last time we left it ambiguous and his confidence dropped for a week.",
        },
    ]

    # Defensive: surface duplicate seed keys at seed time rather than
    # silently overwriting the map below. Catches typos when a future
    # contributor adds a new spec entry.
    seen_keys: set[str] = set()
    for spec in specs:
        if spec["key"] in seen_keys:
            raise RuntimeError(f"duplicate seed key in _seed_coaching_notes: {spec['key']!r}")
        seen_keys.add(spec["key"])

    note_ids_by_key: dict[str, int] = {}
    with _db.connect() as conn:
        for spec in specs:
            cur = conn.execute(
                """
                INSERT INTO coaching_notes (
                    match_id, slot, timestamp_seconds, title, body, category, visibility,
                    drawing_json, created_by, created_at, updated_at,
                    note_type, player_summary, what_happened, why_it_matters,
                    what_to_do_next, coach_private_note
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    spec["match_id"], spec["slot"], spec["timestamp_seconds"],
                    spec["title"], spec["body"], spec["category"], spec["visibility"],
                    json.dumps(spec["drawing"]), "coach1", now, now,
                    spec["note_type"], spec["player_summary"], spec["what_happened"],
                    spec["why_it_matters"], spec["what_to_do_next"], spec["coach_private_note"],
                ),
            )
            note_id = cur.lastrowid
            note_ids_by_key[spec["key"]] = note_id
            for jersey in spec["jerseys"]:
                conn.execute(
                    "INSERT INTO coaching_note_players (note_id, player_id) VALUES (?, ?)",
                    (note_id, roster[jersey]),
                )
            for tag in spec["tags"]:
                conn.execute(
                    "INSERT INTO coaching_note_tags (note_id, tag) VALUES (?, ?)",
                    (note_id, tag),
                )
        conn.commit()
    return note_ids_by_key


def _seed_observation_notes(
    matches: dict[tuple[str, str, str], str],
    roster: dict[str, str],
) -> list[int]:
    """Phase 6e — at least one observation note (text-only, no video) and
    one tactical-board observation visible to family1 (player #7) so the
    My Feedback detail surfaces have something realistic to render. Both
    are `note_context = 'observation'` and carry event_title / event_date /
    event_type instead of match/slot/timestamp.

    The tactical-board observation uses a simple 4-token formation snippet
    that survives `validate_tactical_board_payload` (normalized 0..1
    coordinates, soccer_full pitch).
    """
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    note_ids: list[int] = []

    # Text-only observation, visible to player #7 (family1).
    text_obs = {
        "note_context": "observation",
        "match_id": None,
        "slot": None,
        "timestamp_seconds": None,
        "title": "Tuesday practice — 1v1 defending",
        "body": "Three reps of close-down work in the small-sided game. Focus on body shape, not the lunge.",
        "category": "defending",
        "visibility": "player",
        "drawing_json": "{}",
        "tactical_board_json": None,
        "event_title": "Tuesday practice — 1v1 defending",
        "event_date": "2026-05-05",
        "event_type": "practice",
        "note_type": "correction",
        "player_summary": "Get small and patient on the ball-carrier — let them choose the touch, then commit when their head goes down.",
        "what_happened": "In the 1v1 channel today, you were lunging in early on each rep. The forward feinted once and you opened your hips.",
        "why_it_matters": "Patient defenders win the second touch. Lunging gives away the duel before the forward has even committed.",
        "what_to_do_next": "Sit lower, half-step closer, and keep both feet active. Wait for their head to drop before stepping in.",
        "coach_private_note": "Pulled #7 aside after rep 3 — she nodded but is still over-aggressive when tired. Re-rep on Thursday.",
        "tags": ["defending", "1v1", "practice"],
        "jerseys": ["7"],
    }

    # Tactical board observation visible to player #7 (family1).
    formation_board = {
        "version": 1,
        "pitch_kind": "soccer_full",
        "orientation": "landscape",
        "game_format": "11v11",
        "formation": "4-3-3",
        "tokens": [
            {"kind": "player", "x": 0.10, "y": 0.50, "label": "GK"},
            {"kind": "player", "x": 0.22, "y": 0.20, "label": "RB"},
            {"kind": "player", "x": 0.22, "y": 0.40, "label": "CB"},
            {"kind": "player", "x": 0.22, "y": 0.60, "label": "CB"},
            {"kind": "player", "x": 0.22, "y": 0.80, "label": "LB"},
            {"kind": "player", "x": 0.42, "y": 0.30, "label": "CM"},
            {"kind": "player", "x": 0.42, "y": 0.50, "label": "CM"},
            {"kind": "player", "x": 0.42, "y": 0.70, "label": "CM"},
            {"kind": "player", "x": 0.62, "y": 0.20, "label": "RW"},
            {"kind": "player", "x": 0.62, "y": 0.50, "label": "ST"},
            {"kind": "player", "x": 0.62, "y": 0.80, "label": "LW"},
            {"kind": "ball", "x": 0.60, "y": 0.50},
        ],
        "shapes": [
            {
                "kind": "zone",
                "x": 0.40, "y": 0.18, "w": 0.25, "h": 0.64,
                "color": "#facc15",
                "stroke_width": 3,
            },
            {
                "kind": "label",
                "x": 0.52, "y": 0.10,
                "text": "Compact mid third",
                "color": "#ffffff",
            },
            {
                "kind": "arrow",
                "x1": 0.62, "y1": 0.20, "x2": 0.78, "y2": 0.30,
                "color": "#22c55e",
                "stroke_width": 4,
            },
        ],
    }
    board_obs = {
        "note_context": "observation",
        "match_id": None,
        "slot": None,
        "timestamp_seconds": None,
        "title": "Team shape — compact 4-3-3 mid block",
        "body": "Reference sketch for Saturday's match. Stay compact through the middle, force play wide.",
        "category": "shape",
        "visibility": "player",
        "drawing_json": "{}",
        "tactical_board_json": json.dumps(formation_board),
        "event_title": "Saturday match prep — Pinehurst",
        "event_date": "2026-05-09",
        "event_type": "tactical",
        "note_type": "team_concept",
        "player_summary": "Stay compact through the middle. Push wingers wide, deny the central pass, then rotate to win the duel on the wing.",
        "what_happened": "Last Saturday the centre channel was 8 yards too wide and Pinehurst played through us four times.",
        "why_it_matters": "If our 4-3-3 stays compact, their forwards have to drop deep to get the ball — exactly where our midfield can win it.",
        "what_to_do_next": "When the ball goes wide, the ball-side winger pinches in. The far-side full-back tucks. The 6 covers behind the line.",
        "coach_private_note": "Family1 should see this — #7 plays right-back and we're asking her to tuck on weak-side switches.",
        "tags": ["shape", "build_up"],
        "jerseys": ["7"],
    }

    with _db.connect() as conn:
        for spec in (text_obs, board_obs):
            cur = conn.execute(
                """
                INSERT INTO coaching_notes (
                    match_id, slot, timestamp_seconds, title, body, category, visibility,
                    drawing_json, created_by, created_at, updated_at,
                    note_type, player_summary, what_happened, why_it_matters,
                    what_to_do_next, coach_private_note,
                    note_context, event_title, event_date, event_type, tactical_board_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    spec["match_id"], spec["slot"], spec["timestamp_seconds"],
                    spec["title"], spec["body"], spec["category"], spec["visibility"],
                    spec["drawing_json"], "coach1", now, now,
                    spec["note_type"], spec["player_summary"], spec["what_happened"],
                    spec["why_it_matters"], spec["what_to_do_next"], spec["coach_private_note"],
                    spec["note_context"], spec["event_title"], spec["event_date"],
                    spec["event_type"], spec["tactical_board_json"],
                ),
            )
            note_id = cur.lastrowid
            note_ids.append(note_id)
            for jersey in spec["jerseys"]:
                conn.execute(
                    "INSERT INTO coaching_note_players (note_id, player_id) VALUES (?, ?)",
                    (note_id, roster[jersey]),
                )
            for tag in spec["tags"]:
                conn.execute(
                    "INSERT INTO coaching_note_tags (note_id, tag) VALUES (?, ?)",
                    (note_id, tag),
                )
        conn.commit()
    return note_ids


def _seed_clips(
    matches: dict[tuple[str, str, str], str],
    roster: dict[str, str],
    note_ids_by_key: dict[str, int],
) -> int:
    """Phase 6e — at least one viewer-visible clip so the My Feedback Clips
    tab has content. Anchored to the same match the mock video covers
    (Riverside FC vs Northgate United, first_half), referencing the
    Player #7 defensive-recovery note via its stable seed key
    (`p7_recovery`) so the clip thumbnail can fall through to the source
    note's JPEG.

    Phase 6e follow-up: looks up the source note by stable key instead of
    by positional index. Reordering or adding entries to
    `_seed_coaching_notes` no longer silently rebinds `source_note_id`.
    """
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    m1 = matches[("Riverside FC", "Northgate United", "2025-09-14")]
    note_player7 = note_ids_by_key["p7_recovery"]
    with _db.connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO coaching_clips (
                match_id, slot, start_seconds, end_seconds, title, description,
                category, visibility, source_note_id, drawing_json,
                created_by, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                m1, "first_half", 4.0, 18.0,
                "Player #7 — defensive recovery (clip)",
                "Short clip from the Northgate match showing the recovery angle. Watch how she cuts the passing lane instead of chasing the ball.",
                "defending", "player", note_player7, "{}",
                "coach1", now, now,
            ),
        )
        clip_id = cur.lastrowid
        conn.execute(
            "INSERT INTO coaching_clip_players (clip_id, player_id) VALUES (?, ?)",
            (clip_id, roster["7"]),
        )
        conn.commit()
    return 1


def _seed_playlists(note_ids_by_key: dict[str, int], roster: dict[str, str]) -> int:
    """Two playlists. A is team-visible (`press_trigger` + `first_touch_pressure`);
    B is player-visible (`p7_recovery`) and scoped to player #7 via
    coaching_playlist_players.

    Phase 6e follow-up: notes are looked up by stable seed key instead of
    by positional unpacking, so reordering or adding entries to
    `_seed_coaching_notes` no longer silently rebinds playlist items.
    """
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    with _db.connect() as conn:
        cur = conn.execute(
            "INSERT INTO coaching_playlists (title, description, visibility, pre_roll_seconds,"
            " post_roll_seconds, created_by, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("First-half tactical lessons",
             "Two clips on pressing triggers and first-touch in the build-up.",
             "team", 5.0, 8.0, "coach1", now, now),
        )
        playlist_a = cur.lastrowid
        for position, key in enumerate(("press_trigger", "first_touch_pressure")):
            conn.execute(
                "INSERT INTO coaching_playlist_items (playlist_id, note_id, position) VALUES (?, ?, ?)",
                (playlist_a, note_ids_by_key[key], position),
            )

        cur = conn.execute(
            "INSERT INTO coaching_playlists (title, description, visibility, pre_roll_seconds,"
            " post_roll_seconds, created_by, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("Player #7 development",
             "Defensive recovery moments to review for the week.",
             "player", 5.0, 8.0, "coach1", now, now),
        )
        playlist_b = cur.lastrowid
        conn.execute(
            "INSERT INTO coaching_playlist_items (playlist_id, note_id, position) VALUES (?, ?, ?)",
            (playlist_b, note_ids_by_key["p7_recovery"], 0),
        )
        conn.execute(
            "INSERT INTO coaching_playlist_players (playlist_id, player_id) VALUES (?, ?)",
            (playlist_b, roster["7"]),
        )
        conn.commit()
    return 2


def _seed_player_goals(note_ids_by_key: dict[str, int], roster: dict[str, str]) -> int:
    """Phase 7 demo goals for Coach development profile + My Feedback.
    Includes one goal tied to a note and one tied to the seeded clip so the UI
    can demonstrate evidence-backed action plans and viewer reflections.
    """
    with _db.connect() as conn:
        clip = conn.execute("SELECT id FROM coaching_clips WHERE source_note_id = ?", (note_ids_by_key["p7_recovery"],)).fetchone()
    # The helper creates initial status history and hydrates reflections.
    g1 = _db.create_player_goal({
        "player_id": roster["7"],
        "title": "Scan before receiving under pressure",
        "description": "Before the ball arrives, check both shoulders and open your first touch away from pressure.",
        "priority": "high",
        "target_date": "2026-05-20",
        "success_criteria": "Check both shoulders before at least three first touches in the next match.",
        "coach_private_note": "SEED_GOAL_PRIVATE_CANARY: visible only to coaches/admins.",
        "context": "next_match",
        "status": "in_progress",
        "source_note_id": note_ids_by_key["first_touch_pressure"],
    }, actor="coach1")
    g2 = _db.create_player_goal({
        "player_id": roster["7"],
        "title": "Recover inside to protect the passing lane",
        "description": "When possession turns over, sprint inside first, then slow down to block the forward pass.",
        "priority": "medium",
        "success_criteria": "Recover goal-side within three seconds after a turnover during transition games.",
        "context": "next_training",
        "status": "open",
        "source_clip_id": int(clip["id"]) if clip else None,
    }, actor="coach1")
    g3 = _db.create_player_goal({
        "player_id": roster["14"],
        "title": "Support angle after the pass",
        "description": "Move five yards after you pass so the ball carrier has a simple return option.",
        "visibility": "coach",
        "priority": "low",
        "target_date": "",
        "success_criteria": "Coach-only planning canary: should not appear in My Feedback goal payloads.",
        "coach_private_note": "SEED_COACH_ONLY_GOAL_CANARY",
        "context": "season_goal",
        "status": "open",
    }, actor="coach1")
    with _db.connect() as conn:
        user = conn.execute("SELECT id FROM users WHERE username = ?", ("family1",)).fetchone()
    if user:
        _db.add_player_goal_reflection(g1["id"], user["id"], "I tried checking my shoulder before the first touch in training.")
    return len([g1, g2, g3])


def _seed_match_summaries(matches_by_key: dict[tuple[str, str, str], str], note_ids_by_key: dict[str, int]) -> int:
    """Phase 8 screenshot data: one team-visible summary plus one private draft.

    The viewer-facing summary links only to source ids that are also visible to
    family1/team viewers. The private draft carries a canary phrase so the E2E
    privacy check can verify it never appears in My Feedback.
    """
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    match_id = matches_by_key[MOCK_VIDEO_TARGET]
    with _db.connect() as conn:
        clip = conn.execute(
            "SELECT id FROM coaching_clips WHERE match_id = ? AND visibility IN ('team', 'unlisted') ORDER BY id LIMIT 1",
            (match_id,),
        ).fetchone()
        playlist = conn.execute(
            "SELECT id FROM coaching_playlists WHERE visibility IN ('team', 'unlisted') ORDER BY id LIMIT 1"
        ).fetchone()
        cur = conn.execute(
            "INSERT INTO coaching_match_summaries (match_id, visibility, team_positives, team_improvements, training_focus, body, created_by, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                match_id,
                "team",
                "We pressed together after goal kicks and forced play wide before they could face forward.",
                "Our weak-side winger was late tucking in twice, which opened the switch across midfield.",
                "Practice focus: back-side recovery runs, scanning before the press trigger, and first touch out of pressure.",
                "Overall this was a strong team performance: brave pressure, good recovery habits, and clear next steps for training.",
                "coach1",
                now,
                now,
            ),
        )
        summary_id = cur.lastrowid
        for position, key in enumerate(("press_trigger", "phase8_private_summary_source", "p7_recovery")):
            conn.execute(
                "INSERT INTO coaching_match_summary_notes (summary_id, note_id, position) VALUES (?, ?, ?)",
                (summary_id, note_ids_by_key[key], position),
            )
        if clip:
            conn.execute(
                "INSERT INTO coaching_match_summary_clips (summary_id, clip_id, position) VALUES (?, ?, ?)",
                (summary_id, clip["id"], 0),
            )
        if playlist:
            conn.execute(
                "INSERT INTO coaching_match_summary_playlists (summary_id, playlist_id, position) VALUES (?, ?, ?)",
                (summary_id, playlist["id"], 0),
            )

        conn.execute(
            "INSERT INTO coaching_match_summaries (match_id, visibility, team_positives, team_improvements, training_focus, body, created_by, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                match_id,
                "private",
                "PRIVATE_PHASE8_CANARY: internal staff-only positives.",
                "PRIVATE_PHASE8_CANARY: staff-only improvement notes.",
                "PRIVATE_PHASE8_CANARY: not for families.",
                "PRIVATE_PHASE8_CANARY: private draft body.",
                "coach1",
                now,
                now,
            ),
        )
        conn.commit()
    return 2


# ---------------------------------------------------------------------------
# Mock video — committed alongside the seed script so a fresh seed always has
# at least one playable match. The committed file is a 30-second 1280x720
# h.264/aac SMPTE-bars clip (~420 KB) generated with ffmpeg lavfi. We attach
# it to the first 2025 Riverside FC home match's `first_half` slot, run the
# real HLS variant ladder + match thumbnail through `media.py`, and persist
# `videos`/`video_status` directly so the surfaces that depend on a real
# playable video (player view, Coach Review video player, focused feedback
# clip player) work end-to-end.
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


def _seed_coach_note_and_clip_thumbnails(data_dir: Path) -> str:
    """Phase 3a / 4e — generate per-note + per-clip thumbnails for any
    seeded coaching note or clip whose match slot now has a real source
    MP4 on disk. The runtime equivalent runs as a background task on
    POST /api/coach/notes / /api/coach/clips, but the seed writes
    directly to SQLite and bypasses that flow — without this pass, every
    seeded note/clip card on My Feedback would render the placeholder
    tile because GET /api/coach/notes/{id}/thumbnail 404s.

    Best-effort: notes whose source video isn't on disk yet (or whose
    match was created without a mock video) are silently skipped. The
    seed never fails because a thumbnail couldn't be generated.

    Path-containment is enforced inside `_media.coach_note_thumbnail_path`
    / `_media.clip_thumbnail_path` (purely deterministic from
    match_id + note_id / match_id + clip_id), so the same `match_id`
    that produced the source MP4 is the only one we read."""
    videos_dir = data_dir / "videos"
    originals_dir = data_dir / "videos"  # un-tiered single-volume layout

    note_count = 0
    clip_count = 0
    skipped = 0

    async def _run() -> None:
        nonlocal note_count, clip_count, skipped
        with _db.connect() as conn:
            note_rows = conn.execute(
                "SELECT id, match_id, slot, timestamp_seconds, note_context "
                "FROM coaching_notes "
                "WHERE COALESCE(note_context, 'video') = 'video' "
                "  AND match_id IS NOT NULL AND slot IS NOT NULL"
            ).fetchall()
            clip_rows = conn.execute(
                "SELECT id, match_id, slot, start_seconds FROM coaching_clips"
            ).fetchall()

        for row in note_rows:
            src = _media.find_slot_raw_path(originals_dir, row["match_id"], row["slot"])
            if src is None:
                src = originals_dir / row["match_id"] / f"{row['slot']}.mp4"
            if not src.is_file():
                skipped += 1
                continue
            dest = _media.coach_note_thumbnail_path(
                videos_dir, row["match_id"], row["id"]
            )
            dest.parent.mkdir(parents=True, exist_ok=True)
            ok = await _media.generate_thumbnail_at_timestamp(
                src, dest, timestamp_s=row["timestamp_seconds"] or 0.0,
            )
            if ok:
                note_count += 1
            else:
                skipped += 1

        for row in clip_rows:
            src = _media.find_slot_raw_path(originals_dir, row["match_id"], row["slot"])
            if src is None:
                src = originals_dir / row["match_id"] / f"{row['slot']}.mp4"
            if not src.is_file():
                skipped += 1
                continue
            dest = _media.clip_thumbnail_path(
                videos_dir, row["match_id"], row["id"]
            )
            dest.parent.mkdir(parents=True, exist_ok=True)
            ok = await _media.generate_thumbnail_at_timestamp(
                src, dest, timestamp_s=row["start_seconds"] or 0.0,
            )
            if ok:
                clip_count += 1
            else:
                skipped += 1

    asyncio.run(_run())
    return f"  generated {note_count} note + {clip_count} clip thumbnails (skipped {skipped} without source video)"


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
    roster = _seed_roster()
    links = _seed_player_user_links(roster, users)
    note_ids_by_key = _seed_coaching_notes(matches_by_key, roster)
    obs_note_ids = _seed_observation_notes(matches_by_key, roster)
    clip_count = _seed_clips(matches_by_key, roster, note_ids_by_key)
    playlists = _seed_playlists(note_ids_by_key, roster)
    goals = _seed_player_goals(note_ids_by_key, roster)
    summaries = _seed_match_summaries(matches_by_key, note_ids_by_key)
    mock_video_status = _seed_mock_video(data_dir, matches_by_key)
    # Phase 3a / 4e seed parity: the runtime path (POST /api/coach/notes
    # and /api/coach/clips) spawns a background thumbnail-generation
    # task. The seed bypasses those endpoints and writes straight to
    # SQLite, so without this pass every seeded note/clip card on My
    # Feedback would render the placeholder. Run AFTER `_seed_mock_video`
    # so the source MP4 + HLS are already on disk for any note that
    # targets the mock video's match+slot.
    coach_thumb_status = _seed_coach_note_and_clip_thumbnails(data_dir)

    print()
    print("=" * 60)
    print(" Seed complete")
    print("=" * 60)
    print(f"  Matches:    {len(matches_by_key)}")
    print(f"  Roster:     {len(roster)} players")
    print(f"  Notes:      {len(note_ids_by_key)} video + {len(obs_note_ids)} observation")
    print(f"  Clips:      {clip_count}")
    print(f"  Playlists:  {playlists}")
    print(f"  Goals:      {goals}")
    print(f"  Summaries:  {summaries}")
    print(f"  Links:      {links} player ↔ user")
    print(f"  Mock video:")
    print(mock_video_status)
    print(f"  Coach thumbs:")
    print(coach_thumb_status)
    print()
    print("  Demo accounts (password: %s):" % DEMO_PASSWORD)
    print("    uploader1  — uploader        (admin → matches only)")
    print("    viewer1    — viewer          (read-only)")
    print("    coach1     — coach,uploader  (full /coach workspace)")
    print("    family1    — viewer + linked to roster #7 + #14")
    print("    family2    — viewer + linked to roster #10")
    print()
    print("  Next:  python server.py")
    print(f"         (uses REPLAY_DATA_DIR={data_dir})")
    print()


if __name__ == "__main__":
    main()
