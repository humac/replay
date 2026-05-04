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

    # hull_points must hold a polygon (3+ vertices). 0 entries is a
    # geometric no-op that passed an earlier draft of the validator;
    # cover it explicitly so the regression doesn't return.
    empty_hull = await client.post("/api/coach/notes", json={
        "match_id": match_id,
        "slot": "full",
        "timestamp_seconds": 1,
        "title": "Empty hull",
        "drawing": {
            "version": 2,
            "objects": [{
                "type": "formation",
                "anchors": [
                    {"x": 0.1, "y": 0.1},
                    {"x": 0.2, "y": 0.2},
                    {"x": 0.3, "y": 0.1},
                ],
                "hull_points": [],
            }],
        },
    }, headers=auth_headers)
    assert empty_hull.status_code == 422

    # And explicitly reject a 2-point hull (degenerate polygon).
    short_hull = await client.post("/api/coach/notes", json={
        "match_id": match_id,
        "slot": "full",
        "timestamp_seconds": 1,
        "title": "Two-point hull",
        "drawing": {
            "version": 2,
            "objects": [{
                "type": "formation",
                "anchors": [
                    {"x": 0.1, "y": 0.1},
                    {"x": 0.2, "y": 0.2},
                    {"x": 0.3, "y": 0.1},
                ],
                "hull_points": [{"x": 0.1, "y": 0.1}, {"x": 0.3, "y": 0.1}],
            }],
        },
    }, headers=auth_headers)
    assert short_hull.status_code == 422


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


@pytest.mark.asyncio
async def test_structured_note_round_trip(client, auth_headers):
    """Phase 1: every new note field round-trips through create + list +
    update. Existing payloads (no new fields sent) keep working with
    safe defaults so older clients don't break post-migration."""
    match_resp = await client.post("/api/matches", json={
        "home_team": "OSU Steel",
        "away_team": "Pinehurst Rangers",
        "date": "2026-04-18",
    }, headers=auth_headers)
    assert match_resp.status_code == 200
    match_id = match_resp.json()["id"]

    # Legacy payload — no Phase 1 fields. Should land with the
    # defaults (note_type='correction', everything else '').
    legacy_resp = await client.post("/api/coach/notes", json={
        "match_id": match_id,
        "slot": "full",
        "timestamp_seconds": 5.0,
        "title": "Legacy-shape note",
        "category": "other",
        "visibility": "team",
    }, headers=auth_headers)
    assert legacy_resp.status_code == 200, legacy_resp.text
    legacy = legacy_resp.json()["note"]
    assert legacy["note_type"] == "correction"
    assert legacy["what_happened"] == ""
    assert legacy["coach_private_note"] == ""

    # Full structured payload — every new field round-trips.
    structured_resp = await client.post("/api/coach/notes", json={
        "match_id": match_id,
        "slot": "first_half",
        "timestamp_seconds": 120.5,
        "title": "Body shape on the half-turn",
        "body": "Full coach context.",
        "category": "decision",
        "visibility": "player",
        "note_type": "positive",
        "what_happened": "Took the ball facing forward.",
        "why_it_matters": "Opens the field for the wide runner.",
        "what_to_do_next": "Repeat in the next match against Riverside.",
        "player_summary": "Nice job opening up your hips before receiving!",
        "coach_private_note": "Bench reflection: pair with #7 in build-up.",
    }, headers=auth_headers)
    assert structured_resp.status_code == 200, structured_resp.text
    note = structured_resp.json()["note"]
    note_id = note["id"]
    assert note["note_type"] == "positive"
    assert note["what_happened"] == "Took the ball facing forward."
    assert note["why_it_matters"] == "Opens the field for the wide runner."
    assert note["what_to_do_next"].startswith("Repeat")
    assert note["player_summary"].startswith("Nice job")
    assert note["coach_private_note"].startswith("Bench reflection")

    # PATCH flips note_type and clears the private note.
    patch_resp = await client.patch(f"/api/coach/notes/{note_id}", json={
        "note_type": "individual_goal",
        "coach_private_note": "",
    }, headers=auth_headers)
    assert patch_resp.status_code == 200, patch_resp.text
    assert patch_resp.json()["note"]["note_type"] == "individual_goal"
    assert patch_resp.json()["note"]["coach_private_note"] == ""
    # Other structured fields untouched by the partial update.
    assert patch_resp.json()["note"]["what_happened"] == "Took the ball facing forward."

    # Invalid note_type rejected at the request boundary.
    bad_resp = await client.post("/api/coach/notes", json={
        "match_id": match_id,
        "slot": "full",
        "timestamp_seconds": 0,
        "title": "Bad note type",
        "category": "other",
        "visibility": "team",
        "note_type": "bogus",
    }, headers=auth_headers)
    assert bad_resp.status_code == 422


@pytest.mark.asyncio
async def test_coach_private_note_never_leaks_to_viewer(client, auth_headers):
    """Phase 1 privacy invariant: `coach_private_note` is coach/admin-only.
    A team-visible note that has a private coach note attached should
    appear in My Feedback for any signed-in viewer, but the
    `coach_private_note` field must come back as an empty string."""
    await client.post("/api/users", json={
        "username": "snoopy_viewer",
        "password": "password123",
        "role": "viewer",
    }, headers=auth_headers)
    viewer_headers = await _login(client, "snoopy_viewer")

    match_resp = await client.post("/api/matches", json={
        "home_team": "OSU Steel",
        "away_team": "Bridgewater FC",
        "date": "2026-04-25",
    }, headers=auth_headers)
    match_id = match_resp.json()["id"]

    note_resp = await client.post("/api/coach/notes", json={
        "match_id": match_id,
        "slot": "full",
        "timestamp_seconds": 30.0,
        "title": "Build-up off the keeper",
        "body": "Public coach body.",
        "category": "build_up",
        "visibility": "team",
        "player_summary": "Drop deeper before the keeper passes to you.",
        "coach_private_note": "INTERNAL: Player A is being asked to do too much.",
    }, headers=auth_headers)
    assert note_resp.status_code == 200
    note_id = note_resp.json()["note"]["id"]
    # Coach round-trip still includes the private note.
    assert "INTERNAL" in note_resp.json()["note"]["coach_private_note"]

    # Build a team-visible playlist that includes the same note. The
    # playlist hydration path embeds full note objects under
    # `playlists[].items[]` — that path must also scrub the private
    # field, otherwise the privacy invariant is violated through a
    # second route. (See PR #73 review — this exact leak was found
    # before the fix landed.)
    playlist_resp = await client.post("/api/coach/playlists", json={
        "title": "Build-up rotations",
        "description": "Team-visible playlist for review.",
        "visibility": "team",
        "note_ids": [note_id],
    }, headers=auth_headers)
    assert playlist_resp.status_code == 200, playlist_resp.text

    # Viewer's My Feedback sees the team-visible note + the playlist,
    # but the private field is scrubbed in BOTH places.
    feedback = await client.get("/api/my-feedback", headers=viewer_headers)
    assert feedback.status_code == 200
    payload = feedback.json()

    # 1) `notes[]` path
    visible_titles = [n["title"] for n in payload["notes"]]
    assert "Build-up off the keeper" in visible_titles
    leaked_notes = [n for n in payload["notes"] if n["coach_private_note"]]
    assert leaked_notes == [], f"coach_private_note leaked via notes[]: {leaked_notes}"

    # 2) `playlists[].items[]` path — the previously-missed leak path.
    visible_playlists = [p for p in payload["playlists"] if p["title"] == "Build-up rotations"]
    assert visible_playlists, "team-visible playlist missing from My Feedback"
    leaked_items = [
        item for p in visible_playlists for item in p.get("items", [])
        if item.get("coach_private_note")
    ]
    assert leaked_items == [], (
        "coach_private_note leaked via playlists[].items[]: "
        f"{[(i.get('title'), i.get('coach_private_note')) for i in leaked_items]}"
    )

    # `player_summary` IS visible to the viewer (it's the player-facing
    # text, by design) — same holds in both surfaces.
    summarized = next(n for n in payload["notes"] if n["title"] == "Build-up off the keeper")
    assert summarized["player_summary"].startswith("Drop deeper")
    item_summary = visible_playlists[0]["items"][0].get("player_summary", "")
    assert item_summary.startswith("Drop deeper"), (
        f"player_summary should still be visible inside playlist items, got: {item_summary!r}"
    )


@pytest.mark.asyncio
async def test_legacy_body_visible_when_player_summary_blank(client, auth_headers):
    """PR 1c: a team-visible note with no `player_summary` but a non-
    empty `body` must still reach the viewer. The UI's
    `_feedbackNoteSummary` helper falls back to `body` when
    `player_summary` is empty — verify the API surface still ships
    `body` so that fallback works end-to-end. This guards against any
    future filter that accidentally strips `body` along with private
    fields."""
    await client.post("/api/users", json={
        "username": "legacy_viewer",
        "password": "password123",
        "role": "viewer",
    }, headers=auth_headers)
    viewer_headers = await _login(client, "legacy_viewer")

    match_resp = await client.post("/api/matches", json={
        "home_team": "OSU Steel",
        "away_team": "Highbridge Town",
        "date": "2026-04-19",
    }, headers=auth_headers)
    match_id = match_resp.json()["id"]

    legacy_resp = await client.post("/api/coach/notes", json={
        "match_id": match_id,
        "slot": "full",
        "timestamp_seconds": 12.0,
        "title": "Recovery angle",
        # Legacy shape: only `body`, no Phase 1 fields. Backend
        # defaults `note_type='correction'` and the structured strings
        # to ''.
        "body": "Take a sharper recovery angle so you cut the runner off.",
        "category": "defending",
        "visibility": "team",
    }, headers=auth_headers)
    assert legacy_resp.status_code == 200, legacy_resp.text

    feedback = await client.get("/api/my-feedback", headers=viewer_headers)
    assert feedback.status_code == 200
    payload = feedback.json()
    note = next((n for n in payload["notes"] if n["title"] == "Recovery angle"), None)
    assert note is not None, "team-visible legacy note should reach the viewer"
    assert note["body"].startswith("Take a sharper"), "legacy body must round-trip to viewer"
    # Legacy notes have an empty player_summary and the safe default
    # note_type — the UI fallback handles both.
    assert note["player_summary"] == ""
    assert note["note_type"] == "correction"
    # Privacy invariant still holds (no leak via the legacy path).
    assert note["coach_private_note"] == ""
