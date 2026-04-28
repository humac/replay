"""Upload session management — creation, chunked upload, lifecycle."""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path

import db as _db
import log as _log

logger = _log.setup("replay")


def get_session(session_id: str) -> sqlite3.Row | None:
    with _db.connect() as conn:
        return conn.execute(
            "SELECT * FROM upload_sessions WHERE id = ?",
            (session_id,),
        ).fetchone()


def session_payload(row: sqlite3.Row) -> dict:
    return {
        "session_id": row["id"],
        "match_id": row["match_id"],
        "slot": row["slot"],
        "size_bytes": row["size_bytes"],
        "chunk_size": row["chunk_size"],
        "total_chunks": row["total_chunks"],
        "next_index": row["next_index"],
        "status": row["status"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def session_view(row: sqlite3.Row, stale_seconds: int) -> dict:
    payload = session_payload(row)
    raw_path = Path(row["raw_path"])
    raw_exists = raw_path.exists()
    uploaded_bytes = raw_path.stat().st_size if raw_exists else 0
    now = time.time()
    payload.update(
        {
            "uploaded_bytes": uploaded_bytes,
            "progress_pct": round((uploaded_bytes / row["size_bytes"]) * 100, 1) if row["size_bytes"] else 0,
            "raw_exists": raw_exists,
            "raw_path": str(raw_path),
            "age_seconds": round(max(0, now - row["created_at"]), 1),
            "idle_seconds": round(max(0, now - row["updated_at"]), 1),
            "stale": (now - row["updated_at"]) >= stale_seconds,
        }
    )
    return payload


def find_active_session(
    match_id: str, slot: str, size_bytes: int, ext: str,
    first_chunk_hash: str | None = None,
) -> sqlite3.Row | None:
    with _db.connect() as conn:
        if first_chunk_hash:
            # Strict fingerprint match: only resume a session that was started
            # with the same file. A NULL hash means the session predates this
            # feature; don't resume it for a hashed request so we can't be sure
            # it's the same file.
            return conn.execute(
                """
                SELECT * FROM upload_sessions
                WHERE match_id = ? AND slot = ? AND size_bytes = ? AND ext = ?
                  AND status = 'active' AND first_chunk_hash = ?
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                (match_id, slot, size_bytes, ext, first_chunk_hash),
            ).fetchone()
        return conn.execute(
            """
            SELECT * FROM upload_sessions
            WHERE match_id = ? AND slot = ? AND size_bytes = ? AND ext = ? AND status = 'active'
            ORDER BY updated_at DESC
            LIMIT 1
            """,
            (match_id, slot, size_bytes, ext),
        ).fetchone()


def list_session_views(stale_seconds: int, statuses: tuple[str, ...] | None = None) -> list[dict]:
    with _db.connect() as conn:
        if statuses:
            placeholders = ", ".join("?" for _ in statuses)
            rows = conn.execute(
                f"SELECT * FROM upload_sessions WHERE status IN ({placeholders}) ORDER BY updated_at DESC",
                statuses,
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM upload_sessions ORDER BY updated_at DESC"
            ).fetchall()
    return [session_view(row, stale_seconds) for row in rows]


def mark_session_status(session_id: str, status: str) -> sqlite3.Row | None:
    row = get_session(session_id)
    if not row:
        return None

    raw_path = Path(row["raw_path"])
    raw_path.unlink(missing_ok=True)

    with _db.connect() as conn:
        conn.execute(
            "UPDATE upload_sessions SET status = ?, updated_at = ? WHERE id = ?",
            (status, time.time(), session_id),
        )
        conn.commit()

    return get_session(session_id)


def cleanup_stale_sessions(stale_seconds: int) -> list[str]:
    cutoff = time.time() - stale_seconds
    with _db.connect() as conn:
        rows = conn.execute(
            "SELECT id FROM upload_sessions WHERE status = 'active' AND updated_at < ?",
            (cutoff,),
        ).fetchall()

    cleaned = []
    for row in rows:
        updated = mark_session_status(row["id"], "cancelled")
        if updated:
            cleaned.append(row["id"])
    return cleaned


def cleanup_old_completed_sessions(max_age_seconds: int = 7 * 24 * 3600) -> int:
    """Delete completed/cancelled/replaced session records older than *max_age_seconds*."""
    cutoff = time.time() - max_age_seconds
    with _db.connect() as conn:
        cursor = conn.execute(
            "DELETE FROM upload_sessions WHERE status IN ('completed', 'cancelled', 'replaced')"
            " AND updated_at < ?",
            (cutoff,),
        )
        conn.commit()
        return cursor.rowcount


def cleanup_orphaned_raw_files(videos_dir: Path) -> list[str]:
    """Remove raw upload files that don't belong to any active upload session."""
    with _db.connect() as conn:
        active_raw_paths = {
            row["raw_path"]
            for row in conn.execute(
                "SELECT raw_path FROM upload_sessions WHERE status = 'active'"
            ).fetchall()
        }

    removed: list[str] = []
    if not videos_dir.is_dir():
        return removed

    for match_dir in videos_dir.iterdir():
        if not match_dir.is_dir():
            continue
        for f in match_dir.iterdir():
            if f.name.startswith(("full_raw", "first_half_raw", "second_half_raw")):
                if str(f) not in active_raw_paths:
                    try:
                        f.unlink()
                        removed.append(str(f))
                        logger.info("Removed orphaned raw file: %s", f)
                    except OSError:
                        pass
    return removed


def cancel_conflicting_sessions(match_id: str, slot: str):
    with _db.connect() as conn:
        rows = conn.execute(
            "SELECT id FROM upload_sessions WHERE match_id = ? AND slot = ? AND status = 'active'",
            (match_id, slot),
        ).fetchall()

    for row in rows:
        mark_session_status(row["id"], "replaced")
