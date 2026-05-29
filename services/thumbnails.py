"""Thumbnail path helpers."""

from __future__ import annotations

from pathlib import Path


def thumb_path_within_videos_dir(thumb: Path, videos_dir: Path) -> bool:
    """Return True only when `thumb` resolves under `videos_dir`."""
    try:
        return videos_dir.resolve() in thumb.resolve().parents
    except OSError:
        return False
