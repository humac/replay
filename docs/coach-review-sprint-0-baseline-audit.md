# Coach Review — Sprint 0 Baseline Audit

**Sprint:** 0 of [`docs/coach-review-ui-ux-implementation-plan.md`](coach-review-ui-ux-implementation-plan.md)
**Status:** audit only — no product behavior changed
**Captured:** 2026-05-02 against branch `claude/fervent-mcclintock-ed40c1`
**Tools:** Playwright (`tests/e2e/sprint-0-baseline.spec.js`), Chromium 1217, seeded
SQLite at `/tmp/replay-sprint0-data` via `docs/_seed/seed.py` + `/tmp/seed_coaching.py`

The goal of Sprint 0 is to record the *before* state so Sprints 1–9 have something
concrete to compare against. This document is a freeze of the existing layout's
dimensions, the selectors and methods that drive it, and the specific gaps that the
redesign needs to close. **No source files were edited.**

---

## 1. Capture environment

| Setting | Value |
|---|---|
| App | `uvicorn server:app --host 127.0.0.1 --port 8090` |
| Python venv | `/tmp/replay-venv` (uv, Python 3.14.4, requirements.txt) |
| Data dir | `/tmp/replay-sprint0-data` (isolated; not the user's real archive) |
| Seed scripts | `docs/_seed/seed.py` then `/tmp/seed_coaching.py` |
| Coach login | `coach1 / Replay!Demo123` |
| Family login | `family1 / Replay!Demo123` (linked to "Ava Player" #7) |
| Seeded match used | `e6bee436-d568-422e-a2a4-cc1339c86a12` ("Riverside FC vs Westwood Albion · Oct 12, 2025") |

**Seed contents satisfy the Sprint 0 baseline checklist:**

- 12 matches (DB rows; no real video files — irrelevant for layout audit)
- 4 roster players (Ava #7, Liam #9, Mia #1, Noah #8)
- 7 coaching notes spread across 2 matches (5 on the audit match, 2 on a two-half match)
- 1 player-visibility playlist ("Ava — week 1 review") with 3 items
- 1 family↔player link (`family1` → Ava Player, relationship `guardian`)

---

## 2. Screenshots captured

All saved to [`docs/screenshots/sprint-0-baseline/`](screenshots/sprint-0-baseline/):

### Coach Review — five widths × two crops each

| Width | Top crop | Full page |
|---|---|---|
| 1920 px wide | [`coach-review-1920-wide-top.png`](screenshots/sprint-0-baseline/coach-review-1920-wide-top.png) | [`...-fullpage.png`](screenshots/sprint-0-baseline/coach-review-1920-wide-fullpage.png) |
| 1440 px desktop | [`coach-review-1440-desktop-top.png`](screenshots/sprint-0-baseline/coach-review-1440-desktop-top.png) | [`...-fullpage.png`](screenshots/sprint-0-baseline/coach-review-1440-desktop-fullpage.png) |
| 1024 px laptop | [`coach-review-1024-laptop-top.png`](screenshots/sprint-0-baseline/coach-review-1024-laptop-top.png) | [`...-fullpage.png`](screenshots/sprint-0-baseline/coach-review-1024-laptop-fullpage.png) |
| 768 px tablet | [`coach-review-768-tablet-top.png`](screenshots/sprint-0-baseline/coach-review-768-tablet-top.png) | [`...-fullpage.png`](screenshots/sprint-0-baseline/coach-review-768-tablet-fullpage.png) |
| 390 px mobile | [`coach-review-390-mobile-top.png`](screenshots/sprint-0-baseline/coach-review-390-mobile-top.png) | [`...-fullpage.png`](screenshots/sprint-0-baseline/coach-review-390-mobile-fullpage.png) |

### Adjacent surfaces (1440 px)

These are captured so Sprint-N can verify they're unchanged.

| Surface | File |
|---|---|
| Public season page | [`public-season-1440.png`](screenshots/sprint-0-baseline/public-season-1440.png) |
| Coach > Roster | [`coach-roster-1440.png`](screenshots/sprint-0-baseline/coach-roster-1440.png) |
| Coach > Notes | [`coach-notes-1440.png`](screenshots/sprint-0-baseline/coach-notes-1440.png) |
| Coach > Playlists | [`coach-playlists-1440.png`](screenshots/sprint-0-baseline/coach-playlists-1440.png) |
| /feedback?tab=notes (family1) | [`feedback-notes-1440.png`](screenshots/sprint-0-baseline/feedback-notes-1440.png) |
| /feedback?tab=playlists (family1) | [`feedback-playlists-1440.png`](screenshots/sprint-0-baseline/feedback-playlists-1440.png) |

Capture script: [`tests/e2e/sprint-0-baseline.spec.js`](../tests/e2e/sprint-0-baseline.spec.js)

Re-run with:
```bash
cd tests/e2e
PLAYWRIGHT_BASE_URL=http://127.0.0.1:8090 npx playwright test sprint-0-baseline.spec.js
```

---

## 3. Measured layout dimensions

Captured via `getBoundingClientRect()` from inside the test. All values in CSS pixels.

### 1920 px (wide monitor) — `coach1`, Review tab, match selected

| Element | Width | Height | Top |
|---|---|---|---|
| viewport | 1920 | 1080 | — |
| `.coach-subnav` | 1180 | 52 | 278 |
| `.coach-review-shell` | 1180 | 1299 | 347 |
| `.coach-review-picker` | 1138 | 118 | 364 |
| `.coach-review-grid` | 1138 | 1131 | 498 |
| **video** `#coach-review-video` | **743** | **417** | 499 |
| `.coach-review-wrapper` | 745 | 419 | 498 |
| **side panel** `.coach-review-side` | **373** | 1131 | 498 |
| `#coach-review-toolbar` | 373 | 251 | 532 |
| `#coach-review-form` | 373 | 428 | 830 |
| `#coach-review-notes` | 373 | 311 | 1318 |
| chrome above video | — | **498 px** | — |

### 1440 px desktop

Identical to 1920 because the shell maxes out at `1180 px` and is centered. Video
remains **743 × 417**, side panel **373 × 1131**, video/side ratio ≈ **2 : 1** (66 / 34 %).

### 1024 px laptop

| Element | Width | Height |
|---|---|---|
| viewport | 1024 | 768 |
| `.coach-review-shell` | 928 | 1340 |
| `.coach-review-grid` | 886 | 1172 |
| **video** | **575** | **323** |
| **side panel** | **289** | 1172 |
| chrome above video | — | 498 px |

Video/side ratio still ~2 : 1 but with the side panel down to 289 px controls become
cramped. Video height is only 323 px — barely usable for telestration on a 768-tall
viewport that already burned 498 px on header chrome.

### 768 px tablet

Layout collapses to a **single column**. Video drops below the slot picker and is
**676 × 379**. Toolbar is now a 678-wide horizontal row that extends below the video.
Side panel becomes 678 × 1269 (full width). Total page height is **1939 px** —
significant scrolling for any authoring action.

### 390 px mobile

Single column. Video is 311 × 174. **Chrome above the video is 737 px** because the
intro paragraph + subnav + match/slot picker all stack. Total page height: 1759 px.
Realistically unusable for note authoring on phone, but acceptable as a "view from
the sideline" surface.

---

## 4. Existing selectors and JS methods that drive the layout

These are the targets that Sprint 1+ will modify. Confirmed present and bound at
audit time.

### HTML (in [`index.html`](../index.html))

```
#coach-view
  .options-title.eyebrow ("COACH")        ← visual eyebrow
  h2 ("Coaching workspace")               ← chrome the redesign should shrink
  p (intro paragraph)                     ← chrome the redesign should shrink
  nav.coach-subnav (4 buttons: Roster | Notes | Playlists | Review)
  #coach-tab-review.coach-tab-panel
    .options-card.coach-review-shell      ← outer card; padding 1rem 1.25rem
      .coach-review-picker                ← form-style block to compact in Sprint 2
        select#coach-review-match  onchange="app.handleCoachReviewMatchChange()"
        select#coach-review-slot   onchange="app.handleCoachReviewSlotChange()"
      .coach-review-grid                  ← target for video-first grid (Sprint 1)
        .coach-review-video
          .player-wrapper.coach-review-wrapper
            video#coach-review-video      ← stable id; do not rename
            #coach-review-empty           ← absolute-positioned empty state
        aside.coach-review-side
          h4 "Telestrator"
          #coach-review-toolbar           ← target for icon-first toolbar (Sprint 3)
          h4 "Save note at current time"
          #coach-review-form.coach-mini-form  ← target for fast composer (Sprint 4)
          h4 "Notes for this match"
          #coach-review-notes.coach-panel-notes ← target to move into rail (Sprint 5)
```

### JS (in [`js/coaching.js`](../js/coaching.js))

| Method | Line | What |
|---|---|---|
| `setCoachTab(name)` | 120 | Activates a sub-tab; calls `renderCoachReview()` when name is `review` |
| `renderCoachReview()` | 526 | Top-level Review render: picker, toolbar, form, notes |
| `renderCoachReviewPicker()` | 517 | Populates `#coach-review-match` options |
| `loadCoachReviewVideo(matchId, slot, seekTo, drawing)` | 574 | Sets HLS/MP4 source, seeks, repaints drawing |
| `renderCoachReviewForm()` | 636 | innerHTML of `#coach-review-form` |
| `renderCoachReviewNotes(matchId)` | 604 | innerHTML of `#coach-review-notes` |
| `renderCoachTelestratorToolbar()` | 700 | Toolbar HTML string |
| `setupCoachCanvas()` | 733 | window.resize + video.loadedmetadata listeners + pointer events |
| `_resizeCoachCanvas(canvas, video)` | 751 | Resets canvas bitmap size from video bounding rect |
| `paintCoachCanvas()` | 972 | Re-paint loop for v1/v2/formation drawings |
| `renderCoachDrawing(drawing)` | 631 | Apply a saved drawing |
| `normalizeCoachDrawing(drawing)` | 794 | v1 → v2 in-memory migration |
| `handleCoachReviewMatchChange()` | 561 | onchange handler for `#coach-review-match` |
| `handleCoachReviewSlotChange()` | 568 | onchange handler for `#coach-review-slot` |
| `seekCoachReviewNote(note)` | 624 | Click handler for an existing note row |
| Tool/state mutators | various | `setCoachDrawingTool`, `setCoachDrawingColor`, `setCoachDrawingWidth`, `toggleCoachDrawing`, `undoCoachDrawing`, `deleteSelectedCoachObject`, `clearCoachDrawing` |

Private state on the coaching mixin (do not collide):
`_coachVideoId`, `_coachCanvasId`, `_coachDrawing`, `_coachDrawingTool`,
`_coachDrawingColor`, `_coachDrawingWidth`, `_coachDrawingActive`,
`_coachSelectedObjectIndex`, `_coachFormation`.

### CSS (in [`styles.css`](../styles.css))

The Coach Review block starts around line **6160**. Key rules observed:

```css
.coach-review-shell { padding: 1rem 1.25rem; }
.coach-review-grid {
    display: grid;
    grid-template-columns: minmax(0, 2fr) minmax(280px, 1fr);  /* current 2:1 */
    gap: 1.25rem;
}
.coach-review-side { display: grid; gap: 0.85rem; align-content: start; }
```

Toolbar chrome:

```css
.coach-tool-grid { display: grid; grid-template-columns: repeat(...); }   /* labelled buttons */
.coach-tool-row { display: flex; gap: 0.5rem; }                            /* color + width row */
```

There is **no `.coach-tool-btn` rule yet** — Sprint 3's pointer-aware sizing will need to
introduce one and replace the current `.mini-action-btn` + `.coach-tool-grid` mix.

---

## 5. Gaps the redesign needs to close

Comparing measured baseline against the Sprint 1–9 target:

| Target (from plan) | Baseline | Gap |
|---|---|---|
| Video ~70–80 % of available width | **65 %** at 1440/1920 (743 of 1138) | Tighten grid to `minmax(0, 1fr) 340px`; raise side panel min from 280 → 340 with a hard cap |
| Side panel 320–360 px fixed | **373 px** at 1440 (acceptable), **289 px** at 1024 (too narrow) | Switch from fractional to fixed `340px` so 1024 keeps usable width |
| Side panel scrolls independently | scrolls with page | Add `max-height: calc(100vh - 180px); overflow: auto;` |
| Compact match/slot top bar | **118 px** form block consuming a full row above video | Sprint 2 — convert to inline horizontal toolbar |
| Outer shell padding < 1rem | `1rem 1.25rem` (already close) | Tighten to `0.75rem 1rem` in Review mode |
| Chrome above video | **498 px** at 1440 (header 100 + intro 150 + subnav 70 + picker 178) | Sprint 1 — collapse intro in Review mode; Sprint 2 — fold picker into top bar; target ~200 px |
| Icon-first toolbar (34 px) | text-labelled `.mini-action-btn` (~32 × ~84 px each) | Sprint 3 — refactor to icon buttons + grouped sections |
| Touch ≥44 px under `pointer: coarse` | not enforced — same buttons everywhere | Sprint 3 — add pointer-aware media query |
| Fast note composer with collapsed advanced | all 6 fields + tags + button always shown (form height **428 px**) | Sprint 4 — collapse visibility/tags/body |
| Timeline rail under video | vertical list **373 × 311 px** in the right panel | Sprint 5 — relocate to under-video horizontal rail |
| Focus mode toggle | not present | Sprint 6 |
| Keyboard shortcuts | none in Review specifically | Sprint 7 |
| ARIA: `aria-pressed` on tools, `aria-label` + `title` on icons | tools render plain `<button class="mini-action-btn">` | Sprint 3 / 8 — emit aria during render |
| ResizeObserver on wrapper | only window.resize + loadedmetadata | Sprint 1 — add observer when side panel becomes scrollable |

### Specific rendering observations during audit

1. **Player checklist box has internal scrollbar** that exposes native chrome at narrow widths
   — visible in the 1920 mid-form screenshot (3 of 4 players visible, 4th cut off with an
   unstyled scrollbar gutter). Sprint 8 a11y polish should style this scrollbar consistently
   with the rest of the app, per the user's standing memory rule.
2. **Notes list rows use 3 lines each** ("12:42 · Full / Match / Title"). At 5 notes the
   list is 311 px tall; at 20+ it would dominate the right panel. The rail (Sprint 5) should
   flatten each to a 1-line chip.
3. **Empty-state message** "Pick a match above to start authoring notes." renders inside the
   video wrapper as `position: absolute` on a black background — keep this semantic when
   moving the picker into a top bar.
4. **Coach review video element shows native `<video>` controls** including the kebab menu
   in the bottom-right (visible in screenshots). This is the standard player surface and
   must be preserved through the redesign.
5. **`Save Note` button** is a full-width rectangle inside the form; Sprint 2 needs to add a
   compact duplicate to the top bar without removing the form button.

---

## 6. Privacy/role baseline (sanity check, not a behavior change)

Verified via the captured `/feedback` screenshots (logged in as `family1`):

- **family1** sees the playlist `Ava — week 1 review` (visibility=`player`) ✓
- **family1** sees the team-visible notes from the audit match ✓
- **family1** does NOT see the `private` note ("Goalkeeper distribution") as a standalone
  feedback row ✓
- The public match page renders the standard VOD UI; no coach panel/canvas ✓

These confirm the redesign will start from a working privacy baseline — Sprints 4–6 must
not regress this.

---

## 7. Verification

Static gate at audit time (re-run after every sprint):

```bash
node --check script.js js/coaching.js js/player.js js/api.js   # OK
python3 -m py_compile server.py media.py models.py db.py auth.py settings.py uploads.py live.py streams.py log.py   # OK
pytest tests/test_coaching.py -v                                # 7 / 7 passed
pytest tests/ -v --cov ...                                      # green
```

Source-code git status during audit: **clean** (only this doc + `tests/e2e/sprint-0-baseline.spec.js` + `docs/screenshots/sprint-0-baseline/*.png` are new). No `js/`, `index.html`, or `styles.css` files were modified.

---

## 8. Recommended starting point for Sprint 1

Sprint 1 ("Video-first Coach Review layout") should land:

1. A new `is-review-mode` class added to `#coach-view` (or `#coach-tab-review`) when the
   Review tab is active.
2. Conditional CSS that, when this class is present, shrinks the page intro
   (`.options-title` + `h2` + the intro paragraph) to ~30–50 px total.
3. `.coach-review-grid { grid-template-columns: minmax(0, 1fr) 340px; gap: 0.85rem; }` —
   raises the video share from ~65 % to ~75 % at 1440 px.
4. `.coach-review-side { max-height: calc(100vh - 180px); overflow: auto; }` for an
   independently scrolling inspector.
5. A `ResizeObserver` on `.coach-review-wrapper` registered in `setupCoachCanvas()` and
   torn down in `teardownCoachCanvasListeners()` — the existing window.resize listener will
   no longer fire reliably once the inspector scrolls independently. (See
   [`.agent-skills/video-hls-canvas-overlay.md`](../.agent-skills/video-hls-canvas-overlay.md)
   for the exact pattern.)
6. Keep all selectors and methods listed in §4 above. Don't rename them.

Sprint 1 acceptance test against this baseline:

- Re-run `tests/e2e/sprint-0-baseline.spec.js` after the change.
- Compare `dims` output: video width should rise from 743 → ~810+ at 1440; side panel
  should drop from 373 → ~340; chrome-above-video should drop from 498 → ~250.
- Mobile (390 px) layout must remain a single column with the video still visible above
  the inspector — no horizontal overflow.
- Coach Notes / Playlists / public match page / `/feedback` screenshots must remain
  visually unchanged at 1440 px (compare against the adjacent-surfaces baseline above).
