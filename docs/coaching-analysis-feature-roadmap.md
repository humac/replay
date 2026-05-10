# Coaching Analysis Feature Roadmap

This roadmap covers the product features needed to evolve Replay from a strong match replay and annotation tool into a practical player-development coaching platform.

This is separate from `docs/archive/coach-review-ui-ux-implementation-plan.md`, which focuses on Coach Review layout, compact controls, telestration workspace design, keyboard shortcuts, and responsive UI polish.

Related roadmap:

- `docs/ai-video-analysis-roadmap.md` expands the computer-vision and video-analysis phases in more technical detail.

## Product goal

Replay should help coaches answer:

> What should this player or team improve next, and what match evidence supports that coaching point?

The current system already supports match upload, playback, live viewing, roster players, linked family/player accounts, timestamped notes, telestrator drawings, playlists, visibility controls, and My Feedback review tracking. The next feature work should turn those building blocks into a repeatable coaching and player-development workflow.

## Guiding principles

1. Keep coaches in control. AI and automation should assist, not replace coaching judgment.
2. Make feedback actionable. Every player-facing item should be clear, short, and tied to a specific improvement point.
3. Balance positives and corrections. Youth players need confidence and clarity.
4. Organize around players and development themes, not just matches.
5. Prefer simple, coach-usable workflows over complex analytics dashboards.
6. Preserve privacy and role boundaries.
7. Avoid breaking existing replay, live, upload, My Feedback, and telestrator behavior.
8. Treat computer vision as a suggestion engine until it proves reliable on real match footage.
9. Do not expose experimental AI/video-analysis output to players without coach approval.
10. Do not claim physical KPIs such as distance covered or sprint speed unless field calibration, identity tracking, and confidence scoring are in place.

## Current foundation

Existing useful foundation:

- Match library with full-match and two-half video support.
- HLS playback and MP4 fallback.
- Live stream support.
- Admin/user roles.
- Coach workspace.
- Roster players.
- Player/family account links.
- Timestamped coaching notes.
- Note categories and tags.
- Drawing/telestrator metadata.
- Review playlists with pre-roll and post-roll.
- My Feedback view for players/families.
- Review tracking with optional reflection.

Main gap:

Replay currently behaves mostly like a video-attached coaching notebook. The next phase should make it a player-development system with clip packages, player history, goals, review completion, summaries, and eventually AI-assisted coaching workflows.

Computer vision can later help Replay find candidate moments, player tracks, tactical shapes, highlights, and heatmaps. It should be built after the manual coaching workflow is solid.

---

# Recommended feature rollout

## Status snapshot

- ✅ Phase 1 — Coaching note structure and feedback quality — **complete**
- ✅ Phase 2 — Coach review templates — **complete**
- ✅ Phase 3 — Per-note thumbnails and clip scanability — **complete**
- ✅ Phase 4 — First-class clip builder (incl. per-clip thumbnails) — **complete**
- ✅ Phase 5 — Player development profiles — **complete**
- ✅ Phase 6 — Coach observations and tactical board — **complete**
  - ✅ 6a — Observation note backend
  - ✅ 6b — Coach observation composer
  - ✅ 6c — Tactical board MVP
  - ✅ 6d-1 — Unified Coach Review source modes and creation routing
  - ✅ 6d-2 — Tactical board authoring improvements and formations
  - ✅ 6e — Unified viewer review modal for My Feedback / Player Development
- ✅ Phase 7 — Action items and next-match goals — **complete**
- ✅ Phase 8 — Match coaching summaries — **complete**
- ⏭️ Phase 9 — Coach engagement dashboard — **next**
- ⏳ Phases 10–17 — not started

See `ROADMAP.md` for the per-PR completion log and exact dates.

## Phase 1: Coaching note structure and feedback quality ✅ COMPLETE

### Goal

Make individual notes more useful, consistent, and player-friendly.

### Shipped

PR 1a (`db.py` `_migrate_v9`) added `note_type` (`positive` / `correction` / `question` / `team_concept` / `individual_goal`, default `correction`) plus `what_happened`, `why_it_matters`, `what_to_do_next`, `player_summary`, and `coach_private_note` to `coaching_notes`. PR 1b surfaced the structured fields in the Coach Review composer and Notes-tab Edit modal. PR 1c rendered the player-facing layer in My Feedback (tone pill, `player_summary || body` fallback, structured `<dl>`). `coach_private_note` is scrubbed for viewers via `_strip_private_fields()` on every viewer-visible code path.

### Features

1. Add note type / tone:
   - Positive
   - Correction
   - Question
   - Team concept
   - Individual goal

2. Add coaching point fields:
   - `what_happened`
   - `why_it_matters`
   - `what_to_do_next`

3. Add age-appropriate player-facing summary:
   - short, plain-language version of the coach note
   - optional separate internal coach note remains private

4. Add structured outcome tags:
   - scanning
   - first touch
   - body shape
   - decision making
   - off-ball movement
   - pressing
   - recovery run
   - spacing
   - passing lane
   - defensive shape
   - transition
   - finishing
   - goalkeeper distribution
   - set piece

5. Add positive/correction ratio tracking per playlist and per player.

### Backend data model suggestions

Add columns to `coaching_notes` or add a companion table if minimizing migration risk:

- `note_type TEXT NOT NULL DEFAULT 'correction'`
- `what_happened TEXT DEFAULT ''`
- `why_it_matters TEXT DEFAULT ''`
- `what_to_do_next TEXT DEFAULT ''`
- `player_summary TEXT DEFAULT ''`
- `coach_private_note TEXT DEFAULT ''`

If keeping the schema lighter, store structured coaching details in a `coaching_json` column.

### Acceptance criteria

- Coaches can mark a note as positive, correction, question, team concept, or individual goal.
- My Feedback shows player-friendly summary first, not long internal coach notes.
- Existing notes continue to render after migration.
- API validation prevents invalid note types.
- Tests cover create/update/list behavior for the new fields.

### Coding agent prompt

```text
Implement structured coaching note fields for Replay. Add a note_type/tone enum with Positive, Correction, Question, Team Concept, and Individual Goal. Add fields for what_happened, why_it_matters, what_to_do_next, player_summary, and optional coach_private_note. Preserve existing notes through migration defaults. Update Pydantic validation, DB row mapping, create/update endpoints, Coach note UI, Coach Review save flow, My Feedback rendering, and tests. Keep privacy boundaries intact: player_summary is player-facing, coach_private_note is coach/admin only.
```

---

## Phase 2: Coach review templates ✅ COMPLETE

### Goal

Reduce coach typing and make note quality more consistent.

### Shipped

A static template registry (`js/coaching-templates.js`) with 14 starter soccer templates wired into the Coach Review composer. Selecting a template prefills `note_type`, `category`, `title`, `player_summary`, `what_happened`, `why_it_matters`, `what_to_do_next`, and `tags`; coach-typed text is protected by a confirm-overwrite guard. Templates never populate `coach_private_note`.

### Features

Create reusable templates for common soccer coaching moments:

- Scanning before receiving
- Body shape when receiving
- First touch direction
- Passing decision
- Movement after pass
- Width and depth
- Defensive recovery
- Pressing trigger
- Delay/contain in 1v1 defending
- Tracking runner
- Goalkeeper distribution
- Set-piece marking
- Transition reaction
- Finishing choice

Each template should provide:

- default category
- default note type
- suggested title
- suggested player-facing language
- suggested `what_to_do_next`
- suggested tags

### UX behavior

In Coach Review:

1. Coach chooses template.
2. Template fills structured fields.
3. Coach edits quickly.
4. Coach saves note at current timestamp.

### Storage options

Start with static frontend templates in `js/coaching.js` or a new `js/coaching-templates.js`.

Later, move to DB-backed customizable templates.

### Acceptance criteria

- Coach can pick a template while saving a note.
- Template pre-fills relevant fields without overwriting manually edited text unexpectedly.
- Templates are grouped by category.
- No backend migration is required for static templates.

### Coding agent prompt

```text
Add coach review templates for common soccer coaching moments. Use a static template registry first, preferably in a new js/coaching-templates.js module or a clearly isolated section of js/coaching.js. In the Coach Review note composer, add a template selector grouped by category. Selecting a template should prefill title, category, note_type, player_summary, what_happened, why_it_matters, what_to_do_next, and tags where those fields exist. Do not overwrite fields the coach has manually edited unless the coach confirms or clicks Reset from template. Add tests or manual QA notes for template behavior.
```

---

## Phase 3: Per-note thumbnails and clip scanability ✅ COMPLETE

### Goal

Make notes and playlists visually scannable.

### Shipped

Phase 3a backend generated per-note JPEGs at `<videos>/<match_id>/coach_thumbs/<note_id>.jpg`, served via a visibility-checked `GET /api/coach/notes/{id}/thumbnail` (404 for unknown / unauthorized / missing — viewers cannot probe private-note existence) plus a coach-only regenerate endpoint. Phase 3b mounted thumbnails in Coach Notes, Coach Review timeline, Coach Playlists, the playlist session rail, My Feedback notes, and My Feedback playlists with negative-cached blob loaders, object-URL revocation on logout, and a CSS film-strip placeholder for the no-thumbnail case.

### Features

1. Generate a thumbnail at each coaching note timestamp.
2. Store thumbnail metadata/path.
3. Show thumbnails in:
   - Coach Notes list
   - Coach Review timeline rail
   - Playlist builder
   - Playlist preview
   - My Feedback notes
   - My Feedback playlists

### Backend design

Possible endpoint:

- `POST /api/admin/coaching/notes/{id}/thumbnail/regenerate`
- or automatic thumbnail generation on note create/update

Storage path example:

```text
$REPLAY_DATA_DIR/videos/<match-id>/coach_thumbs/<note-id>.jpg
```

Serve via:

```text
GET /api/coach/notes/{id}/thumbnail
```

Access control:

- Coach/admin can access thumbnails for all notes.
- Viewer can access thumbnails only for notes visible through My Feedback or visible playlist item access.

### Acceptance criteria

- New notes get a thumbnail when a source video exists.
- Missing thumbnails degrade gracefully.
- Thumbnail generation failure does not block note save.
- Viewer access respects note/playlist visibility.
- Playlists become much easier to scan visually.

### Coding agent prompt

```text
Add per-note thumbnail generation for coaching notes. When a note is created or its timestamp changes, generate a JPEG still from the source match slot at timestamp_seconds. Store it under the match folder in a coach_thumbs directory. Add a secure endpoint to serve note thumbnails with role and feedback visibility checks. Show thumbnails in Coach Notes, Coach Review timeline/rail, playlist builder, playlist preview, and My Feedback. Fail gracefully if source video is missing or ffmpeg thumbnail generation fails. Add tests for access control and endpoint behavior.
```

---

## Phase 4: First-class clip builder ✅ COMPLETE

### Goal

Let coaches create actual shareable clip moments, not only timestamped notes.

### Shipped

Phase 4a added the `coaching_clips` + `coaching_clip_players` schema (`_migrate_v10`) and CRUD under `/api/coach/clips` with the strict privacy invariant that only the drawing snapshot is auto-copied from a `source_note_id` — never text fields. Phase 4b wired Coach > Clips, a "Save Clip" button in Coach Review, and seek-based clip playback inside the focused feedback player (no MP4 export). Phase 4e added per-clip thumbnails at `<videos>/<match_id>/clip_thumbs/<clip_id>.jpg` with the same visibility-checked GET + regenerate pattern as note thumbnails, and a four-step JS fallback chain (clip → source-note → co-located note → placeholder). MVP duration cap is 120 s; clips remain video-only.

### Features

1. Create clip from current timestamp.
2. Default pre-roll/post-roll from note or playlist settings.
3. Clip metadata:
   - title
   - match_id
   - slot
   - start_seconds
   - end_seconds
   - player_ids
   - category
   - note_id optional
   - visibility
4. Optional MP4 export job.
5. Clip playback in Coach and My Feedback.
6. Clip can include drawing overlay as metadata during playback.

### Backend design

New tables:

- `coaching_clips`
- optional `coaching_clip_players`
- optional `coaching_clip_exports`

Possible endpoints:

- `GET /api/coach/clips`
- `POST /api/coach/clips`
- `PATCH /api/coach/clips/{id}`
- `DELETE /api/coach/clips/{id}`
- `POST /api/coach/clips/{id}/export-mp4`
- `GET /api/coach/clips/{id}/video` or reuse match video seek playback

### Acceptance criteria

- Coach can create a clip from current video time in Review.
- Clip can be assigned to player/team.
- My Feedback can play assigned clips without navigating to the full match page.
- MP4 export is optional and can be deferred.
- Existing playlists continue working.

### Coding agent prompt

```text
Implement first-class coaching clips. Add a coaching_clips data model with match_id, slot, start_seconds, end_seconds, title, category, visibility, linked players, and optional source note_id. Add coach CRUD endpoints and UI in Coach Review to create a clip from the current timestamp using default pre/post roll. Add clip playback in My Feedback using the existing focused feedback player where possible. Keep MP4 export optional; start with seek-based playback against the source match video. Add access control tests for team-visible and player-specific clips.
```

---

## Phase 5: Player development profiles ✅ COMPLETE

### Goal

Give coaches and families a player-centered view of development over time.

### Shipped

Phase 5a added two read-only aggregation endpoints — coach-only `GET /api/coach/players/{id}/development` and viewer-scoped `GET /api/my-feedback/players/{id}/development` — sharing one `_build_player_development_profile()` builder so the privacy ladder cannot drift. Unknown players and unrelated viewers both return 404 (so a viewer cannot probe roster ids). The profile aggregates counts, themes (note_type buckets, positive-to-correction ratio, top categories/tags), review status, recent notes / positives / corrections / clips / playlists (each capped at 5), and `current_focus_areas` derived from recent corrections + individual_goal notes (labelled `source: "derived_from_recent_notes"` so a future client doesn't treat them as formal goals — Phase 7 will graduate this once `player_goals` lands). `coach_private_note` text is privileged-only on the coach surface and stripped on the viewer surface. Phase 5b wired the UI: a coach-only chart-icon button on every Coach > Roster row opens a wide-modal profile, and a new `Development` sub-tab in My Feedback renders the same profile via `_renderPlayerDevelopmentProfile()`. Note + clip thumbnails go through the existing visibility-checked mounters.

### Features

Player profile should show:

- player details
- linked accounts
- assigned notes
- assigned playlists
- assigned clips
- review status
- reflections
- top categories
- recent positives
- recent corrections
- current derived focus areas, and later active goals once the goals phase lands
- progress over recent matches

Coach view:

```text
Player: #9 Ava
Recent Themes: Scanning, First Touch, Defensive Recovery
Strengths: Movement off ball, effort
Focus Areas: Body shape, checking shoulder
Current Goal: Scan twice before receiving in midfield
Latest Clips: [thumb] [thumb] [thumb]
Review Completion: 8/11 items reviewed
```

Family/player view:

- simpler, more encouraging language
- current derived focus areas, and later active goals once the goals phase lands
- assigned feedback
- reviewed/completed status

### Backend design

Endpoints:

- `GET /api/coach/players/{id}/development`
- `GET /api/my-feedback/players/{id}/development`

Possibly add:

- `player_goals`
- `player_goal_reviews`

### Acceptance criteria

- Coach can open a player profile from roster, note, playlist, or feedback item.
- Profile aggregates notes/playlists/clips by player.
- Family/player only sees their linked player data.
- Private coach notes do not leak into player-facing profile.

### Coding agent prompt

```text
Add player development profiles. Build a coach-facing player profile that aggregates assigned notes, playlists, clips, review status, reflections, top categories, recent positives, recent corrections, and current derived focus areas (formal active goals will be wired in once the goals phase lands). Add a player/family-safe version under My Feedback scoped to linked accounts. Preserve privacy: private coach notes and internal coach_private_note fields must not leak to viewers. Add endpoints for coach and viewer profile data, then add UI entry points from roster, notes, playlists, and feedback items.
```

---

## Phase 6: Coach observations and tactical board

### Goal

Let coaches create player feedback when no match video is available — practice, sideline observations, tactical concepts, formations, set pieces, meetings, and games without footage.

### Why

The existing coaching workflow is video-first: structured notes, clips, playlists, thumbnails, and player development profiles all assume there is a match slot with a `timestamp_seconds` to anchor against. Coaches also need to capture feedback that originates outside that flow. Adding a non-video context to coaching notes — and a simple tactical sketch surface — lets the same structured note shape (note_type, player_summary, what_happened, why_it_matters, what_to_do_next, coach_private_note, visibility, tags, player_ids) carry feedback regardless of whether video evidence exists.

### Concept

Extend coaching notes into two contexts:

1. Video notes
   - Existing match/slot/timestamp-based notes.
   - Can include video telestration/drawing at the note timestamp.
   - The current video workflow stays intact.

2. Observation notes
   - Non-video coaching feedback.
   - Can be attached to a practice, game, meeting, tactical concept, or other event.
   - Can optionally include a tactical board sketch.
   - Reuses the existing structured coaching note fields.

### MVP fields

Extend `coaching_notes` (or a companion table) with:

- `note_context`: `video` | `observation`
- `event_title`
- `event_date`
- `event_type`: `practice` | `game` | `meeting` | `tactical` | `other`
- `tactical_board_json`
- `match_id`, `slot`, `timestamp_seconds` become nullable for observation notes

`tactical_board_json` stores a structured board scene, not a raster image. It should contain `pitch_kind`, normalized coordinates, tokens, shapes, arrows, zones, labels, and any future board metadata needed to re-render or edit the sketch.

Video notes still require `match_id`, `slot`, `timestamp_seconds`. Observation notes do not. Existing video-note payloads should continue to work without requiring `tactical_board_json` or event fields.

### Subphase 6a — Observation note backend ✅ COMPLETE

- Add support for non-video coaching notes through the schema changes above.
- Validation: `note_context = video` requires `match_id` + `slot` + `timestamp_seconds`; `note_context = observation` does not.
- Observation notes use the same visibility/privacy ladder as existing notes (`team` / `player` / `private`).
- `coach_private_note` remains coach/admin-only on both contexts.
- No UI in this subphase.

### Subphase 6b — Coach observation composer ✅ COMPLETE

- Add a Coach UI for creating observation notes without video.
- Entry points from Coach > Roster (per-player "Add observation") and Coach > Notes ("New observation").
- Reuse the existing structured note fields:
  - `note_type`
  - `category`
  - `player_summary`
  - `what_happened`
  - `why_it_matters`
  - `what_to_do_next`
  - `coach_private_note`
  - `visibility`
  - `tags`
  - `player_ids`
- Add the new event title / event date / event type fields.

### Subphase 6c — Tactical board MVP ✅ COMPLETE

- Add a simple tactical sketch component attached to observation notes.
- The board background is sport-specific, not a blank canvas. The MVP ships a **soccer pitch** background drawn to scale with standard markings:
  - touchlines and goal lines
  - halfway line and centre circle / centre spot
  - both penalty areas (18-yard boxes) and goal areas (6-yard boxes)
  - both penalty spots and penalty arcs
  - corner arcs
  - both goals
- The pitch is rendered as resolution-independent vector graphics (SVG or canvas paths) so tokens, arrows, and labels stay aligned across screen sizes and in the read-only viewer. Coordinates inside `tactical_board_json` are stored as normalized pitch-space values (e.g. `0..1` along length and width) so a future re-render at a different size or orientation does not break saved sketches.
- Pitch orientation defaults to landscape (attacking left-to-right). A simple "rotate 90°" toggle is acceptable but not required for the MVP.
- The pitch surface is implemented as a swappable background layer. The MVP only ships soccer, but the data model and renderer should not hardcode "soccer" everywhere — store a `pitch_kind` discriminator (e.g. `soccer_full`) inside `tactical_board_json` so future sports (futsal, 7-a-side, basketball, hockey, etc.) can be added later without a schema migration.
- MVP drawing tools:
  - draggable player tokens (with optional jersey number / roster player label)
  - ball token
  - arrows / lines / zones
  - text labels
  - save / load `tactical_board_json`
  - read-only viewer rendering that paints the same pitch background plus the saved tokens and shapes
- The MVP does not include drill libraries, multi-frame animations, PDF export, kit-color theming, or AI tactical analysis.
- A board preview/thumbnail can be generated later for scanability in Coach Notes, My Feedback, and Player Development Profiles. The MVP only requires editable coach rendering and read-only viewer rendering; thumbnail generation can be deferred.

### Subphase 6d-1 — Unified Coach Review source modes and creation routing ✅ COMPLETE

> **Why 6d was split.** The original Phase 6d combined two large pieces of work: (a) the unified authoring routing (move all creation entry points into Coach Review) and (b) tactical-board tool parity + formations. Each is a substantial PR on its own. 6d-1 ships the routing correction with the existing Phase 6c board tools mostly as-is; 6d-2 evolves the board authoring tools afterwards.

> **Why this subphase exists.** UX testing of 6a/6b/6c surfaced a creation-flow problem: New Note, New Observation, and New Clip all open list-management modals, and the tactical board editor inside the observation modal is cramped and disconnected from the existing Coach Review telestration mental model. The product correction is to make Coach Review the single creation workspace (video notes, video clips, tactical-board observations) and reduce the Coach > Notes / Clips / Playlists / Roster pages to **management surfaces** (view / edit / delete / route to Review). The Phase 6a backend, the Phase 6b composer-side fields, and the Phase 6c board schema + SVG renderer are all retained — 6d-1 is a workflow correction, not a rewrite.

**Shipped:** Coach Review gained Video / Tactical Board source modes. Creation entry points for new notes, clips, and observations now route into Coach Review while list pages remain management surfaces.

#### Goal

Make Coach Review the single creation workspace for **video notes**, **video clips**, and **tactical-board observations**. Coach > Notes / Clips / Playlists / Roster become management surfaces.

#### Coach Review source/mode toggle

A new top-of-Review toggle picks the authoring source:

1. **Video** mode
   - Keeps the existing match/video selection workflow.
   - Keeps the existing video telestration tools.
   - Supports **Save Note** (existing) and **Save Clip** (existing).
   - Receives the rerouted `+ New Note` / `+ New Clip` actions from Coach > Notes / Clips.

2. **Tactical Board** mode
   - Loads the soccer tactical board surface (Phase 6c renderer) instead of a video.
   - Uses the structured `tactical_board_json` scene (Phase 6c schema).
   - Supports **Save Observation**.
   - Receives the rerouted `+ New observation` (Coach > Notes) and `Add observation` (Coach > Roster) actions.
   - When entered from a roster player, **preselect that player** in the observation form.
   - Reuses the existing Phase 6c board tools mostly as-is (player token, ball token, two-click arrow / line / zone, label-text input, drag-to-move, delete / clear). The tool-parity evolution lands in 6d-2 — do not bundle it here.

#### Button reroutes

| Existing action | New behavior |
| --- | --- |
| Coach > Notes > **+ New note** | Route to Coach Review, **Video** mode |
| Coach > Notes > **+ New observation** | Route to Coach Review, **Tactical Board** mode |
| Coach > Clips > **+ New clip** | Route to Coach Review, **Video** mode |
| Coach > Roster > **Add observation** (clipboard icon) | Route to Coach Review, **Tactical Board** mode, with player preselected |
| Coach > Roster > **Add note** (future) | Route to Coach Review, **Video** mode, with player preselected |

#### Modal policy

- **Edit** modals stay where appropriate for structured text + metadata edits on existing objects.
- **Creation** moves to Coach Review.
- The cramped observation-creation modal that currently hosts the Phase 6c board editor should be retired in favor of Coach Review's full-width Tactical Board mode for new observations. Edits to existing observation notes can continue to use the existing edit modal during 6d-1; the in-modal board editor itself is deferred for retirement to 6d-2 once the Coach Review board surface is the canonical authoring path.

#### Reuse from prior subphases (do not throw away)

- Phase 6a backend fields and validation (`note_context`, `event_*`, `tactical_board_json`).
- Phase 6b observation composer / structured-fields surface (now hosted inside Coach Review's Tactical Board mode).
- Phase 6c board schema (`pitch_kind` / `tokens` / `shapes` / normalized 0..1 coordinates) and SVG renderer.
- Phase 6c read-only board renderer (shared with viewer surfaces).
- Existing note / clip save APIs (`POST /api/coach/notes`, `PATCH /api/coach/notes/{id}`, `POST /api/coach/clips`, etc.).
- Existing video telestration mental model and toolset.

#### Out of scope for 6d-1 (deferred to 6d-2 or 6e)

- **No formation selector yet.** Game-format / formation presets land in 6d-2.
- **No tactical-board tool parity work yet.** Drag-to-draw arrows, freehand, resizeable zone box, etc. land in 6d-2.
- **No My Feedback or Player Development polish.** That is 6e.

#### Product boundaries for 6d-1

- No new endpoints.
- No schema migration.
- No My Feedback redesign.
- No Player Development redesign.
- No goals / action plans.
- No AI / CV.
- No drill library.
- No multi-frame animation.
- No PDF export.
- No kit-color theming.
- No full roster-assignment system.
- No new public board endpoint.
- Privacy rules unchanged.

### Subphase 6d-2 — Tactical board authoring improvements and formations ✅ COMPLETE

#### Goal

Now that the routing is fixed (6d-1), evolve the tactical board authoring tools so the surface feels closer to the existing video telestration mental model and ships formation presets that match youth game formats.

**Shipped:** Tactical Board mode now supports drag-to-draw arrows/lines/zones, freehand strokes, resizeable zones, keyboard shortcuts, color and stroke-width parity with the video telestrator, and 7v7 / 9v9 / 11v11 formation presets with optional `game_format` / `formation` metadata in `tactical_board_json`.

#### Tactical board tool parity

- **Drag-to-draw arrows** (replace the drop-arrowhead-then-set-endpoint two-click affordance with a single drag from start to end).
- **Freehand drawing** (continuous-stroke pencil tool, persisted as a `freehand` shape kind in `tactical_board_json`).
- **Resizeable zone box** (resize handles on the existing `zone` shape after placement, in addition to the current two-click corner placement).
- Improved general line / arrow behavior (snap to angle, length readout, etc. as practical).
- Continue to support the 6c basics: select / move, line, text label, player token, ball token, delete / erase, clear.

#### Formation MVP

- Add a **game-format selector** before or alongside formation presets:
  - 7v7
  - 9v9
  - 11v11
- Formation preset options depend on the selected format:
  - **7v7**: 2-3-1, 3-2-1, 2-1-2-1
  - **9v9**: 3-2-3, 3-3-2, 2-3-3, 4-3-1
  - **11v11**: 4-3-3, 4-2-3-1, 4-4-2, 3-5-2, custom
- Formation presets place player tokens in normalized pitch-space positions.
- When practical, persist the selected format + formation name as `tactical_board_json` metadata, e.g.:
  - `game_format`: `"7v7"` | `"9v9"` | `"11v11"`
  - `formation`: `"2-3-1"`

#### Out of scope for 6d-2

- Full roster assignment (per-token player_id binding beyond the existing optional `player_id` field on player tokens).
- Kit-color theming.
- Animation.
- Drill library.
- PDF export.
- AI / CV.

#### Product boundaries for 6d-2

- Backwards-compatible with 6c board scenes (tokens / shapes from a 6d-1 / 6c-era board still load and render).
- Board schema may add new shape kinds (e.g. `freehand`) and optional metadata keys (`game_format`, `formation`) but must not change the meaning of existing fields.
- No new endpoints, no schema migration. The new metadata persists inside `tactical_board_json` (TEXT JSON column).
- Privacy rules unchanged.

### Subphase 6e — Observation rendering polish in My Feedback and Player Development

> Originally numbered 6d before the workflow correction was inserted as 6d-1 / 6d-2. Same scope, deferred until after the unified authoring workspace AND the tactical-board tool parity work land so polish targets the corrected creation flow.

#### Goal

Polish how observation notes and tactical boards appear to **players / families** and in **player development profiles** after the authoring workflow has been corrected.

#### Scope

- Show observation notes in My Feedback > Notes with clear context labels:
  - "Practice observation"
  - "Tactical note"
  - "Coach observation"
- Read-only tactical board display polish (sizing, mobile layout, light/dark theme parity for any new states).
- Player Development Profile integration polish (already present from Phase 5 + Phase 6c; this is a follow-up polish pass against the corrected authoring workflow).
- Tactical board sketches continue to follow the parent note's visibility rules.
- No major My Feedback redesign — that remains separate from the [#82 look-and-feel redesign](https://github.com/humac/replay/issues/82) planning.
- No changes to creation workflow; creation belongs to Coach Review after 6d.

### Privacy rules

- Existing note visibility rules still apply.
- `coach_private_note` never appears to viewers in either context.
- Private observation notes are hidden from viewers.
- Player observation notes are visible only to linked player/family accounts.
- Team observation notes are visible to signed-in viewers according to existing note behavior.
- `tactical_board_json` follows the same visibility rules as the parent note.

### Product boundaries

- Observation notes do not replace video notes.
- Clips remain video-only — tactical board sketches are attached to observation notes, not clips.
- Goals are intentionally placed after observations so a goal can be created from either video feedback or a practice/tactical observation.

### Acceptance criteria

- Coach can create an observation note without selecting a match.
- Coach can attach a tactical board sketch to an observation note.
- My Feedback renders observation notes with a clear context label.
- Player Development Profiles surface observation notes alongside video notes.
- All visibility rules (team / player / private / `coach_private_note`) match existing note behavior.

### Recommended implementation order

Implement the subphases in order; each one is a self-contained ship-target:

- **6a** ✅ — backend model + API support for observation notes, no board UI yet.
- **6b** ✅ — Coach observation composer, text-only observation notes (no tactical board yet).
- **6c** ✅ — tactical board editor and read-only viewer.
- **6d-1** ✅ — Unified Coach Review source modes and creation routing (creation moved to Coach Review for video notes, video clips, and tactical-board observations; Coach > Notes / Clips / Playlists / Roster became management surfaces).
- **6d-2** ✅ — Tactical board authoring improvements and formations (drag-to-draw arrows, freehand, resizeable zone box; 7v7 / 9v9 / 11v11 game-format selector + per-format formation presets; persists `game_format` + `formation` in `tactical_board_json` metadata).
- **6e** ✅ — Unified viewer review modal for My Feedback / Player Development (one focused-feedback modal for video notes, observation notes, tactical-board observations, and clips; compact cards route into that modal).

Phase 6a through 6e have shipped (see ROADMAP.md for completion entries). The 6d-1 / 6d-2 prompts below are retained as historical implementation references, not current handoff prompts. **Phase 7 is now the active next implementation target.**

### Phase 6d-1 coding agent prompt — Unified Coach Review source modes and creation routing

> **Status: COMPLETE / historical reference.** Do not hand this off as new work; the current next target is Phase 7.

```text
- Start from latest main.
- This PR is only 6d-1. Do not bundle 6d-2 or 6e work.
- Goal: make Coach Review the single creation workspace for video notes, video clips, and tactical-board observations.
- Add a Coach Review source/mode toggle:
  - Video
  - Tactical Board
- Video mode:
  - Keep the existing match / video selection workflow.
  - Keep the existing video telestration tools.
  - Keep Save Note (existing flow).
  - Keep Save Clip (existing flow).
  - Receives the routed New Note and New Clip actions from Coach > Notes / Clips.
- Tactical Board mode:
  - Load the existing Phase 6c tactical board surface (the SVG soccer pitch + the Phase 6c board tools).
  - Reuse the existing Phase 6c board tools mostly as-is. Do not redesign arrow / line / zone interactions, do not add freehand, do not add resizeable zones.
  - Support Save Observation.
  - Save via the existing POST /api/coach/notes with note_context="observation".
  - Include the current board state as tactical_board_json on the request body.
  - If launched from Coach > Roster, preselect that player in the observation form and default visibility to "player".
- Creation routing (replace today's modal openers with navigation into Coach Review):
  - Coach > Notes > New note → Coach Review, Video mode.
  - Coach > Notes > New observation → Coach Review, Tactical Board mode.
  - Coach > Clips > New clip → Coach Review, Video mode.
  - Coach > Roster > Add observation → Coach Review, Tactical Board mode, with the player preselected.
- Keep edit modals for existing objects (Notes / Clips / Playlists / observation notes). Only creation moves.
- Coach > Notes / Clips / Playlists / Roster remain management surfaces (view / edit / delete / route to Review).
- Out of scope for this PR (do not implement here):
  - No tactical board tool parity work (drag-to-draw arrows, freehand, resizeable zones). Those are 6d-2.
  - No formation layer / presets. That is 6d-2.
  - No 7v7 / 9v9 / 11v11 game-format selector. That is 6d-2.
  - No My Feedback redesign. That is 6e.
  - No Player Development redesign. That is 6e.
  - No goals / action plans (that is Phase 7).
  - No AI / CV. No drill library. No animation. No PDF export. No kit-color theming. No full roster assignment.
- No new public endpoints.
- No schema migration.
- Privacy rules unchanged. tactical_board_json continues to follow its parent note's visibility via the existing _filter_notes_for_user chain. coach_private_note remains coach/admin-only.
- Tests should cover: each rerouted entry point lands in the correct Coach Review mode; Tactical Board mode correctly seeds player preselection from Roster; edit modals still work for existing objects; no regression to My Feedback / Player Development surfaces; no regression to Phase 6c board persistence or read-only viewer rendering.
- Browser QA (Playwright): walk through each rerouted entry point + a coach + linked-viewer smoke against the seeded dev users.
```

### Phase 6d-2 coding agent prompt — Tactical board authoring improvements and formations

> **Status: COMPLETE / historical reference.** Do not hand this off as new work; the current next target is Phase 7.

```text
- Do not start until 6d-1 is merged. Start from latest main with the 6d-1 routing model already in place.
- Goal: improve the tactical board authoring tools inside Coach Review's Tactical Board mode, and ship game-format-specific formation presets.
- Add tool-parity improvements (these replace / augment the Phase 6c basics — keep 6d-1 routing untouched):
  - drag-to-draw arrows (replace the two-click drop-then-set-endpoint affordance with a single drag from start to end)
  - improved general line / arrow behavior (snap to angle, length readout, etc., as practical)
  - freehand drawing (continuous-stroke pencil tool, persisted as a `freehand` shape kind in tactical_board_json)
  - resizeable zone box (resize handles on the existing `zone` shape after placement, in addition to the existing two-click corner placement)
  - formation layer / presets (see below)
  - game-format selector: 7v7, 9v9, 11v11
- Formation presets (place player tokens in normalized pitch-space positions; presets shown depend on the selected game format):
  - 7v7: 2-3-1, 3-2-1, 2-1-2-1
  - 9v9: 3-2-3, 3-3-2, 2-3-3, 4-3-1
  - 11v11: 4-3-3, 4-2-3-1, 4-4-2, 3-5-2, custom
- When practical, persist the selection inside tactical_board_json as metadata so the editor can re-hydrate it on edit:
  - game_format: "7v7" | "9v9" | "11v11"
  - formation: e.g. "2-3-1"
- Backwards-compat: 6c / 6d-1-era boards (no new shape kinds, no game_format / formation metadata) must still load and render correctly. The board schema may add new optional shape kinds (e.g. `freehand`) and optional metadata keys, but must not change the meaning of existing fields.
- Do not change the 6d-1 routing model.
- Out of scope (do not implement here):
  - No drill library.
  - No animation / multi-frame.
  - No PDF export.
  - No kit-color theming.
  - No full roster-assignment system (per-token player_id binding beyond the existing optional `player_id` field that already lives on player tokens since 6c).
  - No AI / CV.
  - No goals / action plans (Phase 7).
  - No My Feedback / Player Development polish (6e).
- No new public endpoints. No schema migration; the new metadata persists inside the existing tactical_board_json TEXT JSON column.
- Privacy rules unchanged.
```

### Phase 6e — Unified Viewer Review Modal ✅ COMPLETE (2026-05-08)

> **Scope correction**: Phase 6e was originally framed as "observation rendering polish" then reframed to "viewer detail experience" with separate per-kind detail modals. The final design is **one unified review modal**: the existing focused-feedback player IS the single review surface for video notes, observation notes, tactical-board observations, and clips. Cards stay compact (no inline detail) so the reading experience is consistent across all four review types.

**Shipped**:
- `_renderUnifiedFeedbackBody(target, { kind, note?, clip? })` in `js/coaching.js` — the single body composer that fills the focused-feedback player's `[data-field="body"]` slot with a shared structured layout (context pill + tone + category + linked players + Summary + What happened / Why / Next + Additional detail + tags) for every review type.
- `index.html` `feedback-player-template` gained a `[data-field="board-wrapper"]` sibling to the video wrapper. `openFeedbackPlayer`'s `onMount` shows `<video>` for video notes / clips, or the read-only tactical board for observations, and hides the other.
- Cards on My Feedback Notes / Clips are compact (thumb + tone + title + meta only). The previous inline summary, inline tactical board, and per-card "Watch" / "Mark reviewed" / "View details" buttons were removed. The card body opens the unified modal on click / Enter / Space.
- Player Development viewer-side rows route into the SAME modal via `openFeedbackNoteDetailFromDev` / `openFeedbackClipDetailFromDev`; the per-player `_feedbackDevCache` (cleared on `setLoggedOut()`) lets the click hydrate when the dev row's note isn't in `_feedbackData.notes[]`. The "View details" mini-action on the dev clip row was removed; the Watch button alone now opens the unified modal.
- Modal title reflects kind: "Coaching Note" for video notes, an observation-context label ("Practice observation" / "Tactical observation" / etc.) for observations, "Coaching Clip" for clips, "Review Session" for playlists.
- The previous Phase 6e detail-modal path (`_renderFeedbackNoteDetailModal` / `_renderFeedbackClipDetailModal`) was removed; their helpers (`_resolveLinkedPlayerChips`, `_detailStructuredHtml`, `_categoryLabel`, `_observationContextLabel`) are now consumed by the unified body composer.

**Privacy invariant** (unchanged): no new endpoints, no schema migration, no client-side authorization. `_renderUnifiedFeedbackBody` NEVER references `coach_private_note` regardless of payload; the server scrubs it via `_strip_private_fields`. `tactical_board_json` follows the parent note's visibility via `_filter_notes_for_user`.

**Tests**: zero new backend tests (no API change). Existing `pytest tests/` 414/414 unchanged. The Playwright capture spec `tests/e2e/phase-6e-capture.spec.js` (run via `npm run capture-phase-6e`) exercises the unified-modal flow for video / observation / tactical-board / clip + a `coach_private_note` privacy assertion at both the API and DOM layer.

**Future surfaces**: route into `openFeedbackPlayer({ mode, note? clip? })` — do NOT build a parallel detail-modal path. Keeping one composer is part of the privacy story (one place where `coach_private_note` is policed).

**Phase 7 (Goals / Action Plans) is next.**

---

## Phase 7: Action items and next-match goals

### Goal

Turn feedback into practical next steps.

### Features

1. Coach can create an action item from a note, clip, playlist, or player profile.
2. Action item fields:
   - player_id
   - title
   - description
   - source_note_id optional
   - source_clip_id optional
   - source_playlist_id / source_playlist_item_note_id optional
   - target_match_id optional
   - visibility: player, coach (default player)
   - priority: low, medium, high (default medium)
   - target_date: empty or YYYY-MM-DD
   - success_criteria
   - coach_private_note (coach/admin only; scrubbed from viewer payloads)
   - status: open, in_progress, needs_follow_up, achieved, archived
   - due/context: next match, next training, season goal
3. My Feedback shows current goals.
4. Coach can mark achieved or needs follow-up.
5. Player/family can add reflection.

### Acceptance criteria

- Every player can have active goals.
- Goals are visible in Coach and My Feedback.
- Goals can be linked to video evidence.
- Status changes are tracked.

### Suggested PR split

Keep Phase 7 small enough to validate in the existing test suite and browser QA flow:

1. **PR 11a — Goals backend**
   - Add `player_goals` persistence, source references, Pydantic models, and coach/admin + viewer-scoped endpoints.
   - Cover role access, source-link validation, status transitions, and viewer privacy in tests.
2. **PR 11b — Coach goal UI**
   - Add goal creation from player profile, note, clip, playlist item, and observation contexts.
   - Add coach-side active/archived goal lists and status controls.
3. **PR 11c — My Feedback goals + reflections**
   - Show active goals to linked players/families.
   - Allow player/family reflection and surface reflections needing coach follow-up.

### Coding agent prompt

```text
Implement Phase 7 in small PRs. Start with player action items and next-match goals. Add a data model for player_goals with source note/clip/playlist references, status, title, description, and context such as next match, next training, or season goal. Add Coach UI to create a goal from a note, clip, playlist item, observation note, or player profile. Add My Feedback display for active goals and allow player/family reflection. Add coach controls to mark goals achieved, needs follow-up, or archived. Keep privacy rules aligned with player-user links and source visibility. Add tests for role access, source-link validation, privacy, and status transitions.
```

---

## Phase 8: Match-level coaching summary

### Goal

Help coaches summarize the match for a team or player group.

### Features

A match summary should include:

- team positives
- team improvement areas
- top teachable moments
- player-specific highlights
- suggested training focus
- assigned playlists/clips

Manual first. AI-assisted later.

### Backend design

New table:

- `coaching_match_summaries`

Fields:

- `match_id`
- `visibility`
- `team_positives`
- `team_improvements`
- `training_focus`
- `body`
- `created_by`
- timestamps

Optional relationships:

- summary notes
- summary playlists
- summary clips

### Acceptance criteria

- Coach can create/edit a match summary.
- Summary can include linked notes/clips/playlists.
- Team-visible summaries appear in My Feedback.
- Private summaries remain coach/admin only.

### Coding agent prompt

```text
Add match-level coaching summaries. Create a backend model and endpoints for summaries linked to match_id with visibility controls. The summary should support team positives, team improvement areas, training focus, freeform body, and linked notes/clips/playlists. Add Coach UI to create and edit summaries from the match review context. Add My Feedback rendering for visible summaries. Keep private summaries restricted to coach/admin. Add access control tests.
```

---

## Phase 9: Review completion and engagement dashboard

### Goal

Let coaches see whether feedback is actually being consumed.

### Features

Dashboard views:

- review completion by player
- review completion by playlist
- unreviewed assigned items
- reflections needing coach response
- players with no recent feedback
- most watched clips/playlists

Metrics:

- assigned count
- reviewed count
- reflection count
- latest review date
- completion percentage

### Acceptance criteria

- Coach can see who has reviewed assigned feedback.
- Coach can filter by player, playlist, match, and date range.
- Dashboard does not expose private data to viewers.

### Coding agent prompt

```text
Add a coaching engagement dashboard showing review completion by player, playlist, match, and date range. Use existing coaching_reviews data and extend it if needed. Surface unreviewed assigned items, latest review date, player reflections needing response, and players with no recent feedback. Add filters for player, match, playlist, and visibility. Keep this coach/admin-only. Add tests for aggregate accuracy and role access.
```

---

## Phase 10: Coaching analytics dashboards

### Goal

Show trends without overwhelming coaches.

### Features

Start with simple analytics:

1. Player trend:
   - notes by category over time
   - positive/correction ratio
   - top recurring themes
   - active goals

2. Team trend:
   - most common categories
   - match-by-match coaching themes
   - team positives vs corrections

3. Playlist analytics:
   - item count
   - review completion
   - average duration
   - players assigned

4. Coach workload:
   - notes created per match
   - clips created per match
   - playlists created per match

### Acceptance criteria

- Analytics are simple and actionable.
- Charts are optional; tables and compact cards are acceptable first.
- Coaches can click from analytics into underlying notes/clips.

### Coding agent prompt

```text
Add simple coaching analytics dashboards. Start with aggregate cards and tables rather than complex charts. Include player trends, team trends, positive/correction ratios, most common categories, active goals, playlist completion, and coach workload. Every aggregate should link back to the underlying notes, clips, playlists, or player profile. Keep analytics coach/admin-only and add tests for aggregation helpers where practical.
```

---

## Phase 11: AI-assisted coaching workflow

### Goal

Use AI to reduce coach admin work, not to replace coach judgment.

### AI features

1. Rewrite note for player:
   - convert rough coach note into age-appropriate feedback
   - preserve original coach note

2. Suggest tags and category:
   - based on note body/title

3. Generate player summary:
   - summarize last 3 to 5 matches for one player
   - strengths
   - focus areas
   - suggested next goal

4. Generate match summary draft:
   - based on selected notes/clips/playlists
   - coach edits before publishing

5. Playlist assistant:
   - coach selects player/category/time range
   - AI suggests a 5 to 8 item playlist
   - coach approves before saving

6. Reflection triage:
   - summarize player/family reflections needing coach response

### AI guardrails

- Always require coach approval before publishing AI-generated content.
- Clearly label drafts as AI-assisted until saved by coach.
- Do not send private video files unless explicitly configured.
- Prefer text-only AI using existing notes and metadata first.
- Keep all generated output editable.
- Never overwrite coach-authored notes automatically.

### Acceptance criteria

- AI features are optional.
- Coach must approve generated content.
- AI output can be edited before saving.
- System works without AI configured.

### Coding agent prompt

```text
Add optional AI-assisted coaching helpers using existing notes and metadata first. Implement text-only assistance before any video analysis. Add helpers to rewrite coach notes into age-appropriate player summaries, suggest tags/categories, draft player development summaries, draft match summaries, and suggest playlist items. All AI output must be draft-only until the coach approves and saves it. The system must work when AI is disabled or unavailable. Add configuration flags and clear UI states for AI unavailable, generating, draft ready, and saved.
```

---

## Phase 12: Computer-vision analysis foundation

### Goal

Add a detector-agnostic video-analysis foundation so Replay can store and inspect detections from Roboflow, a local model, soccer360, or another future provider.

Candidate provider:

- Roboflow Universe football player detection model: `https://universe.roboflow.com/roboflow-jvuqo/football-players-detection-3zvbc`

Important caveat:

- Treat Roboflow as a swappable candidate provider, not a permanent architectural dependency.
- Before enabling it, verify model license, API terms, current availability, inference cost, rate limits, export options, data retention, and performance on your actual match footage.
- Because footage may include minors, external frame upload should be opt-in and disabled by default.

### Features

1. Analysis job framework:
   - queue offline analysis for a match slot
   - status: queued, running, completed, failed, cancelled
   - provider: mock, roboflow, local_yolo, soccer360_import
   - model name/version
   - frame sample rate
   - errors and metadata

2. Detector-agnostic detections:
   - frame index
   - timestamp
   - class: player, ball, referee, goalkeeper, unknown
   - confidence
   - normalized bounding box coordinates
   - optional track ID

3. Track storage:
   - track ID
   - class
   - team label
   - optional roster player ID
   - start/end time
   - confidence

4. Coach/admin-only APIs:
   - create/list/read/cancel analysis jobs
   - query detections by match, slot, and time range
   - query tracks by match, slot, and time range

### Backend data model suggestions

Add tables:

- `video_analysis_jobs`
- `video_detections`
- `video_tracks`

### Acceptance criteria

- Replay can store detections from any provider.
- The app works with no provider configured.
- Mock provider exists for tests.
- Detection coordinates are normalized 0..1 for reliable overlay rendering.
- No analysis output is player-facing by default.

### Coding agent prompt

```text
Add a detector-agnostic video analysis foundation to Replay. Create video_analysis_jobs, video_detections, and video_tracks through a migration. Add Pydantic models and coach/admin-only endpoints to create/list/read/cancel analysis jobs and query detections/tracks by match, slot, and time range. Add a provider abstraction with a mock provider first. Do not integrate Roboflow yet. Store normalized coordinates. Do not expose analysis output to My Feedback.
```

---

## Phase 13: Offline player detection job runner

### Goal

Run offline player detection against uploaded match video and store detections for coach review.

### Why offline first

Offline detection is safer, cheaper, easier to validate, and does not risk live playback. Live overlays should come much later.

### Features

1. Coach/admin clicks Analyze Match.
2. Backend samples frames from a ready video slot.
3. Worker runs detection through configured provider.
4. Worker stores normalized detections.
5. Job status is visible in Coach/Admin UI.

### Sampling strategy

Start conservative:

- 1 frame per second by default
- configurable sample rate
- configurable max frames per job
- no full-frame every-frame processing in MVP

Suggested environment variables:

```text
REPLAY_ANALYSIS_PROVIDER=mock|roboflow|local_yolo|soccer360_import
REPLAY_ANALYSIS_FRAME_SAMPLE_RATE=1
REPLAY_ANALYSIS_MAX_FRAMES_PER_JOB=600
ROBOFLOW_API_KEY=
ROBOFLOW_MODEL_ID=football-players-detection-3zvbc
ROBOFLOW_MODEL_VERSION=
ROBOFLOW_CONFIDENCE_THRESHOLD=0.35
```

### Roboflow integration rule

Only add the real Roboflow provider after the mock provider and job framework are tested.

### Acceptance criteria

- A ready match slot can be analyzed offline.
- Jobs run asynchronously.
- Detection failures do not break match playback.
- Mock provider is used in tests.
- Roboflow is optional and disabled if credentials are missing.

### Coding agent prompt

```text
Implement the offline video analysis job runner. Sample frames from a ready match slot, run detection through the provider abstraction, normalize boxes, and store detections. Start with 1 fps and a configurable max-frame limit. Use the mock provider in tests. Add robust job status and error handling. Then add an optional Roboflow provider using environment variables for API key, model ID, version, confidence threshold, sample rate, and max frames. Replay must work when Roboflow is not configured.
```

---

## Phase 14: Coach Review detection overlay and detected moments queue

### Goal

Let coaches inspect detections visually and convert useful moments into coaching notes or clips.

### Features

1. Coach Review overlay toggle:
   - Off
   - Players
   - Tracks
   - Teams
   - Confidence

2. Separate analysis overlay layer:
   - do not store detection boxes in coaching drawing JSON
   - keep coach-authored drawings separate from model output

3. Overlay rendering:
   - bounding boxes
   - confidence
   - track ID
   - team label where available

4. Detected moments queue:
   - generated from conservative heuristics
   - coach can jump to timestamp
   - coach can accept, reject, convert to note, or convert to clip

### Data model suggestion

Add table:

- `detected_moments`

Fields:

- `job_id`
- `match_id`
- `slot`
- `timestamp_seconds`
- `moment_type`
- `title`
- `confidence`
- `source`
- `metadata_json`
- `review_status`: new, accepted, rejected, converted_to_note, converted_to_clip

### Acceptance criteria

- Detection overlays stay aligned with the video during resize and focus mode.
- Detected moments are suggestions only.
- Coach must convert/accept suggestions before they become notes, clips, or player-facing feedback.
- False positives can be rejected.

### Coding agent prompt

```text
Add Coach Review analysis overlays and a detected moments queue. Render stored detections/tracks over the coach review video in a separate overlay layer, not in the coach drawing payload. Add overlay modes for players, tracks, teams, and confidence where data exists. Create detected_moments and a coach-only review queue with actions to jump to timestamp, accept, reject, convert to note, and convert to clip. Do not publish detected moments to players automatically.
```

---

## Phase 15: Tracking, tactical snapshots, and semi-automatic player identification

### Goal

Turn raw detections into more useful tactical and player-specific coaching views.

### Features

1. Tracking and smoothing:
   - assign track IDs
   - bridge short detection gaps
   - smooth bounding boxes
   - store track confidence

2. Tactical shape snapshots:
   - show player positions at a timestamp
   - convex hull / formation polygon
   - average positions over a short window
   - convert snapshot to coaching note drawing if coach chooses

3. Team labels:
   - unknown, home, away, goalkeeper_home, goalkeeper_away, referee
   - start with manual or semi-automatic labels
   - kit-color clustering can come later

4. Track-to-player assignment:
   - representative player crops
   - coach assigns track to roster player or jersey number
   - assignment applies to match/slot/job unless explicitly reused elsewhere

### Acceptance criteria

- Track IDs are stable enough for coach review.
- Coach can view tactical shape snapshots.
- Coach can assign tracks to roster players.
- Bad tracks do not pollute My Feedback automatically.

### Coding agent prompt

```text
Add tracking and tactical analysis on top of stored detections. Implement a simple tracking stage that assigns track IDs, smooths boxes, and bridges short gaps. Add tactical shape snapshots showing player positions and convex hulls at a selected timestamp or short time window. Add manual track-to-player assignment using representative crops. Keep all outputs coach/admin-only until explicitly converted to notes or clips.
```

---

## Phase 16: Heatmaps and player performance metrics

### Goal

Summarize activity zones and player involvement without overstating accuracy.

### Important limitation

Video-frame coordinates are not field coordinates. True distance covered, sprint speed, and field-zone heatmaps require field calibration/homography, stable identity tracking, and confidence scoring.

### Metric maturity levels

Level 1: Safe without field calibration

- visible analyzed time
- track appearances
- average screen position
- involvement in accepted clips
- notes/clips by category
- review completion

Level 2: Approximate with field calibration

- zone occupancy
- left/central/right tendency
- team shape width/depth estimates
- movement density

Level 3: Physical KPIs with strong confidence warnings

- estimated total distance covered
- estimated top speed
- sprint count
- high-intensity movement count

### Heatmap approach

1. Start with video-frame heatmaps.
2. Clearly label them as frame-space if no calibration exists.
3. Add field calibration later:
   - coach identifies field corners/lines
   - estimate homography
   - map player bottom-center points to field coordinates

### Acceptance criteria

- MVP does not present frame-space analysis as true physical performance.
- Metrics include confidence labels.
- Field-based metrics require calibration.
- Player-facing metrics are curated by coach.

### Coding agent prompt

```text
Add heatmaps and player metrics in conservative maturity levels. Start with safe non-field-calibrated metrics: visible analyzed time, track appearances, average screen position, involvement in accepted clips, notes/clips by category, and review completion. Add video-frame heatmaps clearly labeled as frame-space. Do not calculate or display distance covered, sprint speed, or field-zone heatmaps as physical truth unless field calibration and identity tracking confidence are available.
```

---

## Phase 17: Broadcast-style stat-tags and live analysis

### Goal

Eventually support broadcast enhancements such as player highlighting, following stat-tags, and near-live overlays.

### Features

Offline replay overlays first:

- highlight selected player
- stat-tag follows assigned track
- roster name or jersey number label
- team shape overlay
- possession-like sequence only if ball/team tracking exists

Live or near-live later:

- sample live feed frames asynchronously
- run detection with clear delay/confidence indicators
- show coach/admin-only delayed overlays first
- public live overlays only after reliability is proven

### Guardrails

- Live stream playback must never depend on analysis.
- Analysis failure must not impact viewing.
- Experimental overlays are off by default.
- Coach/admin previews come before public broadcast features.

### Acceptance criteria

- Offline stat-tags work from stored tracks.
- Overlays are optional and off by default.
- Live analysis is asynchronous and kill-switchable.
- Public viewers do not see experimental overlays unless explicitly enabled.

### Coding agent prompt

```text
Add optional broadcast-style overlays in stages. Start offline only: let a coach select an assigned track/player and show a following highlight/stat-tag during replay. Keep overlays off by default and coach/admin-only. Design near-live analysis as an optional asynchronous service that samples live frames and never blocks playback. Include a kill switch and clear latency/confidence indicators. Do not implement public live overlays until offline tracking is reliable.
```

---

# Best implementation order

Recommended order:

1. Phase 1: Coaching note structure and feedback quality
2. Phase 2: Coach review templates
3. Phase 3: Per-note thumbnails
4. Phase 4: First-class clip builder
5. Phase 5: Player development profiles
6. Phase 6: Coach observations and tactical board
7. Phase 7: Action items and next-match goals
8. Phase 8: Match-level coaching summary
9. Phase 9: Review completion and engagement dashboard
10. Phase 10: Coaching analytics dashboards
11. Phase 11: AI-assisted coaching workflow
12. Phase 12: Computer-vision analysis foundation
13. Phase 13: Offline player detection job runner
14. Phase 14: Coach Review detection overlay and detected moments queue
15. Phase 15: Tracking, tactical snapshots, and semi-automatic player identification
16. Phase 16: Heatmaps and player performance metrics
17. Phase 17: Broadcast-style stat-tags and live analysis

Reasoning:

- Notes are the atomic unit. Improve note structure first.
- Templates make better notes easier.
- Thumbnails and clips make review more usable.
- Player profiles aggregate the video-based feedback loop.
- Coach observations and the tactical board extend feedback to non-video contexts (practice, sideline, tactical, meetings) so the development picture is not limited to footage.
- Goals come after observations so action items can be created from either video feedback or practice/tactical observations.
- Summaries and dashboards build on accumulated structured data.
- Text-based AI should come after the workflow and data model are stable.
- Computer vision should come after the manual coaching loop because detections need a strong human review path.
- Physical KPIs and live/broadcast overlays should come last because they require reliable tracking, calibration, and confidence handling.

---

# Suggested PR breakdown

## PR 1: Structured notes ✅ COMPLETE

Includes:

- Phase 1
- migrations
- Pydantic validation
- Coach UI changes
- My Feedback rendering updates
- tests

## PR 2: Templates and note thumbnails ✅ COMPLETE

Includes:

- Phase 2
- Phase 3
- static template registry
- thumbnail generation and serving
- access control tests

## PR 3: Clip builder MVP ✅ COMPLETE

Includes:

- Phase 4
- clip data model
- coach clip creation
- My Feedback clip playback
- tests

## PR 4: Player development profiles ✅ COMPLETE

Includes:

- Phase 5
- coach and viewer profile endpoints
- profile UI in Coach and My Feedback
- privacy filtering for `coach_private_note`
- tests

Phase 6 ships across **six** PRs, one per subphase, in 6a → 6b → 6c → 6d-1 → 6d-2 → 6e order. Do not bundle them. (The original plan was four PRs ending at "observation notes in My Feedback and Development Profiles"; UX testing of 6a/6b/6c surfaced a creation-flow correction that became Phase 6d, and 6d itself was then split into 6d-1 [routing] and 6d-2 [tactical-board tool parity + formations] because the combined work was too large for one PR.)

## PR 5: Observation note backend ✅ COMPLETE

Includes:

- Phase 6a
- `note_context` schema extension and validation
- nullable `match_id` / `slot` / `timestamp_seconds` for observation notes
- `event_title` / `event_date` / `event_type` / `tactical_board_json` fields
- existing note visibility/privacy behavior
- `coach_private_note` remains coach/admin-only
- no UI
- tests

## PR 6: Coach observation composer ✅ COMPLETE

Includes:

- Phase 6b
- text-only observation note creation
- Coach > Roster "Add observation" entry point
- Coach > Notes "New observation" entry point
- structured note fields reused
- event title / date / type fields
- no tactical board yet
- tests / Playwright screenshots where applicable

## PR 7: Tactical board MVP ✅ COMPLETE

Includes:

- Phase 6c
- soccer pitch renderer
- `pitch_kind` discriminator
- normalized pitch-space coordinates
- draggable player tokens
- ball token
- arrows / lines / zones
- text labels
- save / load `tactical_board_json`
- read-only viewer rendering
- no drill libraries, animations, PDF export, or AI tactical analysis
- tests / Playwright screenshots where applicable

## PR 8: Unified Coach Review source modes and creation routing ✅ COMPLETE

Includes:

- Phase 6d-1
- Coach Review source/mode toggle (Video / Tactical Board)
- New Note / New Clip from Coach > Notes / Clips reroute to Coach Review (Video mode)
- New Observation from Coach > Notes + Add Observation from Coach > Roster reroute to Coach Review (Tactical Board mode), preselecting the player when launched from Roster
- Tactical Board mode loads the Phase 6c renderer + structured `tactical_board_json` scene
- Reuses existing Phase 6c board tools mostly as-is (player token, ball token, two-click arrow / line / zone, label-text input, drag-to-move, delete / clear)
- Coach > Notes / Clips / Playlists / Roster become management surfaces (view / edit / delete / route to Review). Edit modals stay where appropriate.
- **No formation selector** — that is PR 9 (Phase 6d-2)
- **No tactical-board tool parity work** (drag-to-draw arrows, freehand, resizeable zone) — that is PR 9 (Phase 6d-2)
- No My Feedback / Player Development polish — that is PR 10 (Phase 6e)
- No new endpoints; reuses Phase 6a backend + Phase 6c board schema + existing note / clip save APIs
- No goals / AI / drill library / animation / PDF export / kit-color theming / full roster assignment
- Privacy rules unchanged
- tests / Playwright screenshots where applicable

## PR 9: Tactical board authoring improvements and formations ✅ COMPLETE

Includes:

- Phase 6d-2
- Tactical board tool parity inside Coach Review's Tactical Board mode:
  - drag-to-draw arrows (replaces the two-click drop-then-set-endpoint affordance)
  - freehand drawing (new `freehand` shape kind in `tactical_board_json`)
  - resizeable zone box (resize handles on the existing `zone` shape)
  - improved general line / arrow behavior
- Game-format selector (7v7 / 9v9 / 11v11) gates which formation presets show
- Formation presets place player tokens in normalized pitch-space positions:
  - 7v7: 2-3-1, 3-2-1, 2-1-2-1
  - 9v9: 3-2-3, 3-3-2, 2-3-3, 4-3-1
  - 11v11: 4-3-3, 4-2-3-1, 4-4-2, 3-5-2, custom
- Persist `game_format` + `formation` in `tactical_board_json` metadata when practical
- Backwards-compatible: 6c / 6d-1-era boards still load and render
- Board schema may add new shape kinds (e.g. `freehand`) and optional metadata keys but must not change the meaning of existing fields
- No new endpoints, no schema migration (new metadata persists inside the existing `tactical_board_json` TEXT JSON column)
- No full roster assignment, no kit-color theming, no animation, no drill library, no PDF export, no AI / CV
- Privacy rules unchanged
- tests / Playwright screenshots where applicable

## PR 10: Unified viewer review modal for My Feedback and Development Profiles ✅ COMPLETE

Includes:

- Phase 6e
- compact My Feedback Notes / Clips cards that open the focused-feedback modal
- one unified review surface for video notes, observation notes, tactical-board observations, and clips
- read-only tactical board display inside the modal for observation notes
- Player Development Profile recent notes/clips routing into the same modal
- clear modal titles and context labels for video notes, observations, tactical observations, clips, and playlists
- tactical board sketches follow parent note visibility rules
- `coach_private_note` stays absent from the API payload and DOM for viewer surfaces
- privacy tests / Playwright browser QA
- No major My Feedback redesign (separate from issue #82 look-and-feel planning)
- No changes to creation workflow

## PR 11: Goals / action plans

Includes:

- Phase 7
- PR 11a: player goals data model, source references, endpoints, access-control tests
- PR 11b: Coach UI to create goals from notes, clips, playlist items, observation notes, or player profile
- PR 11c: My Feedback display for active goals, player/family reflections, and coach follow-up surfaces
- coach controls for achieved / needs follow-up / archived
- tests

## PR 12: Match summaries and engagement dashboard

Includes:

- Phase 8
- Phase 9
- match summary model/UI
- review completion dashboard
- tests

## PR 13: Analytics dashboard

Includes:

- Phase 10
- aggregate helpers
- simple tables/cards
- drill-down links
- tests where practical

## PR 14: Optional text AI assistance

Includes:

- Phase 11
- AI configuration
- note rewrite draft
- tag/category suggestions
- player and match summary drafts
- playlist suggestions
- no-auto-publish guardrails

## PR 15: Computer-vision analysis foundation

Includes:

- Phase 12
- detector-agnostic job/detection/track schema
- provider abstraction
- mock provider
- coach/admin-only APIs

## PR 16: Offline detection provider and job runner

Includes:

- Phase 13
- offline frame sampling
- optional Roboflow provider
- job status UI
- tests with mock provider

## PR 17: Detection overlays and detected moments

Includes:

- Phase 14
- Coach Review analysis overlay
- detected moments queue
- convert to note/clip actions

## PR 18: Tracking, tactical snapshots, player identification

Includes:

- Phase 15
- tracking/smoothing
- shape snapshots
- manual track-to-player assignment

## PR 19: Heatmaps, metrics, and broadcast overlays

Includes:

- Phase 16
- Phase 17, offline portions first
- conservative metric labels
- optional stat-tags
- no live dependency on analysis

---

# Agent skills and tools needed

## Backend

- FastAPI route design.
- Pydantic request/response models.
- SQLite schema migrations.
- Role-based access control.
- Data aggregation queries.
- Background job orchestration.
- Detector/provider abstraction design.
- ffmpeg frame extraction and thumbnail extraction.
- Secure static/media serving with authorization checks.
- Test-driven backend changes with pytest.

## Frontend

- Vanilla JavaScript modules and mixins.
- Existing `app` mixin architecture.
- DOM rendering without a build step.
- Coach Review UI state management.
- My Feedback rendering.
- Video playback control.
- Drawing overlay compatibility.
- Separate analysis overlay rendering.
- Accessibility and keyboard-friendly controls.

## Product/UX

- Youth soccer coaching workflows.
- Player-friendly feedback writing.
- Coach-admin workflow design.
- Privacy-aware family/player access.
- Analytics that remain actionable instead of noisy.
- Human-in-the-loop AI/video-analysis review.

## Media

- ffmpeg still extraction.
- ffmpeg frame sampling.
- HLS/MP4 playback behavior.
- Clip range playback.
- Optional MP4 clip export later.

## AI

- Prompting for short player-friendly feedback.
- Draft generation with human approval.
- Tag/category classification.
- Summary generation from structured notes.
- Safe fallback when AI is unavailable.

## Computer vision

- Provider abstraction.
- Roboflow or local detector integration.
- Bounding box normalization.
- Detection confidence handling.
- Tracking and smoothing.
- Human-in-the-loop detected moment review.
- Optional soccer360 integration.
- Field calibration and homography concepts for later physical metrics.

---

# Guardrails

Do not do these without a dedicated design decision:

- Do not publish AI-generated feedback without coach approval.
- Do not expose private coach notes to player/family accounts.
- Do not auto-publish computer-vision-detected moments.
- Do not send youth footage to external providers unless explicitly configured and documented.
- Do not make Roboflow or any external provider required for Replay to run.
- Do not present video-frame heatmaps as true field-position heatmaps.
- Do not present distance covered, sprint speed, or possession tracking as accurate without calibration and confidence scoring.
- Do not break existing note visibility rules.
- Do not remove existing category/tag support.
- Do not change drawing schema casually.
- Do not require a frontend build step.
- Do not make the system useless when AI is disabled.
- Do not make players watch full-match pages for assigned feedback if a focused modal/player exists.

---

# Manual QA checklist for every feature PR

- Admin can still create/edit/delete matches.
- Upload and transcoding still work.
- Public replay playback still works.
- Coach can create roster players.
- Coach can link family/player users.
- Coach can create notes.
- Coach can save drawings.
- Coach can build playlists.
- My Feedback only shows allowed content.
- Private content does not leak to viewers.
- Review tracking still works.
- Analysis outputs are coach/admin-only unless explicitly published.
- Replay works with AI/video analysis disabled.
- Existing tests pass.

---

# Future north-star workflow

The eventual coach workflow should be:

1. Upload or live stream match.
2. Open Coach Review.
3. Watch match with compact telestration tools.
4. Use templates to create structured notes quickly.
5. Generate thumbnails and clips automatically from notes.
6. Build player/team playlists.
7. Assign feedback and goals.
8. Players/families review short focused clips.
9. Coach tracks completion and reflections.
10. Player profile shows growth over time.
11. AI drafts summaries and suggestions, coach approves.
12. Offline video analysis suggests detections, tracks, tactical snapshots, and candidate moments.
13. Coach accepts/rejects detected moments and converts the useful ones into notes or clips.
14. Player/team heatmaps and metrics are shown with confidence and calibration context.
15. Broadcast-style stat-tags and live overlays are enabled only after offline analysis is reliable.

That is the path from replay archive to real player-development platform.
