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
