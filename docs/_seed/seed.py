"""Idempotent seed script for documentation screenshots.

Inserts ~12 placeholder matches and 2 demo users (uploader1, viewer1) directly
into the SQLite database via the project's own ``db`` and ``auth`` helpers.
No HTTP / no running server required.

Safety: aborts if the target ``matches`` table already contains rows with
non-empty ``videos_json`` (i.e. real uploaded videos). This is a guard against
running the script against the user's real ``~/replay-data`` archive.

Usage:

    export REPLAY_DATA_DIR=/tmp/replay-docs-data
    python docs/_seed/seed.py
"""

from __future__ import annotations

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


def _seed_matches(data_dir: Path, logos: dict[str, Path]) -> int:
    videos_dir = data_dir / "videos"
    videos_dir.mkdir(parents=True, exist_ok=True)

    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    count = 0
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
            count += 1
        conn.commit()
    return count


def _seed_users() -> list[str]:
    created: list[str] = []
    with _db.connect() as conn:
        placeholders = ",".join("?" for _ in SEEDED_USERS)
        conn.execute(f"DELETE FROM users WHERE username IN ({placeholders})", SEEDED_USERS)
        conn.commit()

    pwd_hash = _auth.hash_password(DEMO_PASSWORD)
    _db.create_user("uploader1", pwd_hash, "uploader", display_name="Uploader Demo")
    created.append("uploader1")
    _db.create_user("viewer1", pwd_hash, "viewer", display_name="Viewer Demo")
    created.append("viewer1")
    return created


def main() -> None:
    data_dir = _resolve_data_dir()
    db_file = data_dir / "replay.db"
    app_assets_dir = data_dir / "app_assets"

    print(f"[seed] data dir: {data_dir}")
    _db.init(data_dir, db_file, app_assets_dir)

    teams = _all_teams()
    logos = _ensure_logo_files(teams)
    print(f"[seed] generated {len(logos)} placeholder team logos in {LOGO_DIR}")

    matches_count = _seed_matches(data_dir, logos)
    users = _seed_users()

    print()
    print("=" * 60)
    print(" Seed complete")
    print("=" * 60)
    print(f"  Matches:  {matches_count}")
    print(f"  Users:    {', '.join(users)}  (password: {DEMO_PASSWORD})")
    print()
    print("  Next:  python server.py")
    print(f"         (uses REPLAY_DATA_DIR={data_dir})")
    print()


if __name__ == "__main__":
    main()
