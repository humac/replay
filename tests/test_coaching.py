"""Tests for coaching workspace, roster links, and player/family feedback."""

from __future__ import annotations

import asyncio

import pytest


async def _login(client, username: str, password: str = "password123") -> dict:
    resp = await client.post("/api/login", json={"username": username, "password": password})
    assert resp.status_code == 200
    return {"Authorization": f"Bearer {resp.json()['token']}"}


async def _drain_background_tasks() -> None:
    """Phase 3a tests: yield control so tasks scheduled via
    `_spawn_task(...)` (which uses `asyncio.create_task`) actually run
    before the test inspects their side-effects. One `sleep(0)` is
    enough for synchronous stubs; we do a short loop to cover any
    chain that itself awaits."""
    for _ in range(5):
        await asyncio.sleep(0)


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


# ---------------------------------------------------------------------------
# Phase 3a — per-coaching-note thumbnails
#
# Tests cover:
#   - missing thumbnail (file not generated yet) -> 404, not 500
#   - file-system path is `<videos>/<match>/coach_thumbs/<note>.jpg`
#   - coach + admin can fetch any thumbnail
#   - team-visible note thumbnail reachable by signed-in viewer
#   - player-visible note thumbnail reachable only by linked family
#   - private note thumbnail is NEVER reachable by viewers (returns 404)
#   - playlist-visible private item thumbnail follows the same boundary
#     rule that `/api/my-feedback` already enforces
#   - coach regenerate endpoint respects the role gate
#   - generation failure (no source video, ffmpeg missing) does NOT
#     break note creation — POST /api/coach/notes still returns 200
#
# Strategy: the file-existence check is the only thing the serving
# endpoint inspects, so each test that needs a "generated" thumbnail
# just writes a small JPEG payload directly to the deterministic path
# under the test's `data_dir`. Tests that exercise the create-time
# generator stub `_media.generate_thumbnail_at_timestamp` to write the
# same payload synchronously (no ffmpeg dependency) — see
# `_install_thumbnail_stub` below. A separate test installs a stub
# that ALWAYS RAISES so we can assert the create flow stays green
# even when the generator throws.
# ---------------------------------------------------------------------------


def _coach_thumb_path(data_dir, match_id: str, note_id: int):
    """Mirror of `_media.coach_note_thumbnail_path` but rooted at the
    test fixture's `data_dir / videos`. Kept duplicated rather than
    importing the helper so a regression in the path convention shows
    up as a test failure here, not a silent move."""
    return data_dir / "videos" / match_id / "coach_thumbs" / f"{note_id}.jpg"


# A 1-byte JPEG is good enough for the file-exists check the serving
# endpoint runs; the actual JPEG header is irrelevant because no test
# decodes the bytes. Using a tiny constant keeps the test data dir
# light. The real ffmpeg-produced JPEGs are ~5-30 KB.
_FAKE_JPEG = b"\xff\xd8\xff\xd9"  # SOI + EOI markers


def _write_fake_thumb(data_dir, match_id: str, note_id: int) -> "Path":
    p = _coach_thumb_path(data_dir, match_id, note_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(_FAKE_JPEG)
    return p


async def _install_thumbnail_stub(monkeypatch, *, succeed: bool = True, raise_exc: bool = False):
    """Replace `_media.generate_thumbnail_at_timestamp` so create/update
    flows don't shell out to ffmpeg in the test suite. When `succeed`
    is True, write the fake JPEG to the destination path so the
    serving endpoint sees a real file. When `raise_exc` is True the
    stub raises a RuntimeError to exercise the safety net in the
    spawn helper. Returns the call log so tests can inspect args."""
    import media as _media
    calls: list[dict] = []

    async def stub(src, dest, *, timestamp_s):
        calls.append({"src": str(src), "dest": str(dest), "timestamp_s": timestamp_s})
        if raise_exc:
            raise RuntimeError("simulated ffmpeg crash")
        if succeed:
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(_FAKE_JPEG)
        return succeed

    monkeypatch.setattr(_media, "generate_thumbnail_at_timestamp", stub)
    return calls


@pytest.mark.asyncio
async def test_thumbnail_404_when_file_missing(client, auth_headers):
    """No file on disk -> 404, never a 500. Covers the path the spec
    calls out: 'missing thumbnail should return 404 or a controlled
    placeholder response, not a server error.'"""
    match_resp = await client.post("/api/matches", json={
        "home_team": "OSU Steel",
        "away_team": "Falcons FC",
        "date": "2026-05-05",
    }, headers=auth_headers)
    match_id = match_resp.json()["id"]
    note_resp = await client.post("/api/coach/notes", json={
        "match_id": match_id,
        "slot": "full",
        "timestamp_seconds": 12.0,
        "title": "Pressing trigger",
        "category": "pressing",
        "visibility": "team",
    }, headers=auth_headers)
    note_id = note_resp.json()["note"]["id"]
    # No stub + no real video means no file; the spawn helper's
    # `if not src.is_file()` guard returns False without raising.
    resp = await client.get(f"/api/coach/notes/{note_id}/thumbnail", headers=auth_headers)
    assert resp.status_code == 404, resp.text


@pytest.mark.asyncio
async def test_thumbnail_404_for_unknown_note(client, auth_headers):
    resp = await client.get("/api/coach/notes/9999999/thumbnail", headers=auth_headers)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_thumbnail_requires_auth(client):
    """Anonymous request fails — no signed-in user."""
    resp = await client.get("/api/coach/notes/1/thumbnail")
    assert resp.status_code in (401, 403)


@pytest.mark.asyncio
async def test_thumbnail_admin_and_coach_can_access_team_note(client, auth_headers, data_dir, monkeypatch):
    """Coach/admin path: both should always succeed once the file exists."""
    await _install_thumbnail_stub(monkeypatch)
    await client.post("/api/users", json={
        "username": "coach1", "password": "password123", "role": "coach",
    }, headers=auth_headers)
    match_resp = await client.post("/api/matches", json={
        "home_team": "OSU Steel", "away_team": "Riverside FC", "date": "2026-05-06",
    }, headers=auth_headers)
    match_id = match_resp.json()["id"]
    note_resp = await client.post("/api/coach/notes", json={
        "match_id": match_id, "slot": "full", "timestamp_seconds": 30.0,
        "title": "Team shape", "category": "shape", "visibility": "team",
    }, headers=auth_headers)
    note_id = note_resp.json()["note"]["id"]
    await _drain_background_tasks()
    assert _coach_thumb_path(data_dir, match_id, note_id).is_file(), \
        "stub should have written the JPEG synchronously"

    # Admin (using the default auth_headers fixture)
    admin_resp = await client.get(f"/api/coach/notes/{note_id}/thumbnail", headers=auth_headers)
    assert admin_resp.status_code == 200
    assert admin_resp.headers["content-type"] == "image/jpeg"
    assert admin_resp.content == _FAKE_JPEG

    # Coach role
    coach_headers = await _login(client, "coach1")
    coach_resp = await client.get(f"/api/coach/notes/{note_id}/thumbnail", headers=coach_headers)
    assert coach_resp.status_code == 200


@pytest.mark.asyncio
async def test_thumbnail_team_visible_note_reachable_by_signed_in_viewer(client, auth_headers, data_dir, monkeypatch):
    """A `visibility=team` note's thumbnail must be reachable by any
    signed-in viewer (matches `/api/my-feedback` behaviour)."""
    await _install_thumbnail_stub(monkeypatch)
    await client.post("/api/users", json={
        "username": "viewer1", "password": "password123", "role": "viewer",
    }, headers=auth_headers)
    match_resp = await client.post("/api/matches", json={
        "home_team": "OSU Steel", "away_team": "Northgate", "date": "2026-05-07",
    }, headers=auth_headers)
    match_id = match_resp.json()["id"]
    note_resp = await client.post("/api/coach/notes", json={
        "match_id": match_id, "slot": "full", "timestamp_seconds": 45.0,
        "title": "Press in midfield", "category": "pressing", "visibility": "team",
    }, headers=auth_headers)
    note_id = note_resp.json()["note"]["id"]
    await _drain_background_tasks()

    viewer_headers = await _login(client, "viewer1")
    resp = await client.get(f"/api/coach/notes/{note_id}/thumbnail", headers=viewer_headers)
    assert resp.status_code == 200
    assert resp.content == _FAKE_JPEG


@pytest.mark.asyncio
async def test_thumbnail_player_visible_only_to_linked_family(client, auth_headers, data_dir, monkeypatch):
    """`visibility=player` thumbnail: linked family member can fetch it,
    unlinked viewer cannot."""
    await _install_thumbnail_stub(monkeypatch)
    family_resp = await client.post("/api/users", json={
        "username": "family1", "password": "password123", "role": "viewer",
    }, headers=auth_headers)
    linked_user_id = family_resp.json()["user"]["id"]
    await client.post("/api/users", json={
        "username": "stranger", "password": "password123", "role": "viewer",
    }, headers=auth_headers)
    player_resp = await client.post("/api/coach/players", json={
        "display_name": "Alex Park", "jersey_number": "7",
    }, headers=auth_headers)
    player_id = player_resp.json()["player"]["id"]
    await client.post("/api/coach/player-links", json={
        "player_id": player_id, "user_id": linked_user_id, "relationship": "parent",
    }, headers=auth_headers)
    match_resp = await client.post("/api/matches", json={
        "home_team": "OSU Steel", "away_team": "Highbridge", "date": "2026-05-08",
    }, headers=auth_headers)
    match_id = match_resp.json()["id"]
    note_resp = await client.post("/api/coach/notes", json={
        "match_id": match_id, "slot": "full", "timestamp_seconds": 60.0,
        "title": "Player #7 — recovery", "category": "defending",
        "visibility": "player", "player_ids": [player_id],
    }, headers=auth_headers)
    note_id = note_resp.json()["note"]["id"]
    await _drain_background_tasks()

    family_headers = await _login(client, "family1")
    family_resp = await client.get(f"/api/coach/notes/{note_id}/thumbnail", headers=family_headers)
    assert family_resp.status_code == 200, family_resp.text

    stranger_headers = await _login(client, "stranger")
    stranger_resp = await client.get(f"/api/coach/notes/{note_id}/thumbnail", headers=stranger_headers)
    assert stranger_resp.status_code == 404, \
        "unlinked viewer must NOT be able to fetch player-visible thumbnail"


@pytest.mark.asyncio
async def test_thumbnail_private_note_never_leaks_to_viewer(client, auth_headers, data_dir, monkeypatch):
    """`visibility=private` thumbnail must be invisible to ANY non-coach
    user, even if the JPEG file exists on disk. Returns 404 (same
    response shape as 'note doesn't exist') so a viewer cannot probe
    the existence of private notes."""
    await _install_thumbnail_stub(monkeypatch)
    await client.post("/api/users", json={
        "username": "viewer2", "password": "password123", "role": "viewer",
    }, headers=auth_headers)
    match_resp = await client.post("/api/matches", json={
        "home_team": "OSU Steel", "away_team": "Pinehurst", "date": "2026-05-09",
    }, headers=auth_headers)
    match_id = match_resp.json()["id"]
    note_resp = await client.post("/api/coach/notes", json={
        "match_id": match_id, "slot": "full", "timestamp_seconds": 75.0,
        "title": "Internal substitution rationale", "category": "other",
        "visibility": "private",
    }, headers=auth_headers)
    note_id = note_resp.json()["note"]["id"]
    await _drain_background_tasks()

    # Confirm the file IS on disk (the stub wrote it for the coach
    # save). The point of the test is that the file existing does
    # NOT make the endpoint serve it to viewers.
    assert _coach_thumb_path(data_dir, match_id, note_id).is_file()

    # Coach can fetch it.
    coach_resp = await client.get(f"/api/coach/notes/{note_id}/thumbnail", headers=auth_headers)
    assert coach_resp.status_code == 200

    # Viewer cannot — even though the file exists.
    viewer_headers = await _login(client, "viewer2")
    viewer_resp = await client.get(f"/api/coach/notes/{note_id}/thumbnail", headers=viewer_headers)
    assert viewer_resp.status_code == 404


@pytest.mark.asyncio
async def test_thumbnail_for_playlist_private_item_blocked_via_standalone_endpoint(
    client, auth_headers, data_dir, monkeypatch
):
    """Phase 3a deliberately keeps the standalone thumbnail endpoint
    private-strict: even if a private note is reachable to a viewer
    INSIDE a visible playlist's items (the playlist-grants-access
    rule, see `test_visible_playlist_grants_access_to_private_items`),
    the standalone `GET /api/coach/notes/{id}/thumbnail` does NOT
    surface the private note's thumbnail. This matches the existing
    `/api/my-feedback` behaviour, which only exposes private items
    via `playlists[].items[]`, not as standalone notes.

    A future Phase 3b may add a `?playlist_id=X` query parameter that
    accepts the playlist-context boundary; this PR scopes that out
    explicitly so the surface area for Phase 3a stays small."""
    await _install_thumbnail_stub(monkeypatch)
    await client.post("/api/users", json={
        "username": "teamview", "password": "password123", "role": "viewer",
    }, headers=auth_headers)
    match_resp = await client.post("/api/matches", json={
        "home_team": "OSU Steel", "away_team": "Marsh Lane", "date": "2026-05-10",
    }, headers=auth_headers)
    match_id = match_resp.json()["id"]
    private_note = await client.post("/api/coach/notes", json={
        "match_id": match_id, "slot": "full", "timestamp_seconds": 90.0,
        "title": "Internal coach note", "category": "other",
        "visibility": "private",
    }, headers=auth_headers)
    private_note_id = private_note.json()["note"]["id"]
    playlist_resp = await client.post("/api/coach/playlists", json={
        "title": "Team review session", "visibility": "team",
        "note_ids": [private_note_id],
    }, headers=auth_headers)
    assert playlist_resp.status_code == 200

    # Confirm the playlist-grants-access rule still works for the
    # note ITSELF inside `/api/my-feedback`.
    viewer_headers = await _login(client, "teamview")
    feedback = await client.get("/api/my-feedback", headers=viewer_headers)
    items = feedback.json()["playlists"][0]["items"]
    assert items[0]["id"] == private_note_id

    # But the standalone thumbnail endpoint does NOT surface it.
    resp = await client.get(f"/api/coach/notes/{private_note_id}/thumbnail", headers=viewer_headers)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_thumbnail_create_does_not_break_when_generator_raises(client, auth_headers, monkeypatch):
    """Acceptance criterion: 'Thumbnail generation failure does not
    block note save.' We simulate a crashing ffmpeg by installing a
    stub that raises. The POST /api/coach/notes call must still
    return 200 with a fully-formed note row, and the subsequent
    GET .../thumbnail must return 404 (file was never written)."""
    await _install_thumbnail_stub(monkeypatch, succeed=False, raise_exc=True)
    match_resp = await client.post("/api/matches", json={
        "home_team": "OSU Steel", "away_team": "Bridgewater", "date": "2026-05-11",
    }, headers=auth_headers)
    match_id = match_resp.json()["id"]

    note_resp = await client.post("/api/coach/notes", json={
        "match_id": match_id, "slot": "full", "timestamp_seconds": 25.0,
        "title": "ffmpeg crashes here", "category": "other", "visibility": "team",
    }, headers=auth_headers)
    assert note_resp.status_code == 200, note_resp.text
    note_id = note_resp.json()["note"]["id"]

    # Drain the spawned `_spawn_coach_note_thumbnail` task explicitly
    # so we're not relying on the follow-up GET to incidentally yield
    # the loop. Once the helper has run, the RuntimeError will have
    # been caught and no file written.
    await _drain_background_tasks()

    # The thumbnail endpoint returns 404 because the spawn helper
    # caught the RuntimeError (so no file was written).
    resp = await client.get(f"/api/coach/notes/{note_id}/thumbnail", headers=auth_headers)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_thumbnail_regenerate_requires_coach(client, auth_headers, monkeypatch):
    """The manual regenerate endpoint is gated like the rest of
    `/api/coach/*` — viewers and unauthenticated users get 403."""
    await _install_thumbnail_stub(monkeypatch)
    await client.post("/api/users", json={
        "username": "viewerR", "password": "password123", "role": "viewer",
    }, headers=auth_headers)
    match_resp = await client.post("/api/matches", json={
        "home_team": "OSU Steel", "away_team": "Eastside", "date": "2026-05-12",
    }, headers=auth_headers)
    match_id = match_resp.json()["id"]
    note_resp = await client.post("/api/coach/notes", json={
        "match_id": match_id, "slot": "full", "timestamp_seconds": 33.0,
        "title": "Roster note", "category": "other", "visibility": "team",
    }, headers=auth_headers)
    note_id = note_resp.json()["note"]["id"]

    # Coach/admin succeeds.
    coach_resp = await client.post(f"/api/coach/notes/{note_id}/thumbnail/regenerate", headers=auth_headers)
    assert coach_resp.status_code == 200
    assert coach_resp.json() == {"ok": True, "generated": True}

    # Viewer is blocked.
    viewer_headers = await _login(client, "viewerR")
    viewer_resp = await client.post(f"/api/coach/notes/{note_id}/thumbnail/regenerate", headers=viewer_headers)
    assert viewer_resp.status_code == 403


@pytest.mark.asyncio
async def test_thumbnail_regenerate_handles_unknown_note(client, auth_headers):
    resp = await client.post("/api/coach/notes/99999/thumbnail/regenerate", headers=auth_headers)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_thumbnail_regenerate_returns_ok_false_when_source_missing(client, auth_headers, monkeypatch):
    """When the source MP4 doesn't exist, regenerate should return
    `{ok: True, generated: False}` so the caller knows the call ran
    but produced nothing — distinct from an unknown-note 404."""
    # Don't install the stub — the real `generate_thumbnail_at_timestamp`
    # runs, sees that `src` doesn't exist, logs a warning, and
    # returns False without raising.
    match_resp = await client.post("/api/matches", json={
        "home_team": "OSU Steel", "away_team": "Coastal", "date": "2026-05-13",
    }, headers=auth_headers)
    match_id = match_resp.json()["id"]
    note_resp = await client.post("/api/coach/notes", json={
        "match_id": match_id, "slot": "full", "timestamp_seconds": 5.0,
        "title": "No source video", "category": "other", "visibility": "team",
    }, headers=auth_headers)
    note_id = note_resp.json()["note"]["id"]

    resp = await client.post(f"/api/coach/notes/{note_id}/thumbnail/regenerate", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "generated": False}


@pytest.mark.asyncio
async def test_thumbnail_path_convention(data_dir):
    """Lock the storage path the spec calls out — anything that
    relocates `coach_thumbs` will trip this."""
    from media import coach_note_thumbnail_path
    p = coach_note_thumbnail_path(data_dir / "videos", "match-abc", 42)
    assert p == data_dir / "videos" / "match-abc" / "coach_thumbs" / "42.jpg"


# ---------------------------------------------------------------------------
# Phase 3a — code-review fix-up regressions
#
# These three tests pin down the two blockers the PR #88 review caught:
#   1. `Cache-Control` must NOT be `public` (per-viewer access-controlled
#      response — a shared cache must not replay it across users), and
#      should carry an `ETag: "{mtime}"` so coaches see a freshly
#      regenerated thumbnail on the next refresh.
#   2. Every site that resolves a coach-note thumbnail path must run it
#      through `_thumb_path_within_videos_dir` so a corrupted DB row whose
#      `match_id` contains `..` cannot escape `VIDEOS_DIR`. We simulate
#      the corrupted-row case by `UPDATE`-ing the note row's `match_id`
#      directly via the DB connection (Pydantic only validates on the
#      create path, so a future bug elsewhere could still let an escaping
#      value land in the DB — defense-in-depth means the serving / spawn
#      / regenerate / delete paths must each refuse to touch it).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_thumbnail_response_is_not_public_cacheable(client, auth_headers, data_dir, monkeypatch):
    """Per-user access-controlled responses must NEVER set
    `Cache-Control: public` — a shared CDN / proxy could otherwise
    replay the JPEG to a different viewer. We mirror `serve_thumbnail`'s
    `no-cache, must-revalidate` + `ETag: "{mtime}"` policy."""
    await _install_thumbnail_stub(monkeypatch)
    match_resp = await client.post("/api/matches", json={
        "home_team": "OSU Steel", "away_team": "Cache Test FC", "date": "2026-05-14",
    }, headers=auth_headers)
    match_id = match_resp.json()["id"]
    note_resp = await client.post("/api/coach/notes", json={
        "match_id": match_id, "slot": "full", "timestamp_seconds": 12.0,
        "title": "Cache header check", "category": "shape", "visibility": "team",
    }, headers=auth_headers)
    note_id = note_resp.json()["note"]["id"]
    await _drain_background_tasks()

    resp = await client.get(f"/api/coach/notes/{note_id}/thumbnail", headers=auth_headers)
    assert resp.status_code == 200
    cache_control = resp.headers.get("cache-control", "")
    assert "public" not in cache_control.lower(), (
        f"Cache-Control must NOT be public on a per-viewer access-controlled "
        f"response (got {cache_control!r})"
    )
    # Positive assertion: must revalidate every request so a coach sees
    # a freshly-regenerated thumbnail on next refresh.
    assert "no-cache" in cache_control.lower() or "private" in cache_control.lower(), (
        f"Cache-Control must include either no-cache or private (got {cache_control!r})"
    )
    # ETag drives conditional revalidation — `serve_thumbnail` uses the
    # mtime of the file. The exact value depends on the stub's write
    # time; just confirm the header exists and is quoted.
    etag = resp.headers.get("etag", "")
    assert etag.startswith('"') and etag.endswith('"') and len(etag) > 2, (
        f"ETag header must be present and quoted (got {etag!r})"
    )
    # X-Content-Type-Options must remain — same defense-in-depth as
    # match-logo / match-thumbnail responses.
    assert resp.headers.get("x-content-type-options") == "nosniff"


@pytest.mark.asyncio
async def test_thumbnail_get_refuses_path_escape(client, auth_headers, data_dir, monkeypatch):
    """If a corrupted DB row's `match_id` would resolve outside
    `VIDEOS_DIR`, the GET endpoint must return the same 404 it uses for
    unknown / unauthorized / missing-file cases — never serve a file
    from outside the videos tree."""
    import db as _db
    await _install_thumbnail_stub(monkeypatch)
    match_resp = await client.post("/api/matches", json={
        "home_team": "OSU Steel", "away_team": "Containment FC", "date": "2026-05-15",
    }, headers=auth_headers)
    match_id = match_resp.json()["id"]
    note_resp = await client.post("/api/coach/notes", json={
        "match_id": match_id, "slot": "full", "timestamp_seconds": 7.0,
        "title": "Containment GET", "category": "shape", "visibility": "team",
    }, headers=auth_headers)
    note_id = note_resp.json()["note"]["id"]
    await _drain_background_tasks()

    # Sanity: with the legitimate match_id it works.
    ok = await client.get(f"/api/coach/notes/{note_id}/thumbnail", headers=auth_headers)
    assert ok.status_code == 200

    # Now mutate the row's match_id to inject a `..` traversal payload.
    # In production this should never happen because `match_id` comes
    # from a validated POST, but defense-in-depth means the serving
    # path must still refuse to escape.
    conn = _db.connect()
    try:
        conn.execute(
            "UPDATE coaching_notes SET match_id=? WHERE id=?",
            ("../escape", note_id),
        )
        conn.commit()
    finally:
        conn.close()

    escape = await client.get(f"/api/coach/notes/{note_id}/thumbnail", headers=auth_headers)
    assert escape.status_code == 404, (
        "GET must refuse to serve a thumbnail whose computed path escapes VIDEOS_DIR"
    )


@pytest.mark.asyncio
async def test_thumbnail_regenerate_refuses_path_escape(client, auth_headers, data_dir, monkeypatch):
    """The regenerate endpoint must short-circuit (no ffmpeg call, no
    write) when the destination path would escape `VIDEOS_DIR`. The
    response shape matches the no-source-MP4 case so callers handle it
    identically."""
    import db as _db
    # Track ffmpeg invocations so we can assert the spawn never happened
    # for the escaping path.
    calls = await _install_thumbnail_stub(monkeypatch)
    match_resp = await client.post("/api/matches", json={
        "home_team": "OSU Steel", "away_team": "Regen Containment FC", "date": "2026-05-16",
    }, headers=auth_headers)
    match_id = match_resp.json()["id"]
    note_resp = await client.post("/api/coach/notes", json={
        "match_id": match_id, "slot": "full", "timestamp_seconds": 9.0,
        "title": "Containment regen", "category": "shape", "visibility": "team",
    }, headers=auth_headers)
    note_id = note_resp.json()["note"]["id"]
    await _drain_background_tasks()
    calls.clear()  # ignore the create-time spawn; we care about regenerate.

    # Mutate match_id to a traversal payload.
    conn = _db.connect()
    try:
        conn.execute(
            "UPDATE coaching_notes SET match_id=? WHERE id=?",
            ("../escape", note_id),
        )
        conn.commit()
    finally:
        conn.close()

    resp = await client.post(
        f"/api/coach/notes/{note_id}/thumbnail/regenerate", headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "generated": False}
    # ffmpeg stub must not have been invoked for the escaping path.
    assert calls == [], (
        f"Regenerate must short-circuit before invoking the generator on an escaping path "
        f"(got generator calls: {calls!r})"
    )


@pytest.mark.asyncio
async def test_thumb_path_within_videos_dir_helper(monkeypatch, tmp_path):
    """Unit-test the helper directly so the contract is locked in
    independently of the endpoint wiring."""
    import server as _server
    monkeypatch.setattr(_server, "VIDEOS_DIR", tmp_path)
    inside = tmp_path / "match-abc" / "coach_thumbs" / "1.jpg"
    outside = tmp_path.parent / "elsewhere" / "1.jpg"
    traversal = tmp_path / "match-abc" / ".." / ".." / "elsewhere" / "1.jpg"

    assert _server._thumb_path_within_videos_dir(inside) is True
    assert _server._thumb_path_within_videos_dir(outside) is False
    # `..`-laden path should resolve outside `tmp_path` and be rejected.
    assert _server._thumb_path_within_videos_dir(traversal) is False


# ---------------------------------------------------------------------------
# Phase 4a — Coaching clips
#
# Backend-only PR: schema + Pydantic models + /api/coach/clips* endpoints
# + clips embedded under /api/my-feedback. No UI, no MP4 export. Tests
# below pin down the visibility ladder (mirrors notes/playlists), the
# private-source-note privacy invariant (clips never auto-copy
# coach-private text), the duration cap, and the source-note default
# behavior.
# ---------------------------------------------------------------------------


async def _create_match_for_clips(client, headers, *, away="Test FC", date="2026-06-01") -> str:
    resp = await client.post("/api/matches", json={
        "home_team": "OSU Steel", "away_team": away, "date": date,
    }, headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


@pytest.mark.asyncio
async def test_clip_coach_can_create_list_update_delete(client, auth_headers):
    """Happy-path CRUD for the coach. Mirrors the note CRUD smoke test."""
    match_id = await _create_match_for_clips(client, auth_headers)

    # Create
    create_resp = await client.post("/api/coach/clips", json={
        "match_id": match_id, "slot": "full",
        "start_seconds": 12.0, "end_seconds": 32.0,
        "title": "Press triggers (early in match)",
        "description": "Three back-pass triggers in the first 5 minutes.",
        "category": "pressing", "visibility": "team",
    }, headers=auth_headers)
    assert create_resp.status_code == 200, create_resp.text
    clip = create_resp.json()["clip"]
    assert clip["title"] == "Press triggers (early in match)"
    assert clip["start_seconds"] == 12.0 and clip["end_seconds"] == 32.0
    assert clip["duration_seconds"] == 20.0
    assert clip["visibility"] == "team"
    assert clip["source_note_id"] is None

    # List
    list_resp = await client.get("/api/coach/clips", headers=auth_headers)
    assert list_resp.status_code == 200
    assert [c["id"] for c in list_resp.json()["clips"]] == [clip["id"]]

    # List with match filter
    other_match_id = await _create_match_for_clips(
        client, auth_headers, away="Other FC", date="2026-06-02"
    )
    filtered = await client.get(
        f"/api/coach/clips?match_id={other_match_id}", headers=auth_headers
    )
    assert filtered.json()["clips"] == []

    # Update
    update_resp = await client.patch(
        f"/api/coach/clips/{clip['id']}",
        json={"title": "Press triggers (renamed)", "end_seconds": 40.0},
        headers=auth_headers,
    )
    assert update_resp.status_code == 200, update_resp.text
    updated = update_resp.json()["clip"]
    assert updated["title"] == "Press triggers (renamed)"
    assert updated["end_seconds"] == 40.0
    assert updated["duration_seconds"] == 28.0

    # Get one
    get_resp = await client.get(f"/api/coach/clips/{clip['id']}", headers=auth_headers)
    assert get_resp.status_code == 200
    assert get_resp.json()["clip"]["title"] == "Press triggers (renamed)"

    # Delete
    del_resp = await client.delete(f"/api/coach/clips/{clip['id']}", headers=auth_headers)
    assert del_resp.status_code == 200
    assert (await client.get("/api/coach/clips", headers=auth_headers)).json()["clips"] == []


@pytest.mark.asyncio
async def test_clip_viewer_cannot_create_update_delete(client, auth_headers):
    """Backend access control: viewers can never write to /api/coach/clips."""
    await client.post("/api/users", json={
        "username": "viewer_clip_blocked", "password": "password123", "role": "viewer",
    }, headers=auth_headers)
    viewer_headers = await _login(client, "viewer_clip_blocked")

    match_id = await _create_match_for_clips(client, auth_headers)
    # Coach creates a clip first so we have something to attempt updating.
    coach_create = await client.post("/api/coach/clips", json={
        "match_id": match_id, "slot": "full",
        "start_seconds": 0.0, "end_seconds": 10.0,
        "title": "Test clip", "category": "other", "visibility": "team",
    }, headers=auth_headers)
    clip_id = coach_create.json()["clip"]["id"]

    # Viewer create → 403
    create_resp = await client.post("/api/coach/clips", json={
        "match_id": match_id, "slot": "full",
        "start_seconds": 0.0, "end_seconds": 10.0,
        "title": "Sneaky clip", "category": "other", "visibility": "team",
    }, headers=viewer_headers)
    assert create_resp.status_code == 403

    # Viewer list → 403
    assert (await client.get("/api/coach/clips", headers=viewer_headers)).status_code == 403

    # Viewer update → 403
    update_resp = await client.patch(
        f"/api/coach/clips/{clip_id}",
        json={"title": "Hijacked"},
        headers=viewer_headers,
    )
    assert update_resp.status_code == 403

    # Viewer delete → 403
    assert (await client.delete(f"/api/coach/clips/{clip_id}", headers=viewer_headers)).status_code == 403


@pytest.mark.asyncio
async def test_clip_my_feedback_team_visible_to_signed_in_viewer(client, auth_headers):
    """A `team` clip is visible to any signed-in viewer through /api/my-feedback."""
    await client.post("/api/users", json={
        "username": "feedback_team_viewer", "password": "password123", "role": "viewer",
    }, headers=auth_headers)
    match_id = await _create_match_for_clips(client, auth_headers, away="Team Vis FC")
    create_resp = await client.post("/api/coach/clips", json={
        "match_id": match_id, "slot": "full",
        "start_seconds": 5.0, "end_seconds": 25.0,
        "title": "Team-visible moment", "category": "shape", "visibility": "team",
    }, headers=auth_headers)
    clip_id = create_resp.json()["clip"]["id"]

    viewer_headers = await _login(client, "feedback_team_viewer")
    feedback_resp = await client.get("/api/my-feedback", headers=viewer_headers)
    assert feedback_resp.status_code == 200
    assert [c["id"] for c in feedback_resp.json()["clips"]] == [clip_id]


@pytest.mark.asyncio
async def test_clip_my_feedback_player_visibility(client, auth_headers):
    """A `player` clip is visible only to viewers linked to a tagged player.
    Unrelated viewers must NOT see it."""
    family_resp = await client.post("/api/users", json={
        "username": "clip_family", "password": "password123", "role": "viewer",
    }, headers=auth_headers)
    family_id = family_resp.json()["user"]["id"]
    await client.post("/api/users", json={
        "username": "clip_stranger", "password": "password123", "role": "viewer",
    }, headers=auth_headers)
    player_resp = await client.post("/api/coach/players", json={
        "display_name": "Sam Player", "jersey_number": "10",
    }, headers=auth_headers)
    player_id = player_resp.json()["player"]["id"]
    await client.post("/api/coach/player-links", json={
        "player_id": player_id, "user_id": family_id, "relationship": "parent",
    }, headers=auth_headers)

    match_id = await _create_match_for_clips(client, auth_headers, away="Player Vis FC")
    create_resp = await client.post("/api/coach/clips", json={
        "match_id": match_id, "slot": "full",
        "start_seconds": 0.0, "end_seconds": 12.0,
        "title": "Player-only moment", "category": "decision", "visibility": "player",
        "player_ids": [player_id],
    }, headers=auth_headers)
    clip_id = create_resp.json()["clip"]["id"]

    family_headers = await _login(client, "clip_family")
    stranger_headers = await _login(client, "clip_stranger")

    family_clips = (await client.get("/api/my-feedback", headers=family_headers)).json()["clips"]
    stranger_clips = (await client.get("/api/my-feedback", headers=stranger_headers)).json()["clips"]
    assert [c["id"] for c in family_clips] == [clip_id]
    assert stranger_clips == []


@pytest.mark.asyncio
async def test_clip_private_does_not_leak_to_viewer(client, auth_headers):
    """Private clips must NEVER reach My Feedback for any viewer (including
    a player who happens to be tagged on the clip)."""
    family_resp = await client.post("/api/users", json={
        "username": "private_clip_family", "password": "password123", "role": "viewer",
    }, headers=auth_headers)
    family_id = family_resp.json()["user"]["id"]
    player_resp = await client.post("/api/coach/players", json={
        "display_name": "Tagged Player", "jersey_number": "11",
    }, headers=auth_headers)
    player_id = player_resp.json()["player"]["id"]
    await client.post("/api/coach/player-links", json={
        "player_id": player_id, "user_id": family_id, "relationship": "parent",
    }, headers=auth_headers)

    match_id = await _create_match_for_clips(client, auth_headers, away="Private FC")
    await client.post("/api/coach/clips", json={
        "match_id": match_id, "slot": "full",
        "start_seconds": 1.0, "end_seconds": 11.0,
        "title": "Coach-only review", "category": "other", "visibility": "private",
        # Tagging the linked player MUST NOT escalate visibility past
        # `private` — that's the bug the Phase 1 / Phase 3a privacy
        # tests pinned for notes / thumbnails. Same rule applies to
        # clips.
        "player_ids": [player_id],
    }, headers=auth_headers)

    family_headers = await _login(client, "private_clip_family")
    feedback = (await client.get("/api/my-feedback", headers=family_headers)).json()
    assert feedback["clips"] == [], (
        "private clip must never reach a viewer, even if they're linked to a tagged player"
    )


@pytest.mark.asyncio
async def test_clip_source_note_does_not_leak_private_text(client, auth_headers):
    """When a clip is created from `source_note_id`, the source note's
    private text fields (body, coach_private_note, what_happened, etc.)
    must NOT be auto-copied into the clip — only match/slot/category +
    drawing-snapshot defaults are pulled in. The clip's own title /
    description come from the request body.

    This is the Phase 4a equivalent of the `_strip_private_fields`
    invariant: the clip endpoint creates a NEW visibility surface for
    the moment, and a coach-private note's text must not slip out
    through a more permissive clip visibility."""
    match_id = await _create_match_for_clips(client, auth_headers, away="Source FC")
    note_resp = await client.post("/api/coach/notes", json={
        "match_id": match_id, "slot": "full", "timestamp_seconds": 30.0,
        "title": "Private note title", "category": "other", "visibility": "private",
        "body": "Public-ish body text.",
        "coach_private_note": "TOP-SECRET coach observation",
        "what_happened": "Specific tactical context coach notes only.",
    }, headers=auth_headers)
    note_id = note_resp.json()["note"]["id"]

    # Coach explicitly requests team visibility on the new clip,
    # against a clip title they wrote (not the private note's title).
    create_resp = await client.post("/api/coach/clips", json={
        "match_id": match_id, "slot": "full",
        "start_seconds": 25.0, "end_seconds": 45.0,
        "title": "Team-shareable clip", "description": "",
        "category": "pressing", "visibility": "team",
        "source_note_id": note_id,
    }, headers=auth_headers)
    assert create_resp.status_code == 200, create_resp.text
    clip = create_resp.json()["clip"]

    # The clip retains its own title — NOT the source note's private title.
    assert clip["title"] == "Team-shareable clip"
    assert clip["description"] == ""
    # And the clip carries no field that re-publishes the source's
    # text. (We don't even *store* `body` / `coach_private_note` on
    # clips — this is structural, not just runtime — but verify the
    # response payload too as belt-and-braces.)
    forbidden_text_substrings = [
        "TOP-SECRET", "coach observation",
        "Public-ish body text",
        "Specific tactical context",
        "Private note title",
    ]
    serialized = str(clip)
    for forbidden in forbidden_text_substrings:
        assert forbidden not in serialized, (
            f"clip response leaked source-note text: {forbidden!r}"
        )

    # source_note_id reference is preserved.
    assert clip["source_note_id"] == note_id


@pytest.mark.asyncio
async def test_clip_source_note_drawing_default(client, auth_headers):
    """When a clip is seeded from `source_note_id` and `drawing` is empty,
    the server defaults the clip's drawing to a SNAPSHOT of the source's
    drawing. The clip stores its own copy so a later note edit/delete
    doesn't strand the clip without context."""
    match_id = await _create_match_for_clips(client, auth_headers, away="Drawing FC")
    note_drawing = {
        "version": 2,
        "objects": [
            {"type": "arrow", "color": "#38bdf8", "width": 4,
             "x1": 0.1, "y1": 0.2, "x2": 0.4, "y2": 0.5},
        ],
    }
    note_resp = await client.post("/api/coach/notes", json={
        "match_id": match_id, "slot": "full", "timestamp_seconds": 30.0,
        "title": "Note with drawing", "category": "shape", "visibility": "team",
        "drawing": note_drawing,
    }, headers=auth_headers)
    note_id = note_resp.json()["note"]["id"]

    create_resp = await client.post("/api/coach/clips", json={
        "match_id": match_id, "slot": "full",
        "start_seconds": 28.0, "end_seconds": 38.0,
        "title": "Clip from drawn note", "category": "shape", "visibility": "team",
        "source_note_id": note_id,
    }, headers=auth_headers)
    clip = create_resp.json()["clip"]
    assert clip["drawing"]["version"] == 2
    assert clip["drawing"]["objects"][0]["type"] == "arrow"

    # Now delete the source note. The clip should remain valid.
    assert (await client.delete(
        f"/api/coach/notes/{note_id}", headers=auth_headers,
    )).status_code == 200
    after = (await client.get(
        f"/api/coach/clips/{clip['id']}", headers=auth_headers,
    )).json()["clip"]
    # Clip drawing snapshot is intact.
    assert after["drawing"]["version"] == 2
    # The source_note_id FK is now NULL (ON DELETE SET NULL).
    assert after["source_note_id"] is None


@pytest.mark.asyncio
async def test_clip_invalid_window_rejected(client, auth_headers):
    """Pydantic-level rejections: end <= start, duration > 120s, negative
    start, etc. All should land as 422 from FastAPI's request-body
    validator without ever creating a row."""
    match_id = await _create_match_for_clips(client, auth_headers, away="Validation FC")

    # end == start → rejected
    resp = await client.post("/api/coach/clips", json={
        "match_id": match_id, "slot": "full",
        "start_seconds": 5.0, "end_seconds": 5.0,
        "title": "Bad", "category": "other", "visibility": "team",
    }, headers=auth_headers)
    assert resp.status_code == 422

    # end < start → rejected
    resp = await client.post("/api/coach/clips", json={
        "match_id": match_id, "slot": "full",
        "start_seconds": 10.0, "end_seconds": 5.0,
        "title": "Bad", "category": "other", "visibility": "team",
    }, headers=auth_headers)
    assert resp.status_code == 422

    # duration > 120s → rejected (MVP cap)
    resp = await client.post("/api/coach/clips", json={
        "match_id": match_id, "slot": "full",
        "start_seconds": 0.0, "end_seconds": 150.0,
        "title": "Too long", "category": "other", "visibility": "team",
    }, headers=auth_headers)
    assert resp.status_code == 422

    # negative start → rejected
    resp = await client.post("/api/coach/clips", json={
        "match_id": match_id, "slot": "full",
        "start_seconds": -1.0, "end_seconds": 10.0,
        "title": "Negative", "category": "other", "visibility": "team",
    }, headers=auth_headers)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_clip_invalid_visibility_and_slot_and_category(client, auth_headers):
    """Enum guards mirror the note model's. Each invalid value lands as 422
    with a message naming the offending field."""
    match_id = await _create_match_for_clips(client, auth_headers, away="Enum FC")

    for body, field in [
        ({"slot": "extra_time"}, "slot"),
        ({"visibility": "public"}, "visibility"),
        ({"category": "skills"}, "category"),
    ]:
        payload = {
            "match_id": match_id, "slot": "full",
            "start_seconds": 0.0, "end_seconds": 10.0,
            "title": "Test", "category": "other", "visibility": "team",
        }
        payload.update(body)
        resp = await client.post("/api/coach/clips", json=payload, headers=auth_headers)
        assert resp.status_code == 422, f"{field} should be rejected"
        assert field in resp.text


@pytest.mark.asyncio
async def test_clip_invalid_match_player_source_note_handled(client, auth_headers):
    """Unknown FK references return 404, not 500."""
    match_id = await _create_match_for_clips(client, auth_headers, away="FK FC")

    # Unknown match_id → 404
    resp = await client.post("/api/coach/clips", json={
        "match_id": "no-such-match", "slot": "full",
        "start_seconds": 0.0, "end_seconds": 10.0,
        "title": "Test", "category": "other", "visibility": "team",
    }, headers=auth_headers)
    assert resp.status_code == 404

    # Unknown player_id → 404
    resp = await client.post("/api/coach/clips", json={
        "match_id": match_id, "slot": "full",
        "start_seconds": 0.0, "end_seconds": 10.0,
        "title": "Test", "category": "other", "visibility": "player",
        "player_ids": ["nonexistent-player-id"],
    }, headers=auth_headers)
    assert resp.status_code == 404

    # Unknown source_note_id → 404
    resp = await client.post("/api/coach/clips", json={
        "match_id": match_id, "slot": "full",
        "start_seconds": 0.0, "end_seconds": 10.0,
        "title": "Test", "category": "other", "visibility": "team",
        "source_note_id": 9999999,
    }, headers=auth_headers)
    assert resp.status_code == 404

    # Update of unknown clip → 404
    resp = await client.patch("/api/coach/clips/9999999", json={"title": "x"}, headers=auth_headers)
    assert resp.status_code == 404
    # Get of unknown clip → 404
    resp = await client.get("/api/coach/clips/9999999", headers=auth_headers)
    assert resp.status_code == 404
    # Delete of unknown clip → 404
    resp = await client.delete("/api/coach/clips/9999999", headers=auth_headers)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_clip_update_window_invariants(client, auth_headers):
    """The PATCH endpoint must enforce the same end>start and ≤120s
    invariants when only one endpoint is modified (Pydantic only catches
    the both-fields-supplied case; the route handler closes the gap by
    merging against the existing row)."""
    match_id = await _create_match_for_clips(client, auth_headers, away="Patch FC")
    create = await client.post("/api/coach/clips", json={
        "match_id": match_id, "slot": "full",
        "start_seconds": 10.0, "end_seconds": 30.0,
        "title": "Existing", "category": "other", "visibility": "team",
    }, headers=auth_headers)
    clip_id = create.json()["clip"]["id"]

    # Move start past the existing end → 422 from route handler
    resp = await client.patch(
        f"/api/coach/clips/{clip_id}",
        json={"start_seconds": 35.0},
        headers=auth_headers,
    )
    assert resp.status_code == 422
    assert "end_seconds must be greater than start_seconds" in resp.text

    # Stretch end so duration > 120s → 422
    resp = await client.patch(
        f"/api/coach/clips/{clip_id}",
        json={"end_seconds": 200.0},
        headers=auth_headers,
    )
    assert resp.status_code == 422
    assert "120 seconds" in resp.text


@pytest.mark.asyncio
async def test_clip_unauthenticated_blocked(client):
    """No-auth requests to coach clip endpoints get 401, not 403 or 500.
    The /api/my-feedback endpoint also requires auth, so anonymous
    requests there can't probe clip existence either."""
    assert (await client.get("/api/coach/clips")).status_code in (401, 403)
    assert (await client.post("/api/coach/clips", json={
        "match_id": "x", "slot": "full",
        "start_seconds": 0.0, "end_seconds": 1.0, "title": "x",
    })).status_code in (401, 403)
    assert (await client.get("/api/my-feedback")).status_code in (401, 403)


@pytest.mark.asyncio
async def test_clip_admin_only_visibility_in_my_feedback_for_coach(client, auth_headers):
    """The admin/coach call to /api/my-feedback should still see clips
    (admins inherit coach role and can call this surface)."""
    match_id = await _create_match_for_clips(client, auth_headers, away="Admin FC")
    create = await client.post("/api/coach/clips", json={
        "match_id": match_id, "slot": "full",
        "start_seconds": 0.0, "end_seconds": 5.0,
        "title": "For admin view", "category": "other", "visibility": "private",
    }, headers=auth_headers)
    clip_id = create.json()["clip"]["id"]

    feedback = (await client.get("/api/my-feedback", headers=auth_headers)).json()
    assert clip_id in {c["id"] for c in feedback["clips"]}, (
        "admin/coach should see private clips in their own /api/my-feedback view"
    )
