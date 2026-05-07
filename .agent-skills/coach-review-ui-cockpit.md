# Coach Review UI cockpit

## Purpose

Single source of truth for the Coach Review redesign target. Replay's `/coach?tab=review` is
the only authoring surface for coaching notes and telestrator drawings. The redesign turns it
from a generic admin-style form into a compact, video-first analysis cockpit.

The canonical plan is [`docs/archive/coach-review-ui-ux-implementation-plan.md`](../docs/archive/coach-review-ui-ux-implementation-plan.md).
This skill restates the target and the invariants so any sprint agent can load it quickly.

## When to use it

- Any sprint of the Coach Review redesign (Sprints 0–9).
- Any change to `#coach-tab-review`, `.coach-review-*` CSS, or `renderCoach*` methods in
  `js/coaching.js`.
- Anything that risks regressing the public match viewer or My Feedback as a side effect.

## Key repo files

- `index.html` — `#coach-tab-review` shell, picker form, video wrapper, side panel containers.
- `styles.css` — `Coach > Review shell` block (~line 6160 onward). Co-locate new rules here.
- `js/coaching.js` — all Coach Review render and state logic (~1779 lines).
- `js/player.js` — `getStreamUrls`, `loadPlaybackSource`, HLS lifecycle (lines ~299–425).

## Target layout (desktop)

```
┌──────────────────────────────────────────────────────────────────┐
│  Match: [select]  Slot: [Full]  Time: 12:42         [Save Note]  │  ← compact top bar
├──────────────────────────────────────────────────────────────────┤
│                                                  ┌──────────────┐│
│                                                  │  Tools (icon)││
│         Large video + telestrator canvas         │  Color/Width ││  ← inspector
│           (~70–80% width, dominant)              │  Note form   ││    320–360 px
│                                                  │  (advanced ▾)││    independent
│                                                  └──────────────┘│    scroll
├──────────────────────────────────────────────────────────────────┤
│  03:12 #7 Width │ 09:44 Team Press │ 12:42 #9 Scan │ 22:18 …      │  ← timeline rail
└──────────────────────────────────────────────────────────────────┘
```

CSS shape:

```css
.coach-review-grid {
    display: grid;
    grid-template-columns: minmax(0, 1fr) 340px;
    gap: 0.85rem;
    align-items: start;
}
.coach-review-side {
    max-height: calc(100vh - 180px);
    overflow: auto;
}
```

Toolbar buttons sized via pointer-aware media queries (compact mouse, large touch — see
[`css-responsive-accessibility.md`](css-responsive-accessibility.md)).

Focus mode (Sprint 6): toggle a class on `#coach-tab-review` or `#coach-view` that collapses
the inspector and chrome so video/canvas approach full width. Escape exits.

## Sprint order (do not skip ahead)

| Sprint | What |
|---|---|
| 0 | Baseline audit + screenshots. No code changes. |
| 1 | Video-first grid (`coach-review-grid`, `coach-review-side`). |
| 2 | Compact match/slot top bar with current-time readout + Save Note CTA. |
| 3 | Icon-first telestrator toolbar with grouped sections. |
| 4 | Fast note composer with collapsed advanced section. |
| 5 | Timeline rail of note chips below video. |
| 6 | Wide / focus mode toggle + Escape exit. |
| 7 | Keyboard shortcuts scoped to Coach Review. |
| 8 | Responsive + a11y polish at 390 / 768 / 1024 / 1440 / 1920 px. |
| 9 | QA pass, regression tests, doc update. |

PR breakdown: PR1 = S1+S2, PR2 = S3+S4, PR3 = S5+S6, PR4 = S7+S8+S9. Do not bundle Sprint 0
into PR1 — it ships an audit, not code.

## Important functions / selectors that must survive

These are referenced by inline handlers, other mixins, or persisted in user state. Renaming
or removing any of them is a breaking change.

### DOM ids

`#coach-view`, `#coach-tab-review`, `#coach-review-match`, `#coach-review-slot`,
`#coach-review-video`, `#coach-drawing-canvas`, `#coach-review-toolbar`, `#coach-review-form`,
`#coach-review-notes`, `#coach-review-empty`, `#coach-review-title`, `#coach-review-body`,
`#coach-review-category`, `#coach-review-visibility`, `#coach-review-players`,
`#coach-review-tags`, `#coach-label-text`, `#coach-formation-controls`.

### CSS classes

`.coach-review-shell`, `.coach-review-grid`, `.coach-review-video`, `.coach-review-side`,
`.coach-review-wrapper`, `.coach-review-empty`, `.coach-review-picker`, `.coach-tool-grid`,
`.coach-tool-row`, `.coach-mini-form`, `.coach-check-list`, `.coach-check-option`,
`.coach-subnav`, `.coach-subnav-btn`, `.coach-tab-panel`, `.coach-telestrator`,
`.coach-formation-roster`, `.coach-formation-controls`.

### `js/coaching.js` methods

Core render: `renderCoachReview`, `renderCoachReviewPicker`, `loadCoachReviewVideo`,
`renderCoachReviewForm`, `renderCoachReviewNotes`, `renderCoachTelestratorToolbar`,
`setCoachTab`, `tearDownCoachReview`.

Event handlers (called from `index.html`): `handleCoachReviewMatchChange`,
`handleCoachReviewSlotChange`, `seekCoachReviewNote`, `setCoachDrawingTool`,
`setCoachDrawingColor`, `setCoachDrawingWidth`, `toggleCoachDrawing`, `undoCoachDrawing`,
`deleteSelectedCoachObject`, `clearCoachDrawing`.

Canvas lifecycle: `setupCoachCanvas`, `_resizeCoachCanvas`, `paintCoachCanvas`,
`renderCoachDrawing`, `normalizeCoachDrawing`, `teardownCoachCanvasListeners`,
`activateCoachCanvas`, `coachDrawStart`, `coachDrawMove`, `coachDrawEnd`.

Private state fields on the coaching mixin (do not collide):

- `_coachVideoId = 'coach-review-video'`
- `_coachCanvasId = 'coach-drawing-canvas'`
- `_coachDrawing`, `_coachDrawingTool`, `_coachDrawingColor`, `_coachDrawingWidth`,
  `_coachDrawingActive`, `_coachSelectedObjectIndex`, `_coachFormation`.

## Constraints

- Do **not** change the `CreateCoachingNoteRequest` payload shape (Sprint 4 may add an
  optional field only if backend already supports it; otherwise UI-only).
- Do **not** change the drawing schema (v1 legacy `strokes`, v2 `objects`, formation anchors
  + hull). Render must remain backward-compatible with existing v1 records.
- Do **not** burn drawings into video. They stay as JSON metadata on `coaching_notes`.
- Do **not** re-introduce the in-match coach side panel (`#coach-match-panel`,
  `#coach-mode-bar`, `toggleCoachMode`) — it was deliberately removed.
- Do **not** alter role gating. `/coach` is `coach|admin`; `/feedback` is signed-in.
- Do **not** change the public `/match/{slug}` page layout.
- Keep the no-build promise — see [`vanilla-js-mixin-pattern.md`](vanilla-js-mixin-pattern.md).

## Commands / checks to run

```bash
# Locate everything Coach-Review-related
rg -n "renderCoachReview|renderCoachTelestratorToolbar|loadCoachReviewVideo" js/ index.html
rg -n "coach-review-|coach-tool-|coach-mini-form|coach-tab-review|coach-drawing-canvas" \
   index.html styles.css js/

# Confirm an inline handler still has a backing method after an edit
rg -n "app\.handleCoachReviewMatchChange|app\.handleCoachReviewSlotChange" index.html js/

# Static gate (must be green at sprint start and end)
node --check script.js js/coaching.js js/player.js js/api.js
pytest tests/test_coaching.py -v
```

## Common failure modes

- **Selector drift.** A sprint renames `.coach-review-grid` but an `is-review-mode` rule still
  references the old name → layout regresses on prod browsers without obvious warning.
- **Canvas drift after layout change.** Sprint 1 makes the side panel scrollable
  independently. Window-resize listener won't fire when only the wrapper resizes — needs a
  `ResizeObserver`. See [`video-hls-canvas-overlay.md`](video-hls-canvas-overlay.md).
- **Inspector overflow.** Forgetting `min-width: 0` on `.coach-review-video` inside the grid
  causes the right column to push out and force a horizontal scrollbar at 1024 px.
- **Reused note query in My Feedback.** Don't borrow Coach Review note queries to render the
  player feedback list; they include `private` content. See
  [`coaching-data-privacy.md`](coaching-data-privacy.md).
- **Removed inline handler with no replacement.** Refactoring the toolbar to event delegation
  is fine, but every old `onclick="app.foo()"` must still resolve until you remove it from
  `index.html` in the same diff.

## Done criteria (per sprint)

A sprint is done when:

- The visible target for that sprint is achieved (compact bar, video dominance, icon
  toolbar, etc.).
- Every selector and method listed under "Important functions / selectors" is still present.
- `node --check` passes for touched JS, `python3 -m py_compile` passes for touched Python.
- `pytest tests/test_coaching.py -v` passes; `pytest tests/ -v` passes.
- The manual regression checklist in [`testing-and-qa.md`](testing-and-qa.md) is logged in
  the PR description.
- Before/after screenshots are attached at the widths in [`pr-review-checklist.md`](pr-review-checklist.md).
- Public `/match/{slug}` and `/feedback` are visually unchanged.
