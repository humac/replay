"""Tests for M4 admin endpoints: diagnostics, errors, retry, verify, export."""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_diagnostics_structure(client, auth_headers):
    """Diagnostics endpoint returns enriched payload with M4 fields."""
    resp = await client.get("/api/admin/diagnostics", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    # Core fields
    assert "counts" in data
    assert "disk" in data
    assert "upload_sessions" in data
    # M4 additions
    assert "failed_slots" in data["counts"]
    assert "failed_slots" in data
    assert "active_jobs" in data
    assert "recent_errors" in data
    assert "disk_usage_by_match" in data


@pytest.mark.asyncio
async def test_match_errors_empty(client, auth_headers):
    """Error history for a match returns empty list when no errors."""
    # Create a match first
    await client.post("/api/matches", json={
        "home_team": "A", "away_team": "B",
    }, headers=auth_headers)
    matches = (await client.get("/api/matches")).json()
    match_id = matches[0]["id"]

    resp = await client.get(f"/api/admin/matches/{match_id}/errors", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["errors"] == []


@pytest.mark.asyncio
async def test_match_errors_logged(client, auth_headers):
    """Errors are persisted and retrievable via the API."""
    import db as _db
    _db.log_video_error("test-match", "full", "disk_full", "No space", "Need 10GB")
    _db.log_video_error("test-match", "full", "cpu_failed", "CPU failed", "exit 1")

    resp = await client.get("/api/admin/matches/test-match/errors", headers=auth_headers)
    assert resp.status_code == 200
    errors = resp.json()["errors"]
    assert len(errors) == 2
    codes = {e["error_code"] for e in errors}
    assert codes == {"disk_full", "cpu_failed"}


@pytest.mark.asyncio
async def test_retry_wrong_status(client, auth_headers):
    """Retry rejects if slot is not in error state."""
    await client.post("/api/matches", json={
        "home_team": "A", "away_team": "B",
    }, headers=auth_headers)
    matches = (await client.get("/api/matches")).json()
    match_id = matches[0]["id"]

    resp = await client.post(
        f"/api/admin/matches/{match_id}/slots/full/retry",
        headers=auth_headers,
    )
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_retry_no_source(client, auth_headers, data_dir):
    """Retry with error status but no source file returns 404."""
    import db as _db
    await client.post("/api/matches", json={
        "home_team": "A", "away_team": "B",
    }, headers=auth_headers)
    matches = (await client.get("/api/matches")).json()
    match_id = matches[0]["id"]

    # Set slot to error manually
    with _db.connect() as conn:
        m = _db.get_match_by_id(match_id)
        m["video_status"]["full"] = "error"
        _db.upsert_match(conn, m)
        conn.commit()

    resp = await client.post(
        f"/api/admin/matches/{match_id}/slots/full/retry",
        headers=auth_headers,
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_verify_assets(client, auth_headers, data_dir):
    """Verify assets endpoint returns slot report."""
    await client.post("/api/matches", json={
        "home_team": "A", "away_team": "B",
    }, headers=auth_headers)
    matches = (await client.get("/api/matches")).json()
    match_id = matches[0]["id"]

    resp = await client.get(
        f"/api/admin/matches/{match_id}/verify",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["match_id"] == match_id
    assert "slots" in data


@pytest.mark.asyncio
async def test_regenerate_hls_no_mp4(client, auth_headers):
    """Regenerate HLS fails if MP4 doesn't exist."""
    await client.post("/api/matches", json={
        "home_team": "A", "away_team": "B",
    }, headers=auth_headers)
    matches = (await client.get("/api/matches")).json()
    match_id = matches[0]["id"]

    resp = await client.post(
        f"/api/admin/matches/{match_id}/slots/full/regenerate-hls",
        headers=auth_headers,
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_export_database(client, auth_headers):
    """Export database returns a downloadable file."""
    resp = await client.post("/api/admin/export-database", headers=auth_headers)
    assert resp.status_code == 200
    assert "replay-backup" in resp.headers.get("content-disposition", "")
    assert len(resp.content) > 0


@pytest.mark.asyncio
async def test_viewer_cannot_access_admin(client, auth_headers):
    """Non-admin users cannot access admin endpoints."""
    # Create viewer
    await client.post("/api/users", json={
        "username": "viewer_admin_test",
        "password": "password123",
        "role": "viewer",
    }, headers=auth_headers)
    resp = await client.post("/api/login", json={
        "username": "viewer_admin_test",
        "password": "password123",
    })
    viewer_headers = {"Authorization": f"Bearer {resp.json()['token']}"}

    resp = await client.get("/api/admin/diagnostics", headers=viewer_headers)
    assert resp.status_code == 403

    resp = await client.post("/api/admin/export-database", headers=viewer_headers)
    assert resp.status_code == 403
