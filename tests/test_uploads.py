"""Tests for upload session lifecycle."""

from __future__ import annotations

import pytest


pytestmark = pytest.mark.asyncio


async def _create_match(client, auth_headers):
    resp = await client.post(
        "/api/matches",
        json={"home_team": "A", "away_team": "B"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    return resp.json()["id"]


async def test_create_upload_session(client, auth_headers):
    match_id = await _create_match(client, auth_headers)
    resp = await client.post(
        f"/api/matches/{match_id}/upload-video/session?slot=full",
        json={"filename": "game.mp4", "size_bytes": 1024 * 1024},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "session_id" in data
    assert data["total_chunks"] >= 1
    assert data["next_index"] == 0


async def test_create_upload_session_requires_auth(client, auth_headers):
    match_id = await _create_match(client, auth_headers)
    resp = await client.post(
        f"/api/matches/{match_id}/upload-video/session?slot=full",
        json={"filename": "game.mp4", "size_bytes": 1024},
    )
    assert resp.status_code == 401


async def test_create_upload_session_bad_extension(client, auth_headers):
    match_id = await _create_match(client, auth_headers)
    resp = await client.post(
        f"/api/matches/{match_id}/upload-video/session?slot=full",
        json={"filename": "game.avi", "size_bytes": 1024},
        headers=auth_headers,
    )
    assert resp.status_code == 400


async def test_create_upload_session_bad_slot(client, auth_headers):
    match_id = await _create_match(client, auth_headers)
    resp = await client.post(
        f"/api/matches/{match_id}/upload-video/session?slot=invalid",
        json={"filename": "game.mp4", "size_bytes": 1024},
        headers=auth_headers,
    )
    assert resp.status_code == 400


async def test_create_upload_session_zero_size(client, auth_headers):
    match_id = await _create_match(client, auth_headers)
    resp = await client.post(
        f"/api/matches/{match_id}/upload-video/session?slot=full",
        json={"filename": "game.mp4", "size_bytes": 0},
        headers=auth_headers,
    )
    assert resp.status_code == 422  # Pydantic rejects gt=0


async def test_create_upload_session_match_not_found(client, auth_headers):
    resp = await client.post(
        "/api/matches/nonexistent/upload-video/session?slot=full",
        json={"filename": "game.mp4", "size_bytes": 1024},
        headers=auth_headers,
    )
    assert resp.status_code == 404


async def test_create_upload_session_mkv(client, auth_headers):
    match_id = await _create_match(client, auth_headers)
    resp = await client.post(
        f"/api/matches/{match_id}/upload-video/session?slot=full",
        json={"filename": "game.mkv", "size_bytes": 2048},
        headers=auth_headers,
    )
    assert resp.status_code == 200


async def test_list_sessions_status_filter(client, auth_headers):
    resp = await client.get("/api/uploads/sessions?status=active", headers=auth_headers)
    assert resp.status_code == 200
    assert "sessions" in resp.json()


async def test_list_sessions_status_cap(client, auth_headers):
    # More than 8 comma-separated values must not cause a 500 — excess are silently dropped.
    many = ",".join(["active"] * 12)
    resp = await client.get(f"/api/uploads/sessions?status={many}", headers=auth_headers)
    assert resp.status_code == 200
    assert "sessions" in resp.json()


async def test_list_sessions_all(client, auth_headers):
    resp = await client.get("/api/uploads/sessions?status=all", headers=auth_headers)
    assert resp.status_code == 200
    assert "sessions" in resp.json()


# ---------------------------------------------------------------------------
# Tiered storage: REPLAY_ORIGINALS_DIR splits raw uploads + finished MP4s
# off the SSD pool onto a separate cold-storage volume. Default is for
# ORIGINALS_DIR to alias VIDEOS_DIR (single-volume legacy layout).
# ---------------------------------------------------------------------------

async def test_chunked_upload_session_writes_raw_to_originals_dir(
    client, auth_headers, data_dir, monkeypatch,
):
    """When ORIGINALS_DIR != VIDEOS_DIR, the raw upload destination saved on
    the upload-session row points into ORIGINALS_DIR, not VIDEOS_DIR."""
    import server
    originals = data_dir / "originals"
    originals.mkdir()
    monkeypatch.setattr(server, "ORIGINALS_DIR", originals)

    match_id = await _create_match(client, auth_headers)
    resp = await client.post(
        f"/api/matches/{match_id}/upload-video/session?slot=full",
        json={"filename": "game.mp4", "size_bytes": 1024},
        headers=auth_headers,
    )
    assert resp.status_code == 200

    # Pull the raw_path out of the DB to confirm the cold-pool prefix.
    import db as _db
    with _db.connect() as conn:
        row = conn.execute(
            "SELECT raw_path FROM upload_sessions WHERE match_id = ? LIMIT 1",
            (match_id,),
        ).fetchone()
    assert row is not None
    raw_path = row["raw_path"]
    assert str(originals) in raw_path, f"expected raw under {originals}, got {raw_path}"
    assert str(data_dir / "videos") not in raw_path, "raw path should not be under VIDEOS_DIR"


async def test_originals_dir_defaults_to_videos_dir_when_unset(client, auth_headers, data_dir):
    """The conftest fixture sets ORIGINALS_DIR == VIDEOS_DIR by default
    (matches the legacy single-volume layout). The chunked upload session
    creator should still succeed and the raw_path should be under that
    shared directory — i.e. existing single-volume deployments don't see
    any change in on-disk layout."""
    match_id = await _create_match(client, auth_headers)
    resp = await client.post(
        f"/api/matches/{match_id}/upload-video/session?slot=full",
        json={"filename": "game.mp4", "size_bytes": 1024},
        headers=auth_headers,
    )
    assert resp.status_code == 200

    import db as _db
    with _db.connect() as conn:
        row = conn.execute(
            "SELECT raw_path FROM upload_sessions WHERE match_id = ? LIMIT 1",
            (match_id,),
        ).fetchone()
    assert str(data_dir / "videos") in row["raw_path"]


# ---------------------------------------------------------------------------
# Disk-space pre-flight: must check the pool the upload + transcode actually
# write to (ORIGINALS_DIR when tiered), not just DATA_DIR. Regression test
# for the bug flagged on PR #18 — when the cold pool is starved but the SSD
# has room, the upload must be rejected with 507 instead of letting ffmpeg
# fail mid-write.
# ---------------------------------------------------------------------------

async def test_upload_rejected_when_cold_pool_full(
    client, auth_headers, data_dir, monkeypatch,
):
    """With tiered storage, a full ORIGINALS_DIR pool blocks the upload even
    when DATA_DIR has plenty of free space."""
    import server
    import shutil
    originals = data_dir / "originals"
    originals.mkdir()
    monkeypatch.setattr(server, "ORIGINALS_DIR", originals)

    # 1 GiB on the SSD; 1 KiB on the cold pool. Default min_free is much
    # higher than 1 KiB, so the cold pool fails the headroom check and the
    # request must be 507'd. Keep the upload size small so the test isn't
    # confused by the headroom multiplier scaling past the SSD's free bytes.
    real_du = shutil.disk_usage

    def fake_disk_usage(path):
        path = str(path)
        if str(originals) in path:
            return shutil._ntuple_diskusage(total=10_000, used=9_000, free=1_024)
        if str(data_dir) in path:
            return shutil._ntuple_diskusage(total=10**12, used=0, free=10**12)
        return real_du(path)

    monkeypatch.setattr(shutil, "disk_usage", fake_disk_usage)

    match_id = await _create_match(client, auth_headers)
    resp = await client.post(
        f"/api/matches/{match_id}/upload-video/session?slot=full",
        json={"filename": "game.mp4", "size_bytes": 1024 * 1024},
        headers=auth_headers,
    )
    assert resp.status_code == 507, f"expected 507, got {resp.status_code}: {resp.text}"
    assert "originals" in resp.text.lower(), f"error should name the cold pool: {resp.text}"


async def test_upload_accepted_when_cold_pool_has_room(
    client, auth_headers, data_dir, monkeypatch,
):
    """The mirror of the previous test: a tiered layout with healthy cold-
    pool free bytes accepts the upload normally."""
    import server
    import shutil
    originals = data_dir / "originals"
    originals.mkdir()
    monkeypatch.setattr(server, "ORIGINALS_DIR", originals)

    def fake_disk_usage(path):
        return shutil._ntuple_diskusage(total=10**12, used=0, free=10**12)

    monkeypatch.setattr(shutil, "disk_usage", fake_disk_usage)

    match_id = await _create_match(client, auth_headers)
    resp = await client.post(
        f"/api/matches/{match_id}/upload-video/session?slot=full",
        json={"filename": "game.mp4", "size_bytes": 1024},
        headers=auth_headers,
    )
    assert resp.status_code == 200


async def test_disk_diagnostics_reports_both_pools_when_tiered(
    client, auth_headers, data_dir, monkeypatch,
):
    """Admin diagnostics should show free space for the cold pool when
    tiered, so an operator can see when the HDD is filling up."""
    import server
    originals = data_dir / "originals"
    originals.mkdir()
    monkeypatch.setattr(server, "ORIGINALS_DIR", originals)

    resp = await client.get("/api/admin/diagnostics", headers=auth_headers)
    assert resp.status_code == 200
    disk = resp.json()["disk"]
    pools = disk.get("pools", {})
    assert "ssd" in pools
    assert "originals" in pools, "tiered layout should expose the originals pool"
    assert disk.get("target_pool") == "originals"
