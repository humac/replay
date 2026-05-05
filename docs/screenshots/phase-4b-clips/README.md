# Phase 4b — Clip authoring + viewer playback screenshots

Captured against the `replay-dev` Claude Preview at commit `42fc821`
(Phase 4b branch) with 4 seeded clips at varied visibility levels:
team / player-only (Alex Park) / private. The video is the same SMPTE
test-pattern source we used for Phase 3b — the color-bar imagery is
ffmpeg's test source, not real footage.

## Inventory

| File | What it shows |
|---|---|
| `coach-clips-list-dark.png` | Coach > Clips sub-tab with 4 clip rows (admin sees private + team + player) — meta + edit/delete/preview actions |
| `coach-clips-list-light.png` | Same surface in light mode |
| `coach-review-save-clip-button.png` | Coach Review picker bar with the new "Save Clip" button next to "Save Note" |
| `coach-clip-composer-modal.png` | The clip composer modal opened from Coach Review — pre-filled `start = currentTime − 5s`, `end = currentTime + 8s`, live duration label, category select, player check-list, visibility |
| `feedback-clips-desktop.png` | My Feedback > Clips tab as `phase3b_viewer` (linked to Alex Park). Shows team clips + Alex's player-only clip. Private clip correctly hidden. |
| `feedback-clips-mobile.png` | Same surface at 390 × 844 — `feedback-card--with-thumb` grid stacks the thumb on top |
| `feedback-clip-playback-modal.png` | Focused feedback player modal opened to the "Shape collapses on the switch" clip. Subtitle shows `match · slot · start–end · duration`. |

## Behaviors verified by these captures

- **Coach Clips list** sorts newest-first by `updated_at`, shows match · slot · window · duration · category · visibility · player count, plus a "From note" badge when `source_note_id` is set.
- **Save Clip** picker-bar button pre-fills `[currentTime − 5s, currentTime + 8s]` (capped at 120 s).
- **Clip composer** validates window invariants live (duration label goes red on `end <= start` or duration > 120 s).
- **Visibility filter** — `phase3b_viewer` (linked to Alex Park) sees team clips + Alex's player-only clip; the `private` clip is correctly hidden.
- **Mobile breakpoint** — `feedback-card--with-thumb` grid stacks the tile above the body at ≤ 720 px.
- **Focused clip playback** — modal shows clip title, match/slot/window/duration subtitle, optional player-friendly description, and the seeked video at the start of the clip window. The end-of-window watcher (`_clipMonitor`) pauses at `end_seconds`.

## Re-capturing

Once Phase 4b is deployed against real soccer footage, re-run a
similar seeding pass (the coach can use the new "Save Clip" button
directly in Coach Review). The CSS / layout contract is the same;
only the tile imagery changes.
