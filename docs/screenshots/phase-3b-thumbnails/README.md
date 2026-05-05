# Phase 3b — Coach-note thumbnail screenshots

This directory holds the visual-regression screenshots for the
Phase 3b UI integration. They are captured **manually** from a running
instance because the automated test path uses stubbed JPEGs (1×1 pixel)
that aren't useful for visual review.

## How to capture

1. Boot the app locally (Docker compose or `python server.py`) with a
   seeded dataset that contains:
   - At least one full match with a finished `full.mp4` so the source
     video exists.
   - At least one two-half match (`first_half.mp4` + `second_half.mp4`).
   - At least 5 coaching notes spread across 2–3 matches so the
     timeline rail and Notes list are interesting.
   - At least 1 review playlist with 3+ notes so the playlist row's
     stacked thumbnail strip and `+N` overflow chip both appear.
   - At least 1 viewer linked to a player who is tagged on a
     `visibility="player"` note.
   - At least 1 `visibility="private"` note that the viewer can NOT see
     (so the "missing-thumbnail placeholder" screenshot has a real
     example to capture).
2. From a coach account, open `/coach?tab=notes`, `/coach?tab=playlists`,
   `/coach?tab=review&match=<id>`. Capture each surface in dark mode
   and again in light mode (Settings → toggle theme).
3. From a viewer account linked to a player, open `/feedback?tab=notes`
   and `/feedback?tab=playlists`. Capture desktop (≥ 1280 px) and
   mobile (390 px DevTools emulation).
4. Save as PNG into this directory using the filenames listed below.

## Files expected

| Filename | What it should show |
|---|---|
| `coach-notes-list-dark.png` | Coach Notes tab with thumbnail tiles + ↻ Regenerate action visible |
| `coach-notes-list-light.png` | Same surface in light mode |
| `coach-review-rail.png` | Coach Review with the timeline chip rail showing thumbnails on chips |
| `coach-playlists-list.png` | Coach Playlists tab with stacked thumbnail strips + `+N` overflow chip |
| `feedback-notes-desktop.png` | My Feedback Notes cards with thumbnail tiles, desktop |
| `feedback-notes-mobile.png` | Same surface at 390 px (thumbnail stacks on top) |
| `feedback-playlists-desktop.png` | My Feedback Playlists with cover thumbnails |
| `feedback-playlist-session-rail.png` | Focused playlist player modal with active-item thumbnail in the rail |
| `placeholder-state.png` | A surface where a note has no thumbnail (placeholder visible) — coach view of a note created before its match's video uploaded |

## Why these aren't auto-generated

The test suite uses a stubbed `_media.generate_thumbnail_at_timestamp`
that writes a 4-byte `\xff\xd8\xff\xd9` JPEG so file-existence checks
pass — that's enough to verify the auth/visibility model but produces
a pure black tile that's useless for reviewing layout.

A meaningful "before/after" capture pass requires a real ffmpeg
extracting actual video frames, which means a real seeded dataset that
the CI environment doesn't provide.
