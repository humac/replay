# Coach Review Cockpit — Design Report

## Executive summary

Coach > Review evolved from a generic admin-style form (PR #56 audit) into a **video-first analysis cockpit** purpose-built for in-game coach annotation. Across nine sprints (PR1 through PR4) the surface gained:

- A wider video column with a fixed, height-matched inspector
- A compact match/slot top bar with live timestamp readout and one-click Save
- An icon-first telestrator toolbar (34 px desktop / 44 px touch)
- A fast note composer with collapsed advanced fields
- A horizontal timeline rail of timestamp chips for fast moment-jumping
- A Focus / Wide mode that maximises the video and exposes tools via a slide-over drawer
- Keyboard shortcuts scoped to Coach Review (Space, J/L, A/F/Z/C/T/D, S, ?, Esc)
- Pointer-aware sizing, themed scrollbars, focus rings, and ARIA on every interactive control

No backend changes, no schema migrations, no public-match-page or My Feedback regressions. Implementation lives in `js/coaching.js`, `styles.css`, and `index.html`.

This report consolidates the design decisions, measured deltas, and acceptance evidence. The full sprint-by-sprint history is in [`ROADMAP.md`](../../ROADMAP.md); the implementation plan is in [`docs/coach-review-ui-ux-implementation-plan.md`](../coach-review-ui-ux-implementation-plan.md).

## Goals

The Sprint 0 audit ([`docs/coach-review-sprint-0-baseline-audit.md`](../coach-review-sprint-0-baseline-audit.md)) measured the legacy state and set the targets:

| Target | Sprint 0 baseline | Goal |
|---|---|---|
| Video share of grid (1440 px) | 65 % (743 / 1138 px) | 70–80 % |
| Side panel width | 373 px (acceptable at 1440), 289 px (cramped at 1024) | Fixed 320–360 px |
| Chrome above the video (1440 px) | 498 px | ~200 px |
| Picker bar height | 118 px form block | < 60 px horizontal toolbar |
| Telestrator toolbar density | 9 text-labelled rectangles, ~277 px tall | 9 icon squares, < 100 px tall |
| Note composer | 6 always-visible fields, 732 px tall | 4-field default + collapsed advanced |
| Notes list | Vertical stack, grew with note count | Horizontal chip rail, fixed 50 px |
| Focus mode | None | Toggleable; collapses chrome + inspector |

## Sprint-by-sprint deltas

### PR1 (Sprints 1 + 2) — video-first layout + compact picker bar

- **Video share of grid**: 65 % → **74 %** at 1440 px, **81 %** at 1920 px (after PR3's outer-container relaxation)
- **Chrome above video**: 498 → **344 px** (-154 px)
- **Picker bar**: 118 px form block → **47 px** horizontal toolbar
- **Side panel**: 373 → 340 px fixed, height-matched to the video wrapper via JS `_syncCoachReviewSideHeight`

### PR2 (Sprints 3 + 4) — icon toolbar + fast note composer

- **Telestrator toolbar**: 277 → 232 px (-45 px); tool buttons 84 × 32 → **34 × 34 px square**, 44 px on touch
- **Note composer**: 732 → **640 px** by default (advanced fields collapse behind `<details>`); coach can save without scrolling
- **Sticky reset behavior**: only title / body / tags clear after save; category, visibility, selected players persist for fast repeated note creation

### PR3 (Sprints 5 + 6) — timeline rail + focus mode

- **Notes list**: stacked rows that grew vertically with note count → **single 50 px horizontal chip rail** under the video; doesn't stretch the page regardless of note count
- **Each chip**: `MM:SS · player indicator · category dot · short title`; click seeks + restores drawing; auto-scroll into view when seeking from outside the visible window
- **Focus mode**: video wrapper grows from 1462 → **1824 px (+25 %)** at 1440 px; Tools slide-over drawer keeps composer reachable; Escape exits

### PR4 (Sprints 7 + 8 + 9) — keyboard shortcuts + a11y polish + docs

- **Keyboard shortcuts**: scoped to Coach > Review only (auto-install on tab activation, uninstall on tab change)
- **Tap targets**: ≥44 px on `pointer:coarse` for every Coach Review control (verified via Playwright iPad Mini emulation)
- **ARIA + focus rings**: every tool button, color swatch, timeline chip, focus toggle, drawer toggle, shortcuts toggle has `aria-label` + `title` + `aria-pressed` + visible `:focus-visible` ring
- **Canvas alignment**: verified across 1024 / 1440 / 1920 px, plus through focus-mode toggle (canvas dimensions track video wrapper within ±2 px)
- **Tab order**: match → slot → save → focus → tools → shortcuts → drawing canvas → composer → timeline rail
- **Documentation**: this report + `docs/coach-review-sprint-0-baseline-audit.md` + sprint completion entries in `ROADMAP.md`

## Architecture

### State machine for Coach Review

```
    setCoachTab('review')  ─┐
                            ├─► is-review-mode class on #coach-view
                            ├─► installCoachReviewShortcuts() (keyboard handler)
                            └─► requestAnimationFrame _syncCoachReviewSideHeight

    setCoachTab(other)     ─┐
                            ├─► remove is-review-mode
                            ├─► uninstallCoachReviewShortcuts()
                            ├─► exitCoachFocusMode() (defensive)
                            └─► tearDownCoachReview() — clears canvas, resets time readouts

    enterCoachFocusMode()  ─┐
                            ├─► is-focus-mode class on #coach-view
                            ├─► coach-focus-mode class on body
                            ├─► capture-phase Escape listener on window
                            └─► requestAnimationFrame canvas + side height re-sync

    openCoachFocusInspector() ─┐
                               ├─► is-focus-drawer-open on #coach-view
                               ├─► coach-focus-drawer-open on body
                               ├─► reparent .coach-review-side to <body>
                               │   (escapes the .coach-tab-panel animation
                               │    stacking-context trap so z-index works)
                               ├─► save inline max-height + scrollTop
                               └─► mount click-outside backdrop element
```

### Key files

- [`js/coaching.js`](../../js/coaching.js) — coach workspace mixin. Sprint-specific helpers: `_syncCoachReviewSideHeight` (Sprint 1), `_renderCoachReviewTime` (Sprint 2), telestrator render (Sprint 3), note composer render (Sprint 4), `_setActiveCoachReviewNote` (Sprint 5), focus mode + drawer (Sprint 6), `installCoachReviewShortcuts` + `_handleCoachReviewShortcut` (Sprint 7).
- [`styles.css`](../../styles.css) — CSS for the cockpit. The Coach Review block lives ~lines 6160–7100.
- [`index.html`](../../index.html) — Coach Review markup at `#coach-tab-review` (~lines 368–460).
- [`tests/e2e/sprint-{1..9}-after.spec.js`](../../tests/e2e/) — Playwright capture specs, all importing the shared `_login.js` helper.

### Critical-path implementation notes

1. **Inspector height sync** (Sprint 1, [`js/coaching.js`](../../js/coaching.js) `_syncCoachReviewSideHeight`): the side panel's `max-height` is JS-driven to match the video wrapper. A `ResizeObserver` on `.coach-review-wrapper` plus a window resize listener keeps them in lockstep. Without this, the inspector overflows the natural row when the page scrolls.

2. **Drawer reparenting** (Sprint 6, [`js/coaching.js`](../../js/coaching.js) `openCoachFocusInspector`): `.coach-review-side` is moved to `<body>` while the drawer is open and restored on close. Required because `.coach-tab-panel` has an `animation` property, which creates a bounded stacking context that traps the drawer's `z-index`. Without reparenting, the backdrop renders above the drawer and intercepts every click. The drawer rule is keyed `body.coach-focus-drawer-open > .coach-review-side` with `z-index: 110` (above `nav.main-nav`'s 100).

3. **Capture-phase Escape listener** (Sprint 6, [`js/coaching.js`](../../js/coaching.js) `enterCoachFocusMode`): the focus-mode Escape handler runs on capture so it wins over any descendant Escape behavior. Bubble-phase `?` shortcut handler from Sprint 7 coexists since they listen for different keys.

4. **Shared e2e login helper** (PR3, [`tests/e2e/_login.js`](../../tests/e2e/_login.js)): retries on 429 with exponential backoff (5s / 10s / 20s / 40s / 60s) so the auth.py 5-per-IP login rate limit doesn't flake when several specs run back-to-back.

## Acceptance evidence

### Static gates

- `node --check script.js js/coaching.js js/player.js js/api.js` — green
- `python3 -m py_compile server.py media.py models.py db.py auth.py settings.py uploads.py live.py streams.py log.py` — green
- `pytest tests/ -v --cov` — 265/265 pass, coverage 65.03 % (CI gate 60)

### End-to-end specs

| Spec | Tests | Result |
|---|---|---|
| `sprint-1-after.spec.js` | 11 | 11/11 |
| `sprint-2-after.spec.js` | 7 | 7/7 |
| `sprint-3-after.spec.js` | 9 | 9/9 |
| `sprint-4-after.spec.js` | 8 | 8/8 |
| `sprint-5-after.spec.js` | 9 | 9/9 |
| `sprint-6-after.spec.js` | 10 | 10/10 |
| `sprint-7-after.spec.js` | 9 | 9/9 |
| `sprint-8-after.spec.js` | 9 | 9/9 |
| **Total** | **72** | **72 / 72** |

### Manual regression checklist

Verified in browser as `coach1` (and `family1` for `/feedback` privacy):

- [x] Coach can open Review tab via subnav
- [x] Match selector loads video (HLS for real matches, MP4 fallback)
- [x] Slot selector switches between Full / 1st Half / 2nd Half
- [x] Drawing canvas toggles on/off via Canvas button + `D`/`F` shortcuts
- [x] Each drawing tool works: select, freehand, arrow, circle, zone, label, spotlight, dim, formation
- [x] Formation overlay accepts 3–16 anchors; collinear sets rejected
- [x] Note saves with current timestamp + drawing payload
- [x] Saved note appears as a new chip in the timeline rail (sorted by timestamp)
- [x] Clicking a chip seeks the video and restores the drawing
- [x] Coach > Playlists > Preview opens the focused-modal player (NOT `/match/{slug}`)
- [x] My Feedback unchanged: `family1` sees only team-visible + linked-player content; `private` notes do not leak
- [x] Public `/match/{slug}` view unchanged (no coach panel, canvas, or toggle)
- [x] Mobile (390 px) layout usable — single-column flow, ≥44 px tap targets
- [x] Focus mode hides chrome, expands video, exposes drawer; Escape exits
- [x] Keyboard shortcuts (Space, J/L, A/F/Z/C/T/D, S, ?, Esc) work outside form fields
- [x] Typing in title / body / tags inputs does NOT trigger shortcuts

### Constraints respected

- No frontend build step introduced
- No backend schema or API changes
- `CreateCoachingNoteRequest` payload unchanged (v1, v2, formation drawings all preserved)
- No drawings burned into video files
- Native browser chrome eliminated from styled controls (the standing rule from `.agent-skills/css-responsive-accessibility.md`)
- Element IDs preserved: `#coach-review-match`, `#coach-review-slot`, `#coach-review-video`, `#coach-drawing-canvas`, `#coach-review-toolbar`, `#coach-review-form`, `#coach-review-notes`, plus per-field IDs for `saveReviewNote`
- Focus mode is session-local (no localStorage / persistence)

## Screenshots

Cumulative captures across all 8 sprint screenshot directories:

- [`docs/screenshots/sprint-0-baseline/`](../screenshots/sprint-0-baseline/) — pre-redesign frozen reference
- [`docs/screenshots/sprint-1-after/`](../screenshots/sprint-1-after/) — refreshes through to PR4 (cumulative cockpit)
- [`docs/screenshots/sprint-2-after/`](../screenshots/sprint-2-after/) — picker bar at 5 widths
- [`docs/screenshots/sprint-3-after/`](../screenshots/sprint-3-after/) — icon toolbar + iPad Mini
- [`docs/screenshots/sprint-4-after/`](../screenshots/sprint-4-after/) — composer collapsed + expanded
- [`docs/screenshots/sprint-5-after/`](../screenshots/sprint-5-after/) — timeline rail at 5 widths
- [`docs/screenshots/sprint-6-after/`](../screenshots/sprint-6-after/) — focus mode + drawer
- [`docs/screenshots/sprint-7-after/`](../screenshots/sprint-7-after/) — keyboard shortcuts help
- [`docs/screenshots/sprint-8-after/`](../screenshots/sprint-8-after/) — multi-width a11y captures + iPad Mini

## What's next (out of scope for this redesign)

Coach Review-specific opportunities the current redesign deliberately did not pursue, suitable for separate work:

- **Per-note thumbnails** generated at the note timestamp (would visually enrich the rail).
- **Note type / tone field** (positive / correction / question / team / individual) — requires a backend column + migration.
- **Player development profile pages** aggregating coaching points across a season.
- **Action items / next-match goals** carried forward in playlists.
- **AI-assisted note cleanup** and auto-tag suggestions.
- **Computer-vision-assisted clip discovery** using the soccer360 pipeline.

These are tracked under "Coaching Analysis Feature Roadmap" in [`docs/coaching-analysis-feature-roadmap.md`](../coaching-analysis-feature-roadmap.md).

---

**Sprints**: 0 (audit) + 9 (implementation)  
**Pull requests**: PR #56 (audit) → PR #57 (S1 + S2) → PR #58 (S3 + S4) → PR #59 (S5 + S6) → PR (S7 + S8 + S9)  
**Net source diff**: ~1500 lines across `js/coaching.js`, `styles.css`, `index.html`  
**Backend changes**: zero  
**Public-surface regressions**: zero
