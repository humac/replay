# Design Report — Coaching Platform UX Restructure

## Executive Summary

The Coaching Platform's UI was reorganized into focused, intent-driven surfaces: `/coach` is now a sub-tabbed workspace (Roster · Notes · Playlists · Review) with a video player + telestrator built into the **Review** tab as the *single* note authoring surface, and `/feedback` is a clean Playlists/Notes split that watches feedback in a focused in-page modal player rather than punting players to the full match VOD page. The in-match coach side panel and its toggle were removed entirely. No backend, API, or data-model change.

## Audit Findings

### Critical (single-surface clarity, accessibility)

- **Notes could be authored in two unrelated places.** The Coach tab had a no-video form that forced timestamp typing; the match page had a hidden side panel with the telestrator. Recent regressions (commits `b542b62`, `8c72aaa`, `cadf1b0`, `060a65a`) all stemmed from toggling this side panel correctly.
- **Players were navigated *out* of `/feedback` to consume feedback.** Clicking a note's *Watch* called `openMatch()` and seeked the full-match `<video id="game-video">` — visually identical to "watching the whole game" and noisy for parents.
- **No semantic per-tab URL state.** Refreshing or sharing a deep link could not target the right sub-area; the workspace was one giant page.

### Major (visual hierarchy, scanability)

- **Coach workspace was four heavy form-style cards stacked on one page** (Roster, Account Links, Note builder, Playlist builder) — long scroll, no primary action per area, hard to find anything.
- **Notes/Playlists rows mixed with the always-open form** that created them — the form dominated the viewport; the actual list was below the fold.
- **Feedback rendered each note's drawing canvas inline**, bloating the page and giving every row a video-shaped placeholder even before clicking Watch.

### Minor (polish, consistency)

- Linked Players appeared as a full card on `/feedback` for what is, at most, a one-line piece of context.
- Playlist preview from the coach side hijacked `/match/{slug}` and appended a session rail onto `.player-wrapper` — context-shift identical to the player flow.

## Design System Touches

This work reused existing tokens — no new colours or fonts. New primitives added:

- `.coach-subnav` / `.coach-subnav-btn` — pill-style sub-tab strip, mirrors the `.btn-head` visual language so it matches the admin shell.
- `.coach-tab-panel` — visible on `[hidden]` removal with a 180ms fade.
- `.coach-review-shell` / `.coach-review-grid` — two-column shell on ≥1024 px (video / telestrator + note form), single column under that.
- `.feedback-linked-strip` / `.feedback-linked-pill` — compact chip strip for linked players.
- `.feedback-player` / `.feedback-player-wrapper` / `.feedback-player-rail` — focused modal player chrome.

Removed primitives:

- `.coach-mode-bar`, `.coach-mode-toggle`, `.coach-match-panel`, `.sidebar.coach-mode-on …` — the in-match coach side panel and its toggle.
- `.coach-playlist-session` (the absolutely-positioned overlay rail that was appended to `.player-wrapper` of the match page).

## Changes Made

### Screen: `/coach` — Coaching Workspace

**Before:** four tall stacked cards on one page (Roster, Account Links, New Note, New Playlist), no hierarchy.

**After:** sub-tabbed shell with `?tab=` deep links.

- **Roster** (default): Roster card + Account Link card side-by-side on ≥1024 px. Verified: roster items render with linked-account chips, delete + add work.
- **Notes** (`?tab=notes`): list-first layout, `+ NEW NOTE` button mounts the form modal cloned from `<template id="coach-note-form-template">`. Each row exposes **Open in Review** (jumps to the Review tab pre-loaded), **Edit**, **Delete**.
- **Playlists** (`?tab=playlists`): same pattern with `+ NEW PLAYLIST` and per-row **Preview** (opens the focused player), **Edit**, **Delete**.
- **Review** (`?tab=review[&match=…&slot=…]`): match picker + slot selector header, two-column shell with the video on the left and the telestrator + "Save note at current time" form on the right. This is the *single* note authoring surface — no more match-page side panel.

**Verified in browser:** all four tabs render, switch via JS click, persist to `?tab=` query string, match picker change updates URL to `?match=…&slot=…`, telestrator tools (8 tools, 6 colours, width slider, Canvas On/Off, Undo, Delete, Clear) all rendered.

### Screen: `/feedback` — My Feedback (player/family)

**Before:** one long stack — Linked Players card → Playlists list → Notes list → inline canvas overlays per note → *Watch* navigates to `/match/{slug}`.

**After:** sub-tabbed shell with `?tab=` deep links.

- Header: **LINKED PLAYERS:** chip strip (compact, single line for typical cases) — no more whole card.
- Sub-tabs: **Playlists** (default) and **Notes**.
- Each item exposes a primary `PLAY` / `WATCH` button + secondary `MARK REVIEWED` toggle.
- *Watch* and *Play* now open a **focused feedback player modal** that loads the per-slot HLS via the existing `getStreamUrls()` helper, seeks to the note timestamp, paints the drawing overlay, and runs a 10 s heartbeat against `/api/matches/{id}/heartbeat?slot=…` so admin-kill still propagates. **The page never navigates to `/match/{slug}`.**

**Verified in browser:** logged in as `family1` (linked to Ava Player). The team-visible Riverside note + the player-tagged Riverside note appear; the player-tagged Eastside note for Liam correctly does *not* appear. Watch opens the modal in-place; URL stays `/feedback?tab=notes`.

### Screen: `/match/{slug}` — Public match VOD

**Before:** match page stacked the in-match coach panel + canvas + mode-toggle bar inside the sidebar and on top of the video, regardless of role.

**After:** clean VOD surface for everyone. Coaches/admins get a single header link **"Coach this match in Review →"** (`#coach-this-match-link`, `updateCoachThisMatchLink()`) that deep-links to `/coach?tab=review&match={id}&slot={current}`.

**Verified in browser:** match page renders without the coach panel/toggle/canvas; the deep-link is visible to admin and clicking it lands on the Review tab pre-loaded with the right match — true one-click handoff between "watching" and "authoring."

## Accessibility Improvements

| Issue | Fix | WCAG Criterion |
|---|---|---|
| Coach sub-nav buttons had no roles or selected-state announcement | `role="tablist"` on the nav, `role="tab"` + `aria-selected` on each button | 4.1.2 Name, Role, Value |
| `[hidden]` panels still allowed pointer interaction in past iterations | Each `.coach-tab-panel` uses native `[hidden]` (full DOM hide, removes from a11y tree) | 1.3.1 Info & Relationships |
| Modal forms cloned from `<template>` ID-collision-free | Form inputs use `data-field="..."` lookups, not duplicated IDs across multiple modal instances | 1.3.1 Info & Relationships |
| Coach Review form fields have explicit `<label>` text | Every field in `coach-note-form-template` and the inline Review form uses `<label>...</label>` siblings | 3.3.2 Labels or Instructions |

Native focus rings preserved; `:focus-visible` accent outline added to `.coach-subnav-btn`.

## Removals (intentional)

- `renderCoachingPanel()`, `renderCoachTelestratorToolbar()` (now lives only as the Review-tab toolbar render), `toggleCoachMode()`, `setupCoachModeToggle()`, `_coachModeOn` state.
- `#coach-match-panel`, `#coach-mode-bar`, `#coach-mode-toggle` and their CSS.
- The in-match `<canvas id="coach-drawing-canvas">` overlay on `.player-wrapper`.
- The match-page `.coach-playlist-session` rail (playlist sessions now run in the focused modal).
- Stale `setupCoachModeToggle?.()` / `renderCoachingPanel?.()` calls in `js/api.js` `setLoggedIn` / `setLoggedOut` / `handleLogin`.

## Routing

- `/coach?tab=roster|notes|playlists|review` (default `roster`); Review additionally accepts `&match={id}&slot={full|first_half|second_half}` for deep linking.
- `/feedback?tab=playlists|notes` (default `playlists`).
- `script.js` `initializeHistory` and `restoreHistoryState` honour the new query strings on first load and on popstate.

## Validation

- `python3 -m py_compile` on all backend modules — clean.
- `node --check` on every touched JS file — clean.
- `pytest tests/ -v --cov --cov-report=term-missing --cov-fail-under=60` → **262 passed, coverage 64.37%**.
- Manual UX walkthrough captured in this report.

## Remaining Recommendations

These were intentionally out of scope for this round but would build naturally on the new shell:

1. **Drag-to-reorder playlist items** in `openCoachPlaylistModal` (today the order is the multi-select pick order).
2. **Saved coach review state** so a coach who closes the tab mid-authoring returns to the same match/slot/timestamp.
3. **Per-note thumbnail** on the Notes/Playlists rows once thumbs-at-timestamp is available — would dramatically improve scanability without canvas-per-row overhead.
4. **Keyboard shortcuts in the Review tab**: `Space` for play/pause, `←/→` for ±1 s seek, `S` to save the note. Surfaces quickly because the player + form share the panel.
5. **"Coach this clip" deep link from a player's `/feedback` modal** — would let a coach jump from a child's feedback view straight back into authoring on the same moment. Trivial once the URL convention is in place.
