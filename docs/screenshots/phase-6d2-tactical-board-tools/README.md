# Phase 6d-2 — Tactical board authoring tools

Screenshots of the new game format / formation selectors, zone resize
handles, telestrator-aligned tool icons, the updated keyboard shortcut
popover, and a mobile layout check.

All shots come from the **live dev server** at `http://localhost:8090`
seeded with `docs/_seed/seed.py` (coach1 / family1, password
`Replay!Demo123`).

Reproduce all screenshots with:

```bash
cd tests/e2e && npm run capture-phase-6d2
```

The npm script runs in single-worker serial mode to avoid the per-IP
login rate limit in `auth.py`.

| File | Role/account | Surface | What it proves |
| --- | --- | --- | --- |
| `01-tactical-board-format-formation-controls.png` | coach1 | Coach > Review (Tactical Board) | Empty board with the new game-format / formation selector + Apply Formation button mounted in the side panel. |
| `02-7v7-2-3-1-formation.png` | coach1 | Coach > Review (Tactical Board) | 7v7 → 2-3-1 applied — 7 player tokens (GK + 2 backs + 3 mids + 1 forward) placed in normalized pitch positions. |
| `03-9v9-3-2-3-formation.png` | coach1 | Coach > Review (Tactical Board) | 9v9 → 3-2-3 applied — 9 player tokens placed. |
| `04-11v11-4-3-3-formation.png` | coach1 | Coach > Review (Tactical Board) | 11v11 → 4-3-3 applied — 11 player tokens placed. |
| `05-zone-resize-handles.png` | coach1 | Coach > Review (Tactical Board) | Selected zone shows eight resize handles (4 corners + 4 edge midpoints). Coach drags a handle to resize; values persist as normalized x/y/w/h. |
| `06-tactical-shortcuts-popover.png` | coach1 | Coach > Review (Tactical Board) | Updated shortcuts popover lists the new tactical-mode shortcuts: V/P/B/A/L/Z/F/T plus Delete/Esc/?. |
| `07-mobile-390-tactical-board.png` | coach1 | Coach > Review (Tactical Board) | 390 px viewport — tactical toolbar wraps to a single column, formation controls span full width, board keeps its aspect ratio. |
| `08-light-mode-11v11-4-2-3-1.png` | coach1 | Coach > Review (Tactical Board) | Light mode — formation tokens, tools, and resize handle styles read cleanly with the same icon set. |
| `09-saved-observation-with-formation.png` | coach1 | Coach > Notes | Saved observation surfaces in Coach > Notes with the board preview rendering the saved 4-3-3 — proves the metadata round-trips end-to-end. |
| `10-color-swatches-and-colored-shapes.png` | coach1 | Coach > Review (Tactical Board) | Color-parity follow-up: side panel renders the same six color swatches as the video telestrator (`#38bdf8` / `#f97316` / `#22c55e` / `#facc15` / `#f43f5e` / `#ffffff`) with the active swatch (`#f97316`) outlined; pitch carries one shape per palette color so saved per-shape `color` metadata is visible. |
| `11-stroke-width-control-and-thicknesses.png` | coach1 | Coach > Review (Tactical Board) | Thickness-parity follow-up: the W slider (range 2–10) sits beside the swatch row, mirroring the video telestrator. Pitch shows five horizontal lines with stroke_widths 2 / 4 / 6 / 8 / 10 — proves per-shape `stroke_width` metadata round-trips and renders. |

## Seeded data assumptions

Every shot uses the seeded `coach1` account from `docs/_seed/seed.py`.
No fixtures or new seed scripts were added for Phase 6d-2.

## Notes

- Shots `02` / `03` / `04` are taken with an **empty board** before
  applying — the Apply Formation button does not show a confirm prompt
  because no player tokens existed.
- Shot `05` uses an in-spec scene fixture (zone + arrow + a couple of
  player tokens) so the resize handles render against real shapes.
  The eight yellow squares are the resize anchors.
- Shot `09` is captured AFTER pressing `#coach-review-save-observation`
  with `formation: "4-3-3"` and `game_format: "11v11"` in the saved
  payload, then navigating to `/coach?tab=notes`. The thumbnail shown
  in the list comes from the saved board scene; metadata round-trip
  is also covered by `tests/test_coaching.py`.
