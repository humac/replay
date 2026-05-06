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
        conn.execute("DELETE FROM coaching_reviews")
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
def _seed_coaching_notes(matches: dict[tuple[str, str, str], str], roster: dict[str, str]) -> list[int]:
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    m1 = matches[("Riverside FC", "Northgate United", "2025-09-14")]
    m2 = matches[("Riverside FC", "Highbridge Town",  "2025-09-28")]
    m3 = matches[("Riverside FC", "Pinehurst Rangers","2025-11-02")]

    # (match_id, slot, ts, title, body, category, visibility, drawing,
    #  linked_player_jerseys, tags, note_type, player_summary,
    #  what_happened, why_it_matters, what_to_do_next, coach_private_note)
    #
    # Phase 1 structured fields are optional — empty strings render the
    # legacy `body`-only path, populated values render the full
    # tone-pill + summary + structured <dl> stack in My Feedback.
    spec = [
        (m1, "first_half",  312.5,
         "Pressing trigger on goal-kick",
         "When their #1 plants the ball, our front three step up together. Watch the angle "
         "the wide forward takes — body shape forces the keeper to go long.",
         "pressing", "team",
         _drawing_arrow_zone(),
         [], ["pressing", "shape"],
         "team_concept",
         "When their keeper plants the ball, step up together — angle the press so the keeper has to go long.",
         "Their goal kick at 5:12. Our front three drifted apart, the keeper had a free short pass to the centre-back, and we lost ten yards of pressure.",
         "If we time the trigger together we force long balls into our centre-backs' headers — that's a 70% recovery rate for us.",
         "Watch your wide partner's first step. When they go, you go. Body shape closes the inside lane, not the keeper directly.",
         "Coach note: drilled this on Tuesday with the front three only — second unit still drifting late."),

        (m1, "second_half", 1820.0,
         "Back-four shape during Northgate spell",
         "The line stayed compact for ten minutes here. Notice how the holding mid drops in "
         "to make a five when Northgate worked the wide channel.",
         "shape", "team",
         _drawing_back_four_formation(roster),
         ["3", "4", "5", "2", "6"], ["shape", "defending"],
         "positive",
         "Best ten-minute defensive spell of the half — line stayed compact and the #6 dropped to make a five in the wide channel.",
         "",
         "",
         "",
         ""),

        (m2, "full",         642.0,
         "First-touch under pressure",
         "Receive across the body, open the hips, and you're already facing forward. "
         "Compare this clip with the turnover at 14:30.",
         "build_up", "team",
         _drawing_circle_label(),
         [], ["technique"],
         "individual_goal",
         "Receive across your body — open hips, take the touch into space, and you're facing forward already.",
         "Ball came from the keeper. You took it facing your own goal, had to turn under pressure, and lost it.",
         "One extra touch backwards is one extra second for their press to set. Open the body once and you skip that whole sequence.",
         "On reception: plant the back foot, point the front foot toward the opponent's goal, take the touch with your far foot.",
         ""),

        (m2, "full",        1430.0,
         "Player #7 — defensive recovery",
         "Strong recovery run from the far side. Track the angle: cut across the passing "
         "lane, don't chase the ball.",
         "defending", "player",
         _drawing_freehand_arrow(),
         ["7"], ["recovery", "1v1"],
         "positive",
         "Beautiful recovery run — you cut across the passing lane instead of chasing the ball. That's the model.",
         "",
         "",
         "",
         ""),

        (m3, "first_half",   215.0,
         "Player #10 — early run",
         "Read the trigger off the keeper and break early. Spotlight is the gap you should "
         "be attacking before the centre-back closes.",
         "transition", "player",
         _drawing_spotlight_dim(),
         ["10"], ["transition"],
         "correction",
         "Break earlier on the keeper's release — attack the gap before the centre-back can close it.",
         "Keeper rolled it out at 3:35. You started moving 1.5 seconds late and the gap had already shut.",
         "If you read the trigger off the keeper's body shape (not the ball), you get a 5–8 yard head start on the centre-back. That's the difference between a chance and a recycle.",
         "Two cues: (1) keeper's plant foot turns sideways → release is coming, (2) centre-back's eyes go to the ball → blind side opens. Move on cue 1, finish on cue 2.",
         "Coach note: pulled #10 at 18' for a debrief on this; he saw it. Repeat in next session's possession game."),

        (m3, "second_half", 1100.0,
         "Internal: substitution rationale",
         "Coaching note only — context for the staff. Subbing for energy in the press, not "
         "punishing the player.",
         "other", "private",
         {"version": 2, "objects": []},
         [], [],
         "correction",
         "",
         "",
         "",
         "",
         "Sub at 65' was for energy in the press, NOT punishment. Make sure the player hears that on Tuesday — last time we left it ambiguous and his confidence dropped for a week."),
    ]

    note_ids: list[int] = []
    with _db.connect() as conn:
        for (match_id, slot, ts, title, body, category, visibility, drawing,
             jerseys, tags, note_type, player_summary, what_happened,
             why_it_matters, what_to_do_next, coach_private_note) in spec:
            cur = conn.execute(
                """
                INSERT INTO coaching_notes (
                    match_id, slot, timestamp_seconds, title, body, category, visibility,
                    drawing_json, created_by, created_at, updated_at,
                    note_type, player_summary, what_happened, why_it_matters,
                    what_to_do_next, coach_private_note
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (match_id, slot, ts, title, body, category, visibility,
                 json.dumps(drawing), "coach1", now, now,
                 note_type, player_summary, what_happened, why_it_matters,
                 what_to_do_next, coach_private_note),
            )
            note_id = cur.lastrowid
            note_ids.append(note_id)
            for jersey in jerseys:
                conn.execute(
                    "INSERT INTO coaching_note_players (note_id, player_id) VALUES (?, ?)",
                    (note_id, roster[jersey]),
                )
            for tag in tags:
                conn.execute(
                    "INSERT INTO coaching_note_tags (note_id, tag) VALUES (?, ?)",
                    (note_id, tag),
                )
        conn.commit()
    return note_ids


def _seed_playlists(note_ids: list[int], roster: dict[str, str]) -> int:
    """Two playlists. A is team-visible (notes 1+3); B is player-visible and
    scoped to player #7 via coaching_playlist_players."""
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    note1, _note2, note3, note4, _note5, _note6 = note_ids
    with _db.connect() as conn:
        cur = conn.execute(
            "INSERT INTO coaching_playlists (title, description, visibility, pre_roll_seconds,"
            " post_roll_seconds, created_by, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("First-half tactical lessons",
             "Two clips on pressing triggers and first-touch in the build-up.",
             "team", 5.0, 8.0, "coach1", now, now),
        )
        playlist_a = cur.lastrowid
        for position, nid in enumerate((note1, note3)):
            conn.execute(
                "INSERT INTO coaching_playlist_items (playlist_id, note_id, position) VALUES (?, ?, ?)",
                (playlist_a, nid, position),
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
            (playlist_b, note4, 0),
        )
        conn.execute(
            "INSERT INTO coaching_playlist_players (playlist_id, player_id) VALUES (?, ?)",
            (playlist_b, roster["7"]),
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
    note_ids = _seed_coaching_notes(matches_by_key, roster)
    playlists = _seed_playlists(note_ids, roster)
    mock_video_status = _seed_mock_video(data_dir, matches_by_key)

    print()
    print("=" * 60)
    print(" Seed complete")
    print("=" * 60)
    print(f"  Matches:    {len(matches_by_key)}")
    print(f"  Roster:     {len(roster)} players")
    print(f"  Notes:      {len(note_ids)}")
    print(f"  Playlists:  {playlists}")
    print(f"  Links:      {links} player ↔ user")
    print(f"  Mock video:")
    print(mock_video_status)
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
