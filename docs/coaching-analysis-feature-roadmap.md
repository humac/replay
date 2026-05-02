# Coaching Analysis Feature Roadmap

This roadmap covers the product features needed to evolve Replay from a strong match replay and annotation tool into a practical player-development coaching platform.

This is separate from `docs/coach-review-ui-ux-implementation-plan.md`, which focuses on Coach Review layout, compact controls, telestration workspace design, keyboard shortcuts, and responsive UI polish.

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

---

# Recommended feature rollout

## Phase 1: Coaching note structure and feedback quality

### Goal

Make individual notes more useful, consistent, and player-friendly.

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

## Phase 2: Coach review templates

### Goal

Reduce coach typing and make note quality more consistent.

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

## Phase 3: Per-note thumbnails and clip scanability

### Goal

Make notes and playlists visually scannable.

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

## Phase 4: First-class clip builder

### Goal

Let coaches create actual shareable clip moments, not only timestamped notes.

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

## Phase 5: Player development profiles

### Goal

Give coaches and families a player-centered view of development over time.

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
- current goals
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
- current goals
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
Add player development profiles. Build a coach-facing player profile that aggregates assigned notes, playlists, clips, review status, reflections, top categories, recent positives, recent corrections, and current goals. Add a player/family-safe version under My Feedback scoped to linked accounts. Preserve privacy: private coach notes and internal coach_private_note fields must not leak to viewers. Add endpoints for coach and viewer profile data, then add UI entry points from roster, notes, playlists, and feedback items.
```

---

## Phase 6: Action items and next-match goals

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
   - target_match_id optional
   - status: open, in_progress, achieved, archived
   - due/context: next match, next training, season goal
3. My Feedback shows current goals.
4. Coach can mark achieved or needs follow-up.
5. Player/family can add reflection.

### Acceptance criteria

- Every player can have active goals.
- Goals are visible in Coach and My Feedback.
- Goals can be linked to video evidence.
- Status changes are tracked.

### Coding agent prompt

```text
Implement player action items and next-match goals. Add a data model for player_goals with source note/clip references, status, title, description, and context such as next match or next training. Add Coach UI to create a goal from a note, clip, playlist item, or player profile. Add My Feedback display for active goals and allow player/family reflection. Add coach controls to mark goals achieved, needs follow-up, or archived. Add tests for role access and privacy.
```

---

## Phase 7: Match-level coaching summary

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

## Phase 8: Review completion and engagement dashboard

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

## Phase 9: Coaching analytics dashboards

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

## Phase 10: AI-assisted coaching workflow

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

## Phase 11: Computer-vision-assisted clip discovery

### Goal

Use automated detection to help coaches find candidate moments faster.

This should come after the manual coaching workflow is solid.

### Possible sources

- Existing match video.
- Future integration with soccer360 pipeline.
- Object/action detection outputs.
- Manually uploaded event files.

### Candidate moments

- goals
- shots
- corners
- throw-ins
- goalkeeper possession
- long breaks in play
- pressing sequences
- transitions
- repeated possession losses
- set pieces

### Data model

New table:

- `detected_moments`

Fields:

- `match_id`
- `slot`
- `timestamp_seconds`
- `moment_type`
- `confidence`
- `source`
- `metadata_json`
- `review_status`: new, accepted, rejected, converted_to_note, converted_to_clip

### Acceptance criteria

- Detected moments are suggestions only.
- Coach can accept, reject, convert to note, or convert to clip.
- False positives do not pollute player-facing feedback.
- Integration is optional.

### Coding agent prompt

```text
Add a detected moments framework for future computer-vision-assisted clip discovery. Create a detected_moments model with match_id, slot, timestamp_seconds, moment_type, confidence, source, metadata_json, and review_status. Add coach-only UI to review suggestions and accept, reject, convert to coaching note, or convert to clip. Do not publish detected moments to players automatically. Keep this source-agnostic so it can later ingest outputs from the soccer360 pipeline or other detection jobs.
```

---

# Best implementation order

Recommended order:

1. Phase 1: Coaching note structure and feedback quality
2. Phase 2: Coach review templates
3. Phase 3: Per-note thumbnails
4. Phase 4: First-class clip builder
5. Phase 5: Player development profiles
6. Phase 6: Action items and next-match goals
7. Phase 7: Match-level coaching summary
8. Phase 8: Review completion and engagement dashboard
9. Phase 9: Coaching analytics dashboards
10. Phase 10: AI-assisted coaching workflow
11. Phase 11: Computer-vision-assisted clip discovery

Reasoning:

- Notes are the atomic unit. Improve note structure first.
- Templates make better notes easier.
- Thumbnails and clips make review more usable.
- Player profiles and goals create the development loop.
- Summaries and dashboards build on accumulated structured data.
- AI should come after the workflow and data model are stable.
- Computer vision should come last because suggestions need a strong manual review system to be useful.

---

# Suggested PR breakdown

## PR 1: Structured notes

Includes:

- Phase 1
- migrations
- Pydantic validation
- Coach UI changes
- My Feedback rendering updates
- tests

## PR 2: Templates and note thumbnails

Includes:

- Phase 2
- Phase 3
- static template registry
- thumbnail generation and serving
- access control tests

## PR 3: Clip builder MVP

Includes:

- Phase 4
- clip data model
- coach clip creation
- My Feedback clip playback
- tests

## PR 4: Player development profiles and goals

Includes:

- Phase 5
- Phase 6
- player profile endpoints/UI
- player goals/action items
- tests

## PR 5: Match summaries and engagement dashboard

Includes:

- Phase 7
- Phase 8
- match summary model/UI
- review completion dashboard
- tests

## PR 6: Analytics dashboard

Includes:

- Phase 9
- aggregate helpers
- simple tables/cards
- drill-down links
- tests where practical

## PR 7: Optional AI assistance

Includes:

- Phase 10
- AI configuration
- note rewrite draft
- tag/category suggestions
- player and match summary drafts
- playlist suggestions
- no-auto-publish guardrails

## PR 8: Detected moments framework

Includes:

- Phase 11
- detected moments data model
- review queue
- convert to note/clip actions
- optional integration hooks

---

# Agent skills and tools needed

## Backend

- FastAPI route design.
- Pydantic request/response models.
- SQLite schema migrations.
- Role-based access control.
- Data aggregation queries.
- ffmpeg thumbnail extraction.
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
- Accessibility and keyboard-friendly controls.

## Product/UX

- Youth soccer coaching workflows.
- Player-friendly feedback writing.
- Coach-admin workflow design.
- Privacy-aware family/player access.
- Analytics that remain actionable instead of noisy.

## Media

- ffmpeg still extraction.
- HLS/MP4 playback behavior.
- Clip range playback.
- Optional MP4 clip export later.

## AI, later phases only

- Prompting for short player-friendly feedback.
- Draft generation with human approval.
- Tag/category classification.
- Summary generation from structured notes.
- Safe fallback when AI is unavailable.

## Computer vision, later phases only

- Importing detection results.
- Timestamp confidence handling.
- Human-in-the-loop review queues.
- Optional soccer360 integration.

---

# Guardrails

Do not do these without a dedicated design decision:

- Do not publish AI-generated feedback without coach approval.
- Do not expose private coach notes to player/family accounts.
- Do not auto-publish computer-vision-detected moments.
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
12. Computer vision suggests candidate moments, coach accepts or rejects.

That is the path from replay archive to real player-development platform.
