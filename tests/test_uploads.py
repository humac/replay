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
