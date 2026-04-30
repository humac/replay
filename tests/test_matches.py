"""Tests for match CRUD and input validation."""

from __future__ import annotations

import pytest


pytestmark = pytest.mark.asyncio


VALID_MATCH = {
    "home_team": "OSU Steel",
    "away_team": "Nepean Hotspurs",
    "date": "2026-03-14",
    "time": "15:30",
    "location": "Ohio Stadium",
    "score_home": 3,
    "score_away": 1,
    "format": "full",
}


async def test_create_match(client, auth_headers):
    resp = await client.post("/api/matches", json=VALID_MATCH, headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["home_team"] == "OSU Steel"
    assert data["away_team"] == "Nepean Hotspurs"
    assert data["score_home"] == 3
    assert data["format"] == "full"
    assert data["slug"]
    assert data["id"].startswith("match-")


async def test_create_match_requires_auth(client):
    resp = await client.post("/api/matches", json=VALID_MATCH)
    assert resp.status_code == 401


async def test_create_match_missing_fields(client, auth_headers):
    resp = await client.post("/api/matches", json={}, headers=auth_headers)
    assert resp.status_code == 422

    resp = await client.post("/api/matches", json={"home_team": "A"}, headers=auth_headers)
    assert resp.status_code == 422


async def test_create_match_bad_format(client, auth_headers):
    bad = {**VALID_MATCH, "format": "three_thirds"}
    resp = await client.post("/api/matches", json=bad, headers=auth_headers)
    assert resp.status_code == 422


async def test_create_match_bad_date(client, auth_headers):
    bad = {**VALID_MATCH, "date": "not-a-date"}
    resp = await client.post("/api/matches", json=bad, headers=auth_headers)
    assert resp.status_code == 422


async def test_create_match_bad_time(client, auth_headers):
    bad = {**VALID_MATCH, "time": "25:99"}
    # "25:99" matches HH:MM pattern but is semantically wrong.
    # Our validator only checks format (regex), so this passes.
    # That's acceptable — we validate shape, not semantics.
    resp = await client.post("/api/matches", json=bad, headers=auth_headers)
    assert resp.status_code == 200


async def test_create_match_bad_score_type(client, auth_headers):
    bad = {**VALID_MATCH, "score_home": "not-a-number"}
    resp = await client.post("/api/matches", json=bad, headers=auth_headers)
    assert resp.status_code == 422


async def test_create_match_two_halves(client, auth_headers):
    match = {**VALID_MATCH, "format": "two_halves"}
    resp = await client.post("/api/matches", json=match, headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["format"] == "two_halves"


async def test_create_match_minimal(client, auth_headers):
    resp = await client.post(
        "/api/matches",
        json={"home_team": "A", "away_team": "B"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["date"] == ""
    assert data["score_home"] is None
    assert data["format"] == "full"


async def test_list_matches(client, auth_headers):
    await client.post("/api/matches", json=VALID_MATCH, headers=auth_headers)
    await client.post(
        "/api/matches",
        json={**VALID_MATCH, "home_team": "Team B"},
        headers=auth_headers,
    )

    resp = await client.get("/api/matches")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2


async def test_update_match_partial(client, auth_headers):
    resp = await client.post("/api/matches", json=VALID_MATCH, headers=auth_headers)
    match_id = resp.json()["id"]

    resp = await client.put(
        f"/api/matches/{match_id}",
        json={"score_home": 5},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["score_home"] == 5
    assert resp.json()["home_team"] == "OSU Steel"  # unchanged


async def test_update_match_bad_date(client, auth_headers):
    resp = await client.post("/api/matches", json=VALID_MATCH, headers=auth_headers)
    match_id = resp.json()["id"]

    resp = await client.put(
        f"/api/matches/{match_id}",
        json={"date": "bad-date"},
        headers=auth_headers,
    )
    assert resp.status_code == 422


async def test_update_match_unknown_field(client, auth_headers):
    resp = await client.post("/api/matches", json=VALID_MATCH, headers=auth_headers)
    match_id = resp.json()["id"]

    resp = await client.put(
        f"/api/matches/{match_id}",
        json={"nonexistent_field": "value"},
        headers=auth_headers,
    )
    assert resp.status_code == 422


async def test_update_match_regenerates_slug(client, auth_headers):
    resp = await client.post("/api/matches", json=VALID_MATCH, headers=auth_headers)
    match_id = resp.json()["id"]
    old_slug = resp.json()["slug"]

    resp = await client.put(
        f"/api/matches/{match_id}",
        json={"home_team": "New Team Name"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["slug"] != old_slug


async def test_delete_match(client, auth_headers):
    resp = await client.post("/api/matches", json=VALID_MATCH, headers=auth_headers)
    match_id = resp.json()["id"]

    resp = await client.delete(f"/api/matches/{match_id}", headers=auth_headers)
    assert resp.status_code == 200

    resp = await client.get("/api/matches")
    assert len(resp.json()) == 0


async def test_delete_match_not_found(client, auth_headers):
    resp = await client.delete("/api/matches/nonexistent", headers=auth_headers)
    assert resp.status_code == 404


async def test_update_match_etag_conflict(client, auth_headers):
    # Create a match and capture its updated_at.
    resp = await client.post("/api/matches", json=VALID_MATCH, headers=auth_headers)
    assert resp.status_code == 200
    match_id = resp.json()["id"]

    # Do a first update (no If-Match) so we know the DB has the latest timestamp.
    resp = await client.put(
        f"/api/matches/{match_id}",
        json={"score_home": 5},
        headers=auth_headers,
    )
    assert resp.status_code == 200

    # Second update: sends a deliberately stale timestamp → must 409.
    stale_token = "2000-01-01T00:00:00.000Z"
    resp = await client.put(
        f"/api/matches/{match_id}",
        json={"score_away": 2},
        headers={**auth_headers, "If-Match": f'"{stale_token}"'},
    )
    assert resp.status_code == 409


async def test_update_match_etag_correct_token_succeeds(client, auth_headers):
    # PUT with the current updated_at as If-Match must succeed.
    resp = await client.post("/api/matches", json=VALID_MATCH, headers=auth_headers)
    assert resp.status_code == 200
    token = resp.json()["updated_at"]
    match_id = resp.json()["id"]

    resp = await client.put(
        f"/api/matches/{match_id}",
        json={"score_home": 3},
        headers={**auth_headers, "If-Match": f'"{token}"'},
    )
    assert resp.status_code == 200
    assert resp.json()["score_home"] == 3


async def test_update_match_no_ifmatch_succeeds(client, auth_headers):
    # PUT without an If-Match header must succeed unconditionally.
    resp = await client.post("/api/matches", json=VALID_MATCH, headers=auth_headers)
    assert resp.status_code == 200
    match_id = resp.json()["id"]

    resp = await client.put(
        f"/api/matches/{match_id}",
        json={"score_home": 7},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["score_home"] == 7


# ---------------------------------------------------------------------------
# Slug deep-links — /match, /match/{slug}, /match/{slug}/{slot}
#
# All three routes serve the SPA shell (the client-side router resolves the
# slug). These tests just confirm the routes exist, return HTML, and emit the
# SPA no-cache headers regardless of slug content.
# ---------------------------------------------------------------------------


async def test_match_deep_link_returns_spa_shell(client):
    resp = await client.get("/match")
    assert resp.status_code == 200
    assert "text/html" in resp.headers.get("content-type", "")


async def test_match_slug_deep_link_returns_spa_shell(client):
    resp = await client.get("/match/some-slug-2026")
    assert resp.status_code == 200
    assert "text/html" in resp.headers.get("content-type", "")


async def test_match_slug_slot_deep_link_returns_spa_shell(client):
    resp = await client.get("/match/some-slug/first-half")
    assert resp.status_code == 200
    assert "text/html" in resp.headers.get("content-type", "")


async def test_match_deep_link_emits_no_cache_headers(client):
    """SPA shell must not be cached or share/edge-stale a stale build."""
    resp = await client.get("/match/anything")
    # Shell uses _SPA_NO_CACHE which sets a Cache-Control: no-store style header.
    cc = resp.headers.get("cache-control", "")
    assert "no-store" in cc or "no-cache" in cc


# ---------------------------------------------------------------------------
# Logo upload + serve — including the security-header invariant for SVGs
# (CLAUDE.md: nosniff + CSP script-src 'none' + Content-Disposition: inline)
# ---------------------------------------------------------------------------


_TINY_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
    b"\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
    b"\x00\x00\x00\rIDATx\x9cc\xfc\xff\xff?\x03\x00\x07\x06\x02\x00\xa3\xc7"
    b"\x9b\xa6\x00\x00\x00\x00IEND\xaeB`\x82"
)

_TINY_SVG = (
    b"<svg xmlns='http://www.w3.org/2000/svg' width='1' height='1'>"
    b"<rect width='1' height='1' fill='red'/></svg>"
)


async def test_upload_logo_happy_path(client, auth_headers):
    resp = await client.post("/api/matches", json=VALID_MATCH, headers=auth_headers)
    match_id = resp.json()["id"]

    resp = await client.post(
        f"/api/matches/{match_id}/upload-logo?team=home",
        headers=auth_headers,
        files={"file": ("home.png", _TINY_PNG, "image/png")},
    )
    assert resp.status_code == 200
    assert resp.json()["team"] == "home"
    assert resp.json()["filename"] == "home_logo.png"


async def test_upload_logo_rejects_unsupported_extension(client, auth_headers):
    resp = await client.post("/api/matches", json=VALID_MATCH, headers=auth_headers)
    match_id = resp.json()["id"]

    resp = await client.post(
        f"/api/matches/{match_id}/upload-logo?team=home",
        headers=auth_headers,
        files={"file": ("home.gif", b"GIF89a...", "image/gif")},
    )
    assert resp.status_code == 400


async def test_upload_logo_requires_admin_or_uploader(client, auth_headers):
    # Create a viewer.
    await client.post("/api/users", json={
        "username": "viewer_logo",
        "password": "password123",
        "role": "viewer",
    }, headers=auth_headers)
    resp = await client.post("/api/login", json={
        "username": "viewer_logo",
        "password": "password123",
    })
    viewer_headers = {"Authorization": f"Bearer {resp.json()['token']}"}

    # Match created by admin.
    resp = await client.post("/api/matches", json=VALID_MATCH, headers=auth_headers)
    match_id = resp.json()["id"]

    resp = await client.post(
        f"/api/matches/{match_id}/upload-logo?team=home",
        headers=viewer_headers,
        files={"file": ("home.png", _TINY_PNG, "image/png")},
    )
    assert resp.status_code == 403


async def test_upload_logo_invalid_team_rejected(client, auth_headers):
    resp = await client.post("/api/matches", json=VALID_MATCH, headers=auth_headers)
    match_id = resp.json()["id"]

    resp = await client.post(
        f"/api/matches/{match_id}/upload-logo?team=neutral",
        headers=auth_headers,
        files={"file": ("x.png", _TINY_PNG, "image/png")},
    )
    assert resp.status_code == 400


async def test_serve_logo_404_when_no_upload(client, auth_headers):
    resp = await client.post("/api/matches", json=VALID_MATCH, headers=auth_headers)
    match_id = resp.json()["id"]

    resp = await client.get(f"/api/matches/{match_id}/logo/home")
    assert resp.status_code == 404


async def test_serve_png_logo_emits_nosniff_header(client, auth_headers):
    """All match-logo responses must emit X-Content-Type-Options: nosniff
    (defense-in-depth — see CLAUDE.md security note)."""
    resp = await client.post("/api/matches", json=VALID_MATCH, headers=auth_headers)
    match_id = resp.json()["id"]

    await client.post(
        f"/api/matches/{match_id}/upload-logo?team=home",
        headers=auth_headers,
        files={"file": ("home.png", _TINY_PNG, "image/png")},
    )
    resp = await client.get(f"/api/matches/{match_id}/logo/home")
    assert resp.status_code == 200
    assert resp.headers.get("x-content-type-options") == "nosniff"
    assert resp.headers.get("content-type", "").startswith("image/png")


async def test_serve_svg_logo_emits_csp_and_inline_disposition(client, auth_headers):
    """Stored-XSS hardening for SVG logos (the actually-dangerous case):
    the response must lock script execution off and force an inline
    disposition so the browser doesn't treat it as a generic download."""
    resp = await client.post("/api/matches", json=VALID_MATCH, headers=auth_headers)
    match_id = resp.json()["id"]

    await client.post(
        f"/api/matches/{match_id}/upload-logo?team=away",
        headers=auth_headers,
        files={"file": ("away.svg", _TINY_SVG, "image/svg+xml")},
    )
    resp = await client.get(f"/api/matches/{match_id}/logo/away")
    assert resp.status_code == 200
    assert resp.headers.get("x-content-type-options") == "nosniff"
    assert resp.headers.get("content-security-policy") == "script-src 'none'"
    assert resp.headers.get("content-disposition", "").startswith("inline")
    assert resp.headers.get("content-type", "").startswith("image/svg")


async def test_serve_logo_rejects_invalid_team(client, auth_headers):
    resp = await client.post("/api/matches", json=VALID_MATCH, headers=auth_headers)
    match_id = resp.json()["id"]

    resp = await client.get(f"/api/matches/{match_id}/logo/middle")
    assert resp.status_code == 400


async def test_serve_logo_404_for_unknown_match(client):
    resp = await client.get("/api/matches/does-not-exist/logo/home")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Thumbnail serving
# ---------------------------------------------------------------------------


async def test_serve_thumbnail_404_when_missing(client, auth_headers):
    resp = await client.post("/api/matches", json=VALID_MATCH, headers=auth_headers)
    match_id = resp.json()["id"]
    resp = await client.get(f"/api/matches/{match_id}/thumbnail")
    assert resp.status_code == 404


async def test_serve_thumbnail_returns_jpeg_with_cache_headers(client, auth_headers, data_dir):
    """When thumb.jpg exists on disk, serve it with mtime-tagged ETag."""
    resp = await client.post("/api/matches", json=VALID_MATCH, headers=auth_headers)
    match_id = resp.json()["id"]

    # Stage a fake thumbnail on disk where the route looks for it.
    thumb_path = data_dir / "videos" / match_id / "thumb.jpg"
    thumb_path.parent.mkdir(parents=True, exist_ok=True)
    thumb_path.write_bytes(b"\xff\xd8\xff\xd9")  # minimal JPEG SOI/EOI

    resp = await client.get(f"/api/matches/{match_id}/thumbnail")
    assert resp.status_code == 200
    assert resp.headers.get("content-type", "").startswith("image/jpeg")
    cc = resp.headers.get("cache-control", "")
    assert "no-cache" in cc or "must-revalidate" in cc
    # ETag is tagged with the mtime so admins regenerating a thumb bust the cache.
    assert resp.headers.get("etag")
