"""Tests for media-layer helpers (no ffmpeg required)."""

from __future__ import annotations

from pathlib import Path

import media as _media


def test_cleanup_hls_staging_dirs_removes_tmp_and_old(tmp_path: Path) -> None:
    """build_hls_assets stages into <slot>.tmp and renames the existing
    <slot> aside as <slot>.old during the swap. cleanup_hls_staging_dirs
    is the lifespan-time sweeper that drops both kinds of staging dir
    when a previous container died mid-swap."""
    videos = tmp_path / "videos"

    match_a = videos / "match-a"
    (match_a / "hls" / "full").mkdir(parents=True)            # live, keep
    (match_a / "hls" / "full" / "master.m3u8").write_text("")
    (match_a / "hls" / "full.tmp").mkdir()                    # orphan, drop
    (match_a / "hls" / "full.old").mkdir()                    # orphan, drop

    match_b = videos / "match-b"
    (match_b / "hls" / "first_half").mkdir(parents=True)      # live, keep
    (match_b / "hls" / "second_half.tmp").mkdir(parents=True) # orphan, drop

    # A match dir without an hls/ subdir shouldn't blow up the sweeper.
    (videos / "match-c").mkdir()

    removed = _media.cleanup_hls_staging_dirs(videos)
    assert removed == 3

    # Live dirs survived
    assert (match_a / "hls" / "full").is_dir()
    assert (match_a / "hls" / "full" / "master.m3u8").is_file()
    assert (match_b / "hls" / "first_half").is_dir()

    # Orphans gone
    assert not (match_a / "hls" / "full.tmp").exists()
    assert not (match_a / "hls" / "full.old").exists()
    assert not (match_b / "hls" / "second_half.tmp").exists()


def test_cleanup_hls_staging_dirs_handles_missing_videos_dir(tmp_path: Path) -> None:
    """No videos directory at all → no error, returns 0."""
    assert _media.cleanup_hls_staging_dirs(tmp_path / "does-not-exist") == 0


def test_cleanup_hls_staging_dirs_idempotent(tmp_path: Path) -> None:
    """Running the sweeper twice in a row leaves the second pass a no-op."""
    videos = tmp_path / "videos"
    (videos / "match-x" / "hls" / "full.tmp").mkdir(parents=True)

    assert _media.cleanup_hls_staging_dirs(videos) == 1
    assert _media.cleanup_hls_staging_dirs(videos) == 0
