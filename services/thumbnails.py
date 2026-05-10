"""Coaching note/clip thumbnail helpers."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import log as _log
import media as _media

logger = _log.setup("replay")


def thumb_path_within_videos_dir(thumb: Path, videos_dir: Path) -> bool:
    """Return True only when `thumb` resolves under `videos_dir`."""
    try:
        return videos_dir.resolve() in thumb.resolve().parents
    except OSError:
        return False


def unique_thumbnail_candidates(paths: list[Path]) -> list[Path]:
    seen: set[Path] = set()
    unique: list[Path] = []
    for path in paths:
        try:
            key = path.resolve(strict=False)
        except OSError:
            key = path
        if key in seen:
            continue
        seen.add(key)
        unique.append(path)
    return unique


def coach_note_thumbnail_candidates(note: dict | None, note_id: int, videos_dir: Path) -> list[Path]:
    if not note or not note.get("match_id") or (note.get("note_context") or "video") != "video":
        return []
    match_id = note["match_id"]
    paths = [
        _media.coach_note_thumbnail_path(videos_dir, match_id, note_id, team_id=note.get("team_id"))
    ]
    if note.get("team_id"):
        paths.append(_media.coach_note_thumbnail_path(videos_dir, match_id, note_id))
    return unique_thumbnail_candidates(paths)


def coach_clip_thumbnail_candidates(clip: dict | None, clip_id: int, videos_dir: Path) -> list[Path]:
    if not clip or not clip.get("match_id"):
        return []
    match_id = clip["match_id"]
    paths = [
        _media.clip_thumbnail_path(videos_dir, match_id, clip_id, team_id=clip.get("team_id"))
    ]
    if clip.get("team_id"):
        paths.append(_media.clip_thumbnail_path(videos_dir, match_id, clip_id))
    return unique_thumbnail_candidates(paths)


async def spawn_coach_note_thumbnail(
    note: dict,
    *,
    videos_dir: Path,
    slot_mp4_path: Callable[[str, str], Path],
) -> None:
    """Best-effort note thumbnail generator — never raises."""
    if not note or not note.get("id") or not note.get("match_id"):
        return
    if (note.get("note_context") or "video") != "video":
        return
    note_id = int(note["id"])
    match_id = note["match_id"]
    slot = note.get("slot") or "full"
    timestamp_s = float(note.get("timestamp_seconds") or 0)
    try:
        src = slot_mp4_path(match_id, slot)
        dest = _media.coach_note_thumbnail_path(videos_dir, match_id, note_id, team_id=note.get("team_id"))
    except ValueError as exc:
        logger.warning(
            "Coach-note thumbnail spawn skipped for note %s: invalid path component (%s)",
            note_id, exc,
        )
        return
    if not thumb_path_within_videos_dir(dest, videos_dir):
        logger.warning(
            "Coach-note thumbnail spawn skipped for note %s: dest path escapes VIDEOS_DIR (%s)",
            note_id, dest,
        )
        return
    try:
        await _media.generate_thumbnail_at_timestamp(src, dest, timestamp_s=timestamp_s)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Coach-note thumbnail spawn failed for note %s: %s", note_id, exc)


async def regenerate_coach_note_thumbnail(
    note: dict,
    note_id: int,
    *,
    videos_dir: Path,
    slot_mp4_path: Callable[[str, str], Path],
) -> bool:
    try:
        src = slot_mp4_path(note["match_id"], note.get("slot") or "full")
        dest = _media.coach_note_thumbnail_path(videos_dir, note["match_id"], note_id, team_id=note.get("team_id"))
    except ValueError:
        return False
    if not thumb_path_within_videos_dir(dest, videos_dir):
        logger.warning(
            "Coach-note thumbnail regenerate skipped for note %s: dest path escapes VIDEOS_DIR (%s)",
            note_id, dest,
        )
        return False
    try:
        return await _media.generate_thumbnail_at_timestamp(
            src, dest, timestamp_s=float(note.get("timestamp_seconds") or 0)
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Coach-note thumbnail regenerate failed for note %s: %s", note_id, exc)
        return False


async def spawn_coach_clip_thumbnail(
    clip: dict,
    *,
    videos_dir: Path,
    slot_mp4_path: Callable[[str, str], Path],
) -> None:
    """Best-effort clip thumbnail generator — never raises."""
    if not clip or not clip.get("id") or not clip.get("match_id"):
        return
    clip_id = int(clip["id"])
    match_id = clip["match_id"]
    slot = clip.get("slot") or "full"
    start_s = float(clip.get("start_seconds") or 0)
    try:
        src = slot_mp4_path(match_id, slot)
        dest = _media.clip_thumbnail_path(videos_dir, match_id, clip_id, team_id=clip.get("team_id"))
    except ValueError as exc:
        logger.warning(
            "Coach-clip thumbnail spawn skipped for clip %s: invalid path component (%s)",
            clip_id, exc,
        )
        return
    if not thumb_path_within_videos_dir(dest, videos_dir):
        logger.warning(
            "Coach-clip thumbnail spawn skipped for clip %s: dest path escapes VIDEOS_DIR (%s)",
            clip_id, dest,
        )
        return
    try:
        await _media.generate_thumbnail_at_timestamp(src, dest, timestamp_s=start_s)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Coach-clip thumbnail spawn failed for clip %s: %s", clip_id, exc)


async def regenerate_coach_clip_thumbnail(
    clip: dict,
    clip_id: int,
    *,
    videos_dir: Path,
    slot_mp4_path: Callable[[str, str], Path],
) -> bool:
    try:
        src = slot_mp4_path(clip["match_id"], clip.get("slot") or "full")
        dest = _media.clip_thumbnail_path(videos_dir, clip["match_id"], clip_id, team_id=clip.get("team_id"))
    except ValueError:
        return False
    if not thumb_path_within_videos_dir(dest, videos_dir):
        logger.warning(
            "Coach-clip thumbnail regenerate skipped for clip %s: dest path escapes VIDEOS_DIR (%s)",
            clip_id, dest,
        )
        return False
    try:
        return await _media.generate_thumbnail_at_timestamp(
            src, dest, timestamp_s=float(clip.get("start_seconds") or 0)
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Coach-clip thumbnail regenerate failed for clip %s: %s", clip_id, exc)
        return False
