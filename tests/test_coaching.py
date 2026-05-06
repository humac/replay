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


# ---------------------------------------------------------------------------
# Phase 4a — PR #95 review follow-up regressions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_clip_player_only_patch_bumps_updated_at(client, auth_headers, monkeypatch):
    """A PATCH that changes ONLY `player_ids` (no scalar field, no
    drawing) must still bump `updated_at` on the clip row, so the
    clip surfaces correctly in `ORDER BY updated_at` lists.

    Pre-fix: `update_coaching_clip`'s `len(updates) > 1` guard
    skipped the UPDATE statement entirely when only `player_ids`
    changed (the `updates` dict at that point only contained
    `updated_at` itself, length 1). The join table was rewritten
    but the row's timestamp stayed stale.

    `_now_iso()` only resolves to seconds, so we monkeypatch a
    deterministic counter so each call returns a distinct timestamp
    without slowing the test with real-time sleeps.
    """
    import db as _db
    counter = {"n": 0}
    def fake_now():
        counter["n"] += 1
        return f"2026-06-10T00:00:{counter['n']:02d}Z"
    monkeypatch.setattr(_db, "_now_iso", fake_now)

    match_resp = await client.post("/api/matches", json={
        "home_team": "OSU Steel", "away_team": "Updated FC", "date": "2026-06-10",
    }, headers=auth_headers)
    match_id = match_resp.json()["id"]
    player_resp = await client.post("/api/coach/players", json={
        "display_name": "Roster Player", "jersey_number": "5",
    }, headers=auth_headers)
    player_id = player_resp.json()["player"]["id"]

    create = await client.post("/api/coach/clips", json={
        "match_id": match_id, "slot": "full",
        "start_seconds": 0.0, "end_seconds": 10.0,
        "title": "Existing", "category": "other", "visibility": "team",
    }, headers=auth_headers)
    clip = create.json()["clip"]
    initial_updated_at = clip["updated_at"]

    patch = await client.patch(
        f"/api/coach/clips/{clip['id']}",
        json={"player_ids": [player_id]},
        headers=auth_headers,
    )
    assert patch.status_code == 200, patch.text
    after = patch.json()["clip"]
    assert after["player_ids"] == [player_id], "player relationship should be updated"
    assert after["updated_at"] != initial_updated_at, (
        f"updated_at must advance on a player-only PATCH "
        f"(was {initial_updated_at}, still {after['updated_at']})"
    )


@pytest.mark.asyncio
async def test_note_player_only_patch_bumps_updated_at(client, auth_headers, monkeypatch):
    """Phase 1 parity fix: same `updated_at` bump applies to coaching
    notes when only `player_ids` or `tags` changes. `_now_iso()` only
    resolves to seconds, so we monkeypatch a deterministic counter."""
    import db as _db
    counter = {"n": 0}
    def fake_now():
        counter["n"] += 1
        return f"2026-06-11T00:00:{counter['n']:02d}Z"
    monkeypatch.setattr(_db, "_now_iso", fake_now)

    match_resp = await client.post("/api/matches", json={
        "home_team": "OSU Steel", "away_team": "Note Updated FC", "date": "2026-06-11",
    }, headers=auth_headers)
    match_id = match_resp.json()["id"]
    player_resp = await client.post("/api/coach/players", json={
        "display_name": "Note Roster", "jersey_number": "8",
    }, headers=auth_headers)
    player_id = player_resp.json()["player"]["id"]

    note_resp = await client.post("/api/coach/notes", json={
        "match_id": match_id, "slot": "full", "timestamp_seconds": 12.0,
        "title": "Note for player-only PATCH", "category": "other", "visibility": "team",
    }, headers=auth_headers)
    note = note_resp.json()["note"]
    initial_updated_at = note["updated_at"]

    # player_ids-only change
    patch_p = await client.patch(
        f"/api/coach/notes/{note['id']}",
        json={"player_ids": [player_id]},
        headers=auth_headers,
    )
    assert patch_p.status_code == 200
    after_p = patch_p.json()["note"]
    assert after_p["player_ids"] == [player_id]
    assert after_p["updated_at"] != initial_updated_at, (
        "note updated_at must advance on player-only PATCH"
    )

    # tags-only change should ALSO bump updated_at
    second_stamp = after_p["updated_at"]
    patch_t = await client.patch(
        f"/api/coach/notes/{note['id']}",
        json={"tags": ["receiving"]},
        headers=auth_headers,
    )
    assert patch_t.status_code == 200
    after_t = patch_t.json()["note"]
    assert after_t["tags"] == ["receiving"]
    assert after_t["updated_at"] != second_stamp, (
        "note updated_at must advance on tags-only PATCH"
    )


@pytest.mark.asyncio
async def test_delete_player_cleans_coaching_clip_players(client, auth_headers):
    """When a roster player is deleted, the join rows in
    `coaching_clip_players` must be removed too — otherwise we leave
    orphan FK references that point at a non-existent player_id.

    Pre-fix: `delete_player` only cleaned `coaching_note_players` and
    `coaching_playlist_players`, missing the new (Phase 4a) clips
    join table. SQLite's `ON DELETE CASCADE` on that table requires
    `PRAGMA foreign_keys = ON`, which this codebase doesn't enable —
    so the manual cleanup is the only safety net.
    """
    import db as _db

    match_resp = await client.post("/api/matches", json={
        "home_team": "OSU Steel", "away_team": "Player Cleanup FC", "date": "2026-06-12",
    }, headers=auth_headers)
    match_id = match_resp.json()["id"]
    player_resp = await client.post("/api/coach/players", json={
        "display_name": "About-to-delete", "jersey_number": "99",
    }, headers=auth_headers)
    player_id = player_resp.json()["player"]["id"]

    clip_resp = await client.post("/api/coach/clips", json={
        "match_id": match_id, "slot": "full",
        "start_seconds": 0.0, "end_seconds": 8.0,
        "title": "Tagged with deletable player", "category": "other",
        "visibility": "player", "player_ids": [player_id],
    }, headers=auth_headers)
    clip_id = clip_resp.json()["clip"]["id"]

    # Sanity: the join row exists at first.
    conn = _db.connect()
    rows = conn.execute(
        "SELECT player_id FROM coaching_clip_players WHERE clip_id = ?", (clip_id,)
    ).fetchall()
    assert [r["player_id"] for r in rows] == [player_id], (
        "test setup: clip should be joined to the player before deletion"
    )

    # Delete the player.
    del_resp = await client.delete(
        f"/api/coach/players/{player_id}", headers=auth_headers,
    )
    assert del_resp.status_code == 200, del_resp.text

    # Join rows must be gone.
    conn = _db.connect()
    rows_after = conn.execute(
        "SELECT player_id FROM coaching_clip_players WHERE clip_id = ?", (clip_id,)
    ).fetchall()
    assert rows_after == [], (
        "deleting a player must remove all coaching_clip_players rows for that "
        "player; orphan rows would point at a non-existent player_id"
    )

    # The clip itself remains (with empty player_ids hydrated).
    clip_after = (await client.get(
        f"/api/coach/clips/{clip_id}", headers=auth_headers,
    )).json()["clip"]
    assert clip_after["player_ids"] == [], (
        "clip's player_ids should hydrate as empty after the only tagged player was deleted"
    )


# ---------------------------------------------------------------------------
# Phase 5a — Player development profile aggregation
# ---------------------------------------------------------------------------


async def _seed_dev_profile_fixture(client, auth_headers):
    """Build a small but realistic data set for development-profile
    tests: one match, one rostered player, a viewer linked to that
    player, an unrelated viewer, and a mix of notes/clips/playlists at
    different visibilities and note_types so the aggregation paths are
    actually exercised."""
    match_resp = await client.post("/api/matches", json={
        "home_team": "Steel", "away_team": "Riverside", "date": "2026-05-20",
    }, headers=auth_headers)
    match_id = match_resp.json()["id"]

    player_resp = await client.post("/api/coach/players", json={
        "display_name": "Ava Dev", "jersey_number": "9",
    }, headers=auth_headers)
    player_id = player_resp.json()["player"]["id"]

    other_player_resp = await client.post("/api/coach/players", json={
        "display_name": "Other Dev", "jersey_number": "12",
    }, headers=auth_headers)
    other_player_id = other_player_resp.json()["player"]["id"]

    linked_user_resp = await client.post("/api/users", json={
        "username": "dev_family_linked", "password": "password123", "role": "viewer",
    }, headers=auth_headers)
    linked_user_id = linked_user_resp.json()["user"]["id"]
    await client.post("/api/coach/player-links", json={
        "player_id": player_id, "user_id": linked_user_id, "relationship": "parent",
    }, headers=auth_headers)

    await client.post("/api/users", json={
        "username": "dev_family_other", "password": "password123", "role": "viewer",
    }, headers=auth_headers)

    notes: dict[str, int] = {}
    payloads = [
        {
            "title": "Great body shape", "note_type": "positive",
            "category": "shape", "visibility": "team", "tags": ["receiving"],
            "what_to_do_next": "Keep doing this", "player_summary": "Nice shape!",
        },
        {
            "title": "Scan before receiving", "note_type": "correction",
            "category": "decision", "visibility": "player",
            "tags": ["scan"], "what_to_do_next": "Check shoulder twice before the pass",
        },
        {
            "title": "Why did you cross there?", "note_type": "question",
            "category": "decision", "visibility": "player",
            "tags": ["scan"], "what_to_do_next": "",
        },
        {
            "title": "Recovery run shape", "note_type": "team_concept",
            "category": "transition", "visibility": "team",
            "tags": ["transition"], "what_to_do_next": "",
        },
        {
            "title": "Goal: scan twice before receiving", "note_type": "individual_goal",
            "category": "decision", "visibility": "player",
            "tags": ["scan"], "what_to_do_next": "Scan twice every reception this week",
        },
        {
            "title": "Private coach thought", "note_type": "correction",
            "category": "shape", "visibility": "private", "tags": [],
            "coach_private_note": "Talk to parents about confidence",
            "what_to_do_next": "Coach-only follow up",
        },
    ]
    for p in payloads:
        body = {
            "match_id": match_id, "slot": "full", "timestamp_seconds": 30.0,
            "title": p["title"], "body": "...", "category": p["category"],
            "visibility": p["visibility"], "player_ids": [player_id],
            "tags": p.get("tags", []), "note_type": p["note_type"],
            "what_to_do_next": p.get("what_to_do_next", ""),
            "player_summary": p.get("player_summary", ""),
            "coach_private_note": p.get("coach_private_note", ""),
        }
        resp = await client.post("/api/coach/notes", json=body, headers=auth_headers)
        assert resp.status_code == 200, resp.text
        notes[p["title"]] = resp.json()["note"]["id"]

    # Note targeting only the OTHER player so we can verify the
    # development profile excludes it.
    await client.post("/api/coach/notes", json={
        "match_id": match_id, "slot": "full", "timestamp_seconds": 60.0,
        "title": "Other player only", "body": "...", "category": "other",
        "visibility": "team", "player_ids": [other_player_id],
        "note_type": "positive",
    }, headers=auth_headers)

    # A clip on the focal player (team-visible) and a private clip that
    # must NOT appear on the viewer surface.
    clip_team = await client.post("/api/coach/clips", json={
        "match_id": match_id, "slot": "full",
        "start_seconds": 10.0, "end_seconds": 18.0,
        "title": "Body shape clip", "category": "shape",
        "visibility": "team", "player_ids": [player_id],
    }, headers=auth_headers)
    assert clip_team.status_code == 200, clip_team.text
    clip_private = await client.post("/api/coach/clips", json={
        "match_id": match_id, "slot": "full",
        "start_seconds": 22.0, "end_seconds": 28.0,
        "title": "Private clip", "category": "other",
        "visibility": "private", "player_ids": [player_id],
    }, headers=auth_headers)
    assert clip_private.status_code == 200

    # A team-visible playlist that includes the player's correction note,
    # plus a private playlist tagged with the player.
    pl_team = await client.post("/api/coach/playlists", json={
        "title": "Scanning improvements", "description": "",
        "visibility": "team", "player_ids": [player_id],
        "note_ids": [notes["Scan before receiving"]],
    }, headers=auth_headers)
    assert pl_team.status_code == 200
    pl_private = await client.post("/api/coach/playlists", json={
        "title": "Coach private playlist", "description": "",
        "visibility": "private", "player_ids": [player_id],
        "note_ids": [],
    }, headers=auth_headers)
    assert pl_private.status_code == 200

    return {
        "match_id": match_id,
        "player_id": player_id,
        "other_player_id": other_player_id,
        "notes": notes,
    }


@pytest.mark.asyncio
async def test_dev_profile_coach_returns_full_aggregation(client, auth_headers):
    fx = await _seed_dev_profile_fixture(client, auth_headers)
    resp = await client.get(
        f"/api/coach/players/{fx['player_id']}/development",
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    profile = resp.json()["profile"]

    # Player object surfaces the coach-side linked-accounts summary.
    assert profile["player"]["display_name"] == "Ava Dev"
    assert profile["viewer_scoped"] is False
    assert profile["linked_accounts"]
    assert profile["linked_accounts"][0]["username"] == "dev_family_linked"
    assert profile["linked_accounts"][0]["relationship"] == "parent"

    # Aggregation includes ALL six notes assigned to this player —
    # the seventh note is on the other roster player so it must be
    # excluded.
    assert profile["counts"]["notes"] == 6
    by_type = profile["themes"]["by_note_type"]
    assert by_type["positive"] == 1
    assert by_type["correction"] == 2  # team-correction + private-correction
    assert by_type["question"] == 1
    assert by_type["team_concept"] == 1
    assert by_type["individual_goal"] == 1
    assert profile["themes"]["positive_to_correction_ratio"] == 0.5

    # Top categories/tags include the player's notes only.
    cat_top = {row["value"] for row in profile["themes"]["top_categories"]}
    assert "decision" in cat_top
    tag_top = {row["value"] for row in profile["themes"]["top_tags"]}
    assert "scan" in tag_top

    # Recent positives / corrections are bucketed correctly.
    recent_pos_titles = [n["title"] for n in profile["recent_positives"]]
    assert recent_pos_titles == ["Great body shape"]
    recent_cor_titles = [n["title"] for n in profile["recent_corrections"]]
    assert "Scan before receiving" in recent_cor_titles
    assert "Private coach thought" in recent_cor_titles

    # Coach surface MUST surface coach_private_note text since the raw
    # note list is used (mirrors `_filter_notes_for_user` short-circuit
    # for privileged users). Otherwise Phase 5a would silently regress
    # the coach's existing access.
    private_match = [
        n for n in profile["recent_notes"]
        if n.get("title") == "Private coach thought"
    ]
    assert private_match
    assert private_match[0]["coach_private_note"] == "Talk to parents about confidence"

    # Clips: both the team and private clip count for the coach.
    assert profile["counts"]["clips"] == 2
    clip_titles = {c["title"] for c in profile["recent_clips"]}
    assert clip_titles == {"Body shape clip", "Private clip"}

    # Playlists: both team and private playlist appear.
    pl_titles = {p["title"] for p in profile["recent_playlists"]}
    assert pl_titles == {"Scanning improvements", "Coach private playlist"}

    # Focus areas come from recent correction / individual_goal notes
    # with a non-empty `what_to_do_next`.
    focus_titles = [f["what_to_do_next"] for f in profile["current_focus_areas"]]
    assert any("Scan twice" in t for t in focus_titles)
    assert any("Check shoulder" in t for t in focus_titles)
    assert all(f["source"] == "derived_from_recent_notes" for f in profile["current_focus_areas"])

    # Review-status structure exists with clip-not-supported flag set.
    assert profile["review_status"]["clips"]["review_supported"] is False
    assert profile["review_status"]["clips"]["assigned_count"] == 2


@pytest.mark.asyncio
async def test_dev_profile_coach_404_for_unknown_player(client, auth_headers):
    resp = await client.get(
        "/api/coach/players/does-not-exist/development",
        headers=auth_headers,
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_dev_profile_coach_endpoint_blocks_viewer(client, auth_headers):
    fx = await _seed_dev_profile_fixture(client, auth_headers)
    viewer_headers = await _login(client, "dev_family_other")
    resp = await client.get(
        f"/api/coach/players/{fx['player_id']}/development",
        headers=viewer_headers,
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_dev_profile_viewer_linked_user_sees_visible_only(client, auth_headers):
    fx = await _seed_dev_profile_fixture(client, auth_headers)
    linked_headers = await _login(client, "dev_family_linked")
    resp = await client.get(
        f"/api/my-feedback/players/{fx['player_id']}/development",
        headers=linked_headers,
    )
    assert resp.status_code == 200, resp.text
    profile = resp.json()["profile"]

    assert profile["viewer_scoped"] is True
    # Linked accounts is a coach-only field — viewer endpoint omits it.
    assert "linked_accounts" not in profile

    # Of the six player-tagged notes, the viewer can see only the
    # team-visible note plus the player-visible notes — five total —
    # because the private note is filtered out.
    visible_titles = {n["title"] for n in profile["recent_notes"]}
    assert "Private coach thought" not in visible_titles
    assert "Great body shape" in visible_titles
    assert "Scan before receiving" in visible_titles
    assert profile["counts"]["notes"] == 5

    # `coach_private_note` must be scrubbed even on notes the viewer
    # can see — defense-in-depth at the development-profile layer
    # mirroring `_filter_notes_for_user`'s `_strip_private_fields`.
    for n in profile["recent_notes"]:
        assert n.get("coach_private_note", "") == ""

    # Clips: only the team-visible clip is visible to the viewer.
    assert profile["counts"]["clips"] == 1
    assert [c["title"] for c in profile["recent_clips"]] == ["Body shape clip"]

    # Playlists: only the team-visible playlist surfaces.
    pl_titles = [p["title"] for p in profile["recent_playlists"]]
    assert pl_titles == ["Scanning improvements"]

    # Theme counts aggregate over visible notes only.
    by_type = profile["themes"]["by_note_type"]
    # Visible: 1 positive, 1 correction (the team-correction-via-tags),
    # 1 question, 1 team_concept, 1 individual_goal — totals to 5.
    assert by_type["positive"] == 1
    assert by_type["correction"] == 1
    assert sum(by_type.values()) == 5


@pytest.mark.asyncio
async def test_dev_profile_viewer_unrelated_user_returns_404(client, auth_headers):
    fx = await _seed_dev_profile_fixture(client, auth_headers)
    other_headers = await _login(client, "dev_family_other")
    resp = await client.get(
        f"/api/my-feedback/players/{fx['player_id']}/development",
        headers=other_headers,
    )
    # 404 (not 403) so an unrelated viewer cannot probe whether a roster
    # id exists. Same shape as "unknown player".
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_dev_profile_viewer_unknown_player_returns_404(client, auth_headers):
    await _seed_dev_profile_fixture(client, auth_headers)
    linked_headers = await _login(client, "dev_family_linked")
    resp = await client.get(
        "/api/my-feedback/players/does-not-exist/development",
        headers=linked_headers,
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_dev_profile_viewer_review_scoped_to_signed_in_user(client, auth_headers):
    fx = await _seed_dev_profile_fixture(client, auth_headers)
    linked_headers = await _login(client, "dev_family_linked")

    # Mark a note review as the linked viewer.
    visible_note_id = fx["notes"]["Scan before receiving"]
    review_resp = await client.post("/api/my-feedback/review", json={
        "note_id": visible_note_id,
        "reflection": "I'll scan twice this week",
    }, headers=linked_headers)
    assert review_resp.status_code == 200

    resp = await client.get(
        f"/api/my-feedback/players/{fx['player_id']}/development",
        headers=linked_headers,
    )
    profile = resp.json()["profile"]
    rs = profile["review_status"]
    assert rs["notes"]["reviewed_count"] == 1
    assert rs["reflection_count"] == 1
    assert rs["latest_reflection"]["reflection"] == "I'll scan twice this week"
    assert rs["clips"]["review_supported"] is False


@pytest.mark.asyncio
async def test_dev_profile_empty_player_returns_zero_counts(client, auth_headers):
    """A roster player with no notes/clips/playlists must return empty
    arrays + zero counts, not 500."""
    player_resp = await client.post("/api/coach/players", json={
        "display_name": "Bench Warmer", "jersey_number": "13",
    }, headers=auth_headers)
    pid = player_resp.json()["player"]["id"]
    resp = await client.get(
        f"/api/coach/players/{pid}/development",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    profile = resp.json()["profile"]
    assert profile["counts"] == {"notes": 0, "clips": 0, "playlists": 0}
    assert profile["recent_notes"] == []
    assert profile["recent_clips"] == []
    assert profile["recent_playlists"] == []
    assert profile["current_focus_areas"] == []
    assert profile["themes"]["positive_to_correction_ratio"] is None


# ---------------------------------------------------------------------------
# Phase 5a — Targeted regression tests (PR #103 review follow-up)
#
# The original 8 tests cover happy-path aggregation + the privacy ladder.
# These three pin behaviors that were verified at runtime during code
# review but not directly asserted at the test layer:
#
#   1. corrections=0 -> positive_to_correction_ratio is None
#   2. A playlist with NO explicit `player_ids` but containing an ordered
#      note item tagged with the player IS included in the profile.
#   3. A viewer-side playlist whose only player-related note item is
#      `visibility: private` is excluded from the viewer profile (because
#      the private note has been filtered out before the playlist
#      association check runs, so the playlist no longer "matches" the
#      player from the viewer's perspective).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dev_profile_zero_corrections_yields_null_ratio(client, auth_headers):
    """1 positive + 0 corrections -> ratio MUST be null (not 0, not Inf).
    The empty-player test pins the all-zeros case; this one covers the
    "all positive, no correction baseline" branch in `_theme_counts`."""
    match_resp = await client.post("/api/matches", json={
        "home_team": "Ratio FC", "away_team": "Null Town", "date": "2026-05-22",
    }, headers=auth_headers)
    match_id = match_resp.json()["id"]
    player_resp = await client.post("/api/coach/players", json={
        "display_name": "Positive-only Player", "jersey_number": "7",
    }, headers=auth_headers)
    pid = player_resp.json()["player"]["id"]

    note_resp = await client.post("/api/coach/notes", json={
        "match_id": match_id, "slot": "full", "timestamp_seconds": 5.0,
        "title": "Only positive", "category": "shape",
        "visibility": "team", "player_ids": [pid], "note_type": "positive",
    }, headers=auth_headers)
    assert note_resp.status_code == 200, note_resp.text

    resp = await client.get(
        f"/api/coach/players/{pid}/development", headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    themes = resp.json()["profile"]["themes"]
    assert themes["positive_count"] == 1
    assert themes["correction_count"] == 0
    # JSON-encoded as `null` — Python decodes it to None.
    assert themes["positive_to_correction_ratio"] is None


@pytest.mark.asyncio
async def test_dev_profile_playlist_included_via_ordered_note_items_only(client, auth_headers):
    """A playlist with empty `player_ids` but containing an ordered note
    item tagged with the player must surface in the profile. This is
    the "playlist about a teaching theme that happens to involve the
    player" path documented in the playlist association rule."""
    match_resp = await client.post("/api/matches", json={
        "home_team": "Pl FC", "away_team": "Items Only", "date": "2026-05-23",
    }, headers=auth_headers)
    match_id = match_resp.json()["id"]
    player_resp = await client.post("/api/coach/players", json={
        "display_name": "Indirect Player", "jersey_number": "21",
    }, headers=auth_headers)
    pid = player_resp.json()["player"]["id"]

    note_resp = await client.post("/api/coach/notes", json={
        "match_id": match_id, "slot": "full", "timestamp_seconds": 12.0,
        "title": "Player-tagged note", "category": "shape",
        "visibility": "team", "player_ids": [pid], "note_type": "correction",
    }, headers=auth_headers)
    note_id = note_resp.json()["note"]["id"]

    # Playlist explicitly has NO `player_ids` — only its ordered note
    # items connect it to the player.
    pl_resp = await client.post("/api/coach/playlists", json={
        "title": "Theme playlist (no explicit player tag)",
        "description": "", "visibility": "team",
        "player_ids": [], "note_ids": [note_id],
    }, headers=auth_headers)
    assert pl_resp.status_code == 200, pl_resp.text

    resp = await client.get(
        f"/api/coach/players/{pid}/development", headers=auth_headers,
    )
    profile = resp.json()["profile"]
    assert profile["counts"]["playlists"] == 1
    titles = [p["title"] for p in profile["recent_playlists"]]
    assert titles == ["Theme playlist (no explicit player tag)"]


@pytest.mark.asyncio
async def test_dev_profile_viewer_excludes_playlist_with_only_private_player_item(client, auth_headers):
    """If a playlist's ONLY player-tagged item is a private note, then
    on the viewer surface the private note is filtered out before the
    playlist association check runs — so from the viewer's perspective
    the playlist has no matching item and must NOT surface in their
    development profile.

    The playlist itself is `team`-visible (so it's reachable as a
    playlist), but it should not be classified as "for this player"
    from the viewer's perspective because the only thing connecting
    it to the player is invisible to them."""
    viewer_resp = await client.post("/api/users", json={
        "username": "playlist_private_only_viewer",
        "password": "password123", "role": "viewer",
    }, headers=auth_headers)
    linked_user_id = viewer_resp.json()["user"]["id"]

    player_resp = await client.post("/api/coach/players", json={
        "display_name": "Private-Item Player", "jersey_number": "33",
    }, headers=auth_headers)
    pid = player_resp.json()["player"]["id"]

    await client.post("/api/coach/player-links", json={
        "player_id": pid, "user_id": linked_user_id, "relationship": "parent",
    }, headers=auth_headers)

    match_resp = await client.post("/api/matches", json={
        "home_team": "Hidden FC", "away_team": "Visible FC", "date": "2026-05-24",
    }, headers=auth_headers)
    match_id = match_resp.json()["id"]

    # The ONLY player-tagged note in the playlist is private.
    private_note_resp = await client.post("/api/coach/notes", json={
        "match_id": match_id, "slot": "full", "timestamp_seconds": 8.0,
        "title": "Private player-tagged note", "category": "shape",
        "visibility": "private", "player_ids": [pid], "note_type": "correction",
    }, headers=auth_headers)
    private_note_id = private_note_resp.json()["note"]["id"]

    # Add a second item that's team-visible but tagged with a different
    # player so the viewer can reach the playlist itself but cannot see
    # any item that ties it back to THIS player.
    other_player_resp = await client.post("/api/coach/players", json={
        "display_name": "Other Indirect", "jersey_number": "44",
    }, headers=auth_headers)
    other_pid = other_player_resp.json()["player"]["id"]
    other_note_resp = await client.post("/api/coach/notes", json={
        "match_id": match_id, "slot": "full", "timestamp_seconds": 18.0,
        "title": "Team note for other player", "category": "transition",
        "visibility": "team", "player_ids": [other_pid], "note_type": "correction",
    }, headers=auth_headers)
    other_note_id = other_note_resp.json()["note"]["id"]

    # Team-visible playlist, no explicit `player_ids`, items = [private,
    # team-other]. From the viewer's perspective, the only thing
    # connecting this playlist to the focal player is the private item,
    # which is filtered out.
    pl_resp = await client.post("/api/coach/playlists", json={
        "title": "Mixed-item playlist",
        "description": "", "visibility": "team",
        "player_ids": [], "note_ids": [private_note_id, other_note_id],
    }, headers=auth_headers)
    assert pl_resp.status_code == 200, pl_resp.text

    linked_headers = await _login(client, "playlist_private_only_viewer")
    resp = await client.get(
        f"/api/my-feedback/players/{pid}/development", headers=linked_headers,
    )
    assert resp.status_code == 200, resp.text
    profile = resp.json()["profile"]

    # Viewer surface: the private note is filtered out, so the playlist
    # has no surviving player-tagged item — it must not be counted as
    # "for this player".
    assert profile["counts"]["playlists"] == 0, (
        "Viewer profile should exclude a playlist whose only "
        "connection to this player is a private (filtered-out) note. "
        f"Got recent_playlists: {profile['recent_playlists']}"
    )
    assert profile["recent_playlists"] == []

    # Sanity: the coach surface (which sees the private note) DOES
    # include the playlist, confirming the only difference is the
    # viewer-side visibility filter.
    coach_resp = await client.get(
        f"/api/coach/players/{pid}/development", headers=auth_headers,
    )
    coach_profile = coach_resp.json()["profile"]
    assert coach_profile["counts"]["playlists"] == 1
    assert [p["title"] for p in coach_profile["recent_playlists"]] == [
        "Mixed-item playlist",
    ]


# ---------------------------------------------------------------------------
# Phase 5a — PR #103 review fixes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dev_profile_latest_reflection_uses_global_sort(client, auth_headers):
    """`latest_reflection` MUST be the globally most-recent review with
    a non-empty reflection — not the first element of the
    `note_reviews + playlist_reviews` concatenation.

    This test seeds the data so the newer reflection lives in the
    SECOND sub-list (the playlist sub-list), proving the fix forces a
    global sort instead of accidentally relying on note-reviews
    appearing first."""
    import db as _db

    viewer_resp = await client.post("/api/users", json={
        "username": "reflection_order_viewer",
        "password": "password123", "role": "viewer",
    }, headers=auth_headers)
    viewer_user_id = viewer_resp.json()["user"]["id"]

    player_resp = await client.post("/api/coach/players", json={
        "display_name": "Order Test", "jersey_number": "8",
    }, headers=auth_headers)
    player_id = player_resp.json()["player"]["id"]
    await client.post("/api/coach/player-links", json={
        "player_id": player_id, "user_id": viewer_user_id, "relationship": "parent",
    }, headers=auth_headers)

    match_resp = await client.post("/api/matches", json={
        "home_team": "OSU Steel", "away_team": "Order FC", "date": "2026-05-25",
    }, headers=auth_headers)
    match_id = match_resp.json()["id"]

    note_resp = await client.post("/api/coach/notes", json={
        "match_id": match_id, "slot": "full", "timestamp_seconds": 5.0,
        "title": "Note for review", "category": "shape",
        "visibility": "team", "player_ids": [player_id], "note_type": "correction",
    }, headers=auth_headers)
    note_id = note_resp.json()["note"]["id"]

    playlist_resp = await client.post("/api/coach/playlists", json={
        "title": "Playlist for review", "description": "",
        "visibility": "team", "player_ids": [player_id], "note_ids": [note_id],
    }, headers=auth_headers)
    playlist_id = playlist_resp.json()["playlist"]["id"]

    # Seed the reviews directly so we control `reviewed_at` ordering
    # exactly. Note review is OLDER (2026-05-25T10:00) and playlist
    # review is NEWER (2026-05-26T10:00). With the buggy unsorted
    # concatenation, `reflections[0]` would be the older note row;
    # the fix's global sort returns the playlist row instead.
    conn = _db.connect()
    conn.execute(
        "INSERT INTO coaching_reviews (user_id, note_id, playlist_id, reflection, reviewed_at) "
        "VALUES (?, ?, NULL, ?, ?)",
        (viewer_user_id, note_id, "Older note reflection", "2026-05-25T10:00:00.000Z"),
    )
    conn.execute(
        "INSERT INTO coaching_reviews (user_id, note_id, playlist_id, reflection, reviewed_at) "
        "VALUES (?, NULL, ?, ?, ?)",
        (viewer_user_id, playlist_id, "Newer playlist reflection", "2026-05-26T10:00:00.000Z"),
    )
    conn.commit()

    viewer_headers = await _login(client, "reflection_order_viewer")
    resp = await client.get(
        f"/api/my-feedback/players/{player_id}/development", headers=viewer_headers,
    )
    assert resp.status_code == 200, resp.text
    rs = resp.json()["profile"]["review_status"]

    # The fix sources `latest_reflection` from the globally sorted list
    # so the playlist row wins.
    assert rs["latest_reviewed_at"] == "2026-05-26T10:00:00.000Z"
    assert rs["reflection_count"] == 2
    assert rs["latest_reflection"]["reflection"] == "Newer playlist reflection"
    assert rs["latest_reflection"]["playlist_id"] == playlist_id
    assert rs["latest_reflection"]["note_id"] is None
    assert rs["latest_reflection"]["reviewed_at"] == "2026-05-26T10:00:00.000Z"


@pytest.mark.asyncio
async def test_dev_profile_viewer_endpoint_scrubs_for_coach_caller(client, auth_headers):
    """A coach/admin user who is also linked to a player via
    `player_user_links` can call `GET /api/my-feedback/players/{id}/development`.
    The endpoint sets `viewer_scoped=True` in the response, so the
    payload contract is "no `coach_private_note` text in any
    note-derived field."

    Without the fix, `_filter_notes_for_user` short-circuits for
    coach/admin and returns the raw list, so a coach caller would see
    the un-scrubbed `coach_private_note` despite `viewer_scoped: true`.
    The fix wraps the filtered list in `_strip_private_fields` for
    every viewer-scoped build."""
    # Create a coach user AND link them to a player.
    coach_resp = await client.post("/api/users", json={
        "username": "linked_coach_caller",
        "password": "password123", "role": "coach,uploader",
    }, headers=auth_headers)
    coach_user_id = coach_resp.json()["user"]["id"]

    player_resp = await client.post("/api/coach/players", json={
        "display_name": "Coach's Kid", "jersey_number": "10",
    }, headers=auth_headers)
    player_id = player_resp.json()["player"]["id"]
    link_resp = await client.post("/api/coach/player-links", json={
        "player_id": player_id, "user_id": coach_user_id, "relationship": "parent",
    }, headers=auth_headers)
    assert link_resp.status_code == 200

    match_resp = await client.post("/api/matches", json={
        "home_team": "Coach FC", "away_team": "Kids FC", "date": "2026-05-26",
    }, headers=auth_headers)
    match_id = match_resp.json()["id"]

    # Notes designed to flow into every viewer-shaped surface that
    # reads from `notes_source`: recent_notes, recent_corrections,
    # current_focus_areas. All three carry `coach_private_note` text
    # that MUST be scrubbed when viewer_scoped=True regardless of
    # caller role.
    secret = "COACH-PRIVATE: should be scrubbed under viewer_scoped=true"
    await client.post("/api/coach/notes", json={
        "match_id": match_id, "slot": "full", "timestamp_seconds": 10.0,
        "title": "Recent correction with private text", "body": "...",
        "category": "decision", "visibility": "team",
        "player_ids": [player_id], "note_type": "correction",
        "what_to_do_next": "Public follow-up text",
        "coach_private_note": secret,
    }, headers=auth_headers)
    await client.post("/api/coach/notes", json={
        "match_id": match_id, "slot": "full", "timestamp_seconds": 25.0,
        "title": "Individual goal with private text", "body": "...",
        "category": "decision", "visibility": "team",
        "player_ids": [player_id], "note_type": "individual_goal",
        "what_to_do_next": "Goal follow-up text",
        "coach_private_note": secret,
    }, headers=auth_headers)

    coach_headers = await _login(client, "linked_coach_caller")
    resp = await client.get(
        f"/api/my-feedback/players/{player_id}/development", headers=coach_headers,
    )
    assert resp.status_code == 200, resp.text
    profile = resp.json()["profile"]

    # Contract: viewer_scoped=true MUST imply scrubbed payload.
    assert profile["viewer_scoped"] is True
    # `linked_accounts` is coach-endpoint-only; the viewer endpoint
    # must not surface it even for a coach caller.
    assert "linked_accounts" not in profile

    # Defense-in-depth: NO note-derived list may contain the private
    # text. Check every surface that sources from `notes_source`.
    for n in profile["recent_notes"]:
        assert (n.get("coach_private_note") or "") == "", (
            f"recent_notes leaked coach_private_note for coach caller: {n}"
        )
    for n in profile["recent_corrections"]:
        assert (n.get("coach_private_note") or "") == ""
    for n in profile["recent_positives"]:
        assert (n.get("coach_private_note") or "") == ""
    # Focus areas only emit the curated public fields by construction,
    # but assert nothing leaks through anyway.
    for f in profile["current_focus_areas"]:
        assert "coach_private_note" not in f
        # The public fields stay populated so a downstream UI can render them.
        assert f.get("what_to_do_next")

    # Sanity: the same coach calling the COACH endpoint still sees
    # the raw private text — the fix is scoped to viewer_scoped=True.
    coach_resp = await client.get(
        f"/api/coach/players/{player_id}/development", headers=coach_headers,
    )
    coach_profile = coach_resp.json()["profile"]
    assert coach_profile["viewer_scoped"] is False
    assert any(
        (n.get("coach_private_note") or "").strip() == secret
        for n in coach_profile["recent_notes"]
    ), "Coach endpoint must still expose coach_private_note text to a coach caller"


# ---------------------------------------------------------------------------
# Phase 4e — per-coaching-clip thumbnails
#
# Mirrors the Phase 3a per-note thumbnail tests. Same JPEG stub pattern:
# a lightweight replacement for `_media.generate_thumbnail_at_timestamp`
# writes a 4-byte JPEG payload synchronously so the serving endpoint
# sees a real file without depending on ffmpeg. Tests cover:
#   - path convention helper
#   - coach/admin GET on a generated thumbnail
#   - team-visible clip thumbnail reachable by signed-in viewer
#   - player-visible clip thumbnail reachable only by linked family
#   - private clip thumbnail never leaks to any viewer
#   - unknown clip / missing file -> 404
#   - generation failure does not break clip create
#   - regenerate requires coach/admin
#   - regenerate returns generated:false when source missing
#   - delete clip removes thumbnail file
#   - path containment on every read/write site
# ---------------------------------------------------------------------------


def _coach_clip_thumb_path(data_dir, match_id: str, clip_id: int):
    """Mirror of `_media.clip_thumbnail_path` rooted at the test
    fixture's `data_dir / videos`. Duplicated so a regression in the
    path convention shows up as a test failure here, not a silent move."""
    return data_dir / "videos" / match_id / "clip_thumbs" / f"{clip_id}.jpg"


async def _install_clip_thumbnail_stub(monkeypatch, *, succeed: bool = True, raise_exc: bool = False):
    """Replace `_media.generate_thumbnail_at_timestamp` so clip create /
    update / regenerate flows don't shell out to ffmpeg in the test
    suite. Same stub used by note-thumbnail tests; we install our own
    copy so the call log is per-test and the existing note tests stay
    isolated."""
    import media as _media
    calls: list[dict] = []

    async def stub(src, dest, *, timestamp_s):
        calls.append({"src": str(src), "dest": str(dest), "timestamp_s": timestamp_s})
        if raise_exc:
            raise RuntimeError("simulated ffmpeg crash for clip thumbnail")
        if succeed:
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(b"\xff\xd8\xff\xd9")
        return succeed

    monkeypatch.setattr(_media, "generate_thumbnail_at_timestamp", stub)
    return calls


@pytest.mark.asyncio
async def test_clip_thumbnail_path_convention(data_dir):
    """Lock the storage path the spec calls out — anything that
    relocates `clip_thumbs/` will trip this."""
    from media import clip_thumbnail_path
    p = clip_thumbnail_path(data_dir / "videos", "match-abc", 7)
    assert p == data_dir / "videos" / "match-abc" / "clip_thumbs" / "7.jpg"


@pytest.mark.asyncio
async def test_clip_thumbnail_404_when_file_missing(client, auth_headers):
    """No file on disk -> 404, never a 500."""
    match_resp = await client.post("/api/matches", json={
        "home_team": "OSU Steel", "away_team": "Falcons FC", "date": "2026-05-20",
    }, headers=auth_headers)
    match_id = match_resp.json()["id"]
    clip_resp = await client.post("/api/coach/clips", json={
        "match_id": match_id, "slot": "full",
        "start_seconds": 5.0, "end_seconds": 18.0,
        "title": "No source video here", "category": "shape", "visibility": "team",
    }, headers=auth_headers)
    assert clip_resp.status_code == 200, clip_resp.text
    clip_id = clip_resp.json()["clip"]["id"]
    # No stub installed + no real video means no file written.
    resp = await client.get(f"/api/coach/clips/{clip_id}/thumbnail", headers=auth_headers)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_clip_thumbnail_404_for_unknown_clip(client, auth_headers):
    resp = await client.get("/api/coach/clips/9999999/thumbnail", headers=auth_headers)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_clip_thumbnail_requires_auth(client):
    resp = await client.get("/api/coach/clips/1/thumbnail")
    assert resp.status_code in (401, 403)


@pytest.mark.asyncio
async def test_clip_thumbnail_admin_and_coach_can_access(client, auth_headers, data_dir, monkeypatch):
    """Coach/admin can fetch the JPEG once it exists on disk."""
    await _install_clip_thumbnail_stub(monkeypatch)
    await client.post("/api/users", json={
        "username": "clipcoach", "password": "password123", "role": "coach",
    }, headers=auth_headers)
    match_resp = await client.post("/api/matches", json={
        "home_team": "OSU Steel", "away_team": "Riverside FC", "date": "2026-05-21",
    }, headers=auth_headers)
    match_id = match_resp.json()["id"]
    clip_resp = await client.post("/api/coach/clips", json={
        "match_id": match_id, "slot": "full",
        "start_seconds": 30.0, "end_seconds": 50.0,
        "title": "Team shape (clip)", "category": "shape", "visibility": "team",
    }, headers=auth_headers)
    clip_id = clip_resp.json()["clip"]["id"]
    await _drain_background_tasks()
    assert _coach_clip_thumb_path(data_dir, match_id, clip_id).is_file(), \
        "stub should have written the JPEG synchronously"

    admin_resp = await client.get(f"/api/coach/clips/{clip_id}/thumbnail", headers=auth_headers)
    assert admin_resp.status_code == 200
    assert admin_resp.headers["content-type"] == "image/jpeg"
    assert admin_resp.content == b"\xff\xd8\xff\xd9"

    coach_headers = await _login(client, "clipcoach")
    coach_resp = await client.get(f"/api/coach/clips/{clip_id}/thumbnail", headers=coach_headers)
    assert coach_resp.status_code == 200


@pytest.mark.asyncio
async def test_clip_thumbnail_team_visible_reachable_by_viewer(client, auth_headers, data_dir, monkeypatch):
    """A `visibility=team` clip thumbnail must be reachable by any
    signed-in viewer — same boundary as note thumbnails."""
    await _install_clip_thumbnail_stub(monkeypatch)
    await client.post("/api/users", json={
        "username": "clipviewer", "password": "password123", "role": "viewer",
    }, headers=auth_headers)
    match_resp = await client.post("/api/matches", json={
        "home_team": "OSU Steel", "away_team": "Northgate", "date": "2026-05-22",
    }, headers=auth_headers)
    match_id = match_resp.json()["id"]
    clip_resp = await client.post("/api/coach/clips", json={
        "match_id": match_id, "slot": "full",
        "start_seconds": 45.0, "end_seconds": 60.0,
        "title": "Press in midfield (clip)", "category": "pressing", "visibility": "team",
    }, headers=auth_headers)
    clip_id = clip_resp.json()["clip"]["id"]
    await _drain_background_tasks()

    viewer_headers = await _login(client, "clipviewer")
    resp = await client.get(f"/api/coach/clips/{clip_id}/thumbnail", headers=viewer_headers)
    assert resp.status_code == 200
    assert resp.content == b"\xff\xd8\xff\xd9"


@pytest.mark.asyncio
async def test_clip_thumbnail_player_visible_only_to_linked_family(client, auth_headers, data_dir, monkeypatch):
    """`visibility=player` clip thumbnail: linked family member can
    fetch it; an unlinked viewer cannot."""
    await _install_clip_thumbnail_stub(monkeypatch)
    family_resp = await client.post("/api/users", json={
        "username": "clipfamily", "password": "password123", "role": "viewer",
    }, headers=auth_headers)
    linked_user_id = family_resp.json()["user"]["id"]
    await client.post("/api/users", json={
        "username": "clipstranger", "password": "password123", "role": "viewer",
    }, headers=auth_headers)
    player_resp = await client.post("/api/coach/players", json={
        "display_name": "Sam Park", "jersey_number": "11",
    }, headers=auth_headers)
    player_id = player_resp.json()["player"]["id"]
    await client.post("/api/coach/player-links", json={
        "player_id": player_id, "user_id": linked_user_id, "relationship": "parent",
    }, headers=auth_headers)
    match_resp = await client.post("/api/matches", json={
        "home_team": "OSU Steel", "away_team": "Highbridge", "date": "2026-05-23",
    }, headers=auth_headers)
    match_id = match_resp.json()["id"]
    clip_resp = await client.post("/api/coach/clips", json={
        "match_id": match_id, "slot": "full",
        "start_seconds": 60.0, "end_seconds": 75.0,
        "title": "Player #11 — recovery (clip)", "category": "defending",
        "visibility": "player", "player_ids": [player_id],
    }, headers=auth_headers)
    clip_id = clip_resp.json()["clip"]["id"]
    await _drain_background_tasks()

    family_headers = await _login(client, "clipfamily")
    family_resp = await client.get(f"/api/coach/clips/{clip_id}/thumbnail", headers=family_headers)
    assert family_resp.status_code == 200, family_resp.text

    stranger_headers = await _login(client, "clipstranger")
    stranger_resp = await client.get(f"/api/coach/clips/{clip_id}/thumbnail", headers=stranger_headers)
    assert stranger_resp.status_code == 404, \
        "unlinked viewer must NOT be able to fetch a player-visible clip thumbnail"


@pytest.mark.asyncio
async def test_clip_thumbnail_private_never_leaks_to_viewer(client, auth_headers, data_dir, monkeypatch):
    """`visibility=private` clip thumbnail must be invisible to ANY non-coach
    user, even if the JPEG file exists on disk. Returns 404 — same response
    shape as 'clip doesn't exist' so a viewer cannot probe."""
    await _install_clip_thumbnail_stub(monkeypatch)
    await client.post("/api/users", json={
        "username": "clipprivateviewer", "password": "password123", "role": "viewer",
    }, headers=auth_headers)
    match_resp = await client.post("/api/matches", json={
        "home_team": "OSU Steel", "away_team": "Pinehurst", "date": "2026-05-24",
    }, headers=auth_headers)
    match_id = match_resp.json()["id"]
    clip_resp = await client.post("/api/coach/clips", json={
        "match_id": match_id, "slot": "full",
        "start_seconds": 75.0, "end_seconds": 90.0,
        "title": "Internal coach analysis (clip)", "category": "other",
        "visibility": "private",
    }, headers=auth_headers)
    clip_id = clip_resp.json()["clip"]["id"]
    await _drain_background_tasks()

    # File IS on disk — point of the test is that the file existing
    # does NOT make the endpoint serve it to viewers.
    assert _coach_clip_thumb_path(data_dir, match_id, clip_id).is_file()

    coach_resp = await client.get(f"/api/coach/clips/{clip_id}/thumbnail", headers=auth_headers)
    assert coach_resp.status_code == 200

    viewer_headers = await _login(client, "clipprivateviewer")
    viewer_resp = await client.get(f"/api/coach/clips/{clip_id}/thumbnail", headers=viewer_headers)
    assert viewer_resp.status_code == 404


@pytest.mark.asyncio
async def test_clip_thumbnail_create_does_not_break_when_generator_raises(client, auth_headers, monkeypatch):
    """Acceptance: generation failure must not block clip save. Stub
    raises so we exercise the safety net in `_spawn_coach_clip_thumbnail`."""
    await _install_clip_thumbnail_stub(monkeypatch, succeed=False, raise_exc=True)
    match_resp = await client.post("/api/matches", json={
        "home_team": "OSU Steel", "away_team": "Bridgewater", "date": "2026-05-25",
    }, headers=auth_headers)
    match_id = match_resp.json()["id"]

    clip_resp = await client.post("/api/coach/clips", json={
        "match_id": match_id, "slot": "full",
        "start_seconds": 25.0, "end_seconds": 40.0,
        "title": "ffmpeg crashes here", "category": "other", "visibility": "team",
    }, headers=auth_headers)
    assert clip_resp.status_code == 200, clip_resp.text
    clip_id = clip_resp.json()["clip"]["id"]

    await _drain_background_tasks()

    resp = await client.get(f"/api/coach/clips/{clip_id}/thumbnail", headers=auth_headers)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_clip_thumbnail_regenerate_requires_coach(client, auth_headers, monkeypatch):
    """The manual regenerate endpoint is gated like the rest of
    `/api/coach/*` — viewers get 403."""
    await _install_clip_thumbnail_stub(monkeypatch)
    await client.post("/api/users", json={
        "username": "clipregenviewer", "password": "password123", "role": "viewer",
    }, headers=auth_headers)
    match_resp = await client.post("/api/matches", json={
        "home_team": "OSU Steel", "away_team": "Eastside", "date": "2026-05-26",
    }, headers=auth_headers)
    match_id = match_resp.json()["id"]
    clip_resp = await client.post("/api/coach/clips", json={
        "match_id": match_id, "slot": "full",
        "start_seconds": 33.0, "end_seconds": 50.0,
        "title": "Regen-gating clip", "category": "other", "visibility": "team",
    }, headers=auth_headers)
    clip_id = clip_resp.json()["clip"]["id"]

    coach_resp = await client.post(
        f"/api/coach/clips/{clip_id}/thumbnail/regenerate", headers=auth_headers,
    )
    assert coach_resp.status_code == 200
    assert coach_resp.json() == {"ok": True, "generated": True}

    viewer_headers = await _login(client, "clipregenviewer")
    viewer_resp = await client.post(
        f"/api/coach/clips/{clip_id}/thumbnail/regenerate", headers=viewer_headers,
    )
    assert viewer_resp.status_code == 403


@pytest.mark.asyncio
async def test_clip_thumbnail_regenerate_handles_unknown_clip(client, auth_headers):
    resp = await client.post("/api/coach/clips/99999/thumbnail/regenerate", headers=auth_headers)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_clip_thumbnail_regenerate_returns_ok_false_when_source_missing(client, auth_headers):
    """Source MP4 doesn't exist -> {ok: True, generated: False}, distinct
    from a 404 unknown-clip response."""
    match_resp = await client.post("/api/matches", json={
        "home_team": "OSU Steel", "away_team": "Coastal", "date": "2026-05-27",
    }, headers=auth_headers)
    match_id = match_resp.json()["id"]
    clip_resp = await client.post("/api/coach/clips", json={
        "match_id": match_id, "slot": "full",
        "start_seconds": 5.0, "end_seconds": 12.0,
        "title": "No source video", "category": "other", "visibility": "team",
    }, headers=auth_headers)
    clip_id = clip_resp.json()["clip"]["id"]

    resp = await client.post(f"/api/coach/clips/{clip_id}/thumbnail/regenerate", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "generated": False}


@pytest.mark.asyncio
async def test_clip_thumbnail_delete_clip_removes_file(client, auth_headers, data_dir, monkeypatch):
    """DELETE /api/coach/clips/{id} should unlink the JPEG so the
    `<videos>/<match>/clip_thumbs/` tree doesn't accumulate orphans."""
    await _install_clip_thumbnail_stub(monkeypatch)
    match_resp = await client.post("/api/matches", json={
        "home_team": "OSU Steel", "away_team": "Marsh Lane", "date": "2026-05-28",
    }, headers=auth_headers)
    match_id = match_resp.json()["id"]
    clip_resp = await client.post("/api/coach/clips", json={
        "match_id": match_id, "slot": "full",
        "start_seconds": 10.0, "end_seconds": 25.0,
        "title": "To be deleted", "category": "other", "visibility": "team",
    }, headers=auth_headers)
    clip_id = clip_resp.json()["clip"]["id"]
    await _drain_background_tasks()
    thumb_path = _coach_clip_thumb_path(data_dir, match_id, clip_id)
    assert thumb_path.is_file()

    del_resp = await client.delete(f"/api/coach/clips/{clip_id}", headers=auth_headers)
    assert del_resp.status_code == 200
    assert not thumb_path.exists(), "DELETE /api/coach/clips must unlink the thumbnail JPEG"


@pytest.mark.asyncio
async def test_clip_thumbnail_delete_survives_unlink_oserror(client, auth_headers, data_dir, monkeypatch):
    """PR #108 review fix-up — `coach_delete_clip` must mirror
    `coach_delete_note`'s defensive `try/except OSError` around the
    thumbnail `unlink(missing_ok=True)`. `missing_ok=True` only swallows
    `FileNotFoundError`; a `PermissionError` / `EBUSY` / `EROFS` would
    otherwise propagate as a 500 AFTER the DB row was already deleted.
    The handler must log the OSError and still return 200 so the UI's
    delete state stays consistent with the DB."""
    import db as _db
    await _install_clip_thumbnail_stub(monkeypatch)
    match_resp = await client.post("/api/matches", json={
        "home_team": "OSU Steel", "away_team": "Unlink OSError FC", "date": "2026-05-30",
    }, headers=auth_headers)
    match_id = match_resp.json()["id"]
    clip_resp = await client.post("/api/coach/clips", json={
        "match_id": match_id, "slot": "full",
        "start_seconds": 10.0, "end_seconds": 25.0,
        "title": "Unlink raises OSError", "category": "other", "visibility": "team",
    }, headers=auth_headers)
    clip_id = clip_resp.json()["clip"]["id"]
    await _drain_background_tasks()

    # Patch Path.unlink to raise PermissionError exactly when the clip
    # thumbnail path is the unlink target. Using a sentinel substring
    # so the patch does not interfere with the dozens of unrelated
    # `unlink(missing_ok=True)` calls FastAPI's TestClient may make on
    # tempfiles inside the request lifecycle.
    from pathlib import Path
    real_unlink = Path.unlink
    sentinel = f"clip_thumbs/{clip_id}.jpg"

    def _raising_unlink(self, *args, **kwargs):
        if sentinel in str(self):
            raise PermissionError("simulated EACCES on clip thumbnail unlink")
        return real_unlink(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", _raising_unlink)

    del_resp = await client.delete(f"/api/coach/clips/{clip_id}", headers=auth_headers)
    assert del_resp.status_code == 200, (
        f"DELETE /api/coach/clips must NOT 500 when thumbnail unlink raises OSError "
        f"(got {del_resp.status_code}: {del_resp.text})"
    )
    # And the DB row is gone — the OSError handling is purely about the
    # thumbnail cleanup; the delete itself committed before the unlink.
    assert _db.get_coaching_clip(clip_id) is None, \
        "Clip should be removed from the DB even when thumbnail unlink fails"


@pytest.mark.asyncio
async def test_clip_thumbnail_response_is_not_public_cacheable(client, auth_headers, data_dir, monkeypatch):
    """Per-user access-controlled responses must NEVER set
    `Cache-Control: public`. Mirrors the note thumbnail header policy."""
    await _install_clip_thumbnail_stub(monkeypatch)
    match_resp = await client.post("/api/matches", json={
        "home_team": "OSU Steel", "away_team": "Cache Test FC", "date": "2026-05-29",
    }, headers=auth_headers)
    match_id = match_resp.json()["id"]
    clip_resp = await client.post("/api/coach/clips", json={
        "match_id": match_id, "slot": "full",
        "start_seconds": 12.0, "end_seconds": 25.0,
        "title": "Cache header check", "category": "shape", "visibility": "team",
    }, headers=auth_headers)
    clip_id = clip_resp.json()["clip"]["id"]
    await _drain_background_tasks()

    resp = await client.get(f"/api/coach/clips/{clip_id}/thumbnail", headers=auth_headers)
    assert resp.status_code == 200
    cache_control = resp.headers.get("cache-control", "")
    assert "public" not in cache_control.lower(), (
        f"Cache-Control must NOT be public on a per-viewer access-controlled "
        f"response (got {cache_control!r})"
    )
    assert "no-cache" in cache_control.lower() or "private" in cache_control.lower()
    etag = resp.headers.get("etag", "")
    assert etag.startswith('"') and etag.endswith('"') and len(etag) > 2
    assert resp.headers.get("x-content-type-options") == "nosniff"


@pytest.mark.asyncio
async def test_clip_thumbnail_get_refuses_path_escape(client, auth_headers, data_dir, monkeypatch):
    """If a corrupted DB row's `match_id` resolves outside `VIDEOS_DIR`,
    the GET endpoint must return the same 404 it uses for unknown /
    unauthorized / missing-file cases — never serve a file from
    outside the videos tree."""
    import db as _db
    await _install_clip_thumbnail_stub(monkeypatch)
    match_resp = await client.post("/api/matches", json={
        "home_team": "OSU Steel", "away_team": "Containment FC", "date": "2026-05-30",
    }, headers=auth_headers)
    match_id = match_resp.json()["id"]
    clip_resp = await client.post("/api/coach/clips", json={
        "match_id": match_id, "slot": "full",
        "start_seconds": 7.0, "end_seconds": 22.0,
        "title": "Containment GET", "category": "shape", "visibility": "team",
    }, headers=auth_headers)
    clip_id = clip_resp.json()["clip"]["id"]
    await _drain_background_tasks()

    # Simulate a corrupted DB row whose `match_id` contains `..` so
    # `videos_dir / match_id / clip_thumbs / <id>.jpg` would resolve
    # outside `VIDEOS_DIR`.
    conn = _db.connect()
    try:
        conn.execute("UPDATE coaching_clips SET match_id=? WHERE id=?",
                     ("../escape", clip_id))
        conn.commit()
    finally:
        conn.close()

    resp = await client.get(f"/api/coach/clips/{clip_id}/thumbnail", headers=auth_headers)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_clip_thumbnail_regenerate_refuses_path_escape(client, auth_headers, data_dir, monkeypatch):
    """PR #108 review fix-up — port the Phase 3a regenerate path-escape
    regression test for the new clip endpoint.

    If a corrupted DB row's `match_id` resolves outside `VIDEOS_DIR`,
    the regenerate POST must short-circuit with `{ok: True,
    generated: False}` — same shape as the source-missing branch — so
    a future refactor can't accidentally drop the `_thumb_path_within_videos_dir`
    guard and start writing JPEGs outside the videos tree. The
    runtime defense lives at `server.py:2266-2272`; this test locks
    the behavior in.
    """
    import db as _db
    # Install the stub so we can ALSO assert ffmpeg is never invoked
    # for the escaping path — the call log lets us see if the
    # short-circuit failed and the generator ran anyway.
    calls = await _install_clip_thumbnail_stub(monkeypatch)
    match_resp = await client.post("/api/matches", json={
        "home_team": "OSU Steel", "away_team": "Containment Regen FC", "date": "2026-05-31",
    }, headers=auth_headers)
    match_id = match_resp.json()["id"]
    clip_resp = await client.post("/api/coach/clips", json={
        "match_id": match_id, "slot": "full",
        "start_seconds": 7.0, "end_seconds": 22.0,
        "title": "Containment regen", "category": "shape", "visibility": "team",
    }, headers=auth_headers)
    clip_id = clip_resp.json()["clip"]["id"]
    await _drain_background_tasks()
    initial_calls = len(calls)

    # Corrupt the DB row's match_id to a `..` payload so the path
    # would escape `VIDEOS_DIR`.
    conn = _db.connect()
    try:
        conn.execute("UPDATE coaching_clips SET match_id=? WHERE id=?",
                     ("../escape", clip_id))
        conn.commit()
    finally:
        conn.close()

    resp = await client.post(
        f"/api/coach/clips/{clip_id}/thumbnail/regenerate", headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"ok": True, "generated": False}, (
        "regenerate must return generated:false when path escapes VIDEOS_DIR — "
        "same shape as the source-missing branch so callers handle it identically"
    )
    # And ffmpeg must NOT have been invoked for the escaping path.
    assert len(calls) == initial_calls, (
        f"generate_thumbnail_at_timestamp must NOT run when path escapes VIDEOS_DIR "
        f"(calls before={initial_calls}, after={len(calls)})"
    )


@pytest.mark.asyncio
async def test_clip_thumbnail_get_404_detail_is_unified(client, auth_headers, data_dir, monkeypatch):
    """PR #108 review fix-up — the clip GET must return the SAME 404
    detail string for every not-servable case (unknown / unauthorized
    / missing file / path escape) so a probing viewer cannot
    distinguish them by response body. This is a tightening of the
    Phase 3a per-note pattern, where the missing-file branch returned
    `Thumbnail not generated yet` — the clip endpoint normalizes to
    `Thumbnail not found` across all four cases.
    """
    import db as _db
    await _install_clip_thumbnail_stub(monkeypatch)
    match_resp = await client.post("/api/matches", json={
        "home_team": "OSU Steel", "away_team": "Detail Norm FC", "date": "2026-06-01",
    }, headers=auth_headers)
    match_id = match_resp.json()["id"]
    clip_resp = await client.post("/api/coach/clips", json={
        "match_id": match_id, "slot": "full",
        "start_seconds": 5.0, "end_seconds": 20.0,
        "title": "Detail norm", "category": "shape", "visibility": "team",
    }, headers=auth_headers)
    clip_id = clip_resp.json()["clip"]["id"]
    await _drain_background_tasks()

    # Case 1 — unknown clip
    r1 = await client.get("/api/coach/clips/9999999/thumbnail", headers=auth_headers)
    assert r1.status_code == 404
    detail = r1.json().get("detail")
    assert detail == "Thumbnail not found", f"unknown clip detail: {detail!r}"

    # Case 2 — missing file (clip exists, no JPEG on disk yet).
    # Delete the stub-generated JPEG so the file-missing branch fires.
    thumb_path = _coach_clip_thumb_path(data_dir, match_id, clip_id)
    thumb_path.unlink(missing_ok=True)
    r2 = await client.get(f"/api/coach/clips/{clip_id}/thumbnail", headers=auth_headers)
    assert r2.status_code == 404
    assert r2.json().get("detail") == "Thumbnail not found", (
        f"missing-file detail must match unknown-clip detail (got {r2.json().get('detail')!r})"
    )

    # Case 3 — unauthorized viewer probing a private clip.
    # Re-create the JPEG so the missing-file branch isn't what trips
    # the 404; we want the visibility branch to fire.
    await client.post(f"/api/coach/clips/{clip_id}/thumbnail/regenerate", headers=auth_headers)
    private_resp = await client.post("/api/coach/clips", json={
        "match_id": match_id, "slot": "full",
        "start_seconds": 5.0, "end_seconds": 20.0,
        "title": "Private detail norm", "category": "shape", "visibility": "private",
    }, headers=auth_headers)
    private_clip_id = private_resp.json()["clip"]["id"]
    await _drain_background_tasks()
    await client.post("/api/users", json={
        "username": "detail_norm_viewer", "password": "password123", "role": "viewer",
    }, headers=auth_headers)
    viewer_headers = await _login(client, "detail_norm_viewer")
    r3 = await client.get(f"/api/coach/clips/{private_clip_id}/thumbnail", headers=viewer_headers)
    assert r3.status_code == 404
    assert r3.json().get("detail") == "Thumbnail not found", (
        f"unauthorized detail must match unknown-clip detail (got {r3.json().get('detail')!r})"
    )

    # Case 4 — path escape. Reuse the public clip and corrupt match_id.
    conn = _db.connect()
    try:
        conn.execute("UPDATE coaching_clips SET match_id=? WHERE id=?",
                     ("../escape", clip_id))
        conn.commit()
    finally:
        conn.close()
    r4 = await client.get(f"/api/coach/clips/{clip_id}/thumbnail", headers=auth_headers)
    assert r4.status_code == 404
    assert r4.json().get("detail") == "Thumbnail not found", (
        f"path-escape detail must match unknown-clip detail (got {r4.json().get('detail')!r})"
    )


@pytest.mark.asyncio
async def test_clip_thumbnail_regenerated_after_start_seconds_patch(client, auth_headers, data_dir, monkeypatch):
    """PATCH /api/coach/clips/{id} with a new start_seconds must trigger
    a regeneration spawn so the captured frame matches the new window."""
    calls = await _install_clip_thumbnail_stub(monkeypatch)
    match_resp = await client.post("/api/matches", json={
        "home_team": "OSU Steel", "away_team": "Window Edit FC", "date": "2026-05-31",
    }, headers=auth_headers)
    match_id = match_resp.json()["id"]
    clip_resp = await client.post("/api/coach/clips", json={
        "match_id": match_id, "slot": "full",
        "start_seconds": 10.0, "end_seconds": 25.0,
        "title": "Window-edit", "category": "shape", "visibility": "team",
    }, headers=auth_headers)
    clip_id = clip_resp.json()["clip"]["id"]
    await _drain_background_tasks()
    initial_calls = len(calls)
    assert initial_calls >= 1, "create should have scheduled one generation"

    # PATCH the start_seconds — must spawn a new generation.
    patch_resp = await client.patch(
        f"/api/coach/clips/{clip_id}",
        json={"start_seconds": 12.0},
        headers=auth_headers,
    )
    assert patch_resp.status_code == 200, patch_resp.text
    await _drain_background_tasks()
    assert len(calls) > initial_calls, \
        "PATCH start_seconds must schedule a new clip thumbnail generation"
    # The most recent call should reflect the new start time.
    assert calls[-1]["timestamp_s"] == 12.0


# ---------------------------------------------------------------------------
# Phase 6a — Observation note backend
#
# These tests pin the contract for non-video coaching notes:
# - Existing video notes default `note_context = "video"` and continue
#   to require match_id / slot / timestamp_seconds.
# - Observation notes can be created without those three.
# - Validation rejects: missing required content, invalid event_type,
#   malformed event_date, oversized tactical_board_json, video flips
#   that drop the moment-anchoring fields.
# - Privacy ladder is shared with video notes — coach_private_note never
#   leaks; private observation notes never reach viewers.
# - Thumbnail generation is suppressed for observation notes.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_observation_existing_note_defaults_to_video_context(client, auth_headers):
    """Migration invariant: every existing video-note payload (no
    note_context sent) round-trips with `note_context = "video"` and
    the empty observation defaults so older clients keep working."""
    match_resp = await client.post("/api/matches", json={
        "home_team": "OSU Steel", "away_team": "Phase6 FC", "date": "2026-05-10",
    }, headers=auth_headers)
    match_id = match_resp.json()["id"]
    note_resp = await client.post("/api/coach/notes", json={
        "match_id": match_id, "slot": "full", "timestamp_seconds": 4.0,
        "title": "Legacy-shape video note", "category": "other", "visibility": "team",
    }, headers=auth_headers)
    assert note_resp.status_code == 200, note_resp.text
    note = note_resp.json()["note"]
    assert note["note_context"] == "video"
    assert note["event_title"] == ""
    assert note["event_date"] == ""
    assert note["event_type"] == ""
    assert note["tactical_board_json"] is None


@pytest.mark.asyncio
async def test_observation_video_note_requires_match_slot_timestamp(client, auth_headers):
    """Phase 6a — video notes still require all three moment-anchoring
    fields. Omitting any of them must 422 even when note_context is
    explicitly set to 'video' (the field-level validators allow them
    to be None; the per-context model validator catches it)."""
    bad = await client.post("/api/coach/notes", json={
        "title": "Missing match", "note_context": "video",
        "category": "other", "visibility": "team",
    }, headers=auth_headers)
    assert bad.status_code == 422
    # Implicit context (legacy default) — still video, still rejected.
    bad_implicit = await client.post("/api/coach/notes", json={
        "title": "Missing match", "category": "other", "visibility": "team",
    }, headers=auth_headers)
    assert bad_implicit.status_code == 422


@pytest.mark.asyncio
async def test_observation_note_can_be_created_without_match(client, auth_headers):
    """Phase 6a — observation notes do NOT require match/slot/timestamp.
    All five new fields (`note_context`, `event_title`, `event_date`,
    `event_type`, `tactical_board_json`) round-trip and the structured
    text fields still apply."""
    resp = await client.post("/api/coach/notes", json={
        "title": "Practice scanning drill",
        "note_context": "observation",
        "category": "decision", "visibility": "team",
        "event_title": "Tuesday practice — scanning",
        "event_date": "2026-05-07",
        "event_type": "practice",
        "what_happened": "Walked through scan-before-receive in 3v2 grid.",
        "why_it_matters": "Carries to Saturday's match.",
        "what_to_do_next": "Repeat the rondo with the same trigger.",
        "tactical_board_json": {"pitch_kind": "soccer_full", "tokens": []},
    }, headers=auth_headers)
    assert resp.status_code == 200, resp.text
    note = resp.json()["note"]
    assert note["note_context"] == "observation"
    assert note["match_id"] is None
    assert note["slot"] is None
    assert note["timestamp_seconds"] is None
    assert note["event_title"] == "Tuesday practice — scanning"
    assert note["event_date"] == "2026-05-07"
    assert note["event_type"] == "practice"
    assert note["tactical_board_json"] == {"pitch_kind": "soccer_full", "tokens": []}
    # Structured fields still flow through.
    assert note["what_happened"].startswith("Walked through")


@pytest.mark.asyncio
async def test_observation_note_rejects_invalid_event_type(client, auth_headers):
    bad = await client.post("/api/coach/notes", json={
        "title": "Bad type", "note_context": "observation",
        "category": "other", "visibility": "team",
        "event_type": "bogus",
    }, headers=auth_headers)
    assert bad.status_code == 422


@pytest.mark.asyncio
async def test_observation_note_rejects_invalid_event_date(client, auth_headers):
    bad = await client.post("/api/coach/notes", json={
        "title": "Bad date", "note_context": "observation",
        "category": "other", "visibility": "team",
        "event_date": "not-a-date",
    }, headers=auth_headers)
    assert bad.status_code == 422


@pytest.mark.asyncio
async def test_observation_note_trims_event_title(client, auth_headers):
    resp = await client.post("/api/coach/notes", json={
        "title": "Trim me",
        "note_context": "observation",
        "category": "other", "visibility": "team",
        "event_title": "   Friday film session   ",
    }, headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["note"]["event_title"] == "Friday film session"


@pytest.mark.asyncio
async def test_observation_note_rejects_malformed_tactical_board(client, auth_headers):
    """Pydantic accepts JSON-compatible dicts via `dict[str, Any]`.
    `validate_tactical_board_payload` rejects non-dict and oversized
    blobs explicitly."""
    huge = {"pitch_kind": "soccer_full", "tokens": [{"i": i, "x": 0.5} for i in range(100_000)]}
    bad = await client.post("/api/coach/notes", json={
        "title": "Huge board", "note_context": "observation",
        "category": "other", "visibility": "team",
        "tactical_board_json": huge,
    }, headers=auth_headers)
    assert bad.status_code == 422


@pytest.mark.asyncio
async def test_observation_note_requires_meaningful_content(client, auth_headers):
    """An observation row that's empty across every coaching-content
    field is meaningless — rejected at the request boundary so we
    don't end up with empty cards in the UI."""
    bad = await client.post("/api/coach/notes", json={
        "note_context": "observation",
        "category": "other", "visibility": "team",
    }, headers=auth_headers)
    assert bad.status_code == 422


@pytest.mark.asyncio
async def test_observation_note_only_tactical_board_is_meaningful(client, auth_headers):
    """A tactical-board-only note (no title, no body, no structured
    text) is still meaningful coaching content because the board
    itself carries the lesson. This is the forward path for Phase 6c
    so a coach can save 'Set-piece corner shape' as a pure sketch."""
    resp = await client.post("/api/coach/notes", json={
        "note_context": "observation",
        "category": "set_piece", "visibility": "team",
        "tactical_board_json": {"pitch_kind": "soccer_full", "tokens": [{"x": 0.5, "y": 0.5}]},
    }, headers=auth_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["note"]["tactical_board_json"]["pitch_kind"] == "soccer_full"


@pytest.mark.asyncio
async def test_observation_note_patch_event_fields(client, auth_headers):
    """Partial PATCH must update event_title / event_date / event_type
    / tactical_board_json and leave the rest of the row untouched."""
    create = await client.post("/api/coach/notes", json={
        "title": "Initial observation",
        "note_context": "observation",
        "category": "other", "visibility": "team",
        "event_title": "Old", "event_type": "tactical",
    }, headers=auth_headers)
    note_id = create.json()["note"]["id"]
    patch = await client.patch(f"/api/coach/notes/{note_id}", json={
        "event_title": "Updated",
        "event_date": "2026-05-11",
        "event_type": "meeting",
        "tactical_board_json": {"pitch_kind": "soccer_full", "tokens": []},
    }, headers=auth_headers)
    assert patch.status_code == 200, patch.text
    note = patch.json()["note"]
    assert note["event_title"] == "Updated"
    assert note["event_date"] == "2026-05-11"
    assert note["event_type"] == "meeting"
    assert note["tactical_board_json"] == {"pitch_kind": "soccer_full", "tokens": []}
    # Untouched fields keep their original values.
    assert note["title"] == "Initial observation"
    assert note["note_context"] == "observation"


@pytest.mark.asyncio
async def test_observation_partial_patch_revalidates_video_note_state(client, auth_headers):
    """PATCH must not be able to leave a video note un-anchored. A
    direct attempt to clear `match_id` while keeping `note_context =
    'video'` must fail."""
    match = await client.post("/api/matches", json={
        "home_team": "OSU Steel", "away_team": "Anchor FC", "date": "2026-05-12",
    }, headers=auth_headers)
    match_id = match.json()["id"]
    create = await client.post("/api/coach/notes", json={
        "match_id": match_id, "slot": "full", "timestamp_seconds": 30,
        "title": "Anchored video note", "category": "other", "visibility": "team",
    }, headers=auth_headers)
    note_id = create.json()["note"]["id"]
    bad = await client.patch(f"/api/coach/notes/{note_id}", json={
        "match_id": None,
    }, headers=auth_headers)
    assert bad.status_code == 422


@pytest.mark.asyncio
async def test_observation_context_flip_video_to_observation_supported(client, auth_headers):
    """Flipping a video note to an observation note via PATCH is
    supported — the merged-state validator stops requiring match/slot/
    timestamp once `note_context` becomes 'observation'."""
    match = await client.post("/api/matches", json={
        "home_team": "OSU Steel", "away_team": "Flip FC", "date": "2026-05-13",
    }, headers=auth_headers)
    match_id = match.json()["id"]
    create = await client.post("/api/coach/notes", json={
        "match_id": match_id, "slot": "full", "timestamp_seconds": 12,
        "title": "Was a video note", "category": "other", "visibility": "team",
    }, headers=auth_headers)
    note_id = create.json()["note"]["id"]
    flip = await client.patch(f"/api/coach/notes/{note_id}", json={
        "note_context": "observation",
        "event_type": "meeting",
        "event_title": "Coach review chat",
    }, headers=auth_headers)
    assert flip.status_code == 200, flip.text
    note = flip.json()["note"]
    assert note["note_context"] == "observation"
    # The original match/slot/timestamp stay on the row — they're not
    # required for observation notes but clearing them isn't required
    # either. A future surface that cares can ignore them when
    # `note_context == "observation"`.
    assert note["match_id"] == match_id


@pytest.mark.asyncio
async def test_observation_context_flip_observation_to_video_requires_match(client, auth_headers):
    """Flipping an observation note BACK to video without supplying
    match/slot/timestamp must 422."""
    create = await client.post("/api/coach/notes", json={
        "title": "Original observation",
        "note_context": "observation",
        "category": "other", "visibility": "team",
        "event_type": "practice",
    }, headers=auth_headers)
    note_id = create.json()["note"]["id"]
    bad = await client.patch(f"/api/coach/notes/{note_id}", json={
        "note_context": "video",
    }, headers=auth_headers)
    assert bad.status_code == 422


@pytest.mark.asyncio
async def test_observation_coach_sees_full_payload_including_private_note(client, auth_headers):
    """Coach round-trip on an observation note still surfaces
    coach_private_note (privacy ladder shared with video notes)."""
    resp = await client.post("/api/coach/notes", json={
        "title": "Coach-only thoughts",
        "note_context": "observation",
        "category": "other", "visibility": "private",
        "event_type": "tactical",
        "coach_private_note": "Sketch — keep to bench.",
        "what_to_do_next": "Discuss with assistant.",
    }, headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["note"]["coach_private_note"] == "Sketch — keep to bench."


@pytest.mark.asyncio
async def test_observation_coach_private_note_scrubbed_for_viewer(client, auth_headers):
    """Privacy invariant: a team-visible observation note shows up in
    My Feedback for the viewer, but `coach_private_note` is `""`."""
    await client.post("/api/users", json={
        "username": "obs_viewer", "password": "password123", "role": "viewer",
    }, headers=auth_headers)
    viewer = await _login(client, "obs_viewer")
    create = await client.post("/api/coach/notes", json={
        "title": "Team observation",
        "note_context": "observation",
        "category": "other", "visibility": "team",
        "event_type": "meeting",
        "player_summary": "Friday meeting takeaways.",
        "coach_private_note": "INTERNAL — not for players.",
    }, headers=auth_headers)
    note_id = create.json()["note"]["id"]
    feedback = await client.get("/api/my-feedback", headers=viewer)
    payload = feedback.json()
    notes = [n for n in payload["notes"] if n["id"] == note_id]
    assert notes, "team-visible observation should appear in My Feedback"
    assert notes[0]["coach_private_note"] == ""
    assert notes[0]["note_context"] == "observation"


@pytest.mark.asyncio
async def test_observation_coach_private_note_scrubbed_via_playlist_items(client, auth_headers):
    """Defense-in-depth — `_filter_notes_for_user` scrubs `coach_private_note`
    on the top-level `notes[]` AND on the embedded `playlists[].items[]`
    via `my_feedback`'s `items_source`. The chain doesn't differentiate
    by `note_context`, so observation notes inside a team playlist must
    also surface to viewers with `coach_private_note=""`."""
    await client.post("/api/users", json={
        "username": "obs_pl_viewer", "password": "password123", "role": "viewer",
    }, headers=auth_headers)
    viewer = await _login(client, "obs_pl_viewer")
    note = await client.post("/api/coach/notes", json={
        "title": "Team observation in playlist",
        "note_context": "observation",
        "category": "other", "visibility": "team",
        "event_type": "meeting",
        "coach_private_note": "INTERNAL — must not leak via playlist.",
    }, headers=auth_headers)
    note_id = note.json()["note"]["id"]
    pl = await client.post("/api/coach/playlists", json={
        "title": "Team observation playlist",
        "visibility": "team",
        "note_ids": [note_id],
    }, headers=auth_headers)
    assert pl.status_code == 200
    feedback = await client.get("/api/my-feedback", headers=viewer)
    payload = feedback.json()
    leaked_items = [
        i for p in payload["playlists"] for i in p.get("items", [])
        if i.get("coach_private_note")
    ]
    assert leaked_items == [], (
        "observation-note coach_private_note leaked via playlists[].items[]: "
        f"{[(i.get('title'), i.get('coach_private_note')) for i in leaked_items]}"
    )


@pytest.mark.asyncio
async def test_observation_private_note_hidden_from_viewer(client, auth_headers):
    await client.post("/api/users", json={
        "username": "obs_viewer_priv", "password": "password123", "role": "viewer",
    }, headers=auth_headers)
    viewer = await _login(client, "obs_viewer_priv")
    await client.post("/api/coach/notes", json={
        "title": "Private observation",
        "note_context": "observation",
        "category": "other", "visibility": "private",
        "event_type": "meeting",
        "what_happened": "Coach-only.",
    }, headers=auth_headers)
    feedback = await client.get("/api/my-feedback", headers=viewer)
    titles = [n["title"] for n in feedback.json()["notes"]]
    assert "Private observation" not in titles


@pytest.mark.asyncio
async def test_observation_player_visibility_only_linked_family(client, auth_headers):
    family_resp = await client.post("/api/users", json={
        "username": "obs_family", "password": "password123", "role": "viewer",
    }, headers=auth_headers)
    family_id = family_resp.json()["user"]["id"]
    await client.post("/api/users", json={
        "username": "obs_unrelated", "password": "password123", "role": "viewer",
    }, headers=auth_headers)
    player_resp = await client.post("/api/coach/players", json={
        "display_name": "Obs Player", "jersey_number": "11",
    }, headers=auth_headers)
    player_id = player_resp.json()["player"]["id"]
    await client.post("/api/coach/player-links", json={
        "player_id": player_id, "user_id": family_id, "relationship": "parent",
    }, headers=auth_headers)
    create = await client.post("/api/coach/notes", json={
        "title": "Player-tagged observation",
        "note_context": "observation",
        "category": "other", "visibility": "player",
        "event_type": "tactical",
        "player_ids": [player_id],
        "player_summary": "Heads up before pressure.",
    }, headers=auth_headers)
    note_id = create.json()["note"]["id"]

    family = await _login(client, "obs_family")
    family_feedback = await client.get("/api/my-feedback", headers=family)
    assert note_id in [n["id"] for n in family_feedback.json()["notes"]]

    unrelated = await _login(client, "obs_unrelated")
    unrelated_feedback = await client.get("/api/my-feedback", headers=unrelated)
    assert note_id not in [n["id"] for n in unrelated_feedback.json()["notes"]]


@pytest.mark.asyncio
async def test_observation_note_appears_in_coach_list(client, auth_headers):
    """GET /api/coach/notes returns observation notes alongside video
    notes so existing list filtering keeps working."""
    match = await client.post("/api/matches", json={
        "home_team": "OSU Steel", "away_team": "Mixed FC", "date": "2026-05-14",
    }, headers=auth_headers)
    match_id = match.json()["id"]
    video = await client.post("/api/coach/notes", json={
        "match_id": match_id, "slot": "full", "timestamp_seconds": 5,
        "title": "Video note", "category": "other", "visibility": "team",
    }, headers=auth_headers)
    obs = await client.post("/api/coach/notes", json={
        "title": "Observation note",
        "note_context": "observation",
        "category": "other", "visibility": "team",
        "event_type": "practice",
    }, headers=auth_headers)
    listing = await client.get("/api/coach/notes", headers=auth_headers)
    payload = listing.json()
    contexts = {n["id"]: n["note_context"] for n in payload["notes"]}
    assert contexts.get(video.json()["note"]["id"]) == "video"
    assert contexts.get(obs.json()["note"]["id"]) == "observation"


@pytest.mark.asyncio
async def test_observation_thumbnail_get_returns_404(client, auth_headers, monkeypatch):
    """GET /api/coach/notes/{id}/thumbnail for an observation note
    must return 404 (no video frame to capture). Same response shape
    as the missing-file branch so a viewer can't probe."""
    # Stub the generator just so we'd notice if it was ever invoked.
    calls = await _install_thumbnail_stub(monkeypatch)
    create = await client.post("/api/coach/notes", json={
        "title": "Observation no-video",
        "note_context": "observation",
        "category": "other", "visibility": "team",
        "event_type": "meeting",
    }, headers=auth_headers)
    note_id = create.json()["note"]["id"]
    await _drain_background_tasks()
    assert calls == [], (
        "observation note must not schedule any thumbnail generation; "
        f"got {len(calls)} call(s)"
    )
    resp = await client.get(f"/api/coach/notes/{note_id}/thumbnail", headers=auth_headers)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_observation_thumbnail_regenerate_returns_generated_false(client, auth_headers):
    """POST regenerate for an observation note returns the existing
    `{ok: true, generated: false}` shape so frontends don't need a
    new branch."""
    create = await client.post("/api/coach/notes", json={
        "title": "Observation regen-target",
        "note_context": "observation",
        "category": "other", "visibility": "team",
        "event_type": "tactical",
        "player_summary": "n/a",
    }, headers=auth_headers)
    note_id = create.json()["note"]["id"]
    resp = await client.post(
        f"/api/coach/notes/{note_id}/thumbnail/regenerate",
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"ok": True, "generated": False}


@pytest.mark.asyncio
async def test_observation_create_does_not_invoke_thumbnail_generator(client, auth_headers, monkeypatch):
    """Defense in depth: observation note POST must not schedule any
    background thumbnail generation. Pairs with the GET 404 test."""
    calls = await _install_thumbnail_stub(monkeypatch)
    await client.post("/api/coach/notes", json={
        "title": "Observation no-spawn",
        "note_context": "observation",
        "category": "other", "visibility": "team",
        "event_type": "practice",
    }, headers=auth_headers)
    await _drain_background_tasks()
    assert calls == []


@pytest.mark.asyncio
async def test_observation_delete_does_not_fail_without_thumbnail(client, auth_headers):
    """DELETE on an observation note must succeed even though there
    is no thumbnail file on disk and no `match_id` to construct a
    path from."""
    create = await client.post("/api/coach/notes", json={
        "title": "Observation to delete",
        "note_context": "observation",
        "category": "other", "visibility": "team",
        "event_type": "other",
    }, headers=auth_headers)
    note_id = create.json()["note"]["id"]
    resp = await client.delete(f"/api/coach/notes/{note_id}", headers=auth_headers)
    assert resp.status_code == 200, resp.text


@pytest.mark.asyncio
async def test_observation_video_note_thumbnail_still_works(client, auth_headers, data_dir, monkeypatch):
    """Phase 6a invariant: existing video-note thumbnail generation
    keeps working — not regressed by the observation-note skip path."""
    calls = await _install_thumbnail_stub(monkeypatch)
    match = await client.post("/api/matches", json={
        "home_team": "OSU Steel", "away_team": "Still Works FC", "date": "2026-05-15",
    }, headers=auth_headers)
    match_id = match.json()["id"]
    note = await client.post("/api/coach/notes", json={
        "match_id": match_id, "slot": "full", "timestamp_seconds": 7,
        "title": "Video thumbnail check", "category": "other", "visibility": "team",
    }, headers=auth_headers)
    await _drain_background_tasks()
    assert len(calls) == 1
    note_id = note.json()["note"]["id"]
    resp = await client.get(
        f"/api/coach/notes/{note_id}/thumbnail", headers=auth_headers
    )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_observation_in_player_development_profile(client, auth_headers):
    """Phase 5a aggregation must include visible observation notes
    alongside video notes — observation notes are still notes."""
    family_resp = await client.post("/api/users", json={
        "username": "obs_dev_family", "password": "password123", "role": "viewer",
    }, headers=auth_headers)
    family_id = family_resp.json()["user"]["id"]
    player_resp = await client.post("/api/coach/players", json={
        "display_name": "Dev Player", "jersey_number": "21",
    }, headers=auth_headers)
    player_id = player_resp.json()["player"]["id"]
    await client.post("/api/coach/player-links", json={
        "player_id": player_id, "user_id": family_id, "relationship": "parent",
    }, headers=auth_headers)

    # Two notes for this player: one video, one observation. Both
    # team-visible so the linked viewer sees both.
    match = await client.post("/api/matches", json={
        "home_team": "OSU Steel", "away_team": "Dev FC", "date": "2026-05-16",
    }, headers=auth_headers)
    match_id = match.json()["id"]
    await client.post("/api/coach/notes", json={
        "match_id": match_id, "slot": "full", "timestamp_seconds": 1,
        "title": "Match note", "category": "other", "visibility": "team",
        "player_ids": [player_id],
    }, headers=auth_headers)
    await client.post("/api/coach/notes", json={
        "title": "Practice observation",
        "note_context": "observation",
        "category": "other", "visibility": "team",
        "event_type": "practice",
        "player_ids": [player_id],
        "what_to_do_next": "Drill again Thursday.",
        "note_type": "correction",
    }, headers=auth_headers)
    # A private observation should NOT show up on the viewer surface.
    await client.post("/api/coach/notes", json={
        "title": "Private observation",
        "note_context": "observation",
        "category": "other", "visibility": "private",
        "event_type": "meeting",
        "player_ids": [player_id],
        "coach_private_note": "Coach-only.",
    }, headers=auth_headers)

    coach_profile = await client.get(
        f"/api/coach/players/{player_id}/development", headers=auth_headers,
    )
    assert coach_profile.status_code == 200
    coach_counts = coach_profile.json()["profile"]["counts"]
    # Coach sees all 3 notes.
    assert coach_counts["notes"] == 3

    family = await _login(client, "obs_dev_family")
    viewer_profile = await client.get(
        f"/api/my-feedback/players/{player_id}/development", headers=family,
    )
    assert viewer_profile.status_code == 200
    viewer_counts = viewer_profile.json()["profile"]["counts"]
    # Viewer sees the 2 team-visible notes (video + observation),
    # never the private one.
    assert viewer_counts["notes"] == 2
    titles = [n["title"] for n in viewer_profile.json()["profile"]["recent_notes"]]
    assert "Practice observation" in titles
    assert "Private observation" not in titles
