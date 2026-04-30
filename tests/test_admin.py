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
    assert "recent_activity" in data
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
async def test_activity_events_surface_in_diagnostics(client, auth_headers):
    """Recent operational activity is exposed separately from video errors."""
    import db as _db

    _db.log_activity_event(
        "transcode.succeeded",
        severity="success",
        message="Transcode finished",
        match_id="match-activity",
        slot="full",
        actor="admin",
    )

    resp = await client.get("/api/admin/diagnostics", headers=auth_headers)
    assert resp.status_code == 200
    activity = resp.json()["recent_activity"]
    assert activity
    assert activity[0]["event_type"] == "transcode.succeeded"
    assert activity[0]["message"] == "Transcode finished"
    assert activity[0]["match_id"] == "match-activity"


@pytest.mark.asyncio
async def test_match_create_logs_activity(client, auth_headers):
    """Creating a match writes a durable overview activity event."""
    resp = await client.post("/api/matches", json={
        "home_team": "Activity A", "away_team": "Activity B",
    }, headers=auth_headers)
    assert resp.status_code == 200
    match_id = resp.json()["id"]

    diag = await client.get("/api/admin/diagnostics", headers=auth_headers)
    assert diag.status_code == 200
    events = diag.json()["recent_activity"]
    assert any(
        e["event_type"] == "match.created" and e["match_id"] == match_id
        for e in events
    )


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
async def test_retry_ready_without_force_rejected(client, auth_headers):
    """Without ?force=true, a ready slot can't be retried."""
    import db as _db
    await client.post("/api/matches", json={
        "home_team": "A", "away_team": "B",
    }, headers=auth_headers)
    matches = (await client.get("/api/matches")).json()
    match_id = matches[0]["id"]

    with _db.connect() as conn:
        m = _db.get_match_by_id(match_id)
        m["video_status"]["full"] = "ready"
        _db.upsert_match(conn, m)
        conn.commit()

    resp = await client.post(
        f"/api/admin/matches/{match_id}/slots/full/retry",
        headers=auth_headers,
    )
    # 409 because status is 'ready', not 'error'.
    assert resp.status_code == 409
    detail = resp.json().get("detail", "")
    # The error message should hint at the ?force=true escape hatch.
    assert "force" in detail.lower()


@pytest.mark.asyncio
async def test_retry_ready_with_force_accepts(client, auth_headers, data_dir):
    """With ?force=true, a ready slot CAN be retried — but it'll 404 if no
    source file is on disk. We assert we get past the status guard (i.e.
    not 409) and into the source-file check (404), proving force=true was
    honored without actually kicking off a real ffmpeg job in the test.
    """
    import db as _db
    await client.post("/api/matches", json={
        "home_team": "A", "away_team": "B",
    }, headers=auth_headers)
    matches = (await client.get("/api/matches")).json()
    match_id = matches[0]["id"]

    with _db.connect() as conn:
        m = _db.get_match_by_id(match_id)
        m["video_status"]["full"] = "ready"
        _db.upsert_match(conn, m)
        conn.commit()

    resp = await client.post(
        f"/api/admin/matches/{match_id}/slots/full/retry?force=true",
        headers=auth_headers,
    )
    # We passed the status gate (force=true allowed ready). The next step
    # tries to find a source file on disk — there isn't one in this test —
    # so 404 is the expected outcome.
    assert resp.status_code == 404
    assert "source" in resp.json().get("detail", "").lower()


@pytest.mark.asyncio
async def test_retry_transcoding_always_rejected(client, auth_headers):
    """Even with force=true, a transcoding slot can't be retried."""
    import db as _db
    await client.post("/api/matches", json={
        "home_team": "A", "away_team": "B",
    }, headers=auth_headers)
    matches = (await client.get("/api/matches")).json()
    match_id = matches[0]["id"]

    with _db.connect() as conn:
        m = _db.get_match_by_id(match_id)
        m["video_status"]["full"] = "transcoding"
        _db.upsert_match(conn, m)
        conn.commit()

    # Without force.
    resp = await client.post(
        f"/api/admin/matches/{match_id}/slots/full/retry",
        headers=auth_headers,
    )
    assert resp.status_code == 409

    # With force — still rejected.
    resp = await client.post(
        f"/api/admin/matches/{match_id}/slots/full/retry?force=true",
        headers=auth_headers,
    )
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_retry_force_admin_only(client, auth_headers):
    """Non-admins can't trigger force re-transcode (or any retry)."""
    await client.post("/api/users", json={
        "username": "viewer_force_test",
        "password": "password123",
        "role": "viewer",
    }, headers=auth_headers)
    resp = await client.post("/api/login", json={
        "username": "viewer_force_test",
        "password": "password123",
    })
    viewer_headers = {"Authorization": f"Bearer {resp.json()['token']}"}

    # Create a match as admin.
    await client.post("/api/matches", json={
        "home_team": "A", "away_team": "B",
    }, headers=auth_headers)
    matches = (await client.get("/api/matches")).json()
    match_id = matches[0]["id"]

    resp = await client.post(
        f"/api/admin/matches/{match_id}/slots/full/retry?force=true",
        headers=viewer_headers,
    )
    assert resp.status_code == 403


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


@pytest.mark.asyncio
async def test_dashboard_data_endpoints_reachable(client, auth_headers):
    """Both endpoints the unified Admin Dashboard polls (diagnostics + streams)
    are reachable for an admin and shaped how the front-end expects."""
    diag = await client.get("/api/admin/diagnostics", headers=auth_headers)
    assert diag.status_code == 200
    diag_data = diag.json()
    assert "counts" in diag_data
    assert "disk" in diag_data

    streams = await client.get("/api/admin/streams", headers=auth_headers)
    assert streams.status_code == 200
    streams_data = streams.json()
    assert isinstance(streams_data.get("active"), list)
    assert isinstance(streams_data.get("blocks"), list)


# ---------------------------------------------------------------------------
# Performance Tuning panel — /api/admin/performance + /capture
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_performance_endpoint_shape(client, auth_headers):
    """The Performance Tuning admin endpoint returns the keys the frontend
    panel reads in renderPerformanceTuning()."""
    resp = await client.get("/api/admin/performance", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()

    # Top-level shape consumed by the panel.
    for key in ("ts", "host", "disk", "throughput", "transcode", "active_sessions", "tuning_settings"):
        assert key in data, f"missing top-level key: {key}"

    # Throughput sub-shape.
    tp = data["throughput"]
    assert "samples" in tp
    assert "capture" in tp
    assert isinstance(tp["samples"], list)
    assert isinstance(tp["capture"], dict)
    assert "fast" in tp["capture"]
    assert "remaining_seconds" in tp["capture"]

    # Transcode sub-shape.
    tx = data["transcode"]
    assert "concurrency_limit" in tx
    assert "gpu" in tx
    assert "recent" in tx
    assert isinstance(tx["recent"], list)

    # Tuning settings echo back the keys (no values leaked beyond them).
    assert isinstance(data["tuning_settings"], dict)
    assert "transcode_concurrency" in data["tuning_settings"]


@pytest.mark.asyncio
async def test_performance_endpoint_admin_only(client, auth_headers):
    """Non-admin users cannot read /api/admin/performance."""
    await client.post("/api/users", json={
        "username": "viewer_perf_test",
        "password": "password123",
        "role": "viewer",
    }, headers=auth_headers)
    resp = await client.post("/api/login", json={
        "username": "viewer_perf_test",
        "password": "password123",
    })
    viewer_headers = {"Authorization": f"Bearer {resp.json()['token']}"}

    resp = await client.get("/api/admin/performance", headers=viewer_headers)
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_capture_endpoint_default_seconds(client, auth_headers):
    """POST without a body starts the capture with the default 60 s."""
    resp = await client.post("/api/admin/performance/capture", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["fast"] is True
    # Default is 60s; allow a small slack for clock granularity.
    assert 55 <= data["remaining_seconds"] <= 60


@pytest.mark.asyncio
async def test_capture_endpoint_validates_range(client, auth_headers):
    """The Pydantic model rejects out-of-range seconds with 422."""
    # Below minimum (5 s).
    resp = await client.post(
        "/api/admin/performance/capture",
        json={"seconds": 1},
        headers=auth_headers,
    )
    assert resp.status_code == 422

    # Above maximum (600 s).
    resp = await client.post(
        "/api/admin/performance/capture",
        json={"seconds": 99999},
        headers=auth_headers,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_capture_endpoint_admin_only(client, auth_headers):
    """Non-admins can't start a capture window."""
    await client.post("/api/users", json={
        "username": "viewer_capture_test",
        "password": "password123",
        "role": "viewer",
    }, headers=auth_headers)
    resp = await client.post("/api/login", json={
        "username": "viewer_capture_test",
        "password": "password123",
    })
    viewer_headers = {"Authorization": f"Bearer {resp.json()['token']}"}

    resp = await client.post("/api/admin/performance/capture", headers=viewer_headers)
    assert resp.status_code == 403


def test_intel_gpu_busy_returns_none_without_sysfs(tmp_path, monkeypatch):
    """On hosts without /sys/class/drm/card0/engine, helper returns None
    rather than the previous always-100% fake value."""
    import server

    # Reset the per-engine cache so prior test runs don't leak in.
    server._perf_prev_gpu.update(ts=0.0, engines={})
    # Point the helper at a non-existent base via monkeypatching Path? The
    # helper hardcodes the path, so we just rely on the file not existing
    # in the test environment. Both macOS dev and Linux CI without an
    # Intel iGPU should miss this dir.
    from pathlib import Path as _Path
    if _Path("/sys/class/drm/card0/engine").exists():
        pytest.skip("test host has an Intel iGPU; skipping null-path assertion")
    assert server._intel_gpu_busy_pct() is None


def test_intel_gpu_busy_diff_pattern(tmp_path, monkeypatch):
    """With two simulated reads of the per-engine `busy` counter, the helper
    returns a delta-derived percentage instead of the broken absolute value.

    Simulates an engine that advanced 0.5 s of GPU time across 1 s of wall
    time — should report ~50 % busy."""
    import server
    import time as _time

    fake_engine = tmp_path / "engine" / "rcs0"
    fake_engine.mkdir(parents=True)
    busy_file = fake_engine / "busy"

    monkeypatch.setattr(
        "server.Path",
        lambda p: tmp_path / "engine" if p == "/sys/class/drm/card0/engine" else server.Path(p),
    )
    server._perf_prev_gpu.update(ts=0.0, engines={})

    # First call seeds the cache; returns None because there's no prior.
    busy_file.write_text("0")
    assert server._intel_gpu_busy_pct() is None

    # Pretend a second elapsed and 5e8 ns (0.5 s) of GPU time accumulated.
    server._perf_prev_gpu["ts"] = _time.time() - 1.0
    busy_file.write_text(str(500_000_000))
    pct = server._intel_gpu_busy_pct()
    assert pct is not None
    assert 40.0 <= pct <= 60.0, f"expected ~50%, got {pct}"
