# Phase 3b — Coach-note thumbnail screenshots

Captured against the `replay-dev` Claude Preview environment on commit
`e9c0448` (Phase 3b branch) with a 2-minute SMPTE-test-pattern source MP4.
The color-bar imagery in the tiles is from that test source — in
production the tiles show real frames extracted by ffmpeg at each
note's timestamp.

## Inventory

| File | What it shows |
|---|---|
| `coach-notes-list-dark.png` | Coach Notes tab in dark mode — every row has a 120×68 thumbnail tile with timestamp chip + ↻ Regenerate action button |
| `coach-notes-list-light.png` | Same surface in light mode — placeholder + tile + chip all themed correctly |
| `coach-review-rail.png` | Coach Review cockpit at full height — video + telestrator + timeline chip rail with thumbnails |
| `coach-review-rail-zoom.png` | Tight zoom on the timeline rail showing thumbnail + timestamp + player indicator + category dot + truncated title for each chip |
| `coach-playlists-list.png` | Coach Playlists tab full-page — three playlists with mixed thumbnail-strip + placeholder states |
| `coach-playlists-zoom.png` | Tight zoom on the playlist rows — "Match recap" shows a stacked 3-tile strip; "Player #7 development" shows a single-tile strip; "First-half tactical lessons" shows the placeholder strip (notes pre-date the seeded video) |
| `feedback-notes-desktop.png` | My Feedback Notes (viewer perspective) — 220px-thumbnail-left + body-right grid, mixing real tiles and a placeholder card |
| `feedback-notes-mobile.png` | Same surface at 390×844 — thumbnail stacks on top per the 720px breakpoint |
| `feedback-playlists-desktop.png` | My Feedback Playlists (viewer perspective) — "Match recap" shows the cover thumbnail, "First-half tactical lessons" shows the placeholder |
| `feedback-playlist-session-rail.png` | Focused playlist player modal mid-session — active-item thumbnail in the rail |
| `feedback-playlist-session-rail-zoom.png` | Tight zoom on the rail showing the rail-variant tile (80×45) + session metadata + tone pill + player_summary |
| `placeholder-state.png` | Coach Notes list with a "Demo: thumbnail placeholder" note at top — proves a note created against a match WITHOUT a source video shows the film-strip glyph cleanly next to notes that DO have thumbnails |

## How these were captured

- The Phase 3b worktree was hot-reloaded into the `replay-dev` Claude Preview
  on port 8090 (`/tmp/replay-sprint1-data`) by detaching `HEAD` to the
  `claude/coaching-thumbnails-phase-3b` commit; uvicorn's `--reload` flag
  picked up the swap automatically.
- A 2-minute test-pattern MP4 was generated via `ffmpeg lavfi` and uploaded
  to one of the existing matches via the chunked-upload API.
- Six coaching notes (5 visible + 1 private with a coach-only note) were
  seeded at varied timestamps via `POST /api/coach/notes`. The Phase 3a
  background generator ran automatically and produced one JPEG per note.
- A review playlist of 5 notes was created.
- A viewer account (`phase3b_viewer`) was created and linked as parent of
  player Alex Park (#7), so the player-only note "Alex – improve first
  touch direction" surfaces in My Feedback for that account.
- Screenshots were captured with Playwright in headless Chromium at
  1440×900 desktop and 390×844 mobile.

## Re-capturing on a real environment

Once Phase 3b is deployed against real soccer footage, re-run a similar
seeding pass and re-capture for the README — the layout/CSS contract is
the same, only the tile imagery changes.
