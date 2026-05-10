"""Coaching visibility and viewer scrubbing helpers.

This module centralizes the privacy ladder used by coach/player feedback
surfaces without importing the FastAPI application. Keep visibility decisions
separate from response scrubbing so call sites can explicitly choose when a
viewer-safe copy is required.
"""

from __future__ import annotations

import auth as _auth
import db as _db

ACTIVE_GOAL_STATUSES = {"open", "in_progress", "needs_follow_up"}


def same_team(item: dict | None, team_id: str | None) -> bool:
    return item is not None and (team_id is None or str(item.get("team_id")) == str(team_id))


def team_scoped_items(items: list[dict], team_id: str | None) -> list[dict]:
    if team_id is None:
        return items
    return [item for item in items if same_team(item, team_id)]


def _ids_for_team(items: list[dict], team_id: str | None) -> set:
    return {item["id"] for item in team_scoped_items(items, team_id)}


def _sanitize_playlist_source_ids(playlists: list[dict], team_id: str | None) -> list[dict]:
    if team_id is None:
        return playlists
    same_team_note_ids = _ids_for_team(_db.list_coaching_notes(), team_id)
    return [
        {**playlist, "note_ids": [note_id for note_id in playlist.get("note_ids", []) if note_id in same_team_note_ids]}
        for playlist in playlists
    ]


def _sanitize_summary_source_ids(summaries: list[dict], team_id: str | None) -> list[dict]:
    if team_id is None:
        return summaries
    same_team_note_ids = _ids_for_team(_db.list_coaching_notes(), team_id)
    same_team_clip_ids = _ids_for_team(_db.list_coaching_clips(), team_id)
    same_team_playlist_ids = _ids_for_team(_db.list_coaching_playlists(), team_id)
    return [
        {
            **summary,
            "note_ids": [note_id for note_id in summary.get("note_ids", []) if note_id in same_team_note_ids],
            "clip_ids": [clip_id for clip_id in summary.get("clip_ids", []) if clip_id in same_team_clip_ids],
            "playlist_ids": [playlist_id for playlist_id in summary.get("playlist_ids", []) if playlist_id in same_team_playlist_ids],
        }
        for summary in summaries
    ]


def strip_private_fields(note: dict) -> dict:
    """Return a viewer-safe note copy with coach-private text scrubbed."""
    if "coach_private_note" not in note:
        return note
    safe = dict(note)
    safe["coach_private_note"] = ""
    return safe


def strip_goal_private_fields(goal: dict) -> dict:
    out = dict(goal)
    out["coach_private_note"] = ""
    return out


def filter_notes_for_user(notes: list[dict], user: dict, team_id: str | None = None) -> list[dict]:
    notes = team_scoped_items(notes, team_id)
    if _auth.has_role(user, "admin", "coach"):
        return notes
    linked_players = set(_db.linked_player_ids_for_user(user.get("user_id"), team_id=team_id))
    visible = []
    for note in notes:
        visibility = note.get("visibility", "private")
        if visibility in {"team", "unlisted"}:
            visible.append(strip_private_fields(note))
            continue
        if visibility == "player" and linked_players.intersection(note.get("player_ids", [])):
            visible.append(strip_private_fields(note))
    return visible


def filter_playlists_for_user(playlists: list[dict], user: dict, team_id: str | None = None) -> list[dict]:
    playlists = team_scoped_items(playlists, team_id)
    playlists = _sanitize_playlist_source_ids(playlists, team_id)
    if _auth.has_role(user, "admin", "coach"):
        return playlists
    linked_players = set(_db.linked_player_ids_for_user(user.get("user_id"), team_id=team_id))
    visible = []
    for playlist in playlists:
        visibility = playlist.get("visibility", "private")
        if visibility in {"team", "unlisted"}:
            visible.append(playlist)
            continue
        if visibility == "player" and linked_players.intersection(playlist.get("player_ids", [])):
            visible.append(playlist)
    return visible


def filter_clips_for_user(clips: list[dict], user: dict, team_id: str | None = None) -> list[dict]:
    """Apply the coaching visibility ladder to clip rows."""
    clips = team_scoped_items(clips, team_id)
    if _auth.has_role(user, "admin", "coach"):
        return clips
    linked_players = set(_db.linked_player_ids_for_user(user.get("user_id"), team_id=team_id))
    visible = []
    for clip in clips:
        visibility = clip.get("visibility", "private")
        if visibility in {"team", "unlisted"}:
            visible.append(clip)
            continue
        if visibility == "player" and linked_players.intersection(clip.get("player_ids", [])):
            visible.append(clip)
    return visible


def filter_goals_for_user(goals: list[dict], user: dict, team_id: str | None = None) -> list[dict]:
    goals = team_scoped_items(goals, team_id)
    if _auth.has_role(user, "admin", "coach"):
        return goals
    linked_players = set(_db.linked_player_ids_for_user(user.get("user_id"), team_id=team_id))
    return [
        g for g in goals
        if g.get("player_id") in linked_players
        and g.get("status") in ACTIVE_GOAL_STATUSES
        and g.get("visibility", "player") == "player"
    ]


def _playlists_with_items(playlists: list[dict], notes: list[dict] | None = None) -> list[dict]:
    notes_by_id = {note["id"]: note for note in (notes if notes is not None else _db.list_coaching_notes())}
    hydrated = []
    for playlist in playlists:
        item_notes = [
            notes_by_id[note_id]
            for note_id in playlist.get("note_ids", [])
            if note_id in notes_by_id
        ]
        hydrated.append({**playlist, "note_ids": [note["id"] for note in item_notes], "items": item_notes})
    return hydrated


def goal_with_visible_sources(goal: dict, user: dict, team_id: str | None = None) -> dict:
    out = dict(goal)
    if not _auth.has_role(user, "admin", "coach"):
        out = strip_goal_private_fields(out)
        user_id = user.get("user_id")
        reflections = [
            {k: v for k, v in r.items() if k != "user_id"}
            for r in (out.get("reflections") or [])
            if r.get("user_id") == user_id
        ]
        out["reflections"] = reflections
        out["latest_reflection"] = reflections[0] if reflections else None
        out["needs_coach_follow_up"] = any(r.get("needs_coach_follow_up") for r in reflections)
    note = _db.get_coaching_note(goal.get("source_note_id")) if goal.get("source_note_id") is not None else None
    clip = _db.get_coaching_clip(goal.get("source_clip_id")) if goal.get("source_clip_id") is not None else None
    playlist = _db.get_coaching_playlist(goal.get("source_playlist_id")) if goal.get("source_playlist_id") is not None else None
    visible_notes = filter_notes_for_user([note], user, team_id=team_id) if note else []
    visible_clips = filter_clips_for_user([clip], user, team_id=team_id) if clip else []
    visible_playlists = filter_playlists_for_user([playlist], user, team_id=team_id) if playlist else []
    viewer_notes_source = filter_notes_for_user(_db.list_coaching_notes(), user, team_id=team_id)
    if not _auth.has_role(user, "admin", "coach"):
        viewer_notes_source = [strip_private_fields(n) for n in viewer_notes_source]
        visible_notes = [strip_private_fields(n) for n in visible_notes]
    out["source_note"] = visible_notes[0] if visible_notes else None
    out["source_clip"] = visible_clips[0] if visible_clips else None
    out["source_playlist"] = _playlists_with_items(visible_playlists, viewer_notes_source)[0] if visible_playlists else None
    if team_id is not None:
        same_team_note_ids = _ids_for_team(_db.list_coaching_notes(), team_id)
        same_team_clip_ids = _ids_for_team(_db.list_coaching_clips(), team_id)
        same_team_playlist_ids = _ids_for_team(_db.list_coaching_playlists(), team_id)
        if out.get("source_note_id") not in same_team_note_ids:
            out["source_note_id"] = None
        if out.get("source_playlist_item_note_id") not in same_team_note_ids:
            out["source_playlist_item_note_id"] = None
        if out.get("source_clip_id") not in same_team_clip_ids:
            out["source_clip_id"] = None
        if out.get("source_playlist_id") not in same_team_playlist_ids:
            out["source_playlist_id"] = None
    out["source_context_notes"] = viewer_notes_source
    return out


def goals_with_visible_sources(goals: list[dict], user: dict, team_id: str | None = None) -> list[dict]:
    goals = team_scoped_items(goals, team_id)
    return [goal_with_visible_sources(g, user, team_id=team_id) for g in goals]


def filter_match_summaries_for_user(summaries: list[dict], user: dict, team_id: str | None = None) -> list[dict]:
    """Apply viewer-scoped match summary visibility and sanitize source ids."""
    summaries = team_scoped_items(summaries, team_id)
    if _auth.has_role(user, "admin", "coach"):
        return _sanitize_summary_source_ids(summaries, team_id)
    visible_note_ids = {n["id"] for n in filter_notes_for_user(_db.list_coaching_notes(), user, team_id=team_id)}
    visible_clip_ids = {c["id"] for c in filter_clips_for_user(_db.list_coaching_clips(), user, team_id=team_id)}
    visible_playlist_ids = {p["id"] for p in filter_playlists_for_user(_db.list_coaching_playlists(), user, team_id=team_id)}
    visible = []
    for summary in summaries:
        if summary.get("visibility", "private") not in {"team", "unlisted"}:
            continue
        safe = dict(summary)
        safe["note_ids"] = [nid for nid in summary.get("note_ids", []) if nid in visible_note_ids]
        safe["clip_ids"] = [cid for cid in summary.get("clip_ids", []) if cid in visible_clip_ids]
        safe["playlist_ids"] = [pid for pid in summary.get("playlist_ids", []) if pid in visible_playlist_ids]
        visible.append(safe)
    return visible


def can_view_coach_note(user: dict, note: dict, team_id: str | None = None) -> bool:
    """Return whether a user can see a standalone coaching note."""
    if _auth.has_role(user, "admin", "coach"):
        return True
    visible = filter_notes_for_user([note], user, team_id=team_id)
    return bool(visible)


def can_view_coach_clip(user: dict, clip: dict, team_id: str | None = None) -> bool:
    """Return whether a user can see a standalone coaching clip."""
    if _auth.has_role(user, "admin", "coach"):
        return True
    visible = filter_clips_for_user([clip], user, team_id=team_id)
    return bool(visible)
