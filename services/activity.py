"""Activity feed helpers for Replay admin/coach events."""

from __future__ import annotations

import db as _db
import log as _log

logger = _log.setup("replay")


def log_activity(
    event_type: str,
    *,
    severity: str = "info",
    message: str = "",
    match_id: str | None = None,
    slot: str | None = None,
    actor: str | None = None,
    metadata: dict | None = None,
) -> None:
    """Best-effort admin activity feed writer."""
    try:
        _db.log_activity_event(
            event_type,
            severity=severity,
            message=message,
            match_id=match_id,
            slot=slot,
            actor=actor,
            metadata=metadata,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Activity event logging failed: %s", exc)


def stream_activity_logger(event_type: str, *, severity: str = "info", match_id=None, slot=None, metadata=None):
    metadata = metadata or {}
    kind = metadata.get("kind") or "stream"
    if event_type == "stream.started":
        label = "Live viewer connected" if kind == "live" else "VOD viewer connected"
    elif event_type == "stream.ended":
        label = "Live viewer disconnected" if kind == "live" else "VOD viewer disconnected"
    else:
        label = event_type.replace(".", " ")
    log_activity(
        event_type,
        severity=severity,
        message=label,
        match_id=match_id,
        slot=slot,
        metadata=metadata,
    )


def coach_note_activity_label(note: dict | None) -> str:
    """Pick a safe human-readable coaching-note label for activity logs.

    Never uses coach_private_note; the activity feed can be read by roles beyond
    the note's coach.
    """
    if not note:
        return ""
    for key in ("title", "event_title", "player_summary"):
        value = (note.get(key) or "").strip()
        if value:
            return value
    if (note.get("note_context") or "video") == "observation":
        return "Observation note"
    return ""
