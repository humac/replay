# Coaching Platform MVP Design

## Scope

The coaching platform adds private coach workflows on top of the existing public replay library. Public VOD, live viewing, uploads, score hiding, Cast, and AirPlay remain unchanged.

The MVP covers:

- Coach/admin-only roster management.
- Player records separate from login users.
- Family/player account links through `player_user_links`.
- Timestamped coaching notes with telestrator drawing overlay metadata.
- Review playlists built from coaching note moments with real sequenced playback.
- A signed-in `My Feedback` view filtered to linked roster players.
- Review tracking for assigned notes and playlists.

## Backend

Coaching persistence lives in `db.py` migration v8:

- `players`
- `player_user_links`
- `coaching_notes`
- `coaching_note_players`
- `coaching_note_tags`
- `coaching_playlists`
- `coaching_playlist_items`
- `coaching_playlist_players`
- `coaching_reviews`

Request validation lives in `models.py`. Route registration remains in `server.py`, with business logic delegated to `db.py` and role checks delegated to `auth.py`.

## Roles And Access

Roles are additive and may be comma-separated:

- `admin`: manages users, roster links, and all coaching content.
- `coach`: manages roster, notes, drawings, playlists, and assignments.
- `uploader`: manages match CRUD and uploads.
- `viewer`: has normal signed-in viewing access.

`admin` inherits coach/uploader/viewer capabilities. Coaching APIs require coach/admin unless they are the viewer-facing `/api/my-feedback` endpoints.

## Privacy Model

Anonymous users see public replay and live-stream surfaces only. Signed-in viewer users may see team-visible feedback. Linked family/player users see feedback assigned to roster players connected to their login account. Private coaching notes and playlists are visible only to coach/admin users.

A playlist is an assignment boundary: if a user can see a playlist, the ordered note moments inside that playlist are available inside the playlist review session, even if those notes are not shown as standalone feedback cards.

No public player profile pages are part of the MVP.

## Frontend

`js/coaching.js` owns the coaching UI:

- `/coach` renders the coach workspace for roster links, notes, and playlists.
- `/feedback` renders player/family feedback for signed-in users.
- Match pages render a coach-only panel for timestamped notes and telestrator metadata capture.

The drawing canvas is an overlay above the existing replay player. Drawings are stored as JSON metadata on coaching notes and are rendered back on authorized playback; they are not burned into video files.

Drawing metadata is versioned. `version: 1` legacy strokes still render. `version: 2` stores normalized objects for freehand lines, arrows, circles, zones, labels, spotlight, dim overlays, and **multi-player formations** (added in PR #54).

### Formation overlay (Phase 1)

A `formation` v2 object lets a coach highlight 3–16 players at one freeze frame and visualize their convex-hull shape. Each anchor is a `{x, y, player_id?, label?}` in normalized 0..1 coordinates; `hull_points` is the convex polygon (3–16 vertices) connecting them. The painter mirrors the existing `spotlight` `destination-out` cutout so multiple anchors share one dim layer, then strokes a translucent polygon in the active swatch color.

Authoring runs in the Coach > Review tab. The **Quick** mode drops auto-numbered anchors at every click; **Linked** mode lets the coach pick roster players in placement order so each anchor binds to a `player_id` and renders the player's jersey number as the label. Per-anchor `player_id` is the forward-compat hook for the deferred phases — when Phase 3 (animated keyframes) or Phase 4 (server-side player tracking) ships, those anchors can move through video time without the coach re-authoring the formation. Phase 1 itself is purely static; the formation paints once, on a freeze frame, like every other v2 drawing object. ROADMAP.md tracks the deferred phases (connectors + per-anchor edit; animated keyframes with drawing schema v3; server-side player tracking via FFmpeg + ByteTrack).

The validator in `models.py` enforces 3–16 anchors and 3–16 hull points so the polygon invariant holds at the API boundary, not just in the JS author UI. The frontend `finalizeFormation()` also rejects collinear anchor sets (the convex hull degenerates to < 3 points) before saving, with a coach-readable error.

Review playlists use the existing video player. Playback seeks each item to timestamp minus pre-roll, pauses briefly on the annotated freeze frame, resumes through post-roll, and advances automatically. Review completion remains manual.

## Validation

Coverage is anchored by `tests/test_coaching.py` for role gating, roster links, note visibility, team-visible notes, playlist item privacy, drawing validation, and review tracking. Existing regression coverage continues to exercise auth, users, matches, uploads, settings, live, streams, media, db, models, and server behavior.
