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

import db as _db
import auth as _auth


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
    if rows:
        print(
            f"\nABORT: The matches table at this data dir contains {len(rows)} match(es) "
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

    # (match_id, slot, ts, title, body, category, visibility, drawing, linked_player_jerseys, tags)
    spec = [
        (m1, "first_half",  312.5,
         "Pressing trigger on goal-kick",
         "When their #1 plants the ball, our front three step up together. Watch the angle "
         "the wide forward takes — body shape forces the keeper to go long.",
         "pressing", "team",
         _drawing_arrow_zone(),
         [], ["pressing", "shape"]),

        (m1, "second_half", 1820.0,
         "Back-four shape during Northgate spell",
         "The line stayed compact for ten minutes here. Notice how the holding mid drops in "
         "to make a five when Northgate worked the wide channel.",
         "shape", "team",
         _drawing_back_four_formation(roster),
         ["3", "4", "5", "2", "6"], ["shape", "defending"]),

        (m2, "full",         642.0,
         "First-touch under pressure",
         "Receive across the body, open the hips, and you're already facing forward. "
         "Compare this clip with the turnover at 14:30.",
         "build_up", "team",
         _drawing_circle_label(),
         [], ["technique"]),

        (m2, "full",        1430.0,
         "Player #7 — defensive recovery",
         "Strong recovery run from the far side. Track the angle: cut across the passing "
         "lane, don't chase the ball.",
         "defending", "player",
         _drawing_freehand_arrow(),
         ["7"], ["recovery", "1v1"]),

        (m3, "first_half",   215.0,
         "Player #10 — early run",
         "Read the trigger off the keeper and break early. Spotlight is the gap you should "
         "be attacking before the centre-back closes.",
         "transition", "player",
         _drawing_spotlight_dim(),
         ["10"], ["transition"]),

        (m3, "second_half", 1100.0,
         "Internal: substitution rationale",
         "Coaching note only — context for the staff. Subbing for energy in the press, not "
         "punishing the player.",
         "other", "private",
         {"version": 2, "objects": []},
         [], []),
    ]

    note_ids: list[int] = []
    with _db.connect() as conn:
        for match_id, slot, ts, title, body, category, visibility, drawing, jerseys, tags in spec:
            cur = conn.execute(
                """
                INSERT INTO coaching_notes (
                    match_id, slot, timestamp_seconds, title, body, category, visibility,
                    drawing_json, created_by, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (match_id, slot, ts, title, body, category, visibility,
                 json.dumps(drawing), "coach1", now, now),
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

    print()
    print("=" * 60)
    print(" Seed complete")
    print("=" * 60)
    print(f"  Matches:    {len(matches_by_key)}")
    print(f"  Roster:     {len(roster)} players")
    print(f"  Notes:      {len(note_ids)}")
    print(f"  Playlists:  {playlists}")
    print(f"  Links:      {links} player ↔ user")
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
