"""Durable background job service for in-process Replay workers."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

import db as _db

TERMINAL_STATUSES = {"succeeded", "failed", "cancelled"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _future_iso(seconds: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat()


def _loads(value: str | None, default: Any) -> Any:
    if not value:
        return default
    return json.loads(value)


def _row_to_job(row: sqlite3.Row | dict | None) -> dict[str, Any] | None:
    if row is None:
        return None
    data = dict(row)
    data["payload"] = _loads(data.pop("payload_json", None), {})
    data["result"] = _loads(data.pop("result_json", None), None)
    return data


def _validate_json(value: Any, field: str) -> str:
    try:
        return json.dumps(value if value is not None else {}, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be JSON serializable") from exc


def get(job_id: int, *, team_id: str | None = None) -> dict[str, Any] | None:
    with _db.connect() as conn:
        if team_id is None:
            row = conn.execute("SELECT * FROM background_jobs WHERE id = ?", (job_id,)).fetchone()
        else:
            row = conn.execute("SELECT * FROM background_jobs WHERE id = ? AND team_id = ?", (job_id, team_id)).fetchone()
        return _row_to_job(row)


def list_for_team(team_id: str, *, status: str | None = None, kind: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
    limit = max(1, min(int(limit or 50), 200))
    clauses = ["team_id = ?"]
    params: list[Any] = [team_id]
    if status:
        clauses.append("status = ?")
        params.append(status)
    if kind:
        clauses.append("kind = ?")
        params.append(kind)
    params.append(limit)
    with _db.connect() as conn:
        rows = conn.execute(
            f"""
            SELECT * FROM background_jobs
            WHERE {' AND '.join(clauses)}
            ORDER BY created_at DESC, id DESC
            LIMIT ?
            """,
            params,
        ).fetchall()
    return [_row_to_job(row) for row in rows if row is not None]


def enqueue(
    kind: str,
    payload: dict[str, Any] | None,
    *,
    team_id: str,
    idempotency_key: str | None = None,
    max_attempts: int = 3,
    scheduled_at: str | None = None,
    payload_version: int = 1,
) -> int:
    kind = (kind or "").strip()
    team_id = (team_id or "").strip()
    if not kind:
        raise ValueError("kind is required")
    if not team_id:
        raise ValueError("team_id is required")
    if max_attempts < 1:
        raise ValueError("max_attempts must be at least 1")
    payload_json = _validate_json(payload or {}, "payload")
    now = _now_iso()
    scheduled = scheduled_at or now
    conn = _db.connect()
    if idempotency_key is not None:
        conn.execute(
            """
            INSERT OR IGNORE INTO background_jobs (
                kind, payload_json, payload_version, idempotency_key, team_id, status,
                attempts, max_attempts, scheduled_at, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, 'pending', 0, ?, ?, ?, ?)
            """,
            (kind, payload_json, payload_version, idempotency_key, team_id, max_attempts, scheduled, now, now),
        )
        row = conn.execute(
            "SELECT id FROM background_jobs WHERE team_id = ? AND kind = ? AND idempotency_key = ?",
            (team_id, kind, idempotency_key),
        ).fetchone()
        conn.commit()
        if row is None:  # pragma: no cover - defensive; unique select should exist after insert/ignore
            raise RuntimeError("failed to enqueue idempotent job")
        return int(row["id"])

    cur = conn.execute(
        """
        INSERT INTO background_jobs (
            kind, payload_json, payload_version, idempotency_key, team_id, status,
            attempts, max_attempts, scheduled_at, created_at, updated_at
        ) VALUES (?, ?, ?, NULL, ?, 'pending', 0, ?, ?, ?, ?)
        """,
        (kind, payload_json, payload_version, team_id, max_attempts, scheduled, now, now),
    )
    conn.commit()
    return int(cur.lastrowid)


def lease(kinds: Iterable[str], worker_id: str, *, lease_seconds: int = 60) -> dict[str, Any] | None:
    kinds = [kind for kind in kinds if kind]
    if not kinds:
        raise ValueError("at least one kind is required")
    worker_id = (worker_id or "").strip()
    if not worker_id:
        raise ValueError("worker_id is required")
    now = _now_iso()
    locked_until = _future_iso(lease_seconds)
    conn = _db.connect()
    placeholders = ",".join("?" for _ in kinds)
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            f"""
            SELECT * FROM background_jobs
            WHERE status = 'pending'
              AND scheduled_at <= ?
              AND kind IN ({placeholders})
            ORDER BY scheduled_at ASC, id ASC
            LIMIT 1
            """,
            [now, *kinds],
        ).fetchone()
        if row is None:
            conn.commit()
            return None
        conn.execute(
            """
            UPDATE background_jobs
            SET status = 'running', locked_by = ?, locked_until = ?, last_heartbeat = ?,
                started_at = COALESCE(started_at, ?), attempts = attempts + 1, updated_at = ?
            WHERE id = ? AND status = 'pending'
            """,
            (worker_id, locked_until, now, now, now, row["id"]),
        )
        claimed = conn.execute("SELECT * FROM background_jobs WHERE id = ?", (row["id"],)).fetchone()
        conn.commit()
        return _row_to_job(claimed)
    except Exception:
        conn.rollback()
        raise


def start(job_id: int, worker_id: str, *, lease_seconds: int = 60) -> dict[str, Any] | None:
    """Claim a specific pending job for an in-process task wrapper."""
    worker_id = (worker_id or "").strip()
    if not worker_id:
        raise ValueError("worker_id is required")
    now = _now_iso()
    locked_until = _future_iso(lease_seconds)
    conn = _db.connect()
    cur = conn.execute(
        """
        UPDATE background_jobs
        SET status = 'running', locked_by = ?, locked_until = ?, last_heartbeat = ?,
            started_at = COALESCE(started_at, ?), attempts = attempts + 1, updated_at = ?
        WHERE id = ? AND status = 'pending' AND scheduled_at <= ?
        """,
        (worker_id, locked_until, now, now, now, job_id, now),
    )
    conn.commit()
    if cur.rowcount != 1:
        return None
    return get(job_id)


def heartbeat(job_id: int, worker_id: str, *, lease_seconds: int = 60) -> int:
    now = _now_iso()
    locked_until = _future_iso(lease_seconds)
    conn = _db.connect()
    cur = conn.execute(
        """
        UPDATE background_jobs
        SET locked_until = ?, last_heartbeat = ?, updated_at = ?
        WHERE id = ? AND locked_by = ? AND status = 'running' AND locked_until >= ?
        """,
        (locked_until, now, now, job_id, worker_id, now),
    )
    conn.commit()
    return int(cur.rowcount)


def complete(job_id: int, worker_id: str, result: dict[str, Any] | None = None) -> int:
    result_json = _validate_json(result or {}, "result")
    now = _now_iso()
    conn = _db.connect()
    cur = conn.execute(
        """
        UPDATE background_jobs
        SET status = 'succeeded', result_json = ?, finished_at = ?, locked_by = NULL,
            locked_until = NULL, last_heartbeat = NULL, updated_at = ?
        WHERE id = ? AND locked_by = ? AND status = 'running' AND locked_until >= ?
        """,
        (result_json, now, now, job_id, worker_id, now),
    )
    conn.commit()
    return int(cur.rowcount)


def fail(job_id: int, worker_id: str, error_text: str) -> int:
    now = _now_iso()
    conn = _db.connect()
    cur = conn.execute(
        """
        UPDATE background_jobs
        SET status = 'failed', error_text = ?, finished_at = ?, locked_by = NULL,
            locked_until = NULL, last_heartbeat = NULL, updated_at = ?
        WHERE id = ? AND locked_by = ? AND status = 'running' AND locked_until >= ?
        """,
        (str(error_text)[:4000], now, now, job_id, worker_id, now),
    )
    conn.commit()
    return int(cur.rowcount)


def cancel(job_id: int, *, team_id: str) -> int:
    now = _now_iso()
    conn = _db.connect()
    cur = conn.execute(
        """
        UPDATE background_jobs
        SET status = 'cancelled', finished_at = ?, locked_by = NULL, locked_until = NULL,
            last_heartbeat = NULL, updated_at = ?
        WHERE id = ? AND team_id = ? AND status = 'pending'
        """,
        (now, now, job_id, team_id),
    )
    conn.commit()
    return int(cur.rowcount)


def recover_stuck() -> dict[str, int]:
    now = _now_iso()
    conn = _db.connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        rows = conn.execute(
            """
            SELECT id, attempts, max_attempts FROM background_jobs
            WHERE status = 'running' AND locked_until IS NOT NULL AND locked_until < ?
            ORDER BY id ASC
            """,
            (now,),
        ).fetchall()
        requeued = 0
        failed = 0
        for row in rows:
            if int(row["attempts"] or 0) < int(row["max_attempts"] or 3):
                cur = conn.execute(
                    """
                    UPDATE background_jobs
                    SET status = 'pending', locked_by = NULL, locked_until = NULL,
                        last_heartbeat = NULL, updated_at = ?
                    WHERE id = ? AND status = 'running' AND locked_until IS NOT NULL AND locked_until < ?
                    """,
                    (now, row["id"], now),
                )
                requeued += int(cur.rowcount)
            else:
                cur = conn.execute(
                    """
                    UPDATE background_jobs
                    SET status = 'failed', error_text = ?, finished_at = ?, locked_by = NULL,
                        locked_until = NULL, last_heartbeat = NULL, updated_at = ?
                    WHERE id = ? AND status = 'running' AND locked_until IS NOT NULL AND locked_until < ?
                    """,
                    ("exceeded max_attempts after stuck recovery", now, now, row["id"], now),
                )
                failed += int(cur.rowcount)
        conn.commit()
        return {"requeued": requeued, "failed": failed}
    except Exception:
        conn.rollback()
        raise
