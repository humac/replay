"""Global-admin team, season, and membership management service."""

from __future__ import annotations

import re
import sqlite3
import time
import uuid
from dataclasses import dataclass

import db as _db

_SLUG_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_VALID_GAME_FORMATS = {"full", "7v7", "9v9", "11v11"}
_VALID_MEMBERSHIP_ROLES = {"team_admin", "coach", "assistant_coach", "guardian", "player", "viewer"}


@dataclass
class TeamServiceError(Exception):
    status_code: int
    detail: str


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _row(row: sqlite3.Row | None) -> dict | None:
    return dict(row) if row is not None else None


def _require_team(conn: sqlite3.Connection, team_id: str) -> dict:
    team = _row(conn.execute("SELECT * FROM teams WHERE id = ?", (team_id,)).fetchone())
    if team is None:
        raise TeamServiceError(404, "Team not found")
    return team


def _validate_slug(slug: str) -> str:
    cleaned = (slug or "").strip().lower()
    if not _SLUG_RE.match(cleaned):
        raise TeamServiceError(422, "Team slug must be URL-safe lowercase letters, numbers, and hyphens")
    return cleaned


def _validate_game_format(game_format: str | None) -> str:
    value = (game_format or "full").strip()
    if value not in _VALID_GAME_FORMATS:
        raise TeamServiceError(422, "Unsupported game format")
    return value


def _validate_membership_role(role: str) -> str:
    value = (role or "").strip().lower()
    if value not in _VALID_MEMBERSHIP_ROLES:
        raise TeamServiceError(422, "Unsupported membership role")
    return value


def _validate_date(value: str | None, field_name: str) -> str:
    cleaned = (value or "").strip()
    if cleaned and not _DATE_RE.match(cleaned):
        raise TeamServiceError(422, f"{field_name} must be empty or YYYY-MM-DD")
    return cleaned


def list_teams() -> list[dict]:
    with _db.connect() as conn:
        rows = conn.execute("SELECT * FROM teams ORDER BY created_at ASC, name COLLATE NOCASE ASC").fetchall()
        return [dict(row) for row in rows]


def get_team_by_slug(slug: str) -> dict | None:
    with _db.connect() as conn:
        row = conn.execute("SELECT * FROM teams WHERE slug = ?", (_validate_slug(slug),)).fetchone()
        return _row(row)


def create_team(*, name: str, slug: str, game_format: str = "full") -> dict:
    clean_name = (name or "").strip()
    if not clean_name:
        raise TeamServiceError(422, "Team name is required")
    clean_slug = _validate_slug(slug)
    clean_format = _validate_game_format(game_format)
    team_id = str(uuid.uuid4())
    now = _now_iso()
    try:
        with _db.connect() as conn:
            conn.execute(
                "INSERT INTO teams (id, name, slug, game_format, created_at) VALUES (?, ?, ?, ?, ?)",
                (team_id, clean_name, clean_slug, clean_format, now),
            )
            conn.commit()
            return dict(conn.execute("SELECT * FROM teams WHERE id = ?", (team_id,)).fetchone())
    except sqlite3.IntegrityError as exc:
        if "teams.slug" in str(exc) or "UNIQUE" in str(exc):
            raise TeamServiceError(409, "Team slug already exists") from exc
        raise


def update_team(team_id: str, *, name: str | None = None, game_format: str | None = None) -> dict:
    updates: dict[str, str] = {}
    if name is not None:
        clean_name = name.strip()
        if not clean_name:
            raise TeamServiceError(422, "Team name is required")
        updates["name"] = clean_name
    if game_format is not None:
        updates["game_format"] = _validate_game_format(game_format)
    with _db.connect() as conn:
        _require_team(conn, team_id)
        if updates:
            set_clause = ", ".join(f"{key} = ?" for key in updates)
            conn.execute(f"UPDATE teams SET {set_clause} WHERE id = ?", [*updates.values(), team_id])
            conn.commit()
        return dict(conn.execute("SELECT * FROM teams WHERE id = ?", (team_id,)).fetchone())


def list_seasons(team_id: str) -> list[dict]:
    with _db.connect() as conn:
        _require_team(conn, team_id)
        rows = conn.execute(
            "SELECT * FROM seasons WHERE team_id = ? ORDER BY starts_on ASC, created_at ASC, name COLLATE NOCASE ASC",
            (team_id,),
        ).fetchall()
        return [dict(row) for row in rows]


def create_season(*, team_id: str, name: str, starts_on: str = "", ends_on: str = "") -> dict:
    clean_name = (name or "").strip()
    if not clean_name:
        raise TeamServiceError(422, "Season name is required")
    clean_starts_on = _validate_date(starts_on, "starts_on")
    clean_ends_on = _validate_date(ends_on, "ends_on")
    season_id = str(uuid.uuid4())
    now = _now_iso()
    with _db.connect() as conn:
        _require_team(conn, team_id)
        conn.execute(
            "INSERT INTO seasons (id, team_id, name, starts_on, ends_on, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (season_id, team_id, clean_name, clean_starts_on, clean_ends_on, now),
        )
        conn.commit()
        return dict(conn.execute("SELECT * FROM seasons WHERE id = ?", (season_id,)).fetchone())


def list_memberships(team_id: str) -> list[dict]:
    with _db.connect() as conn:
        _require_team(conn, team_id)
        rows = conn.execute(
            """
            SELECT m.*, u.username, u.display_name
            FROM team_user_memberships AS m
            JOIN users AS u ON u.id = m.user_id
            WHERE m.team_id = ?
            ORDER BY u.username COLLATE NOCASE ASC, m.role ASC, m.id ASC
            """,
            (team_id,),
        ).fetchall()
        return [dict(row) for row in rows]


def grant_membership(*, team_id: str, user_id: str, role: str) -> dict:
    clean_role = _validate_membership_role(role)
    now = _now_iso()
    try:
        with _db.connect() as conn:
            _require_team(conn, team_id)
            user = conn.execute("SELECT id FROM users WHERE id = ?", (user_id,)).fetchone()
            if user is None:
                raise TeamServiceError(404, "User not found")
            cursor = conn.execute(
                "INSERT INTO team_user_memberships (team_id, user_id, role, created_at) VALUES (?, ?, ?, ?)",
                (team_id, user_id, clean_role, now),
            )
            conn.commit()
            row = conn.execute(
                """
                SELECT m.*, u.username, u.display_name
                FROM team_user_memberships AS m
                JOIN users AS u ON u.id = m.user_id
                WHERE m.id = ?
                """,
                (cursor.lastrowid,),
            ).fetchone()
            return dict(row)
    except sqlite3.IntegrityError as exc:
        if "team_user_memberships" in str(exc) or "UNIQUE" in str(exc):
            raise TeamServiceError(409, "Membership already exists") from exc
        raise


def revoke_membership(*, team_id: str, membership_id: int) -> dict:
    with _db.connect() as conn:
        try:
            conn.execute("BEGIN IMMEDIATE")
            _require_team(conn, team_id)
            membership = conn.execute(
                "SELECT * FROM team_user_memberships WHERE id = ? AND team_id = ?",
                (membership_id, team_id),
            ).fetchone()
            if membership is None:
                raise TeamServiceError(404, "Membership not found")
            if membership["role"] == "team_admin":
                admin_count = conn.execute(
                    "SELECT COUNT(*) AS count FROM team_user_memberships WHERE team_id = ? AND role = 'team_admin'",
                    (team_id,),
                ).fetchone()["count"]
                if admin_count <= 1:
                    raise TeamServiceError(409, "Cannot revoke the last team_admin membership")
            conn.execute("DELETE FROM team_user_memberships WHERE id = ?", (membership_id,))
            conn.commit()
            return dict(membership)
        except Exception:
            conn.rollback()
            raise


def grant_membership_by_username(*, team_slug: str, username: str, role: str) -> dict:
    with _db.connect() as conn:
        team = conn.execute("SELECT * FROM teams WHERE slug = ?", (_validate_slug(team_slug),)).fetchone()
        if team is None:
            raise TeamServiceError(404, "Team not found")
        user = conn.execute("SELECT * FROM users WHERE username = ? COLLATE NOCASE", (username,)).fetchone()
        if user is None:
            raise TeamServiceError(404, "User not found")
    return grant_membership(team_id=team["id"], user_id=user["id"], role=role)


def revoke_membership_by_username(*, team_slug: str, username: str, role: str) -> dict:
    clean_role = _validate_membership_role(role)
    with _db.connect() as conn:
        team = conn.execute("SELECT * FROM teams WHERE slug = ?", (_validate_slug(team_slug),)).fetchone()
        if team is None:
            raise TeamServiceError(404, "Team not found")
        membership = conn.execute(
            """
            SELECT m.*
            FROM team_user_memberships AS m
            JOIN users AS u ON u.id = m.user_id
            WHERE m.team_id = ? AND u.username = ? COLLATE NOCASE AND m.role = ?
            """,
            (team["id"], username, clean_role),
        ).fetchone()
        if membership is None:
            raise TeamServiceError(404, "Membership not found")
        membership_id = membership["id"]
    return revoke_membership(team_id=team["id"], membership_id=membership_id)
