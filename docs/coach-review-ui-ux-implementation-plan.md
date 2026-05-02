# Coach Review UI/UX Implementation Plan

This document gives a coding agent a practical, sprint-based plan to improve the Coach Review experience in Replay. The goal is to turn Coach > Review from a general admin-style page into a compact, video-first coaching cockpit.

The public match viewer and My Feedback screens should remain touch-friendly and visually generous. The Coach Review screen is different. It is an authoring workspace. Coaches need more video, faster controls, less padding, compact tools, keyboard shortcuts, and a better way to scan notes during match review.

## Product direction

Coach Review should feel less like a sports website form and more like a lightweight tactical analysis workbench.

Core principles:

1. Video first. The video and drawing canvas should dominate the screen.
2. Compact controls on desktop. Coaches using a mouse and keyboard should not waste space on large buttons.
3. Touch-friendly controls on tablets and phones. Do not shrink controls for coarse pointer devices.
4. Fast authoring. A coach should be able to create a note in seconds while watching video.
5. Keep the current information architecture. Coach > Review remains the single authoring surface.
6. Avoid breaking the public viewing experience.
7. Keep the app no-build-step friendly. Use existing vanilla JS, HTML, and CSS patterns.

## Current areas to inspect first

Read these files before coding:

- `index.html`
  - `#coach-view`
  - `.coach-subnav`
  - `#coach-tab-review`
  - `.coach-review-shell`
  - `.coach-review-picker`
  - `.coach-review-grid`
  - `.coach-review-video`
  - `.coach-review-side`
  - `#coach-review-toolbar`
  - `#coach-review-form`
  - `#coach-review-notes`
- `styles.css`
  - Coach workspace styles
  - `.options-card`
  - `.coach-review-*`
  - `.coach-subnav-*`
  - `.coach-mini-form`
  - `.coach-check-list`
  - responsive breakpoints
- `js/coaching.js`
  - `renderCoachReview()`
  - `renderCoachReviewPicker()`
  - `loadCoachReviewVideo()`
  - `renderCoachReviewForm()`
  - `renderCoachReviewNotes()`
  - `renderCoachTelestratorToolbar()`
  - drawing tool handlers
  - formation overlay handlers
- `js/player.js`
  - video source loading
  - HLS player handling
  - existing keyboard shortcut conventions
- `js/api.js`
  - auth and role helpers
  - coaching API calls
- `docs/design/design-report.md`
  - existing UX restructure assumptions
- `specs/coaching-platform-design.md`
  - coaching feature scope and privacy model
- `tests/test_coaching.py`
  - backend assumptions that should not be broken

## Definition of done for the whole effort

The Coach Review screen should meet these criteria:

- On desktop, the video and telestration canvas use roughly 70 to 80 percent of the available width.
- The right-side control panel is compact, fixed-width, and scrollable when needed.
- Telestrator tools are small, icon-first buttons with accessible labels and tooltips.
- The match and slot selectors are in a compact top bar, not a large form block.
- The note form has a fast default state and an expandable advanced section.
- Notes for the current match can be scanned quickly in a compact timeline rail.
- A wide/focus mode exists for larger telestration work.
- Desktop uses smaller controls only when `pointer: fine` applies.
- Touch devices keep accessible, larger control targets.
- Keyboard shortcuts support common review actions.
- Existing note creation, drawing save/load, playlist preview, My Feedback playback, role gating, and match playback still work.
- `node --check` passes for touched JS files.
- `python3 -m py_compile` passes for touched Python files if any backend files are changed.
- Existing tests pass, especially `tests/test_coaching.py`.

---

# Sprint 0: Baseline audit and screenshot capture

## Goal

Create a before-state reference so later UI changes can be compared visually and behaviorally.

## Scope

No product changes. Audit only.

## Tasks

1. Run the app locally with sample data or seed a small dataset:
   - one full match
   - one two-half match
   - at least three roster players
   - at least five coaching notes
   - at least one playlist
2. Capture screenshots of:
   - `/coach?tab=roster`
   - `/coach?tab=notes`
   - `/coach?tab=playlists`
   - `/coach?tab=review`
   - `/coach?tab=review&match=<id>&slot=full`
   - `/feedback?tab=notes`
   - `/feedback?tab=playlists`
   - public match page
3. Record current desktop dimensions:
   - video width and height
   - right panel width
   - total viewport width
   - amount of vertical space consumed above the video
4. Identify the existing Coach Review CSS selectors that control spacing, grid layout, button sizing, and form density.

## Acceptance criteria

- A short audit note is added to the implementation branch or PR description.
- Before screenshots exist for desktop and mobile/tablet width.
- No app behavior is changed.

## Coding agent prompt

```text
You are working in the Replay repo. Do not change product behavior in this sprint. Audit the current Coach Review UI and capture the before-state layout. Inspect index.html, styles.css, js/coaching.js, js/player.js, docs/design/design-report.md, and specs/coaching-platform-design.md. Identify the selectors and JS methods that control Coach Review layout, telestrator toolbar rendering, note form rendering, and current match notes rendering. Produce a concise audit summary with screenshots, current proportions, and the specific files/selectors to modify in later sprints. Do not refactor yet.
```

---

# Sprint 1: Video-first Coach Review layout

## Goal

Make Coach Review feel like an analysis workspace by giving the video/telestrator area most of the screen.

## UX target

Desktop layout:

```text
Compact match/slot bar

[                  large video + canvas                  ][ compact inspector ]
```

Target proportions:

- video area: flexible, dominant column
- side panel: 320 to 360 px fixed width
- gap: under 1 rem
- outer shell padding: under 1 rem

## Tasks

1. Add a Review-specific layout class when the Review tab is active, for example:
   - `coach-review-active` on `#coach-view`, or
   - `is-review-mode` on `#coach-tab-review`
2. Reduce unnecessary vertical chrome in Review mode:
   - shrink or hide the large Coach page intro text when Review is active
   - keep the subnav visible but compact
3. Convert `.coach-review-grid` to a video-first grid:

```css
.coach-review-grid {
    display: grid;
    grid-template-columns: minmax(0, 1fr) 340px;
    gap: 0.85rem;
    align-items: start;
}
```

4. Make the right panel scroll independently:

```css
.coach-review-side {
    max-height: calc(100vh - 180px);
    overflow: auto;
}
```

5. Reduce `.coach-review-shell` padding and card chrome.
6. Keep the public match page unchanged.

## Acceptance criteria

- On desktop, the video visibly dominates the Review tab.
- The right panel does not consume more than roughly 360 px.
- The right panel scrolls if tools/form/notes exceed viewport height.
- On tablet/mobile, the layout falls back to a single column.
- No functional regressions in loading a match, switching slot, seeking to notes, or rendering drawings.

## Coding agent prompt

```text
Implement a video-first desktop layout for Coach > Review. Keep the public match viewer and My Feedback UI unchanged. In index.html, styles.css, and js/coaching.js, add a Review-active class when the review tab is selected, then use it to reduce page chrome and make the video/telestrator area the dominant column. The right panel should be a compact fixed-width inspector around 320 to 360 px and independently scrollable. Preserve mobile and tablet usability with a single-column layout. Do not change backend APIs or coaching data models. Validate by loading /coach?tab=review with a match selected and confirming the video area is larger than before.
```

---

# Sprint 2: Compact match and slot control bar

## Goal

Replace the current form-like match/slot picker with a compact top control bar.

## UX target

```text
Match: [select.....................]  Slot: [Full]  Time: 12:42  [Save Note]
```

## Tasks

1. Refactor the `coach-review-picker` markup into a compact horizontal toolbar.
2. Keep the existing `#coach-review-match` and `#coach-review-slot` IDs so current JS handlers continue to work.
3. Add a read-only current time display near the picker.
4. Update the time display from the Review video `timeupdate` event.
5. Add a primary compact `Save Note` button in the top bar that calls the same note save behavior as the form button.
6. Ensure the top bar wraps cleanly on narrow screens.

## Acceptance criteria

- Match and slot selectors no longer consume a large form block.
- Current video time is visible in the review header.
- The Save Note action is accessible from the top bar.
- Existing match/slot change behavior remains unchanged.

## Coding agent prompt

```text
Refactor the Coach Review match and slot selector into a compact top control bar. Preserve the existing element IDs and handlers so match loading and slot switching continue to work. Add a current-time readout bound to the coach review video's timeupdate event. Add a compact Save Note button in the bar that reuses the existing save-note logic. Keep controls accessible with labels or aria-labels. Do not alter the public game player.
```

---

# Sprint 3: Compact icon-first telestrator toolbar

## Goal

Shrink the telestrator controls so they do not crowd the video canvas.

## UX target

Use small square icon buttons on desktop:

```text
Tools
[✎] [↗] [○] [▭] [T] [◎] [◐] [👥]
Color [swatches]
Width [slider]
[Undo] [Delete] [Clear]
```

## Tasks

1. Refactor `renderCoachTelestratorToolbar()` in `js/coaching.js` to output grouped toolbar sections:
   - drawing tools
   - formation tools
   - color swatches
   - width slider
   - canvas actions
   - destructive actions
2. Convert most tool buttons to icon-first buttons.
3. Add `title` and `aria-label` attributes to every icon button.
4. Keep text labels for destructive actions like Clear if needed.
5. Use compact CSS for desktop with `pointer: fine`.
6. Preserve larger targets on touch devices.

Suggested CSS:

```css
@media (pointer: fine) and (min-width: 900px) {
    .coach-tool-btn {
        width: 34px;
        height: 34px;
        padding: 0;
        border-radius: 8px;
    }

    .coach-tool-btn .label {
        display: none;
    }
}

@media (pointer: coarse), (max-width: 899px) {
    .coach-tool-btn {
        min-width: 44px;
        min-height: 44px;
    }
}
```

## Acceptance criteria

- Toolbar is much shorter and more compact on desktop.
- Every tool remains discoverable through tooltip/title and accessible label.
- Canvas on/off, tool selection, undo, delete, clear, color, width, and formation tools still work.
- Touch devices still have 44 px approximate targets.

## Coding agent prompt

```text
Redesign the Coach Review telestrator toolbar as a compact icon-first desktop toolbar. Work primarily in js/coaching.js and styles.css. Keep all existing drawing behaviors working: freehand, arrow, circle, zone, label, spotlight, dim, formation, select/move, delete, undo, clear, color, width, and canvas toggle. Add title and aria-label to icon buttons. Use pointer-sensitive CSS so desktop controls are compact while touch devices keep larger tap targets. Do not change drawing payload schemas.
```

---

# Sprint 4: Fast note composer with advanced details collapsed

## Goal

Let coaches save useful notes quickly without filling out a full form every time.

## UX target

Default compact composer:

```text
Title
Player chips
Category     Type
[Save at 12:42]
More details ▾
```

Expanded advanced section:

```text
Visibility
Tags
Long note body
```

## Tasks

1. Refactor `renderCoachReviewForm()` into a compact default composer.
2. Keep the existing note payload behavior.
3. Add a new optional note type field if the backend already supports it. If not, do not add backend changes in this sprint. Instead, prepare the UI with a local placeholder only if harmless.
4. Collapse advanced fields by default:
   - visibility
   - tags
   - long body
5. Use compact player selection chips.
6. Make the save button clearly show the current timestamp.
7. Reset only the right fields after save:
   - title and body should clear
   - category/type may remain sticky for fast repeated note creation
   - selected players should optionally remain sticky while reviewing one player

## Acceptance criteria

- A coach can save a basic note with title, category, player, and current timestamp without scrolling.
- Advanced fields are available but not visually dominant.
- Existing note creation still sends valid data to `/api/coach/notes`.
- Note list refreshes after save.
- Drawing payload is still saved with the note.

## Coding agent prompt

```text
Refactor the Coach Review note form into a fast compact composer. The default state should show title, linked player chips, category, and a Save at current time button. Move visibility, tags, and long body text into a collapsed More details section. Preserve the existing CreateCoachingNoteRequest payload and the drawing save behavior. Do not make backend schema changes unless strictly required. After saving, refresh notes for the match and keep the workflow fast for repeated note creation.
```

---

# Sprint 5: Current-match timeline rail

## Goal

Replace the bulky current-match notes list with a compact timeline rail that helps coaches jump between moments quickly.

## UX target

Bottom rail under video:

```text
03:12 #7 Width | 09:44 Team Press | 12:42 #9 Scan | 22:18 Recovery
```

Each chip should show:

- timestamp
- player number or team indicator where available
- category/type indicator
- short title

## Tasks

1. Move `#coach-review-notes` out of the right panel or create a second compact rendering location under the video.
2. Keep the existing right-panel notes list only if useful, but prefer one compact timeline rail.
3. Update `renderCoachReviewNotes(matchId)` to render compact chips.
4. Clicking a chip should:
   - seek to the note timestamp
   - render the note drawing
   - optionally highlight the selected chip
5. Add horizontal scrolling for many notes.
6. Include empty state when no notes exist.

## Acceptance criteria

- Notes for a match are scannable without taking over the side panel.
- Clicking a note chip still seeks and loads drawings.
- The rail handles many notes without stretching the page vertically.
- Mobile layout remains usable.

## Coding agent prompt

```text
Create a compact current-match notes timeline rail for Coach Review. The rail should sit under the video or directly below the review grid and render timestamp chips instead of large note rows. Each chip should show the clock time, short title, category, and player indicator if available. Clicking a chip must reuse existing seekCoachReviewNote behavior: seek to timestamp and render the saved drawing. Use horizontal scrolling for many notes. Keep accessibility and keyboard focus states.
```

---

# Sprint 6: Wide telestration/focus mode

## Goal

Give coaches a mode where the video and drawing canvas use nearly the entire screen.

## UX target

A toggle called one of:

- Focus Mode
- Wide Review
- Telestrator Mode

When enabled:

- reduce or hide Coach page header
- collapse side panel to a narrow icon rail or hide it behind a drawer
- video area expands
- note composer becomes a slide-over, drawer, or compact floating panel
- timeline rail remains accessible

## Tasks

1. Add a focus mode state, for example `_coachFocusMode` in `js/coaching.js`.
2. Add a button in the review top bar to toggle focus mode.
3. Add a CSS class to `#coach-tab-review` or `#coach-view` when enabled.
4. In focus mode:
   - make grid single-column or video-dominant
   - collapse `.coach-review-side`
   - expose tools through a compact floating toolbar or icon rail
5. Add Escape key to exit focus mode.
6. Persist focus mode only during the current session, not permanently.

## Acceptance criteria

- Focus mode noticeably increases the video/telestrator area.
- Coach can still access tools and save notes.
- Escape exits focus mode.
- Leaving Review tab tears down or resets safely.
- No impact on public match page.

## Coding agent prompt

```text
Add a Wide Review or Focus Mode to Coach > Review. This mode should prioritize the video/telestrator canvas by collapsing or minimizing the right inspector panel and reducing page chrome. Add a toggle in the compact review control bar and allow Escape to exit. Preserve access to drawing tools and note saving, either through a compact floating toolbar, icon rail, or slide-over inspector. Keep this state session-local and do not affect public playback or My Feedback.
```

---

# Sprint 7: Keyboard shortcuts for coach review

## Goal

Make Coach Review fast for power users.

## Suggested shortcuts

| Key | Action |
|---|---|
| Space | Play/pause video, unless typing in an input or textarea |
| J | Back 5 or 10 seconds |
| L | Forward 5 or 10 seconds |
| Left | Back 1 second |
| Right | Forward 1 second |
| Shift+Left | Back 10 or 30 seconds |
| Shift+Right | Forward 10 or 30 seconds |
| S | Save note, unless typing |
| A | Arrow tool |
| F | Freehand tool |
| Z | Zone tool |
| C | Circle tool |
| T | Label tool |
| D | Dim/spotlight tool, whichever is most useful |
| Escape | Exit focus mode or cancel active drawing |

## Tasks

1. Add Coach Review-specific keyboard handling in `js/coaching.js`.
2. Do not hijack keys when focus is in:
   - input
   - textarea
   - select
   - contenteditable
3. Reuse existing video seek/play logic where possible.
4. Add a small keyboard shortcuts help popover or tooltip.
5. Make shortcuts active only while Coach Review is visible.
6. Clean up event listeners when leaving Coach Review.

## Acceptance criteria

- Shortcuts work only in Coach Review.
- Typing in form fields is not interrupted.
- Existing global shortcuts do not conflict badly.
- Save shortcut uses current timestamp and current drawing.
- Shortcut help is discoverable.

## Coding agent prompt

```text
Add keyboard shortcuts scoped to Coach > Review only. Implement play/pause, small seek, larger seek, save note, tool selection, and Escape to exit focus mode or cancel drawing. Do not intercept keys while typing in inputs, textareas, selects, or contenteditable elements. Reuse existing video and drawing state methods in js/coaching.js where possible. Add a compact shortcuts help affordance in the Review UI. Make sure listeners are installed only while Review is active and cleaned up when leaving.
```

---

# Sprint 8: Responsive and accessibility polish

## Goal

Make the denser desktop UI accessible and avoid harming tablet/mobile usability.

## Tasks

1. Add pointer-aware CSS:
   - compact for `pointer: fine`
   - larger controls for `pointer: coarse`
2. Validate tab order through:
   - match selector
   - slot selector
   - video
   - tools
   - note form
   - timeline rail
3. Add or verify `aria-label`, `aria-selected`, `aria-pressed`, and `title` where appropriate.
4. Ensure focus rings are visible on compact buttons.
5. Test at widths:
   - 390 px mobile
   - 768 px tablet
   - 1024 px small laptop
   - 1440 px desktop
   - 1920 px wide monitor
6. Check that the canvas still aligns perfectly over the video after layout changes.
7. Check native video controls still behave properly with HLS and MP4 fallback.

## Acceptance criteria

- Desktop is compact and efficient.
- Touch devices remain comfortable.
- Keyboard navigation works.
- Canvas alignment is correct at all tested sizes.
- No horizontal page overflow except intentional timeline rail scrolling.

## Coding agent prompt

```text
Polish the Coach Review responsive and accessibility behavior. Use pointer-aware CSS so compact desktop controls do not make touch devices hard to use. Verify keyboard focus, aria labels, aria-pressed state on tool buttons, and visible focus rings. Test mobile, tablet, laptop, desktop, and wide monitor layouts. Confirm the drawing canvas stays aligned with the video after resizing and mode changes. Do not change backend behavior.
```

---

# Sprint 9: QA, regression tests, and documentation update

## Goal

Lock in the UX changes and document the new Coach Review workflow.

## Tasks

1. Run static checks:

```bash
node --check script.js
node --check js/coaching.js
node --check js/player.js
node --check js/api.js
```

2. Run backend checks if any Python files changed:

```bash
python3 -m py_compile server.py media.py models.py db.py auth.py settings.py uploads.py live.py streams.py log.py
```

3. Run tests:

```bash
pytest tests/test_coaching.py -v
pytest tests/ -v
```

4. Manual regression checklist:
   - coach can open Review tab
   - match selector loads video
   - slot selector switches video
   - drawing canvas toggles on/off
   - each drawing tool works
   - formation overlay still works
   - note saves current timestamp and drawing
   - saved note appears in timeline rail
   - clicking note seeks and restores drawing
   - playlist preview still works
   - My Feedback still plays notes/playlists
   - public match view unchanged
   - mobile layout usable
   - focus mode exits cleanly

5. Update docs:
   - `docs/design/design-report.md`, or
   - create `docs/design/coach-review-cockpit-report.md`

6. Include before/after screenshots in the PR description.

## Acceptance criteria

- Static checks pass.
- Tests pass.
- Manual checklist is documented in PR.
- Design docs explain the new cockpit layout.
- Screenshots show before/after improvement.

## Coding agent prompt

```text
Perform the final QA pass for the Coach Review cockpit redesign. Run node syntax checks for touched JS, py_compile if Python changed, and pytest with emphasis on tests/test_coaching.py. Manually verify the full Coach Review workflow: match loading, slot switching, telestrator tools, formation overlays, note saving, timeline note seeking, focus mode, keyboard shortcuts, playlist preview, My Feedback playback, and public match playback. Update the design documentation with the new layout decisions and add a concise before/after summary for the PR.
```

---

# Recommended implementation order

Do the work in this order:

1. Sprint 0: Baseline audit and screenshots
2. Sprint 1: Video-first layout
3. Sprint 2: Compact match and slot bar
4. Sprint 3: Compact telestrator toolbar
5. Sprint 4: Fast note composer
6. Sprint 5: Current-match timeline rail
7. Sprint 6: Wide/focus mode
8. Sprint 7: Keyboard shortcuts
9. Sprint 8: Responsive and accessibility polish
10. Sprint 9: QA and docs

Do not start with focus mode or keyboard shortcuts. They depend on the layout and component structure being cleaned up first.

---

# Suggested PR breakdown

If the agent is making pull requests, keep the PRs small:

## PR 1: Coach Review layout foundation

Includes:

- Sprint 1
- Sprint 2

## PR 2: Compact tool and note authoring

Includes:

- Sprint 3
- Sprint 4

## PR 3: Timeline rail and focus mode

Includes:

- Sprint 5
- Sprint 6

## PR 4: Keyboard shortcuts, responsive polish, docs

Includes:

- Sprint 7
- Sprint 8
- Sprint 9

---

# Skills and tools the coding agent should use

## Repo navigation and code inspection

- `rg` or equivalent search for selectors and function names.
- GitHub code search for `coach-review`, `coach-drawing`, `renderCoachTelestratorToolbar`, `renderCoachReviewForm`, and `renderCoachReviewNotes`.
- Browser devtools for layout inspection and live CSS tuning.

## Frontend skills

- Vanilla JavaScript DOM manipulation.
- ES module mixin pattern used by this repo.
- CSS Grid and Flexbox.
- Responsive CSS with media queries.
- Pointer-aware CSS using `@media (pointer: fine)` and `@media (pointer: coarse)`.
- Accessible button states with `aria-label`, `aria-pressed`, `aria-selected`, and visible focus rings.
- HTML video element behavior.
- Canvas overlay alignment above video.
- Keyboard event scoping and input focus guards.

## Video and player skills

- HLS.js lifecycle basics.
- Native HLS fallback behavior.
- MP4 fallback behavior.
- HTML video events:
  - `loadedmetadata`
  - `timeupdate`
  - `seeked`
  - `play`
  - `pause`
  - `resize` handling through layout observers if needed

## Canvas and telestration skills

- Canvas coordinate normalization.
- Maintaining overlay alignment during resize.
- Pointer/mouse event handling.
- Drawing object state management.
- Existing drawing payload compatibility:
  - version 1 legacy strokes
  - version 2 objects
  - formation overlays

## Testing and QA tools

Use these where available:

- Browser devtools responsive mode.
- Playwright or another browser automation tool for screenshots and smoke checks.
- Axe DevTools or Lighthouse accessibility checks.
- `node --check` for touched JS files.
- `python3 -m py_compile` if backend files change.
- `pytest tests/test_coaching.py -v`.
- Full `pytest tests/ -v` before final merge.

## Visual QA checklist

Capture screenshots for:

- desktop Coach Review before and after
- wide monitor Coach Review
- 1024 px layout
- mobile layout
- focus mode
- timeline rail with many notes
- drawing overlay active
- advanced note section open

## Guardrails

Do not do these unless explicitly scoped:

- Do not change coaching API payloads without migration and tests.
- Do not change drawing schema unless absolutely required.
- Do not alter public match playback layout.
- Do not alter My Feedback playback behavior except where needed to preserve compatibility.
- Do not remove existing role checks.
- Do not burn drawings into video files.
- Do not introduce a frontend build step.

---

# Future follow-up ideas outside this UI sprint

These are valuable, but should be separate from the Coach Review cockpit redesign:

1. Per-note thumbnails generated at the timestamp.
2. Positive vs correction note type in the backend model.
3. Player development profile pages.
4. Action items and next-match goals.
5. Match-level coaching summary.
6. AI-assisted note cleanup and tag suggestions.
7. AI-assisted playlist generation.
8. Computer-vision-assisted clip discovery using the soccer360 pipeline.

Keep those separate so the UI/UX redesign does not become too large to review.
