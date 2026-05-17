"""Tests for media-layer helpers (no ffmpeg required).

The actual transcode pipeline is exercised end-to-end on a host with ffmpeg
available; in CI we mock ffprobe/ffmpeg so the suite stays fast and hermetic.
"""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path

import pytest

import media as _media
import db as _db
import uploads as _uploads
from scripts import relocate_to_team_paths


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

    team_match = videos / "teams" / "team-1" / "matches" / "match-d"
    (team_match / "hls" / "full").mkdir(parents=True)         # live, keep
    (team_match / "hls" / "full.tmp").mkdir()                 # orphan, drop

    # A match dir without an hls/ subdir shouldn't blow up the sweeper.
    (videos / "match-c").mkdir()

    removed = _media.cleanup_hls_staging_dirs(videos)
    assert removed == 4

    # Live dirs survived
    assert (match_a / "hls" / "full").is_dir()
    assert (match_a / "hls" / "full" / "master.m3u8").is_file()
    assert (match_b / "hls" / "first_half").is_dir()
    assert (team_match / "hls" / "full").is_dir()

    # Orphans gone
    assert not (match_a / "hls" / "full.tmp").exists()
    assert not (match_a / "hls" / "full.old").exists()
    assert not (match_b / "hls" / "second_half.tmp").exists()
    assert not (team_match / "hls" / "full.tmp").exists()


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


def test_slot_mp4_path_writes_team_aware_when_team_id_present(tmp_path: Path) -> None:
    p = _media.slot_mp4_path(tmp_path, "m1", "first_half", team_id="team-1")
    assert p == tmp_path / "teams" / "team-1" / "matches" / "m1" / "first_half.mp4"


def test_slot_hls_paths_write_team_aware_when_team_id_present(tmp_path: Path) -> None:
    hls_dir = _media.slot_hls_dir(tmp_path, "m1", "full", team_id="team-1")
    assert hls_dir == tmp_path / "teams" / "team-1" / "matches" / "m1" / "hls" / "full"
    assert _media.slot_hls_master_path(tmp_path, "m1", "full", team_id="team-1") == hls_dir / "master.m3u8"


def test_thumbnail_paths_write_team_aware_when_team_id_present(tmp_path: Path) -> None:
    assert _media.coach_note_thumbnail_path(tmp_path, "m1", 42, team_id="team-1") == (
        tmp_path / "teams" / "team-1" / "matches" / "m1" / "coach_thumbs" / "42.jpg"
    )
    assert _media.clip_thumbnail_path(tmp_path, "m1", 7, team_id="team-1") == (
        tmp_path / "teams" / "team-1" / "matches" / "m1" / "clip_thumbs" / "7.jpg"
    )


def test_slot_raw_path_layout(tmp_path: Path) -> None:
    p = _media.slot_raw_path(tmp_path, "m1", "full", ".mkv")
    assert p == tmp_path / "m1" / "full_raw.mkv"


def test_slot_raw_path_writes_team_aware_when_team_id_present(tmp_path: Path) -> None:
    p = _media.slot_raw_path(tmp_path, "m1", "full", ".mkv", team_id="team-1")
    assert p == tmp_path / "teams" / "team-1" / "matches" / "m1" / "full_raw.mkv"


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


def test_find_slot_raw_path_prefers_team_aware_then_legacy(tmp_path: Path) -> None:
    legacy = tmp_path / "m1"
    legacy.mkdir(parents=True)
    (legacy / "full_raw.mp4").write_bytes(b"legacy")
    assert _media.find_slot_raw_path(tmp_path, "m1", "full", team_id="team-1") == legacy / "full_raw.mp4"

    team_dir = tmp_path / "teams" / "team-1" / "matches" / "m1"
    team_dir.mkdir(parents=True)
    (team_dir / "full_raw.mp4").write_bytes(b"team")
    assert _media.find_slot_raw_path(tmp_path, "m1", "full", team_id="team-1") == team_dir / "full_raw.mp4"


def test_existing_slot_path_falls_back_to_legacy_until_team_path_exists(tmp_path: Path) -> None:
    legacy_master = tmp_path / "m1" / "hls" / "full" / "master.m3u8"
    legacy_master.parent.mkdir(parents=True)
    legacy_master.write_text("#EXTM3U\n")
    assert _media.existing_slot_hls_master_path(tmp_path, "m1", "full", team_id="team-1") == legacy_master

    team_master = tmp_path / "teams" / "team-1" / "matches" / "m1" / "hls" / "full" / "master.m3u8"
    team_master.parent.mkdir(parents=True)
    team_master.write_text("#EXTM3U\n")
    assert _media.existing_slot_hls_master_path(tmp_path, "m1", "full", team_id="team-1") == team_master


def test_path_containment_rejects_traversal_for_team_and_match_ids(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        _media.slot_hls_dir(tmp_path, "../m1", "full", team_id="team-1")
    with pytest.raises(ValueError):
        _media.slot_hls_dir(tmp_path, "m1", "full", team_id="../team")
    with pytest.raises(ValueError):
        _media.slot_raw_path(tmp_path, "/abs", "full", ".mp4", team_id="team-1")


def test_caddy_hls_regexes_match_legacy_and_team_aware_shapes_without_cross_fallback() -> None:
    assets = {
        "ts": ["seg.ts", "720p/segment_000.ts"],
        "mp4": ["seg.m4s", "720p/segment_000.m4s"],
        "pl": ["master.m3u8", "720p/index.m3u8"],
    }
    for config_path in (Path("Caddyfile"), Path("docker-compose-intel.yml")):
        text = config_path.read_text()
        assert "try_files /videos/teams" not in text
        assert text.count("reverse_proxy replay:8091") >= 4
        for suffix, suffix_assets in assets.items():
            patterns = [
                re.compile(pattern)
                for name, pattern in re.findall(r"path_regexp (vod_hls(?:_team)?_\w+) (\^.*\$)", text)
                if name.endswith(suffix)
            ]
            for asset in suffix_assets:
                assert any(p.match(f"/api/matches/m1/hls/full/{asset}") for p in patterns)
                assert any(p.match(f"/api/matches/m1/hls/teams/team-1/full/{asset}") for p in patterns)
                assert not any(p.match(f"/api/matches/m1/hls/teams/../full/{asset}") for p in patterns)
                assert not any(p.match(f"/api/matches/m1/hls/teams/team-1/full/../{asset}") for p in patterns)


@pytest.mark.asyncio
async def test_hls_routes_support_legacy_and_team_aware_urls_and_reject_wrong_team(client, auth_headers, data_dir) -> None:
    import db as _db

    resp = await client.post(
        "/api/matches",
        json={"home_team": "A", "away_team": "B"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    match_id = resp.json()["id"]
    match = _db.get_match_by_id(match_id)
    assert match and match.get("team_id")
    team_id = str(match["team_id"])
    match.setdefault("video_status", {})["full"] = "ready"
    _db.save_matches_unlocked([match])

    legacy_dir = data_dir / "videos" / match_id / "hls" / "full"
    legacy_dir.mkdir(parents=True)
    (legacy_dir / "master.m3u8").write_text("#EXTM3U\n")
    (legacy_dir / "720p").mkdir()
    (legacy_dir / "720p" / "index.m3u8").write_text("#EXTM3U\n")
    (legacy_dir / "720p" / "seg.ts").write_bytes(b"legacy")

    legacy_master = await client.get(f"/api/matches/{match_id}/hls/full/master.m3u8")
    assert legacy_master.status_code == 200
    legacy_variant = await client.get(f"/api/matches/{match_id}/hls/full/720p/index.m3u8")
    assert legacy_variant.status_code == 200
    legacy_segment = await client.get(f"/api/matches/{match_id}/hls/full/720p/seg.ts")
    assert legacy_segment.status_code == 200
    assert legacy_segment.content == b"legacy"

    team_dir = data_dir / "videos" / "teams" / team_id / "matches" / match_id / "hls" / "full"
    team_dir.mkdir(parents=True)
    (team_dir / "master.m3u8").write_text("#EXTM3U\n")
    (team_dir / "720p").mkdir()
    (team_dir / "720p" / "index.m3u8").write_text("#EXTM3U\n")
    (team_dir / "720p" / "seg.ts").write_bytes(b"team")

    team_master = await client.get(f"/api/matches/{match_id}/hls/teams/{team_id}/full/master.m3u8")
    assert team_master.status_code == 200
    assert team_master.headers["access-control-allow-origin"] == "*"
    team_variant = await client.get(f"/api/matches/{match_id}/hls/teams/{team_id}/full/720p/index.m3u8")
    assert team_variant.status_code == 200
    assert team_variant.headers["access-control-allow-origin"] == "*"
    team_segment = await client.get(f"/api/matches/{match_id}/hls/teams/{team_id}/full/720p/seg.ts")
    assert team_segment.status_code == 200
    assert team_segment.headers["access-control-allow-origin"] == "*"
    assert team_segment.content == b"team"

    wrong_team_master = await client.get(f"/api/matches/{match_id}/hls/teams/not-{team_id}/full/master.m3u8")
    assert wrong_team_master.status_code == 404
    traversal = await client.get(f"/api/matches/{match_id}/hls/teams/{team_id}/full/../seg.ts")
    assert traversal.status_code in {400, 404}


@pytest.mark.asyncio
async def test_direct_upload_stages_raw_and_final_destination_under_team_path(client, auth_headers, data_dir, monkeypatch) -> None:
    import db as _db
    import server

    spawned: list[tuple[Path, Path]] = []
    monkeypatch.setattr(server, "_spawn_transcode", lambda _mid, _slot, src, dest: spawned.append((src, dest)))

    resp = await client.post(
        "/api/matches",
        json={"home_team": "A", "away_team": "B"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    match_id = resp.json()["id"]
    team_id = _db.get_match_by_id(match_id)["team_id"]

    upload = await client.post(
        f"/api/matches/{match_id}/upload-video?slot=full",
        headers=auth_headers,
        files={"file": ("video.mp4", b"fake-mp4", "video/mp4")},
    )
    assert upload.status_code == 200
    assert spawned
    raw_path, final_path = spawned[0]
    team_match_dir = data_dir / "videos" / "teams" / team_id / "matches" / match_id
    assert raw_path == team_match_dir / "full_raw.mp4"
    assert final_path == team_match_dir / "full.mp4"
    assert raw_path.read_bytes() == b"fake-mp4"


@pytest.mark.asyncio
async def test_chunked_upload_session_uses_team_path_for_raw_and_final_destination(client, auth_headers, data_dir, monkeypatch) -> None:
    import db as _db
    import server

    spawned: list[tuple[Path, Path]] = []
    monkeypatch.setattr(server, "_spawn_transcode", lambda _mid, _slot, src, dest: spawned.append((src, dest)))

    resp = await client.post(
        "/api/matches",
        json={"home_team": "A", "away_team": "B"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    match_id = resp.json()["id"]
    team_id = _db.get_match_by_id(match_id)["team_id"]
    body = b"chunked-mp4"

    session = await client.post(
        f"/api/matches/{match_id}/upload-video/session?slot=full",
        json={"filename": "video.mp4", "size_bytes": len(body)},
        headers=auth_headers,
    )
    assert session.status_code == 200
    session_id = session.json()["session_id"]
    put = await client.put(
        f"/api/uploads/sessions/{session_id}/chunk?index=0",
        content=body,
        headers=auth_headers,
    )
    assert put.status_code == 200
    complete = await client.post(f"/api/uploads/sessions/{session_id}/complete", headers=auth_headers)
    assert complete.status_code == 200
    assert spawned
    raw_path, final_path = spawned[0]
    team_match_dir = data_dir / "videos" / "teams" / team_id / "matches" / match_id
    assert raw_path == team_match_dir / "full_raw.mp4"
    assert final_path == team_match_dir / "full.mp4"
    assert raw_path.read_bytes() == body


def test_thumbnail_cleanup_candidates_include_team_and_legacy_paths(data_dir, monkeypatch) -> None:
    import server

    monkeypatch.setattr(server, "VIDEOS_DIR", data_dir / "videos")
    note = {"match_id": "m1", "team_id": "team-1", "note_context": "video"}
    clip = {"match_id": "m1", "team_id": "team-1"}

    note_paths = server._coach_note_thumbnail_candidates(note, 42)
    assert note_paths == [
        data_dir / "videos" / "teams" / "team-1" / "matches" / "m1" / "coach_thumbs" / "42.jpg",
        data_dir / "videos" / "m1" / "coach_thumbs" / "42.jpg",
    ]
    clip_paths = server._coach_clip_thumbnail_candidates(clip, 7)
    assert clip_paths == [
        data_dir / "videos" / "teams" / "team-1" / "matches" / "m1" / "clip_thumbs" / "7.jpg",
        data_dir / "videos" / "m1" / "clip_thumbs" / "7.jpg",
    ]


def test_cleanup_orphaned_raw_files_scans_team_aware_layout(data_dir) -> None:
    videos = data_dir / "videos"
    originals = data_dir / "originals"
    legacy_raw = originals / "m1" / "full_raw.mp4"
    team_raw = originals / "teams" / "team-1" / "matches" / "m2" / "second_half_raw.mkv"
    non_raw = originals / "teams" / "team-1" / "matches" / "m2" / "full.mp4"
    legacy_raw.parent.mkdir(parents=True)
    team_raw.parent.mkdir(parents=True)
    legacy_raw.write_bytes(b"legacy")
    team_raw.write_bytes(b"team")
    non_raw.write_bytes(b"final")

    removed = _uploads.cleanup_orphaned_raw_files(videos, originals)

    assert str(legacy_raw) in removed
    assert str(team_raw) in removed
    assert not legacy_raw.exists()
    assert not team_raw.exists()
    assert non_raw.exists()


def test_relocation_dry_run_reports_moves_without_touching_disk(tmp_path: Path) -> None:
    videos = tmp_path / "videos"
    originals = tmp_path / "originals"
    (videos / "m1" / "hls" / "full").mkdir(parents=True)
    (videos / "m1" / "hls" / "full" / "master.m3u8").write_text("#EXTM3U\n")
    (videos / "m1" / "coach_thumbs").mkdir(parents=True)
    (videos / "m1" / "coach_thumbs" / "42.jpg").write_bytes(b"jpg")
    (videos / "m1" / "thumb.jpg").write_bytes(b"public-thumb")
    (videos / "m1" / "home_logo.png").write_bytes(b"logo")
    (originals / "m1").mkdir(parents=True)
    (originals / "m1" / "full.mp4").write_bytes(b"mp4")

    moves = relocate_to_team_paths.plan_moves(
        [{"id": "m1", "team_id": "team-1"}],
        videos_dir=videos,
        originals_dir=originals,
    )
    assert moves
    assert any(move.source == videos / "m1" / "hls" for move in moves)
    assert any(move.source == videos / "m1" / "coach_thumbs" for move in moves)
    assert any(move.source == originals / "m1" / "full.mp4" for move in moves)
    assert all(move.source.name not in {"thumb.jpg", "home_logo.png"} for move in moves)

    relocate_to_team_paths.apply_moves(moves, execute=False)
    assert (videos / "m1" / "hls" / "full" / "master.m3u8").is_file()
    assert not (videos / "teams" / "team-1" / "matches" / "m1" / "hls").exists()


def test_relocation_execute_updates_upload_session_raw_paths(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    videos = data_dir / "videos"
    originals = data_dir / "originals"
    db_file = data_dir / "replay.db"
    raw = originals / "m1" / "full_raw.mp4"
    raw.parent.mkdir(parents=True)
    raw.write_bytes(b"raw")
    _db.close_thread_connection()
    _db.init(data_dir, db_file, Path(__file__).resolve().parents[1])
    team_id = _db.get_default_team()["id"]
    season_id = _db.get_default_season(team_id)["id"]
    with _db.connect() as conn:
        _db.upsert_match(
            conn,
            {
                "id": "m1",
                "team_id": team_id,
                "season_id": season_id,
                "home_team": "Home",
                "away_team": "Away",
                "date": "2026-01-02",
                "location": "Field",
                "videos": {},
                "video_status": {},
            },
        )
        conn.execute(
            """
            INSERT INTO upload_sessions
                (id, match_id, slot, ext, raw_path, size_bytes, chunk_size, total_chunks, next_index, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("sess-1", "m1", "full", ".mp4", str(raw), 3, 3, 1, 1, "completed", 1, 1),
        )
        conn.commit()

    moves = relocate_to_team_paths.plan_moves(_db.load_matches_unlocked(), videos_dir=videos, originals_dir=originals)
    changed = relocate_to_team_paths.apply_moves(moves, execute=True)

    dest = originals / "teams" / team_id / "matches" / "m1" / "full_raw.mp4"
    assert changed == 1
    assert dest.read_bytes() == b"raw"
    assert not raw.exists()
    with _db.connect() as conn:
        row = conn.execute("SELECT raw_path FROM upload_sessions WHERE id = ?", ("sess-1",)).fetchone()
    assert row["raw_path"] == str(dest)


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
