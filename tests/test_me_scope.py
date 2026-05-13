from __future__ import annotations

import json

import pytest


def _auth_headers(user_id: str, role: str, username: str) -> dict[str, str]:
    import auth as _auth

    token = _auth.create_token(user_id, role, username)
    return {"Authorization": f"Bearer {token}"}


def _insert_team_with_season(conn, team_id: str, slug: str, *, name: str | None = None, season_id: str | None = None):
    now = "2026-04-01T00:00:00Z"
    season_id = season_id or f"{team_id}-season"
    conn.execute(
        "INSERT INTO teams (id, name, slug, game_format, created_at) VALUES (?, ?, ?, 'full', ?)",
        (team_id, name or team_id.replace('-', ' ').title(), slug, now),
    )
    conn.execute(
        "INSERT INTO seasons (id, team_id, name, starts_on, ends_on, created_at) VALUES (?, ?, 'Default Season', '', '', ?)",
        (season_id, team_id, now),
    )
    return season_id


def _insert_user(conn, user_id: str, username: str, role: str = "viewer", *, display_name: str = "", last_team_id: str | None = None):
    now = "2026-04-01T00:00:00Z"
    conn.execute(
        """
        INSERT INTO users (id, username, password_hash, role, display_name, enabled, created_at, updated_at, last_team_id)
        VALUES (?, ?, 'hash', ?, ?, 1, ?, ?, ?)
        """,
        (user_id, username, role, display_name, now, now, last_team_id),
    )


def _grant_membership(conn, team_id: str, user_id: str, role: str):
    conn.execute(
        "INSERT INTO team_user_memberships (team_id, user_id, role, created_at) VALUES (?, ?, ?, '2026-04-01T00:00:00Z')",
        (team_id, user_id, role),
    )


@pytest.mark.asyncio
async def test_me_scope_single_team_user_gets_active_scope(client):
    import db as _db

    with _db.connect() as conn:
        _insert_team_with_season(conn, "scope-one", "scope-one", name="Scope One")
        _insert_user(conn, "scope-user", "scope_user", "viewer", display_name="Scope User")
        _grant_membership(conn, "scope-one", "scope-user", "coach")
        conn.commit()

    resp = await client.get("/api/me", headers=_auth_headers("scope-user", "coach", "scope_user"))

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["user"] == {
        "id": "scope-user",
        "username": "scope_user",
        "display_name": "Scope User",
        "role": "viewer",
        "roles": ["viewer"],
        "is_global_admin": False,
        "last_team_id": None,
        "last_season_id": None,
    }
    assert body["selection_required"] is False
    assert body["active_scope"]["team"]["id"] == "scope-one"
    assert body["active_scope"]["season"]["id"] == "scope-one-season"
    assert body["active_scope"]["membership"]["role"] == "coach"
    assert [team["id"] for team in body["teams"]] == ["scope-one"]
    assert [membership["team_id"] for membership in body["memberships"]] == ["scope-one"]


@pytest.mark.asyncio
async def test_me_scope_multi_team_user_lists_eligible_teams_without_sensitive_data(client):
    import db as _db

    with _db.connect() as conn:
        _insert_team_with_season(conn, "scope-a", "scope-a", name="Scope A")
        _insert_team_with_season(conn, "scope-b", "scope-b", name="Scope B")
        _insert_team_with_season(conn, "scope-unrelated", "scope-unrelated", name="Scope Unrelated")
        _insert_user(conn, "multi-user", "multi_user", "viewer")
        _insert_user(conn, "other-user", "other_user", "viewer", display_name="Other User")
        _grant_membership(conn, "scope-a", "multi-user", "coach")
        _grant_membership(conn, "scope-b", "multi-user", "assistant_coach")
        _grant_membership(conn, "scope-unrelated", "other-user", "coach")
        conn.commit()

    resp = await client.get("/api/me", headers=_auth_headers("multi-user", "coach", "multi_user"))

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["active_scope"] is None
    assert body["selection_required"] is True
    assert {team["id"] for team in body["teams"]} == {"scope-a", "scope-b"}
    assert {season["team_id"] for season in body["seasons"]} == {"scope-a", "scope-b"}
    serialized = json.dumps(body)
    assert "password_hash" not in serialized
    assert "hash" not in serialized
    assert "other_user" not in serialized
    assert "Other User" not in serialized
    assert "scope-unrelated" not in serialized


@pytest.mark.asyncio
async def test_me_scope_viewer_membership_does_not_expose_unrelated_player_data(client):
    import db as _db

    now = "2026-04-01T00:00:00Z"
    with _db.connect() as conn:
        _insert_team_with_season(conn, "family-team", "family-team", name="Family Team")
        _insert_user(conn, "family-user", "family_user", "viewer")
        _grant_membership(conn, "family-team", "family-user", "guardian")
        conn.execute(
            """
            INSERT INTO players (id, display_name, jersey_number, active, notes, created_at, updated_at, team_id, season_id)
            VALUES ('linked-player', 'Linked Player', '9', 1, '', ?, ?, 'family-team', 'family-team-season')
            """,
            (now, now),
        )
        conn.execute(
            """
            INSERT INTO players (id, display_name, jersey_number, active, notes, created_at, updated_at, team_id, season_id)
            VALUES ('unrelated-player', 'Unrelated Player', '10', 1, '', ?, ?, 'family-team', 'family-team-season')
            """,
            (now, now),
        )
        conn.execute(
            """
            INSERT INTO player_user_links (player_id, user_id, relationship, created_at, team_id)
            VALUES ('linked-player', 'family-user', 'parent', ?, 'family-team')
            """,
            (now,),
        )
        conn.commit()

    resp = await client.get("/api/me", headers=_auth_headers("family-user", "viewer", "family_user"))

    assert resp.status_code == 200, resp.text
    body = resp.json()
    serialized = json.dumps(body)
    assert "players" not in body
    assert "linked-player" not in serialized
    assert "Linked Player" not in serialized
    assert "unrelated-player" not in serialized
    assert "Unrelated Player" not in serialized


@pytest.mark.asyncio
async def test_me_scope_explicit_team_selector_resolves_multi_team_user(client):
    import db as _db

    with _db.connect() as conn:
        _insert_team_with_season(conn, "explicit-a", "explicit-a", name="Explicit A")
        _insert_team_with_season(conn, "explicit-b", "explicit-b", name="Explicit B")
        _insert_user(conn, "explicit-user", "explicit_user", "viewer")
        _grant_membership(conn, "explicit-a", "explicit-user", "coach")
        _grant_membership(conn, "explicit-b", "explicit-user", "coach")
        conn.commit()

    resp = await client.get("/api/me?team=explicit-b", headers=_auth_headers("explicit-user", "coach", "explicit_user"))

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["selection_required"] is False
    assert body["active_scope"]["team"]["id"] == "explicit-b"
    assert {team["id"] for team in body["teams"]} == {"explicit-a", "explicit-b"}


@pytest.mark.asyncio
async def test_me_scope_collapses_unavailable_explicit_selectors_without_tenant_enumeration(client):
    import db as _db

    with _db.connect() as conn:
        _insert_team_with_season(conn, "eligible-team", "eligible-team", name="Eligible Team")
        _insert_team_with_season(conn, "hidden-team", "hidden-team", name="Hidden Team", season_id="hidden-season")
        _insert_user(conn, "probe-user", "probe_user", "viewer")
        _grant_membership(conn, "eligible-team", "probe-user", "coach")
        conn.commit()

    headers = _auth_headers("probe-user", "coach", "probe_user")
    probes = [
        "/api/me?team=hidden-team",
        "/api/me?team=missing-team",
        "/api/me?team_id=hidden-team",
        "/api/me?team_id=missing-team",
        "/api/me?season_id=hidden-season",
        "/api/me?season_id=missing-season",
    ]

    for url in probes:
        resp = await client.get(url, headers=headers)
        assert resp.status_code == 200, f"{url}: {resp.text}"
        body = resp.json()
        assert body["active_scope"] is None
        assert body["selection_required"] is False
        serialized = json.dumps(body)
        assert "eligible-team" in serialized
        assert "hidden-team" not in serialized
        assert "hidden-season" not in serialized


@pytest.mark.asyncio
async def test_me_scope_can_save_team_and_season_and_subsequent_requests_use_saved_scope(client):
    import db as _db

    with _db.connect() as conn:
        _insert_team_with_season(conn, "persist-a", "persist-a", name="Persist A")
        _insert_team_with_season(conn, "persist-b", "persist-b", name="Persist B")
        conn.execute(
            "INSERT INTO seasons (id, team_id, name, starts_on, ends_on, created_at) VALUES (?, ?, 'Spring Season', '2026-04-01', '', ?)",
            ("persist-b-spring", "persist-b", "2026-04-02T00:00:00Z"),
        )
        _insert_user(conn, "persist-user", "persist_user", "viewer")
        _grant_membership(conn, "persist-a", "persist-user", "coach")
        _grant_membership(conn, "persist-b", "persist-user", "coach")
        conn.commit()

    headers = _auth_headers("persist-user", "coach", "persist_user")
    saved = await client.put(
        "/api/me/scope",
        headers=headers,
        json={"team_id": "persist-b", "season_id": "persist-b-spring"},
    )

    assert saved.status_code == 200, saved.text
    assert saved.json()["active_scope"]["team"]["id"] == "persist-b"
    assert saved.json()["active_scope"]["season"]["id"] == "persist-b-spring"
    assert saved.json()["selection_required"] is False

    refreshed = await client.get("/api/me", headers=headers)
    assert refreshed.status_code == 200, refreshed.text
    body = refreshed.json()
    assert body["active_scope"]["team"]["id"] == "persist-b"
    assert body["active_scope"]["season"]["id"] == "persist-b-spring"
    assert body["user"]["last_team_id"] == "persist-b"
    assert body["user"]["last_season_id"] == "persist-b-spring"

    explicit_team = await client.get("/api/me?team_id=persist-b", headers=headers)
    assert explicit_team.status_code == 200, explicit_team.text
    assert explicit_team.json()["active_scope"]["season"]["id"] == "persist-b-spring"


@pytest.mark.asyncio
async def test_me_scope_rejects_saving_team_without_membership(client):
    import db as _db

    with _db.connect() as conn:
        _insert_team_with_season(conn, "member-team", "member-team")
        _insert_team_with_season(conn, "non-member-team", "non-member-team")
        _insert_user(conn, "membership-user", "membership_user", "viewer")
        _grant_membership(conn, "member-team", "membership-user", "coach")
        conn.commit()

    headers = _auth_headers("membership-user", "coach", "membership_user")
    existing = await client.put(
        "/api/me/scope",
        headers=headers,
        json={"team_id": "non-member-team", "season_id": "non-member-team-season"},
    )
    missing = await client.put(
        "/api/me/scope",
        headers=headers,
        json={"team_id": "missing-team", "season_id": "missing-team-season"},
    )

    assert existing.status_code == 403
    assert missing.status_code == 403
    assert existing.json() == missing.json() == {"detail": "Scope selection is not available"}


@pytest.mark.asyncio
async def test_me_scope_rejects_saving_season_from_another_team(client):
    import db as _db

    with _db.connect() as conn:
        _insert_team_with_season(conn, "season-member-team", "season-member-team")
        _insert_team_with_season(conn, "season-other-team", "season-other-team")
        _insert_user(conn, "season-user", "season_user", "viewer")
        _grant_membership(conn, "season-member-team", "season-user", "coach")
        conn.commit()

    headers = _auth_headers("season-user", "coach", "season_user")
    existing = await client.put(
        "/api/me/scope",
        headers=headers,
        json={"team_id": "season-member-team", "season_id": "season-other-team-season"},
    )
    missing = await client.put(
        "/api/me/scope",
        headers=headers,
        json={"team_id": "season-member-team", "season_id": "missing-season"},
    )

    assert existing.status_code == 403
    assert missing.status_code == 403
    assert existing.json() == missing.json() == {"detail": "Scope selection is not available"}


@pytest.mark.asyncio
async def test_me_scope_rejects_blank_active_scope_selectors(client):
    import db as _db

    with _db.connect() as conn:
        _insert_team_with_season(conn, "blank-team", "blank-team")
        _insert_user(conn, "blank-user", "blank_user", "viewer")
        _grant_membership(conn, "blank-team", "blank-user", "coach")
        conn.commit()

    resp = await client.put(
        "/api/me/scope",
        headers=_auth_headers("blank-user", "coach", "blank_user"),
        json={"team_id": "   ", "season_id": "blank-team-season"},
    )

    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_me_scope_revoked_saved_membership_requires_reselection(client):
    import db as _db

    with _db.connect() as conn:
        _insert_team_with_season(conn, "revoked-a", "revoked-a")
        _insert_team_with_season(conn, "revoked-b", "revoked-b")
        _insert_user(conn, "revoked-user", "revoked_user", "viewer")
        _grant_membership(conn, "revoked-a", "revoked-user", "coach")
        _grant_membership(conn, "revoked-b", "revoked-user", "coach")
        conn.commit()

    headers = _auth_headers("revoked-user", "coach", "revoked_user")
    saved = await client.put(
        "/api/me/scope",
        headers=headers,
        json={"team_id": "revoked-b", "season_id": "revoked-b-season"},
    )
    assert saved.status_code == 200, saved.text

    with _db.connect() as conn:
        conn.execute("DELETE FROM team_user_memberships WHERE team_id = 'revoked-b' AND user_id = 'revoked-user'")
        conn.commit()

    refreshed = await client.get("/api/me", headers=headers)
    assert refreshed.status_code == 200, refreshed.text
    body = refreshed.json()
    assert body["active_scope"] is None
    assert body["selection_required"] is True
    assert body["user"]["last_team_id"] is None
    assert body["user"]["last_season_id"] is None


@pytest.mark.asyncio
async def test_matches_endpoint_filters_by_authorized_active_scope(client):
    import db as _db

    now = "2026-04-01T00:00:00Z"
    with _db.connect() as conn:
        _insert_team_with_season(conn, "matches-a", "matches-a", name="Matches A")
        _insert_team_with_season(conn, "matches-b", "matches-b", name="Matches B")
        _insert_user(conn, "matches-user", "matches_user", "viewer")
        _grant_membership(conn, "matches-a", "matches-user", "coach")
        conn.commit()
    noisy_unrelated_matches = [
        {
            "id": f"match-scope-b-noise-{idx}",
            "home_team": "Matches B",
            "away_team": f"Visitors {idx}",
            "date": "2026-04-02",
            "time": "10:00",
            "location": "Field B",
            "score_home": "2",
            "score_away": "0",
            "format": "full",
            "videos": {"full": None, "first_half": None, "second_half": None},
            "video_status": {"full": "none", "first_half": "none", "second_half": "none"},
            "home_logo": None,
            "away_logo": None,
            "created_at": f"2026-04-02T00:{idx // 60:02d}:{idx % 60:02d}Z",
            "updated_at": now,
            "slug": f"match-scope-b-noise-{idx}",
            "team_id": "matches-b",
            "season_id": "matches-b-season",
        }
        for idx in range(501)
    ]
    _db.save_matches_unlocked([
        *noisy_unrelated_matches,
        {
            "id": "match-scope-a",
            "home_team": "Matches A",
            "away_team": "Visitors",
            "date": "2026-04-01",
            "time": "10:00",
            "location": "Field A",
            "score_home": "1",
            "score_away": "0",
            "format": "full",
            "videos": {"full": None, "first_half": None, "second_half": None},
            "video_status": {"full": "none", "first_half": "none", "second_half": "none"},
            "home_logo": None,
            "away_logo": None,
            "created_at": now,
            "updated_at": now,
            "slug": "match-scope-a",
            "team_id": "matches-a",
            "season_id": "matches-a-season",
        },
        {
            "id": "match-scope-b",
            "home_team": "Matches B",
            "away_team": "Visitors",
            "date": "2026-04-02",
            "time": "10:00",
            "location": "Field B",
            "score_home": "2",
            "score_away": "0",
            "format": "full",
            "videos": {"full": None, "first_half": None, "second_half": None},
            "video_status": {"full": "none", "first_half": "none", "second_half": "none"},
            "home_logo": None,
            "away_logo": None,
            "created_at": now,
            "updated_at": now,
            "slug": "match-scope-b",
            "team_id": "matches-b",
            "season_id": "matches-b-season",
        },
    ])

    headers = _auth_headers("matches-user", "coach", "matches_user")
    scoped = await client.get("/api/matches?team_id=matches-a&season_id=matches-a-season", headers=headers)
    unauthorized = await client.get("/api/matches?team_id=matches-b&season_id=matches-b-season", headers=headers)
    anonymous = await client.get("/api/matches?team_id=matches-a&season_id=matches-a-season")

    assert scoped.status_code == 200, scoped.text
    assert [match["id"] for match in scoped.json()] == ["match-scope-a"]
    assert unauthorized.status_code == 403
    assert anonymous.status_code == 401


@pytest.mark.asyncio
async def test_me_scope_requires_authentication(client):
    resp = await client.get("/api/me")

    assert resp.status_code == 401
