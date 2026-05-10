#!/usr/bin/env python3
"""Plan or perform one-shot relocation from legacy match media paths to team paths.

This script is intentionally not wired into application startup or deploys. It is
an ops helper for Phase 10 or manual per-team storage partitioning work.
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import db as _db  # noqa: E402
import media as _media  # noqa: E402


@dataclass(frozen=True)
class PlannedMove:
    source: Path
    destination: Path


_LEGACY_STATIC_ASSETS = {
    "thumb.jpg",
    "home_logo.png",
    "home_logo.jpg",
    "home_logo.jpeg",
    "home_logo.svg",
    "home_logo.webp",
    "away_logo.png",
    "away_logo.jpg",
    "away_logo.jpeg",
    "away_logo.svg",
    "away_logo.webp",
}


def _iter_legacy_children(match_root: Path) -> Iterable[Path]:
    if not match_root.is_dir():
        return []
    # Match cards/logos are still served from the legacy public URLs. Leave
    # them in place until a future PR makes those public assets tenant-aware.
    return [child for child in match_root.iterdir() if child.name != "teams" and child.name not in _LEGACY_STATIC_ASSETS]


def plan_moves(
    matches: Iterable[Mapping],
    *,
    videos_dir: Path,
    originals_dir: Path,
) -> list[PlannedMove]:
    """Return filesystem moves needed to place legacy media under team paths."""
    moves: list[PlannedMove] = []
    for match in matches:
        match_id = str(match.get("id") or "")
        team_id = match.get("team_id")
        if not match_id or not team_id:
            continue
        # Validate/sanitize through media helpers before composing destinations.
        video_team_root = _media._match_media_dir(videos_dir, match_id, str(team_id))
        originals_team_root = _media._match_media_dir(originals_dir, match_id, str(team_id))

        legacy_video_root = _media._match_media_dir(videos_dir, match_id)
        for child in _iter_legacy_children(legacy_video_root):
            moves.append(PlannedMove(child, video_team_root / child.name))

        legacy_originals_root = _media._match_media_dir(originals_dir, match_id)
        if legacy_originals_root.resolve() == legacy_video_root.resolve():
            continue
        for child in _iter_legacy_children(legacy_originals_root):
            moves.append(PlannedMove(child, originals_team_root / child.name))
    return moves


def _update_upload_session_paths(moves: Iterable[PlannedMove]) -> int:
    """Update DB rows that store absolute raw paths moved by --execute."""
    moved = {str(move.source): str(move.destination) for move in moves}
    if not moved:
        return 0
    with _db.connect() as conn:
        existing = conn.execute("SELECT id, raw_path FROM upload_sessions").fetchall()
        changed = 0
        for row in existing:
            new_path = moved.get(str(row["raw_path"]))
            if not new_path:
                continue
            conn.execute("UPDATE upload_sessions SET raw_path = ? WHERE id = ?", (new_path, row["id"]))
            changed += 1
        conn.commit()
    return changed


def apply_moves(moves: Iterable[PlannedMove], *, execute: bool) -> int:
    moves = list(moves)
    moved: list[PlannedMove] = []
    for move in moves:
        print(f"{'MOVE' if execute else 'DRY-RUN'} {move.source} -> {move.destination}")
        if not execute:
            continue
        if not move.source.exists():
            continue
        if move.destination.exists():
            raise FileExistsError(f"Destination already exists: {move.destination}")
        move.destination.parent.mkdir(parents=True, exist_ok=True)
        os.rename(move.source, move.destination)
        moved.append(move)
    return _update_upload_session_paths(moved) if execute else 0


def _load_matches_from_db() -> list[dict]:
    return [dict(row) for row in _db.load_matches_unlocked()]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="Print planned moves without touching disk")
    mode.add_argument("--execute", action="store_true", help="Perform planned moves with os.rename")
    parser.add_argument("--data-dir", type=Path, default=Path(os.getenv("REPLAY_DATA_DIR", ROOT / "data")))
    parser.add_argument("--db-file", type=Path, default=None)
    parser.add_argument("--videos-dir", type=Path, default=None)
    parser.add_argument("--originals-dir", type=Path, default=None)
    args = parser.parse_args(argv)

    data_dir = args.data_dir
    db_file = args.db_file or data_dir / "replay.db"
    videos_dir = args.videos_dir or data_dir / "videos"
    originals_dir = args.originals_dir or Path(os.getenv("REPLAY_ORIGINALS_DIR", str(videos_dir)))

    _db.init(data_dir, db_file, ROOT)
    moves = plan_moves(_load_matches_from_db(), videos_dir=videos_dir, originals_dir=originals_dir)
    moved_upload_session_paths = apply_moves(moves, execute=args.execute)
    print(f"planned_moves={len(moves)} execute={args.execute} updated_upload_session_paths={moved_upload_session_paths}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
