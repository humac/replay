"""Team-scoped member management and invite service."""

from __future__ import annotations

import json
import os
import secrets
import sqlite3
import time
import uuid

import auth as _auth
import db as _db
from services import teams as _teams

INVITE_TTL = 7 * 86400


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _normalize_email(email: str) -> str:
    value = (email or "").strip().lower()
    if "@" not in value or value.startswith("@") or value.endswith("@"):
        raise _teams.TeamServiceError(422, "Invite email is required")
    return value


def _invite_metadata(row: sqlite3.Row | dict) -> dict:
    try:
        return json.loads(row["metadata_json"] or "{}")
    except Exception:
        return {}


def _public_invite(row: sqlite3.Row | None, *, include_token: str | None = None) -> dict | None:
    if row is None:
        return None
    data = dict(row)
    data.pop("token_hash", None)
    data["metadata"] = _invite_metadata(row)
    data.pop("metadata_json", None)
    if include_token is not None:
        data["invite_token"] = include_token
    return data


def _public_user(row_or_user: sqlite3.Row | dict) -> dict:
    return {
        "id": row_or_user["id"],
        "username": row_or_user["username"],
        "role": row_or_user["role"],
        "display_name": row_or_user.get("display_name", "") if isinstance(row_or_user, dict) else (row_or_user["display_name"] or ""),
        "enabled": bool(row_or_user["enabled"]),
    }


def _membership_row(conn: sqlite3.Connection, membership_id: int) -> dict:
    row = conn.execute(
        """
        SELECT m.*, u.username, u.display_name
        FROM team_user_memberships AS m
        JOIN users AS u ON u.id = m.user_id
        WHERE m.id = ?
        """,
        (membership_id,),
    ).fetchone()
    if row is None:
        raise _teams.TeamServiceError(500, "Membership not found after write")
    return dict(row)


def _assert_team_admin(team_id: str, actor: dict) -> None:
    user_id = actor.get("user_id")
    with _db.connect() as conn:
        row = conn.execute(
            "SELECT role FROM team_user_memberships WHERE team_id = ? AND user_id = ?",
            (team_id, user_id),
        ).fetchone()
    if row is None or row["role"] != "team_admin":
        raise _teams.TeamServiceError(403, "Team admin membership required")


def list_memberships(team_id: str, actor: dict) -> list[dict]:
    _assert_team_admin(team_id, actor)
    return _teams.list_memberships(team_id)


def grant_membership(team_id: str, user_id: str, role: str, actor: dict) -> dict:
    _assert_team_admin(team_id, actor)
    return _teams.grant_membership(team_id=team_id, user_id=user_id, role=role)


def revoke_membership(team_id: str, membership_id: int, actor: dict) -> dict:
    _assert_team_admin(team_id, actor)
    return _teams.revoke_membership(team_id=team_id, membership_id=membership_id)


def _validate_season(conn: sqlite3.Connection, team_id: str, season_id: str | None) -> str | None:
    if not season_id:
        return None
    row = conn.execute("SELECT id FROM seasons WHERE id = ? AND team_id = ?", (season_id, team_id)).fetchone()
    if row is None:
        raise _teams.TeamServiceError(404, "Season not found for team")
    return season_id


def _validate_player_ids(conn: sqlite3.Connection, team_id: str, player_ids: list[str]) -> list[str]:
    cleaned = []
    for player_id in player_ids:
        value = str(player_id).strip()
        if not value or value in cleaned:
            continue
        row = conn.execute("SELECT id FROM players WHERE id = ? AND team_id = ?", (value, team_id)).fetchone()
        if row is None:
            raise _teams.TeamServiceError(404, "Invite player link not found for team")
        cleaned.append(value)
    return cleaned


def list_invites(team_id: str, actor: dict) -> list[dict]:
    _assert_team_admin(team_id, actor)
    with _db.connect() as conn:
        rows = conn.execute(
            "SELECT * FROM team_invites WHERE team_id = ? ORDER BY created_at DESC, id DESC",
            (team_id,),
        ).fetchall()
        return [_public_invite(row) for row in rows]


def create_invite(*, team_id: str, email: str, role: str, actor: dict, season_id: str | None = None, player_ids: list[str] | None = None) -> dict:
    _assert_team_admin(team_id, actor)
    clean_role = _teams._validate_membership_role(role)
    normalized_email = _normalize_email(email)
    token = secrets.token_urlsafe(32)
    invite_id = str(uuid.uuid4())
    now = time.time()
    expires_at = now + INVITE_TTL
    with _db.connect() as conn:
        if conn.execute("SELECT id FROM teams WHERE id = ?", (team_id,)).fetchone() is None:
            raise _teams.TeamServiceError(404, "Team not found")
        clean_season_id = _validate_season(conn, team_id, season_id)
        clean_player_ids = _validate_player_ids(conn, team_id, player_ids or [])
        metadata = {"player_ids": clean_player_ids}
        conn.execute(
            """
            INSERT INTO team_invites (
                id, team_id, season_id, normalized_email, role, status, token_hash,
                expires_at, created_at, created_by_user_id, metadata_json
            ) VALUES (?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?, ?)
            """,
            (
                invite_id,
                team_id,
                clean_season_id,
                normalized_email,
                clean_role,
                _auth.token_hash(token),
                expires_at,
                now,
                actor.get("user_id"),
                json.dumps(metadata, sort_keys=True),
            ),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM team_invites WHERE id = ?", (invite_id,)).fetchone()
    include_token = token if os.environ.get("REPLAY_DEV_TOKEN_DELIVERY") == "1" else None
    invite = _public_invite(row, include_token=include_token)
    if invite is None:
        raise _teams.TeamServiceError(500, "Invite not created")
    return invite


def revoke_invite(team_id: str, invite_id: str, actor: dict) -> dict:
    _assert_team_admin(team_id, actor)
    now = time.time()
    with _db.connect() as conn:
        row = conn.execute("SELECT * FROM team_invites WHERE id = ? AND team_id = ?", (invite_id, team_id)).fetchone()
        if row is None:
            raise _teams.TeamServiceError(404, "Invite not found")
        if row["status"] != "pending":
            raise _teams.TeamServiceError(409, "Invite is not pending")
        conn.execute("UPDATE team_invites SET status = 'revoked', revoked_at = ? WHERE id = ?", (now, invite_id))
        conn.commit()
        return _public_invite(conn.execute("SELECT * FROM team_invites WHERE id = ?", (invite_id,)).fetchone())


def _existing_user_for_invite(conn: sqlite3.Connection, invite: sqlite3.Row, user_id: str) -> dict:
    user = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if user is None or not bool(user["enabled"]):
        raise _teams.TeamServiceError(404, "User not found")
    profile = conn.execute("SELECT normalized_email FROM user_profiles WHERE user_id = ?", (user_id,)).fetchone()
    normalized = (profile["normalized_email"] if profile else "") or ""
    if normalized.strip().lower() != invite["normalized_email"]:
        raise _teams.TeamServiceError(403, "Invite email does not match user")
    return dict(user)


def _create_user_for_invite(conn: sqlite3.Connection, invite: sqlite3.Row, *, username: str | None, password: str | None, display_name: str | None) -> dict:
    clean_username = (username or "").strip()
    if not clean_username or not password:
        raise _teams.TeamServiceError(422, "Invite acceptance requires user_id or username/password")
    if conn.execute("SELECT id FROM users WHERE username = ? COLLATE NOCASE", (clean_username,)).fetchone() is not None:
        raise _teams.TeamServiceError(409, "Username already exists")
    now_iso = _now_iso()
    now_real = time.time()
    new_user = {
        "id": str(uuid.uuid4()),
        "username": clean_username,
        "password_hash": _auth.hash_password(password),
        "role": "viewer",
        "display_name": (display_name or clean_username).strip(),
        "enabled": 1,
        "created_at": now_iso,
        "updated_at": now_iso,
    }
    conn.execute(
        """
        INSERT INTO users (id, username, password_hash, role, display_name, enabled, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, 1, ?, ?)
        """,
        (new_user["id"], new_user["username"], new_user["password_hash"], new_user["role"], new_user["display_name"], now_iso, now_iso),
    )
    conn.execute(
        """
        INSERT INTO user_profiles (user_id, email, normalized_email, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (new_user["id"], invite["normalized_email"], invite["normalized_email"], now_real, now_real),
    )
    return new_user


def _grant_or_get_membership(conn: sqlite3.Connection, *, team_id: str, user_id: str, role: str) -> dict:
    existing = conn.execute(
        """
        SELECT m.*, u.username, u.display_name
        FROM team_user_memberships AS m
        JOIN users AS u ON u.id = m.user_id
        WHERE m.team_id = ? AND m.user_id = ? AND m.role = ?
        """,
        (team_id, user_id, role),
    ).fetchone()
    if existing is not None:
        return dict(existing)
    now = _now_iso()
    cursor = conn.execute(
        "INSERT INTO team_user_memberships (team_id, user_id, role, created_at) VALUES (?, ?, ?, ?)",
        (team_id, user_id, role, now),
    )
    return _membership_row(conn, cursor.lastrowid)


def _link_invite_players(conn: sqlite3.Connection, invite: sqlite3.Row, user_id: str) -> None:
    metadata = _invite_metadata(invite)
    relationship = "guardian" if invite["role"] == "guardian" else invite["role"]
    now = _now_iso()
    for player_id in metadata.get("player_ids") or []:
        player = conn.execute("SELECT id, team_id FROM players WHERE id = ? AND team_id = ?", (player_id, invite["team_id"])).fetchone()
        if player is None:
            raise _teams.TeamServiceError(404, "Invite player link not found for team")
        conn.execute(
            """
            INSERT INTO player_user_links (player_id, user_id, relationship, created_at, team_id)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(player_id, user_id) DO UPDATE SET relationship = excluded.relationship, team_id = excluded.team_id
            """,
            (player_id, user_id, relationship, now, invite["team_id"]),
        )


def accept_invite(*, token: str, user_id: str | None = None, username: str | None = None, password: str | None = None, display_name: str | None = None) -> dict:
    now = time.time()
    with _db.connect() as conn:
        try:
            conn.execute("BEGIN IMMEDIATE")
            invite = conn.execute("SELECT * FROM team_invites WHERE token_hash = ?", (_auth.token_hash(token),)).fetchone()
            if invite is None:
                raise _teams.TeamServiceError(404, "Invite not found")
            if invite["status"] != "pending" or invite["accepted_at"] or invite["revoked_at"]:
                raise _teams.TeamServiceError(409, "Invite is not pending")
            if invite["expires_at"] <= now:
                conn.execute("UPDATE team_invites SET status = 'expired' WHERE id = ?", (invite["id"],))
                conn.commit()
                raise _teams.TeamServiceError(410, "Invite expired")
            user = _existing_user_for_invite(conn, invite, user_id) if user_id else _create_user_for_invite(
                conn,
                invite,
                username=username,
                password=password,
                display_name=display_name,
            )
            membership = _grant_or_get_membership(conn, team_id=invite["team_id"], user_id=user["id"], role=invite["role"])
            _link_invite_players(conn, invite, user["id"])
            conn.execute(
                "UPDATE team_invites SET status = 'accepted', accepted_at = ?, accepted_by_user_id = ? WHERE id = ?",
                (now, user["id"], invite["id"]),
            )
            conn.commit()
        except _teams.TeamServiceError:
            if conn.in_transaction:
                conn.rollback()
            raise
        except sqlite3.IntegrityError as exc:
            if conn.in_transaction:
                conn.rollback()
            if "UNIQUE" in str(exc):
                raise _teams.TeamServiceError(409, "Invite acceptance conflicts with existing data") from exc
            raise
        except Exception:
            if conn.in_transaction:
                conn.rollback()
            raise
    return {"ok": True, "invite": get_invite(invite["id"]), "user": _public_user(user), "membership": membership}


def get_invite(invite_id: str) -> dict | None:
    with _db.connect() as conn:
        return _public_invite(conn.execute("SELECT * FROM team_invites WHERE id = ?", (invite_id,)).fetchone())
