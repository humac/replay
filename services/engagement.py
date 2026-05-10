"""Coach engagement dashboard aggregation service."""

from __future__ import annotations

import time
from collections.abc import Iterable

import db as _db


def _same_team(item: dict | None, team_id: str | None) -> bool:
    return item is not None and (team_id is None or str(item.get("team_id")) == str(team_id))


def _sort_recent(items: list[dict], key: str = "updated_at") -> list[dict]:
    return sorted(items, key=lambda item: item.get(key) or "", reverse=True)


def _pct(reviewed: int, assigned: int) -> int:
    return int(round((reviewed / assigned) * 100)) if assigned else 0


def _phase9_item_date(item: dict, matches_by_id: dict[str, dict]) -> str:
    match = matches_by_id.get(item.get("match_id") or "")
    if match and match.get("date"):
        return match["date"]
    return (item.get("updated_at") or item.get("created_at") or "")[:10]


def _phase9_in_date_range(item: dict, matches_by_id: dict[str, dict], start_date: str | None, end_date: str | None) -> bool:
    item_date = _phase9_item_date(item, matches_by_id)
    if start_date and item_date and item_date < start_date:
        return False
    if end_date and item_date and item_date > end_date:
        return False
    return True


def build_coach_engagement_dashboard(
    *,
    player_id: str | None = None,
    playlist_id: int | None = None,
    match_id: str | None = None,
    visibility: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    team_id: str | None = None,
) -> dict:
    """Review-completion dashboard built from existing coaching data.

    Payload intentionally contains aggregate metadata only: no note bodies,
    playlist descriptions, drawings, or coach_private_note text.
    """
    players = _db.list_players(include_inactive=True, team_id=team_id)
    linked_user_ids_by_player: dict[str, set[str]] = {
        p["id"]: {str(link.get("user_id")) for link in (p.get("links") or []) if link.get("user_id")}
        for p in players
    }
    player_rows = {
        p["id"]: {
            "player_id": p["id"],
            "display_name": p.get("display_name") or "",
            "jersey_number": p.get("jersey_number") or "",
            "active": bool(p.get("active", True)),
            "assigned_count": 0,
            "reviewed_count": 0,
            "reflection_count": 0,
            "latest_reviewed_at": None,
            "completion_percentage": 0,
        }
        for p in players
        if not player_id or p["id"] == player_id
    }
    matches_by_id = {m["id"]: m for m in _db.load_matches_unlocked() if _same_team(m, team_id)}
    all_notes = [n for n in _db.list_coaching_notes() if _same_team(n, team_id)]
    all_playlists = [p for p in _db.list_coaching_playlists() if _same_team(p, team_id)]
    reviews = _db.list_coaching_reviews()
    note_by_id = {n["id"]: n for n in all_notes}

    def note_ok(note: dict) -> bool:
        if note.get("visibility") == "private":
            return False
        if player_id and player_id not in (note.get("player_ids") or []):
            return False
        if match_id and note.get("match_id") != match_id:
            return False
        if visibility and note.get("visibility") != visibility:
            return False
        return _phase9_in_date_range(note, matches_by_id, start_date, end_date)

    notes = [n for n in all_notes if note_ok(n)]
    note_ids = {n["id"] for n in notes}

    def reviews_for_player(item_reviews: list[dict], pid: str) -> list[dict]:
        linked_user_ids = linked_user_ids_by_player.get(pid) or set()
        return [r for r in item_reviews if str(r.get("user_id")) in linked_user_ids]

    def reviews_for_players(item_reviews: list[dict], pids: Iterable[str]) -> list[dict]:
        allowed: set[str] = set()
        for pid in pids:
            allowed.update(linked_user_ids_by_player.get(pid) or set())
        return [r for r in item_reviews if str(r.get("user_id")) in allowed]

    def playlist_matching_notes(playlist: dict) -> list[dict]:
        matched: list[dict] = []
        for nid in (playlist.get("note_ids") or []):
            note = note_by_id.get(nid)
            if not note or note.get("visibility") == "private":
                continue
            if match_id and note.get("match_id") != match_id:
                continue
            if not _phase9_in_date_range(note, matches_by_id, start_date, end_date):
                continue
            matched.append(note)
        return matched

    def playlist_assigned_player_ids(playlist: dict) -> set[str]:
        matched_notes = playlist_matching_notes(playlist)
        pids: set[str] = set()
        if match_id or start_date or end_date:
            for note in matched_notes:
                pids.update(note.get("player_ids") or [])
        else:
            pids.update(playlist.get("player_ids") or [])
            for note in matched_notes:
                pids.update(note.get("player_ids") or [])
        if player_id:
            pids = {pid for pid in pids if pid == player_id}
        return pids

    def playlist_ok(playlist: dict) -> bool:
        if playlist_id and int(playlist.get("id") or 0) != playlist_id:
            return False
        if playlist.get("visibility") == "private":
            return False
        if visibility and playlist.get("visibility") != visibility:
            return False
        item_notes = playlist_matching_notes(playlist)
        pids = playlist_assigned_player_ids(playlist)
        if player_id and not pids:
            return False
        if match_id and not item_notes:
            return False
        if start_date or end_date:
            if item_notes or (match_id and not item_notes):
                return bool(item_notes)
            return _phase9_in_date_range({"updated_at": playlist.get("updated_at"), "created_at": playlist.get("created_at")}, matches_by_id, start_date, end_date)
        return True

    playlists = [p for p in all_playlists if playlist_ok(p)]
    playlist_ids = {p["id"] for p in playlists}
    reviews_by_note: dict[int, list[dict]] = {}
    reviews_by_playlist: dict[int, list[dict]] = {}
    for review in reviews:
        if review.get("note_id") in note_ids:
            reviews_by_note.setdefault(review["note_id"], []).append(review)
        if review.get("playlist_id") in playlist_ids:
            reviews_by_playlist.setdefault(review["playlist_id"], []).append(review)

    unreviewed: list[dict] = []
    summary_reviews: list[dict] = []
    most_watched_entries: list[dict] = []
    match_rows: dict[str, dict] = {}

    def match_label(mid: str | None) -> str:
        match = matches_by_id.get(mid or "")
        if not match:
            return "Observation / no match"
        home = match.get("home_team") or "Home"
        away = match.get("away_team") or "Away"
        return f"{home} vs {away}"

    def apply_to_match(mid: str | None, item_reviews: list[dict]) -> None:
        key = mid or ""
        row = match_rows.setdefault(key, {
            "match_id": mid,
            "label": match_label(mid),
            "date": (matches_by_id.get(mid or "") or {}).get("date") or "",
            "assigned_count": 0,
            "reviewed_count": 0,
            "reflection_count": 0,
            "latest_reviewed_at": None,
            "completion_percentage": 0,
        })
        row["assigned_count"] += 1
        if item_reviews:
            row["reviewed_count"] += 1
        row["reflection_count"] += sum(1 for r in item_reviews if (r.get("reflection") or "").strip())
        latest = _sort_recent(item_reviews, key="reviewed_at")[:1]
        if latest and (not row["latest_reviewed_at"] or latest[0]["reviewed_at"] > row["latest_reviewed_at"]):
            row["latest_reviewed_at"] = latest[0]["reviewed_at"]

    def apply_to_player(pid: str, item_reviews: list[dict]) -> None:
        row = player_rows.get(pid)
        if not row:
            return
        item_reviews = reviews_for_player(item_reviews, pid)
        row["assigned_count"] += 1
        if item_reviews:
            row["reviewed_count"] += 1
        row["reflection_count"] += sum(1 for r in item_reviews if (r.get("reflection") or "").strip())
        latest = _sort_recent(item_reviews, key="reviewed_at")[:1]
        if latest and (not row["latest_reviewed_at"] or latest[0]["reviewed_at"] > row["latest_reviewed_at"]):
            row["latest_reviewed_at"] = latest[0]["reviewed_at"]

    for note in notes:
        item_reviews = reviews_by_note.get(note["id"], [])
        pids = [pid for pid in (note.get("player_ids") or []) if pid in player_rows]
        scoped_item_reviews = reviews_for_players(item_reviews, pids)
        summary_reviews.extend(scoped_item_reviews)
        if scoped_item_reviews:
            most_watched_entries.append({"kind": "note", "item_id": note["id"], "title": note.get("title") or "", "review_count": len(scoped_item_reviews)})
        for pid in pids:
            apply_to_player(pid, item_reviews)
        if pids:
            apply_to_match(note.get("match_id"), scoped_item_reviews)
        if pids and not scoped_item_reviews:
            unreviewed.append({
                "kind": "note",
                "item_id": note["id"],
                "title": note.get("title") or "",
                "player_ids": pids,
                "match_id": note.get("match_id"),
                "date": _phase9_item_date(note, matches_by_id),
            })

    by_playlist: list[dict] = []
    for playlist in playlists:
        item_reviews = reviews_by_playlist.get(playlist["id"], [])
        pids = playlist_assigned_player_ids(playlist)
        pids = {pid for pid in pids if pid in player_rows}
        scoped_item_reviews = reviews_for_players(item_reviews, pids)
        summary_reviews.extend(scoped_item_reviews)
        if scoped_item_reviews:
            most_watched_entries.append({"kind": "playlist", "item_id": playlist["id"], "title": playlist.get("title") or "", "review_count": len(scoped_item_reviews)})
        for pid in pids:
            apply_to_player(pid, item_reviews)
        if pids:
            mids = {note.get("match_id") for note in playlist_matching_notes(playlist)}
            if match_id:
                mids = {match_id}
            for mid in (mids or {None}):
                apply_to_match(mid, scoped_item_reviews)
        latest = _sort_recent(scoped_item_reviews, key="reviewed_at")[:1]
        refs = [r for r in scoped_item_reviews if (r.get("reflection") or "").strip()]
        by_playlist.append({
            "playlist_id": playlist["id"],
            "title": playlist.get("title") or "",
            "player_ids": sorted(pids),
            "assigned_count": 1 if pids else 0,
            "reviewed_count": 1 if scoped_item_reviews else 0,
            "reflection_count": len(refs),
            "latest_reviewed_at": latest[0]["reviewed_at"] if latest else None,
            "completion_percentage": 100 if scoped_item_reviews else 0,
        })
        if pids and not scoped_item_reviews:
            unreviewed.append({
                "kind": "playlist",
                "item_id": playlist["id"],
                "title": playlist.get("title") or "",
                "player_ids": sorted(pids),
                "match_id": match_id,
                "date": (playlist.get("updated_at") or playlist.get("created_at") or "")[:10],
            })

    for row in player_rows.values():
        row["completion_percentage"] = _pct(row["reviewed_count"], row["assigned_count"])
    for row in match_rows.values():
        row["completion_percentage"] = _pct(row["reviewed_count"], row["assigned_count"])
    by_player = sorted(
        [row for row in player_rows.values() if row["assigned_count"] or not player_id],
        key=lambda r: (-r["assigned_count"], r["display_name"].lower(), r["player_id"]),
    )
    by_playlist = sorted(by_playlist, key=lambda r: (-r["assigned_count"], r["title"].lower(), r["playlist_id"]))
    sorted_reviews = _sort_recent(summary_reviews, key="reviewed_at")
    reflections = [r for r in sorted_reviews if (r.get("reflection") or "").strip()]
    assigned_total = sum(row["assigned_count"] for row in by_player)
    reviewed_total = sum(row["reviewed_count"] for row in by_player)
    no_recent_cutoff = end_date or time.strftime("%Y-%m-%d", time.gmtime(time.time() - 14 * 24 * 60 * 60))
    recent_pids = {
        pid
        for n in all_notes
        if n.get("visibility") != "private"
        if _phase9_item_date(n, matches_by_id) >= no_recent_cutoff
        for pid in (n.get("player_ids") or [])
    }
    most_watched = sorted(
        most_watched_entries,
        key=lambda item: (-item["review_count"], item["kind"], item["item_id"]),
    )[:5]
    return {
        "filters": {"player_id": player_id, "playlist_id": playlist_id, "match_id": match_id, "visibility": visibility, "start_date": start_date, "end_date": end_date},
        "summary": {
            "assigned_items": assigned_total,
            "reviewed_items": reviewed_total,
            "reflection_count": len(reflections),
            "latest_reviewed_at": sorted_reviews[0]["reviewed_at"] if sorted_reviews else None,
            "completion_percentage": _pct(reviewed_total, assigned_total),
            "unreviewed_items": max(0, assigned_total - reviewed_total),
        },
        "by_player": by_player,
        "by_playlist": by_playlist,
        "by_match": sorted(match_rows.values(), key=lambda r: (r.get("date") or "", r.get("label") or ""), reverse=True),
        "unreviewed_assigned_items": sorted(unreviewed, key=lambda item: (item.get("date") or "", item["kind"], item["item_id"]), reverse=True)[:25],
        "reflections_needing_response": [
            {"user_id": r.get("user_id"), "note_id": r.get("note_id"), "playlist_id": r.get("playlist_id"), "reflection": r.get("reflection") or "", "reviewed_at": r.get("reviewed_at")}
            for r in reflections[:25]
        ],
        "players_with_no_recent_feedback": [
            {"player_id": p["id"], "display_name": p.get("display_name") or "", "jersey_number": p.get("jersey_number") or ""}
            for p in players
            if p.get("active", True) and (not player_id or p["id"] == player_id) and p["id"] not in recent_pids
        ],
        "most_watched": most_watched,
        "limitations": {
            "clip_reviews_supported": False,
            "most_watched_source": "coaching_reviews note_id/playlist_id counts; clip watch tracking is not yet supported.",
            "reflection_response_tracking_supported": False,
            "goal_reflections_supported": False,
            "goal_reflections_scope": "Phase 9 tracks feedback review reflections only; player goal reflections needing coach follow-up stay in player development/goals APIs for now.",
        },
    }
