"""Tests for media-layer helpers (no ffmpeg required).

The actual transcode pipeline is exercised end-to-end on a host with ffmpeg
available; in CI we mock ffprobe/ffmpeg so the suite stays fast and hermetic.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

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


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------


def test_slot_mp4_path_layout(tmp_path: Path) -> None:
    p = _media.slot_mp4_path(tmp_path, "m1", "first_half")
    assert p == tmp_path / "m1" / "first_half.mp4"


def test_slot_raw_path_layout(tmp_path: Path) -> None:
    p = _media.slot_raw_path(tmp_path, "m1", "full", ".mkv")
    assert p == tmp_path / "m1" / "full_raw.mkv"


def test_find_slot_raw_path_prefers_mp4_over_mkv(tmp_path: Path) -> None:
    base = tmp_path / "m1"
    base.mkdir()
    (base / "full_raw.mp4").write_bytes(b"x")
    (base / "full_raw.mkv").write_bytes(b"x")
    found = _media.find_slot_raw_path(tmp_path, "m1", "full")
    assert found == base / "full_raw.mp4"


def test_find_slot_raw_path_falls_back_to_mkv(tmp_path: Path) -> None:
    base = tmp_path / "m1"
    base.mkdir()
    (base / "full_raw.mkv").write_bytes(b"x")
    found = _media.find_slot_raw_path(tmp_path, "m1", "full")
    assert found == base / "full_raw.mkv"


def test_find_slot_raw_path_returns_none_when_missing(tmp_path: Path) -> None:
    assert _media.find_slot_raw_path(tmp_path, "missing", "full") is None


# ---------------------------------------------------------------------------
# verify_slot_assets
# ---------------------------------------------------------------------------


def test_verify_slot_assets_reports_missing_mp4(tmp_path: Path) -> None:
    info = _media.verify_slot_assets(tmp_path, "m1", "full")
    assert info["mp4_exists"] is False
    assert info["mp4_size"] == 0
    assert info["hls_master_exists"] is False
    assert info["hls_complete"] is False
    assert info["missing_variants"] == []


def test_verify_slot_assets_detects_mp4_and_complete_hls(tmp_path: Path) -> None:
    # Untiered: originals_dir defaults to videos_dir.
    match_dir = tmp_path / "m1"
    match_dir.mkdir()
    (match_dir / "full.mp4").write_bytes(b"X" * 1024)
    hls_dir = match_dir / "hls" / "full"
    hls_dir.mkdir(parents=True)
    (hls_dir / "master.m3u8").write_text(
        "#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=1000\n720p.m3u8\n"
    )
    (hls_dir / "720p.m3u8").write_text("#EXTM3U\n")

    info = _media.verify_slot_assets(tmp_path, "m1", "full")
    assert info["mp4_exists"] is True
    assert info["mp4_size"] == 1024
    assert info["hls_master_exists"] is True
    assert info["hls_complete"] is True
    assert info["missing_variants"] == []


def test_verify_slot_assets_flags_missing_variants(tmp_path: Path) -> None:
    match_dir = tmp_path / "m1"
    match_dir.mkdir()
    (match_dir / "full.mp4").write_bytes(b"X")
    hls_dir = match_dir / "hls" / "full"
    hls_dir.mkdir(parents=True)
    # Master references two variants but only one playlist exists.
    (hls_dir / "master.m3u8").write_text(
        "#EXTM3U\n"
        "#EXT-X-STREAM-INF:BANDWIDTH=2000\n720p.m3u8\n"
        "#EXT-X-STREAM-INF:BANDWIDTH=600\n360p.m3u8\n"
    )
    (hls_dir / "720p.m3u8").write_text("#EXTM3U\n")

    info = _media.verify_slot_assets(tmp_path, "m1", "full")
    assert info["hls_master_exists"] is True
    assert info["hls_complete"] is False
    assert info["missing_variants"] == ["360p.m3u8"]


def test_verify_slot_assets_supports_tiered_originals(tmp_path: Path) -> None:
    """When originals_dir != videos_dir, MP4 lives on cold pool, HLS on SSD."""
    videos = tmp_path / "ssd"
    originals = tmp_path / "cold"
    (originals / "m1").mkdir(parents=True)
    (originals / "m1" / "full.mp4").write_bytes(b"X" * 100)
    info = _media.verify_slot_assets(videos, "m1", "full", originals_dir=originals)
    assert info["mp4_exists"] is True
    assert info["mp4_size"] == 100
    assert info["hls_master_exists"] is False


# ---------------------------------------------------------------------------
# select_hwaccel
# ---------------------------------------------------------------------------


def test_select_hwaccel_explicit_choice_is_returned(monkeypatch):
    monkeypatch.delenv("REPLAY_HWACCEL", raising=False)
    assert _media.select_hwaccel("nvenc") == "nvenc"
    assert _media.select_hwaccel("cpu") == "cpu"


def test_select_hwaccel_auto_prefers_qsv_when_render_node_exists(monkeypatch, tmp_path):
    fake_node = tmp_path / "renderD128"
    fake_node.write_bytes(b"")
    monkeypatch.setattr(_media, "VAAPI_RENDER_NODE", str(fake_node))
    assert _media.select_hwaccel("auto") == "qsv"


def test_select_hwaccel_auto_falls_back_to_nvenc_when_no_render_node(monkeypatch, tmp_path):
    monkeypatch.setattr(_media, "VAAPI_RENDER_NODE", str(tmp_path / "nope"))
    assert _media.select_hwaccel("auto") == "nvenc"


def test_select_hwaccel_unknown_value_falls_back_to_auto(monkeypatch, tmp_path):
    monkeypatch.setattr(_media, "VAAPI_RENDER_NODE", str(tmp_path / "nope"))
    assert _media.select_hwaccel("nonsense") == "nvenc"


# ---------------------------------------------------------------------------
# ffprobe parsers — mock the subprocess so no ffprobe binary is required.
# ---------------------------------------------------------------------------


class _FakeProc:
    def __init__(self, stdout: bytes, stderr: bytes = b"", returncode: int = 0):
        self._stdout = stdout
        self._stderr = stderr
        self.returncode = returncode

    async def communicate(self):
        return self._stdout, self._stderr


def _patch_subprocess(monkeypatch, proc):
    async def _create(*args, **kwargs):
        return proc
    monkeypatch.setattr(asyncio, "create_subprocess_exec", _create)


@pytest.mark.asyncio
async def test_probe_codecs_parses_streams(monkeypatch, tmp_path):
    payload = {
        "streams": [
            {"codec_type": "video", "codec_name": "h264"},
            {"codec_type": "audio", "codec_name": "aac"},
        ]
    }
    _patch_subprocess(monkeypatch, _FakeProc(json.dumps(payload).encode()))
    v, a = await _media.probe_codecs(tmp_path / "x.mp4")
    assert v == "h264"
    assert a == "aac"


@pytest.mark.asyncio
async def test_probe_codecs_returns_none_on_failure(monkeypatch, tmp_path):
    _patch_subprocess(monkeypatch, _FakeProc(b"", b"oops", returncode=1))
    v, a = await _media.probe_codecs(tmp_path / "x.mp4")
    assert (v, a) == (None, None)


@pytest.mark.asyncio
async def test_probe_codecs_handles_video_only(monkeypatch, tmp_path):
    payload = {"streams": [{"codec_type": "video", "codec_name": "hevc"}]}
    _patch_subprocess(monkeypatch, _FakeProc(json.dumps(payload).encode()))
    v, a = await _media.probe_codecs(tmp_path / "x.mp4")
    assert v == "hevc"
    assert a is None


@pytest.mark.asyncio
async def test_probe_video_dimensions_returns_first_video_stream(monkeypatch, tmp_path):
    payload = {
        "streams": [
            {"codec_type": "audio"},
            {"codec_type": "video", "width": 1920, "height": 1080},
        ]
    }
    _patch_subprocess(monkeypatch, _FakeProc(json.dumps(payload).encode()))
    w, h = await _media.probe_video_dimensions(tmp_path / "x.mp4")
    assert (w, h) == (1920, 1080)


@pytest.mark.asyncio
async def test_probe_video_dimensions_returns_none_when_no_video(monkeypatch, tmp_path):
    payload = {"streams": [{"codec_type": "audio"}]}
    _patch_subprocess(monkeypatch, _FakeProc(json.dumps(payload).encode()))
    w, h = await _media.probe_video_dimensions(tmp_path / "x.mp4")
    assert (w, h) == (None, None)


@pytest.mark.asyncio
async def test_probe_duration_parses_format(monkeypatch, tmp_path):
    payload = {"format": {"duration": "123.456"}}
    _patch_subprocess(monkeypatch, _FakeProc(json.dumps(payload).encode()))
    d = await _media.probe_duration(tmp_path / "x.mp4")
    assert d == pytest.approx(123.456)


@pytest.mark.asyncio
async def test_probe_duration_returns_none_on_missing_field(monkeypatch, tmp_path):
    _patch_subprocess(monkeypatch, _FakeProc(b'{"format": {}}'))
    assert await _media.probe_duration(tmp_path / "x.mp4") is None


# ---------------------------------------------------------------------------
# Transcode history
# ---------------------------------------------------------------------------


def test_record_transcode_history_computes_rt_factor():
    _media._transcode_history.clear()
    _media.record_transcode_history(
        match_id="m1", slot="full", hwaccel="qsv",
        source_seconds=100.0, wall_seconds=25.0, variant_count=3,
    )
    history = _media.get_transcode_history()
    assert history[-1]["rt_factor"] == 0.25
    assert history[-1]["variant_count"] == 3
    assert history[-1]["hwaccel"] == "qsv"


def test_record_transcode_history_rt_factor_none_when_source_unknown():
    _media._transcode_history.clear()
    _media.record_transcode_history(
        match_id="m1", slot="full", hwaccel="cpu",
        source_seconds=None, wall_seconds=10.0,
    )
    assert _media.get_transcode_history()[-1]["rt_factor"] is None
