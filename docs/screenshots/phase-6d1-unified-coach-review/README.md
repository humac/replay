# Phase 6d-1 — Unified Coach Review screenshots

These captures show the Phase 6d-1 unified Coach Review surface end-to-end. Each PNG was captured by `tests/e2e/phase-6d1-capture.spec.js` running against the local dev server (`http://localhost:8090`) with the seeded `coach1` (and `family1` for the viewer regression) accounts created by `docs/_seed/seed.py`.

To re-capture after future edits:

```bash
# 1. Seed the demo data (idempotent; safe to re-run)
python3 docs/_seed/seed.py
# 2. Start the dev server
python3 server.py
# 3. From the e2e folder, run the dedicated capture script.
#    The spec wraps its tests in `test.describe.configure({ mode: 'serial' })`
#    so it stays inside `auth.py`'s 5/IP/window login rate limit
#    regardless of how it's invoked. The npm script also passes
#    `--workers=2` defensively.
cd tests/e2e && PLAYWRIGHT_BASE_URL=http://localhost:8090 \
    npm run capture-phase-6d1
```

The spec writes PNGs into this folder (`docs/screenshots/phase-6d1-unified-coach-review/`) using `page.screenshot()` so the captured pixels are exactly what the user sees in the live app — no synthetic markup.

## Files

### 01-coach-review-video-mode.png

Coach Review with `data-source="video"` (the default). Surface: `#coach-tab-review .coach-review-shell`. Proves:

- Source toggle ("▶ Video" active, "⌬ Tactical Board" inactive) renders at the top of the shell.
- Picker bar shows Match selector / Slot / Time / Save Note / Save Clip / Focus / Shortcuts.
- Main canvas is the existing video player (with the seeded match loaded so the timeline rail populates with notes).
- Side panel shows the existing Telestrator (9 tools) + color swatches + the Save Note at Current Time form (template selector, title, players, category, tone radiogroup, Save-at-MM:SS button + collapsible More details).
- Timeline rail at the bottom renders the seeded match's notes as horizontally-scrollable chips with thumbnails.

### 02-coach-review-tactical-board-mode.png

Coach Review with `data-source="tactical_board"` and a sample scene loaded by the spec. Surface: `#coach-tab-review .coach-review-shell`. Proves:

- Source toggle highlights "⌬ Tactical Board" with white text on accent blue (matches `.btn-primary`).
- Picker bar swaps to Event title / Date / Type + **Save Observation** + Focus + Shortcuts (no Match / Slot / Time / Save Note / Save Clip).
- Main canvas is the SVG soccer pitch in the same visual slot the video player would occupy. Grass-green frame (`#168a3f`) with white markings; sample scene shows 5 player tokens (#2, #5, #3, #8, #10) + ball + 2 fanning arrows + a yellow dashed zone with "pin wide 7" label + a freehand stroke.
- Side panel shows Board Tools (Select / Player / Ball / Arrow / Line / Zone / Pen / Label) + Player # / Label text inputs + Delete selected / Clear board, then the Observation composer (Title, category, visibility, tone radiogroup, linked players, More details disclosure).

### 03-coach-notes-routing-buttons.png

Coach > Notes management surface (`#coach-tab-notes`). Proves:

- Two routing buttons in the panel head: **+ New observation** and **+ New note** (both wired to `app.routeNewObservation()` / `app.routeNewNote()` in markup).
- Existing observation and video note rows render side-by-side: observation rows carry the `OBSERVATION` + `⌬ Board` pills with a tactical-board tile preview; video rows carry the `VIDEO` pill with their thumbnail and `Open in Review` action.

### 04-coach-roster-add-observation.png

Coach > Roster surface (`#coach-tab-roster`). Proves:

- Each roster row's icon-button group includes a "Add observation note" clipboard icon wired to `app.routeNewObservation({ playerId })` in markup.
- The full roster table renders with jersey badges, status pills, and link chips.

### 05-tactical-board-focus-mode-picker.png

The picker bar alone, captured while focus mode is on (`#coach-view.is-focus-mode`) in Tactical Board mode. Crop scoped to `.coach-review-picker`. Proves:

- All controls (Source toggle, Event title input, Date, Type, Save Observation, Focus, Tools, Shortcuts) fit in a single row — Event Title shrinks via `flex: 1 1 0; min-width: 200px` so the Tools button (which appears only in focus mode) doesn't push Shortcuts to a second row.

### 06-tactical-board-focus-drawer.png

Tactical Board mode in focus mode, drawer open with the Player tool armed. Full viewport. Proves:

- Drawer (slid in from the right) shows ONLY the Board Tools side pane — no video Telestrator. The body class `coach-focus-drawer-tb-mode` makes the dim backdrop pass-through (`pointer-events: none`).
- Status pill in the pitch's bottom-left reads "Click the pitch to drop a player token." in white-on-navy — readable against the green grass.
- Player # / Label text inputs and Delete selected / Clear board actions are visible below the tool grid; Observation form (Title, Shape, Private, tone radiogroup, Linked Players) renders below.

### 07-video-focus-drawer.png

Video mode in focus mode, drawer open. Regression check. Full viewport. Proves:

- Drawer shows ONLY the Telestrator pane — no tactical board tools. Confirms the source-only show/hide rules also scope correctly when the drawer is re-parented to `<body>` for the focus-mode stacking context.
- 9-tool icon toolbar (Select / Freehand / Arrow / Circle / Zone / Label / Spotlight / Dim / Formation) + 6 color swatches + width slider + Canvas Off / Undo / Delete / Clear actions.
- Save Note at Current Time form below (template, title, players, category, tone, Save-at-MM:SS, More details).

### 08-saved-observation-in-notes-list.png

Coach > Notes immediately after the spec's Save Observation flow. Surface: `#coach-tab-notes`. Proves the round-trip:

- The new observation "Switch the field early" appears at the top of the notes list with the `OBSERVATION` + `⌬ Board` pills.
- The tile-preview on the left shows the saved scene (player + ball + arrow + freehand + label) — the scene round-tripped through `POST /api/coach/notes` with `note_context: "observation"` and `tactical_board_json` populated.
- Edit and Delete actions are present (no `Open in Review` because observations have no video timestamp).

### 09-viewer-feedback-notes.png

`family1`'s My Feedback view, Notes tab. Surface: `#feedback-view`. Privacy regression check. Proves:

- Linked-player chip strip (Alex Park, Riley Park) renders.
- The seeded player-visibility notes render with their structured fields (player_summary visible) — but `coach_private_note` is ALWAYS scrubbed for viewers (verified server-side via `_strip_private_fields`; the test_coaching pytest suite covers this end-to-end).

## Notes

- The capture spec is intentionally separate from the existing `sprint-{1..8}-after.spec.js` suite so a future Phase 6d-2 capture can extend it without touching the prior screenshots.
- Each test in `phase-6d1-capture.spec.js` is independent (runs in its own browser context via `test.use`) so a failure in one capture doesn't poison the others.
- The spec uses `_login.js`'s `login()` helper which retries on 429 (the auth login rate limit kicks in if the spec is run back-to-back with other e2e suites).
