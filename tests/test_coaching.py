"""Tests for coaching workspace, roster links, and player/family feedback."""

from __future__ import annotations

import pytest


async def _login(client, username: str, password: str = "password123") -> dict:
    resp = await client.post("/api/login", json={"username": username, "password": password})
    assert resp.status_code == 200
    return {"Authorization": f"Bearer {resp.json()['token']}"}


@pytest.mark.asyncio
async def test_coach_role_can_use_coaching_workspace(client, auth_headers):
    resp = await client.post("/api/users", json={
        "username": "coach1",
        "password": "password123",
        "role": "coach,uploader",
    }, headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["user"]["role"] == "coach,uploader"

    coach_headers = await _login(client, "coach1")
    resp = await client.get("/api/coach/players", headers=coach_headers)
    assert resp.status_code == 200
    assert resp.json()["players"] == []


@pytest.mark.asyncio
async def test_viewer_cannot_use_coach_api(client, auth_headers):
    await client.post("/api/users", json={
        "username": "viewer_coach_blocked",
        "password": "password123",
        "role": "viewer",
    }, headers=auth_headers)
    viewer_headers = await _login(client, "viewer_coach_blocked")

    resp = await client.get("/api/coach/players", headers=viewer_headers)
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_player_link_controls_my_feedback_visibility(client, auth_headers):
    viewer_resp = await client.post("/api/users", json={
        "username": "family1",
        "password": "password123",
        "role": "viewer",
    }, headers=auth_headers)
    linked_user_id = viewer_resp.json()["user"]["id"]
    other_resp = await client.post("/api/users", json={
        "username": "family2",
        "password": "password123",
        "role": "viewer",
    }, headers=auth_headers)
    assert other_resp.status_code == 200

    player_resp = await client.post("/api/coach/players", json={
        "display_name": "Ava Player",
        "jersey_number": "9",
    }, headers=auth_headers)
    assert player_resp.status_code == 200
    player_id = player_resp.json()["player"]["id"]

    link_resp = await client.post("/api/coach/player-links", json={
        "player_id": player_id,
        "user_id": linked_user_id,
        "relationship": "parent",
    }, headers=auth_headers)
    assert link_resp.status_code == 200

    match_resp = await client.post("/api/matches", json={
        "home_team": "OSU Steel",
        "away_team": "Riverside FC",
        "date": "2026-04-30",
    }, headers=auth_headers)
    assert match_resp.status_code == 200
    match_id = match_resp.json()["id"]

    note_resp = await client.post("/api/coach/notes", json={
        "match_id": match_id,
        "slot": "full",
        "timestamp_seconds": 42.5,
        "title": "Check shoulder before receiving",
        "body": "Scan once before the pass arrives.",
        "category": "decision",
        "visibility": "player",
        "player_ids": [player_id],
        "tags": ["receiving", "scan"],
        "drawing": {"version": 1, "strokes": [{"points": [{"x": 0.1, "y": 0.2}]}]},
    }, headers=auth_headers)
    assert note_resp.status_code == 200

    linked_headers = await _login(client, "family1")
    feedback_resp = await client.get("/api/my-feedback", headers=linked_headers)
    assert feedback_resp.status_code == 200
    feedback = feedback_resp.json()
    assert [p["display_name"] for p in feedback["players"]] == ["Ava Player"]
    assert [n["title"] for n in feedback["notes"]] == ["Check shoulder before receiving"]
    assert feedback["notes"][0]["drawing"]["version"] == 1

    other_headers = await _login(client, "family2")
    other_feedback = await client.get("/api/my-feedback", headers=other_headers)
    assert other_feedback.status_code == 200
    assert other_feedback.json()["notes"] == []


@pytest.mark.asyncio
async def test_team_visible_note_and_review_tracking(client, auth_headers):
    await client.post("/api/users", json={
        "username": "teamviewer",
        "password": "password123",
        "role": "viewer",
    }, headers=auth_headers)
    match_resp = await client.post("/api/matches", json={
        "home_team": "OSU Steel",
        "away_team": "Bridgewater",
        "date": "2026-05-01",
    }, headers=auth_headers)
    match_id = match_resp.json()["id"]

    note_resp = await client.post("/api/coach/notes", json={
        "match_id": match_id,
        "slot": "full",
        "timestamp_seconds": 90,
        "title": "Team pressing trigger",
        "category": "pressing",
        "visibility": "team",
    }, headers=auth_headers)
    note_id = note_resp.json()["note"]["id"]

    viewer_headers = await _login(client, "teamviewer")
    feedback = await client.get("/api/my-feedback", headers=viewer_headers)
    assert [n["id"] for n in feedback.json()["notes"]] == [note_id]

    reviewed = await client.post("/api/my-feedback/review", json={
        "note_id": note_id,
        "reflection": "Press when the back pass is slow.",
    }, headers=viewer_headers)
    assert reviewed.status_code == 200
    assert reviewed.json()["review"]["reflection"] == "Press when the back pass is slow."

    feedback = await client.get("/api/my-feedback", headers=viewer_headers)
    assert feedback.json()["reviews"][0]["note_id"] == note_id


@pytest.mark.asyncio
async def test_v2_drawing_validation(client, auth_headers):
    match_resp = await client.post("/api/matches", json={
        "home_team": "OSU Steel",
        "away_team": "Drawing FC",
        "date": "2026-05-02",
    }, headers=auth_headers)
    match_id = match_resp.json()["id"]

    valid = await client.post("/api/coach/notes", json={
        "match_id": match_id,
        "slot": "full",
        "timestamp_seconds": 12,
        "title": "Annotated shape",
        "category": "shape",
        "visibility": "private",
        "drawing": {
            "version": 2,
            "objects": [
                {"type": "arrow", "color": "#38bdf8", "width": 4, "x1": 0.1, "y1": 0.2, "x2": 0.4, "y2": 0.5},
                {"type": "label", "color": "#ffffff", "x": 0.5, "y": 0.5, "text": "9"},
                {"type": "spotlight", "x": 0.2, "y": 0.2, "w": 0.3, "h": 0.3},
            ],
        },
    }, headers=auth_headers)
    assert valid.status_code == 200
    assert valid.json()["note"]["drawing"]["version"] == 2

    invalid = await client.post("/api/coach/notes", json={
        "match_id": match_id,
        "slot": "full",
        "timestamp_seconds": 12,
        "title": "Bad drawing",
        "drawing": {"version": 2, "objects": [{"type": "arrow", "x1": 2, "y1": 0, "x2": 0, "y2": 0}]},
    }, headers=auth_headers)
    assert invalid.status_code == 422


@pytest.mark.asyncio
async def test_formation_drawing_validation(client, auth_headers):
    """The formation object type carries N anchors + a convex-hull polygon.

    Roundtrip a valid formation; reject one with fewer than 3 anchors.
    """
    match_resp = await client.post("/api/matches", json={
        "home_team": "OSU Steel",
        "away_team": "Formation FC",
        "date": "2026-05-03",
    }, headers=auth_headers)
    match_id = match_resp.json()["id"]

    valid = await client.post("/api/coach/notes", json={
        "match_id": match_id,
        "slot": "first_half",
        "timestamp_seconds": 30,
        "title": "Back line spacing",
        "category": "shape",
        "visibility": "team",
        "drawing": {
            "version": 2,
            "objects": [
                {
                    "type": "formation",
                    "color": "#38bdf8",
                    "width": 3,
                    "anchors": [
                        {"x": 0.20, "y": 0.30, "player_id": "p-ava", "label": "7"},
                        {"x": 0.50, "y": 0.40},
                        {"x": 0.60, "y": 0.20, "label": "9"},
                    ],
                    "hull_points": [
                        {"x": 0.20, "y": 0.30},
                        {"x": 0.60, "y": 0.20},
                        {"x": 0.50, "y": 0.40},
                    ],
                },
            ],
        },
    }, headers=auth_headers)
    assert valid.status_code == 200
    obj = valid.json()["note"]["drawing"]["objects"][0]
    assert obj["type"] == "formation"
    assert len(obj["anchors"]) == 3
    assert obj["anchors"][0]["player_id"] == "p-ava"
    assert obj["anchors"][0]["label"] == "7"

    too_few = await client.post("/api/coach/notes", json={
        "match_id": match_id,
        "slot": "full",
        "timestamp_seconds": 1,
        "title": "Bad formation",
        "drawing": {
            "version": 2,
            "objects": [{
                "type": "formation",
                "anchors": [{"x": 0.1, "y": 0.1}, {"x": 0.2, "y": 0.2}],
                "hull_points": [{"x": 0.1, "y": 0.1}, {"x": 0.2, "y": 0.2}],
            }],
        },
    }, headers=auth_headers)
    assert too_few.status_code == 422


@pytest.mark.asyncio
async def test_visible_playlist_grants_access_to_private_items(client, auth_headers):
    await client.post("/api/users", json={
        "username": "playlistviewer",
        "password": "password123",
        "role": "viewer",
    }, headers=auth_headers)
    match_resp = await client.post("/api/matches", json={
        "home_team": "OSU Steel",
        "away_team": "Playlist FC",
        "date": "2026-05-03",
    }, headers=auth_headers)
    match_id = match_resp.json()["id"]
    note_resp = await client.post("/api/coach/notes", json={
        "match_id": match_id,
        "slot": "full",
        "timestamp_seconds": 75,
        "title": "Private playlist moment",
        "category": "decision",
        "visibility": "private",
    }, headers=auth_headers)
    note_id = note_resp.json()["note"]["id"]
    playlist_resp = await client.post("/api/coach/playlists", json={
        "title": "Team review sequence",
        "description": "One private item shared through the playlist.",
        "visibility": "team",
        "note_ids": [note_id],
        "pre_roll_seconds": 6,
        "post_roll_seconds": 11,
    }, headers=auth_headers)
    assert playlist_resp.status_code == 200
    assert playlist_resp.json()["playlist"]["items"][0]["id"] == note_id

    viewer_headers = await _login(client, "playlistviewer")
    feedback = await client.get("/api/my-feedback", headers=viewer_headers)
    payload = feedback.json()
    assert payload["notes"] == []
    assert payload["playlists"][0]["pre_roll_seconds"] == 6
    assert payload["playlists"][0]["post_roll_seconds"] == 11
    assert payload["playlists"][0]["items"][0]["title"] == "Private playlist moment"
