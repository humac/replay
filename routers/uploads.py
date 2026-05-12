"""Uploads domain routes: chunked-upload session lifecycle + legacy single-shot upload.

PR-BE 2/N — mechanical extraction from server.py. Handler bodies and decorator
paths are verbatim copies. Late imports from `server` break the circular import
that would otherwise occur because server.py imports this module to register
the router.

The root-level `uploads.py` service module (session-state and chunk persistence)
is untouched; this file is the HTTP layer only.
"""
from __future__ import annotations

import hashlib
import math
import time
import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, UploadFile

import auth as _auth
import db as _db
import uploads as _uploads
from models import CreateUploadSessionRequest

router = APIRouter()


@router.post("/api/matches/{match_id}/upload-video/session")
async def create_upload_session(match_id: str, request: Request, body: CreateUploadSessionRequest):
    from server import (
        ORIGINALS_DIR,
        VIDEOS_DIR,
        _ensure_disk_space,
        _log_activity,
        _slot_raw_path,
        current_max_upload_size_bytes,
        current_stale_upload_session_seconds,
        current_upload_chunk_size_bytes,
        logger,
    )
    user = _auth.require_role(request, "admin", "uploader")
    stale_seconds = current_stale_upload_session_seconds()
    _uploads.cleanup_stale_sessions(stale_seconds)
    slot = request.query_params.get("slot", "full")
    if slot not in ("full", "first_half", "second_half"):
        raise HTTPException(400, "slot must be full, first_half, or second_half")

    filename = body.filename.strip()
    size_bytes = body.size_bytes
    max_upload = current_max_upload_size_bytes()
    if size_bytes > max_upload:
        raise HTTPException(413, f"Uploaded file exceeds max size of {max_upload} bytes")

    ext = Path(filename).suffix.lower()
    if ext not in (".mp4", ".mkv"):
        raise HTTPException(400, "Only .mp4 and .mkv files are supported")

    match = _db.get_match_by_id(match_id)
    if not match:
        raise HTTPException(404, "Match not found")

    first_chunk_hash = body.first_chunk_hash or None
    existing = _uploads.find_active_session(match_id, slot, size_bytes, ext, first_chunk_hash)
    if existing:
        logger.info(
            "Reusing active upload session: %s match=%s slot=%s next_index=%d",
            existing["id"], match_id, slot, existing["next_index"],
            extra={"session_id": existing["id"], "match_id": match_id, "slot": slot},
        )
        return _uploads.session_payload(existing)

    _ensure_disk_space(size_bytes)
    _uploads.cancel_conflicting_sessions(match_id, slot)

    # Raw upload lands on the cold pool (ORIGINALS_DIR). Make sure the per-
    # match directory there exists first; the SSD-side videos directory is
    # also ensured because thumbnails + HLS still write to it post-transcode.
    (ORIGINALS_DIR / match_id).mkdir(parents=True, exist_ok=True)
    (VIDEOS_DIR / match_id).mkdir(parents=True, exist_ok=True)
    raw_path = _slot_raw_path(match_id, slot, ext)
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path.unlink(missing_ok=True)

    session_id = uuid.uuid4().hex
    chunk_size = current_upload_chunk_size_bytes()
    total_chunks = max(1, math.ceil(size_bytes / chunk_size))
    now = time.time()

    with _db.connect() as conn:
        conn.execute(
            """
            INSERT INTO upload_sessions (
                id, match_id, slot, ext, raw_path, size_bytes, chunk_size,
                total_chunks, next_index, status, created_at, updated_at, first_chunk_hash
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, 'active', ?, ?, ?)
            """,
            (
                session_id,
                match_id,
                slot,
                ext,
                str(raw_path),
                size_bytes,
                chunk_size,
                total_chunks,
                now,
                now,
                first_chunk_hash,
            ),
        )
        conn.commit()

    logger.info(
        "Chunked upload session created: %s match=%s slot=%s size=%d chunks=%d",
        session_id, match_id, slot, size_bytes, total_chunks,
        extra={"session_id": session_id, "match_id": match_id, "slot": slot,
               "size_bytes": size_bytes, "total_chunks": total_chunks},
    )
    _log_activity(
        "upload.started",
        severity="info",
        message="Upload started",
        match_id=match_id,
        slot=slot,
        actor=user["username"],
        metadata={"session_id": session_id, "filename": filename, "size_bytes": size_bytes},
    )
    return {
        "session_id": session_id,
        "chunk_size": chunk_size,
        "total_chunks": total_chunks,
        "next_index": 0,
    }


@router.get("/api/uploads/sessions")
async def list_upload_sessions(request: Request):
    from server import current_stale_upload_session_seconds
    _auth.require_role(request, "admin", "uploader")
    status_param = (request.query_params.get("status") or "active").strip().lower()
    stale_seconds = current_stale_upload_session_seconds()
    if status_param == "all":
        sessions = _uploads.list_session_views(stale_seconds, None)
    else:
        statuses = tuple(part.strip() for part in status_param.split(",") if part.strip())[:8]
        sessions = _uploads.list_session_views(stale_seconds, statuses or ("active",))
    return {"sessions": sessions}


@router.put("/api/uploads/sessions/{session_id}/chunk")
async def upload_session_chunk(session_id: str, request: Request):
    from server import _append_bytes_file
    _auth.require_role(request, "admin", "uploader")
    try:
        index = int(request.query_params.get("index", "-1"))
    except ValueError:
        raise HTTPException(400, "index must be an integer")

    row = _uploads.get_session(session_id)
    if not row:
        raise HTTPException(404, "Upload session not found")
    if row["status"] != "active":
        raise HTTPException(409, "Upload session is not active")
    if index < 0 or index >= row["total_chunks"]:
        raise HTTPException(400, "index out of range")

    # Idempotent retry of already-written chunk.
    if index < row["next_index"]:
        return {"ok": True, "next_index": row["next_index"]}

    if index > row["next_index"]:
        raise HTTPException(409, f"Expected chunk index {row['next_index']}")

    data = await request.body()
    if not data:
        raise HTTPException(400, "empty chunk body")
    if len(data) > row["chunk_size"]:
        raise HTTPException(400, "chunk exceeds session chunk_size")

    # Defense-in-depth: verify that the first chunk belongs to the same file that
    # created this session. Guards against two uploaders who both passed the same
    # (size, ext) fingerprint to bind — unlikely but conceivable.
    if index == 0 and row["first_chunk_hash"]:
        actual = hashlib.sha256(data[:65536]).hexdigest()
        if actual != row["first_chunk_hash"]:
            raise HTTPException(
                409,
                "First-chunk fingerprint mismatch — this session belongs to a different file",
            )

    raw_path = Path(row["raw_path"])
    await _append_bytes_file(raw_path, data)

    with _db.connect() as conn:
        conn.execute(
            """
            UPDATE upload_sessions
            SET next_index = next_index + 1, updated_at = ?
            WHERE id = ?
            """,
            (time.time(), session_id),
        )
        conn.commit()

    return {"ok": True, "next_index": index + 1}


@router.get("/api/uploads/sessions/{session_id}")
async def get_upload_session(session_id: str, request: Request):
    from server import current_stale_upload_session_seconds
    _auth.require_role(request, "admin", "uploader")
    row = _uploads.get_session(session_id)
    if not row:
        raise HTTPException(404, "Upload session not found")
    return _uploads.session_view(row, current_stale_upload_session_seconds())


@router.delete("/api/uploads/sessions/{session_id}")
async def cancel_upload_session(session_id: str, request: Request):
    from server import _log_activity, current_stale_upload_session_seconds
    user = _auth.require_role(request, "admin", "uploader")
    row = _uploads.mark_session_status(session_id, "cancelled")
    if not row:
        raise HTTPException(404, "Upload session not found")
    _log_activity(
        "upload.cancelled",
        severity="warning",
        message="Upload cancelled",
        match_id=row["match_id"],
        slot=row["slot"],
        actor=user["username"],
        metadata={"session_id": session_id},
    )
    return {"ok": True, "session": _uploads.session_view(row, current_stale_upload_session_seconds())}


@router.post("/api/uploads/sessions/cleanup")
async def cleanup_upload_sessions(request: Request):
    from server import ORIGINALS_DIR, VIDEOS_DIR, current_stale_upload_session_seconds
    _auth.require_role(request, "admin")
    cleaned = _uploads.cleanup_stale_sessions(current_stale_upload_session_seconds())
    expired = _uploads.cleanup_old_completed_sessions()
    orphaned = _uploads.cleanup_orphaned_raw_files(VIDEOS_DIR, originals_dir=ORIGINALS_DIR)
    return {
        "ok": True,
        "cleaned_session_ids": cleaned,
        "count": len(cleaned),
        "expired_sessions": expired,
        "orphaned_files_removed": len(orphaned),
    }


@router.post("/api/uploads/sessions/{session_id}/complete")
async def complete_upload_session(session_id: str, request: Request):
    from server import (
        _log_activity,
        _set_video_status,
        _slot_mp4_write_path,
        _spawn_transcode,
        logger,
    )
    user = _auth.require_role(request, "admin", "uploader")
    row = _uploads.get_session(session_id)
    if not row:
        raise HTTPException(404, "Upload session not found")
    if row["status"] != "active":
        raise HTTPException(409, "Upload session is not active")
    if row["next_index"] != row["total_chunks"]:
        raise HTTPException(409, "Upload incomplete")

    raw_path = Path(row["raw_path"])
    if not raw_path.exists():
        raise HTTPException(500, "Uploaded file not found")
    actual_size = raw_path.stat().st_size
    if actual_size != row["size_bytes"]:
        raise HTTPException(409, f"Uploaded size mismatch: expected {row['size_bytes']}, got {actual_size}")

    match_id = row["match_id"]
    slot = row["slot"]
    final_path = _slot_mp4_write_path(match_id, slot)

    # CAS: only the first concurrent /complete call wins; the conditional UPDATE
    # ensures exactly one caller transitions 'active' → 'completed' and spawns
    # the transcode task.
    with _db.connect() as conn:
        cursor = conn.execute(
            "UPDATE upload_sessions SET status = 'completed', updated_at = ? WHERE id = ? AND status = 'active'",
            (time.time(), session_id),
        )
        conn.commit()
    if cursor.rowcount != 1:
        raise HTTPException(409, "Upload session is not active")

    await _set_video_status(match_id, slot, "transcoding", None)

    logger.info(
        "Chunked upload complete: %s match=%s slot=%s size=%d",
        session_id, match_id, slot, actual_size,
        extra={"session_id": session_id, "match_id": match_id, "slot": slot, "size_bytes": actual_size},
    )
    _log_activity(
        "upload.completed",
        severity="success",
        message="Upload completed",
        match_id=match_id,
        slot=slot,
        actor=user["username"],
        metadata={"session_id": session_id, "size_bytes": actual_size},
    )
    _spawn_transcode(match_id, slot, raw_path, final_path)
    return {"ok": True, "status": "transcoding", "slot": slot, "size_mb": round(actual_size / 1e6, 1)}


@router.post("/api/matches/{match_id}/upload-video")
async def upload_video(match_id: str, file: UploadFile, request: Request):
    """Upload a video file (MP4 / MKV).  Query param: slot=full|first_half|second_half"""
    from server import (
        ORIGINALS_DIR,
        VIDEOS_DIR,
        _log_activity,
        _save_upload_file,
        _set_video_status,
        _slot_mp4_write_path,
        _slot_raw_path,
        _spawn_transcode,
        current_max_upload_size_bytes,
        logger,
    )
    user = _auth.require_role(request, "admin", "uploader")
    slot = request.query_params.get("slot", "full")
    if slot not in ("full", "first_half", "second_half"):
        raise HTTPException(400, "slot must be full, first_half, or second_half")

    match = _db.get_match_by_id(match_id)
    if not match:
        raise HTTPException(404, "Match not found")

    fname = file.filename or "video.mp4"
    ext = Path(fname).suffix.lower()
    if ext not in (".mp4", ".mkv"):
        raise HTTPException(400, "Only .mp4 and .mkv files are supported")

    # Raw upload + finished MP4 live on the cold pool (ORIGINALS_DIR);
    # HLS + thumbnails will land on VIDEOS_DIR after transcode.
    (ORIGINALS_DIR / match_id).mkdir(parents=True, exist_ok=True)
    (VIDEOS_DIR / match_id).mkdir(parents=True, exist_ok=True)

    raw_path = _slot_raw_path(match_id, slot, ext)
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    max_upload = current_max_upload_size_bytes()
    logger.info(
        "Upload started: %s/%s filename=%s max_size_bytes=%d",
        match_id, slot, fname, max_upload,
        extra={"match_id": match_id, "slot": slot, "upload_filename": fname},
    )
    started_at = time.time()
    try:
        bytes_written = await _save_upload_file(file, raw_path, max_size_bytes=max_upload)
    except HTTPException:
        raw_path.unlink(missing_ok=True)
        raise

    size_mb = round(bytes_written / 1e6, 1)
    elapsed = round(time.time() - started_at, 2)
    logger.info(
        "Upload saved: %s/%s (%s MB in %ss) — starting transcode",
        match_id, slot, size_mb, elapsed,
        extra={"match_id": match_id, "slot": slot, "size_mb": size_mb, "elapsed_s": elapsed},
    )
    _log_activity(
        "upload.completed",
        severity="success",
        message="Upload completed",
        match_id=match_id,
        slot=slot,
        actor=user["username"],
        metadata={"filename": fname, "size_bytes": bytes_written, "elapsed_s": elapsed},
    )

    await _set_video_status(match_id, slot, "transcoding", None)

    final_path = _slot_mp4_write_path(match_id, slot)
    _spawn_transcode(match_id, slot, raw_path, final_path)

    return {"ok": True, "slot": slot, "size_mb": size_mb, "status": "transcoding"}
