"""CSV roster import preview and commit helpers.

Phase 9.4 keeps import business rules out of ``server.py`` so the coach
routes stay thin: preview is strictly read-only, while commit performs a
single transactional write for players, existing guardian links, and pending
guardian invite reuse/creation.
"""

from __future__ import annotations

import csv
import io
import json
import os
import secrets
import sqlite3
import time
import uuid
from dataclasses import dataclass
from typing import Any

import auth as _auth
import db as _db
from services import team_members as _team_members
from services import teams as _teams

_MAX_CSV_BYTES = 256_000
_MAX_IMPORT_ROWS = 500


class RosterImportError(Exception):
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


@dataclass(slots=True)
class ParsedImportRow:
    row_number: int
    player_id: str
    display_name: str
    jersey_number: str
    notes: str
    active: bool
    guardian_email: str
    relationship: str


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _normalize_key(value: str | None) -> str:
    return " ".join((value or "").strip().lower().split())


def _normalize_email(value: str | None) -> str:
    if not value or not value.strip():
        return ""
    return _team_members._normalize_email(value)


def _parse_bool(value: str | None, *, default: bool = True) -> bool:
    raw = (value or "").strip().lower()
    if not raw:
        return default
    if raw in {"1", "true", "yes", "y", "active"}:
        return True
    if raw in {"0", "false", "no", "n", "inactive"}:
        return False
    raise ValueError("active must be true/false")


def parse_csv(csv_text: str) -> tuple[list[ParsedImportRow], list[dict[str, Any]]]:
    if len((csv_text or "").encode("utf-8")) > _MAX_CSV_BYTES:
        raise RosterImportError(413, "Roster import CSV is too large")
    try:
        reader = csv.DictReader(io.StringIO(csv_text or ""))
    except csv.Error as exc:
        raise RosterImportError(422, "Roster import CSV could not be parsed") from exc
    if not reader.fieldnames:
        raise RosterImportError(422, "Roster import CSV header is required")

    parsed: list[ParsedImportRow] = []
    errors: list[dict[str, Any]] = []
    for idx, raw in enumerate(reader, start=2):
        if len(parsed) + len(errors) >= _MAX_IMPORT_ROWS:
            errors.append({"row_number": idx, "status": "error", "errors": [f"Import limited to {_MAX_IMPORT_ROWS} rows"]})
            break
        row = {str(k or "").strip().lower(): (v or "").strip() for k, v in (raw or {}).items()}
        if not any(row.values()):
            continue
        row_errors: list[str] = []
        display_name = row.get("display_name") or row.get("player_name") or row.get("name") or ""
        if not display_name:
            row_errors.append("display_name is required")
        if len(display_name) > 120:
            row_errors.append("display_name is too long")
        jersey_number = (row.get("jersey_number") or row.get("jersey") or "")[:20]
        notes = (row.get("position") or row.get("notes") or "")[:1000]
        relationship = (row.get("relationship") or "guardian").strip().lower()
        if relationship not in {"guardian", "parent", "family"}:
            row_errors.append("relationship must be guardian, parent, or family")
        try:
            guardian_email = _normalize_email(row.get("guardian_email") or row.get("parent_email") or row.get("family_email"))
        except _teams.TeamServiceError as exc:
            guardian_email = ""
            row_errors.append(exc.detail)
        try:
            active = _parse_bool(row.get("active"), default=True)
        except ValueError as exc:
            active = True
            row_errors.append(str(exc))
        player_id = row.get("player_id") or ""
        if len(player_id) > 80:
            row_errors.append("player_id is too long")
        if row_errors:
            errors.append({
                "row_number": idx,
                "status": "error",
                "errors": row_errors,
                "input": {"display_name": display_name, "jersey_number": jersey_number, "guardian_email": guardian_email},
            })
            continue
        parsed.append(ParsedImportRow(
            row_number=idx,
            player_id=player_id,
            display_name=display_name.strip(),
            jersey_number=jersey_number.strip(),
            notes=notes.strip(),
            active=active,
            guardian_email=guardian_email,
            relationship=relationship,
        ))
    if not parsed and not errors:
        raise RosterImportError(422, "Roster import CSV has no player rows")
    return parsed, errors


def _assert_team_admin(conn: sqlite3.Connection, team_id: str, actor: dict) -> None:
    user_id = actor.get("user_id") or actor.get("id")
    row = conn.execute(
        "SELECT role FROM team_user_memberships WHERE team_id = ? AND user_id = ?",
        (team_id, user_id),
    ).fetchone()
    if row is None or row["role"] != "team_admin":
        raise RosterImportError(403, "Team admin membership required")


def _validate_scope(conn: sqlite3.Connection, team_id: str, season_id: str | None) -> str | None:
    if conn.execute("SELECT id FROM teams WHERE id = ?", (team_id,)).fetchone() is None:
        raise RosterImportError(404, "Team not found")
    if season_id:
        if conn.execute("SELECT id FROM seasons WHERE id = ? AND team_id = ?", (season_id, team_id)).fetchone() is None:
            raise RosterImportError(404, "Season not found for team")
        return season_id
    row = conn.execute("SELECT id FROM seasons WHERE team_id = ? ORDER BY starts_on DESC, created_at DESC LIMIT 1", (team_id,)).fetchone()
    return row["id"] if row else None


def _existing_player_for_row(conn: sqlite3.Connection, team_id: str, row: ParsedImportRow) -> sqlite3.Row | None:
    if row.player_id:
        scoped = conn.execute("SELECT * FROM players WHERE id = ? AND team_id = ?", (row.player_id, team_id)).fetchone()
        if scoped is None:
            raise RosterImportError(409, "Import references a player outside the active team")
        return scoped
    return conn.execute(
        """
        SELECT * FROM players
        WHERE team_id = ?
          AND lower(trim(display_name)) = ?
          AND COALESCE(jersey_number, '') = ?
        ORDER BY created_at ASC
        LIMIT 1
        """,
        (team_id, _normalize_key(row.display_name), row.jersey_number),
    ).fetchone()


def _user_for_email(conn: sqlite3.Connection, normalized_email: str) -> sqlite3.Row | None:
    if not normalized_email:
        return None
    return conn.execute(
        """
        SELECT u.*
        FROM user_profiles p
        JOIN users u ON u.id = p.user_id
        WHERE p.normalized_email = ? AND u.enabled = 1
        ORDER BY u.created_at ASC
        LIMIT 1
        """,
        (normalized_email,),
    ).fetchone()


def _pending_invite_for_email(conn: sqlite3.Connection, team_id: str, normalized_email: str) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT * FROM team_invites
        WHERE team_id = ? AND normalized_email = ? AND role = 'guardian'
          AND status = 'pending' AND accepted_at IS NULL AND revoked_at IS NULL
        ORDER BY created_at ASC
        LIMIT 1
        """,
        (team_id, normalized_email),
    ).fetchone()


def _metadata_player_ids(invite: sqlite3.Row | dict | None) -> list[str]:
    if invite is None:
        return []
    try:
        data = json.loads(invite["metadata_json"] or "{}")
    except Exception:
        data = {}
    return [str(pid) for pid in data.get("player_ids") or [] if str(pid)]


def _public_invite(row: sqlite3.Row, *, include_token: str | None = None) -> dict:
    data = _team_members._public_invite(row, include_token=include_token)
    return data or {}


def preview_roster_import(*, csv_text: str, team_id: str, season_id: str | None, actor: dict) -> dict:
    rows, parse_errors = parse_csv(csv_text)
    with _db.connect() as conn:
        _assert_team_admin(conn, team_id, actor)
        _validate_scope(conn, team_id, season_id)
        preview_rows: list[dict[str, Any]] = []
        guardian_emails: dict[str, int] = {}
        for row in rows:
            try:
                existing = _existing_player_for_row(conn, team_id, row)
            except RosterImportError as exc:
                preview_rows.append({"row_number": row.row_number, "status": "error", "errors": [exc.detail], "input": row.__dict__})
                continue
            user = _user_for_email(conn, row.guardian_email) if row.guardian_email else None
            invite = _pending_invite_for_email(conn, team_id, row.guardian_email) if row.guardian_email and user is None else None
            guardian_action = "none"
            if row.guardian_email:
                if user is not None:
                    guardian_action = "link_existing_user"
                elif invite is not None or guardian_emails.get(row.guardian_email, 0) > 0:
                    guardian_action = "reuse_invite"
                else:
                    guardian_action = "create_invite"
                guardian_emails[row.guardian_email] = guardian_emails.get(row.guardian_email, 0) + 1
            preview_rows.append({
                "row_number": row.row_number,
                "status": "ready",
                "player_action": "update_player" if existing else "create_player",
                "guardian_action": guardian_action,
                "player": {
                    "id": existing["id"] if existing else None,
                    "display_name": row.display_name,
                    "jersey_number": row.jersey_number,
                    "active": row.active,
                    "notes": row.notes,
                },
                "guardian_email": row.guardian_email,
                "warnings": ["Duplicate guardian email; one invite/account will be reused"] if row.guardian_email and guardian_emails[row.guardian_email] > 1 else [],
                "errors": [],
            })
    all_rows = preview_rows + parse_errors
    return {"ok": True, "mode": "preview", "summary": _summary(all_rows, committed=False), "rows": all_rows}


def _summary(rows: list[dict[str, Any]], *, committed: bool) -> dict[str, int]:
    errors = sum(1 for row in rows if row.get("status") == "error")
    if committed:
        return {
            "rows": len(rows),
            "errors": errors,
            "created_players": sum(1 for row in rows if row.get("player_action") == "created"),
            "existing_players": sum(1 for row in rows if row.get("player_action") in {"existing", "updated"}),
            "guardian_invites": len({row.get("guardian_invite_id") for row in rows if row.get("guardian_invite_id")}),
            "linked_existing_users": sum(1 for row in rows if row.get("guardian_action") == "linked_existing_user"),
        }
    return {
        "rows": len(rows),
        "errors": errors,
        "create_players": sum(1 for row in rows if row.get("player_action") == "create_player"),
        "update_players": sum(1 for row in rows if row.get("player_action") == "update_player"),
        "guardian_invites": len({row.get("guardian_email") for row in rows if row.get("guardian_action") in {"create_invite", "reuse_invite"} and row.get("guardian_email")}),
        "linked_existing_users": sum(1 for row in rows if row.get("guardian_action") == "link_existing_user"),
    }


def _upsert_guardian_membership_and_link(conn: sqlite3.Connection, *, team_id: str, user_id: str, player_id: str, relationship: str) -> None:
    now = _now_iso()
    if conn.execute(
        "SELECT id FROM team_user_memberships WHERE team_id = ? AND user_id = ? AND role = 'guardian'",
        (team_id, user_id),
    ).fetchone() is None:
        conn.execute(
            "INSERT INTO team_user_memberships (team_id, user_id, role, created_at) VALUES (?, ?, 'guardian', ?)",
            (team_id, user_id, now),
        )
    conn.execute(
        """
        INSERT INTO player_user_links (player_id, user_id, relationship, created_at, team_id)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(player_id, user_id) DO UPDATE SET relationship = excluded.relationship, team_id = excluded.team_id
        """,
        (player_id, user_id, relationship, now, team_id),
    )


def _create_or_update_invite(conn: sqlite3.Connection, *, team_id: str, season_id: str | None, email: str, player_ids: list[str], actor: dict) -> tuple[sqlite3.Row, str | None]:
    existing = _pending_invite_for_email(conn, team_id, email)
    if existing is not None:
        combined = []
        for pid in _metadata_player_ids(existing) + player_ids:
            if pid not in combined:
                combined.append(pid)
        conn.execute(
            "UPDATE team_invites SET metadata_json = ?, season_id = COALESCE(season_id, ?) WHERE id = ?",
            (json.dumps({"player_ids": combined}, sort_keys=True), season_id, existing["id"]),
        )
        return conn.execute("SELECT * FROM team_invites WHERE id = ?", (existing["id"],)).fetchone(), None

    token = secrets.token_urlsafe(32)
    invite_id = str(uuid.uuid4())
    now = time.time()
    conn.execute(
        """
        INSERT INTO team_invites (
            id, team_id, season_id, normalized_email, role, status, token_hash,
            expires_at, created_at, created_by_user_id, metadata_json
        ) VALUES (?, ?, ?, ?, 'guardian', 'pending', ?, ?, ?, ?, ?)
        """,
        (
            invite_id,
            team_id,
            season_id,
            email,
            _auth.token_hash(token),
            now + _team_members.INVITE_TTL,
            now,
            actor.get("user_id") or actor.get("id"),
            json.dumps({"player_ids": player_ids}, sort_keys=True),
        ),
    )
    return conn.execute("SELECT * FROM team_invites WHERE id = ?", (invite_id,)).fetchone(), token


def commit_roster_import(*, csv_text: str, team_id: str, season_id: str | None, actor: dict) -> dict:
    parsed_rows, parse_errors = parse_csv(csv_text)
    if parse_errors:
        return {"ok": False, "mode": "commit", "summary": _summary(parse_errors, committed=True), "rows": parse_errors, "guardian_invites": []}
    committed_rows: list[dict[str, Any]] = []
    invite_player_ids: dict[str, list[str]] = {}
    invite_rows: dict[str, tuple[sqlite3.Row, str | None]] = {}
    try:
        with _db.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            _assert_team_admin(conn, team_id, actor)
            clean_season_id = _validate_scope(conn, team_id, season_id)
            for row in parsed_rows:
                existing = _existing_player_for_row(conn, team_id, row)
                now = _now_iso()
                if existing is None:
                    player_id = str(uuid.uuid4())
                    conn.execute(
                        """
                        INSERT INTO players (id, display_name, jersey_number, active, notes, created_at, updated_at, team_id, season_id)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (player_id, row.display_name, row.jersey_number, 1 if row.active else 0, row.notes, now, now, team_id, clean_season_id),
                    )
                    player_action = "created"
                else:
                    player_id = existing["id"]
                    conn.execute(
                        "UPDATE players SET display_name = ?, jersey_number = ?, active = ?, notes = ?, updated_at = ? WHERE id = ? AND team_id = ?",
                        (row.display_name, row.jersey_number, 1 if row.active else 0, row.notes, now, player_id, team_id),
                    )
                    player_action = "existing"
                guardian_action = "none"
                invite_id = None
                if row.guardian_email:
                    user = _user_for_email(conn, row.guardian_email)
                    if user is not None:
                        _upsert_guardian_membership_and_link(
                            conn,
                            team_id=team_id,
                            user_id=user["id"],
                            player_id=player_id,
                            relationship=row.relationship,
                        )
                        guardian_action = "linked_existing_user"
                    else:
                        invite_player_ids.setdefault(row.guardian_email, [])
                        if player_id not in invite_player_ids[row.guardian_email]:
                            invite_player_ids[row.guardian_email].append(player_id)
                        guardian_action = "invited_guardian"
                committed_rows.append({
                    "row_number": row.row_number,
                    "status": "committed",
                    "player_action": player_action,
                    "guardian_action": guardian_action,
                    "guardian_email": row.guardian_email,
                    "guardian_invite_id": invite_id,
                    "player": {
                        "id": player_id,
                        "display_name": row.display_name,
                        "jersey_number": row.jersey_number,
                        "active": row.active,
                        "notes": row.notes,
                        "team_id": team_id,
                        "season_id": clean_season_id,
                    },
                    "errors": [],
                })
            for email, player_ids in invite_player_ids.items():
                invite, token = _create_or_update_invite(
                    conn,
                    team_id=team_id,
                    season_id=clean_season_id,
                    email=email,
                    player_ids=player_ids,
                    actor=actor,
                )
                invite_rows[email] = (invite, token)
                for committed in committed_rows:
                    if committed.get("guardian_email") == email and committed.get("guardian_action") == "invited_guardian":
                        committed["guardian_invite_id"] = invite["id"]
            conn.commit()
    except RosterImportError:
        raise
    except sqlite3.IntegrityError as exc:
        raise RosterImportError(409, "Roster import conflicts with existing data") from exc
    except Exception:
        raise

    for invite, token in invite_rows.values():
        if token:
            _team_members._send_invite_email(invite["id"], token)

    if invite_rows:
        with _db.connect() as conn:
            invite_rows = {
                email: (
                    conn.execute("SELECT * FROM team_invites WHERE id = ?", (invite["id"],)).fetchone() or invite,
                    token,
                )
                for email, (invite, token) in invite_rows.items()
            }

    public_invites = [
        _public_invite(invite, include_token=(token if os.environ.get("REPLAY_DEV_TOKEN_DELIVERY") == "1" else None))
        for invite, token in invite_rows.values()
    ]
    return {
        "ok": True,
        "mode": "commit",
        "summary": _summary(committed_rows, committed=True),
        "rows": committed_rows,
        "guardian_invites": public_invites,
    }
