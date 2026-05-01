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

Drawing metadata is versioned. `version: 1` legacy strokes still render. `version: 2` stores normalized objects for freehand lines, arrows, circles, zones, labels, spotlight, and dim overlays.

Review playlists use the existing video player. Playback seeks each item to timestamp minus pre-roll, pauses briefly on the annotated freeze frame, resumes through post-roll, and advances automatically. Review completion remains manual.

## Validation

Coverage is anchored by `tests/test_coaching.py` for role gating, roster links, note visibility, team-visible notes, playlist item privacy, drawing validation, and review tracking. Existing regression coverage continues to exercise auth, users, matches, uploads, settings, live, streams, media, db, models, and server behavior.
