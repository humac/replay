"""Strict tenancy guardrails for tenant-aware DB helpers."""

from __future__ import annotations

import os

import pytest

import db as _db


@pytest.mark.asyncio
async def test_strict_tenancy_enabled_by_default_in_tests(client):
    assert os.environ.get("REPLAY_STRICT_TENANCY") == "1"
    assert _db.strict_tenancy_enabled() is True


@pytest.mark.asyncio
async def test_strict_tenancy_requires_team_id_for_tenant_aware_helpers(client):
    player = _db.create_player("Strict Scope Player")

    with pytest.raises(RuntimeError, match="list_players requires team_id"):
        _db.list_players()
    with pytest.raises(RuntimeError, match="get_player requires team_id"):
        _db.get_player(player["id"])
    with pytest.raises(RuntimeError, match="list_users requires team_id"):
        _db.list_users()
    with pytest.raises(RuntimeError, match="linked_player_ids_for_user requires team_id"):
        _db.linked_player_ids_for_user("some-user")


@pytest.mark.asyncio
async def test_strict_tenancy_allows_explicit_team_scope_and_documented_global_reads(client):
    team = _db.get_default_team()
    player = _db.create_player("Strict Scoped Player", team_id=team["id"])

    assert any(p["id"] == player["id"] for p in _db.list_players(team_id=team["id"]))
    assert _db.get_player(player["id"], team_id=team["id"])["id"] == player["id"]
    assert isinstance(_db.list_users(team_id=team["id"]), list)
    assert _db.linked_player_ids_for_user("missing-user", team_id=team["id"]) == []

    assert isinstance(_db.list_players(allow_unscoped=True), list)
    assert _db.get_player(player["id"], allow_unscoped=True)["id"] == player["id"]
    assert isinstance(_db.list_users(allow_unscoped=True), list)
    assert _db.linked_player_ids_for_user("missing-user", allow_unscoped=True) == []


@pytest.mark.asyncio
async def test_non_strict_legacy_fallback_still_allows_omitted_team_id(client, monkeypatch):
    monkeypatch.setenv("REPLAY_STRICT_TENANCY", "0")
    player = _db.create_player("Legacy Fallback Player")

    assert _db.strict_tenancy_enabled() is False
    assert any(p["id"] == player["id"] for p in _db.list_players())
    assert _db.get_player(player["id"])["id"] == player["id"]
    assert isinstance(_db.list_users(), list)
    assert _db.linked_player_ids_for_user("missing-user") == []
