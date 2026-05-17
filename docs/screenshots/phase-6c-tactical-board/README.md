# Phase 6c — Tactical Board screenshots

These screenshots were captured against the local dev server at
`http://localhost:8091/` using Playwright (Python). Each screenshot
mounts the real `app.tacticalBoardSvg` / `app.mountTacticalBoardSection`
mixin into a synthetic host element on the live site so the captured
DOM is the production renderer in production CSS — no fakes.

Auth note: the QA harness does NOT log into the API. Every captured
surface (the editor section + read-only renderer + composer wrapper)
is a pure UI primitive that doesn't depend on `/api/coach/*` or
`/api/my-feedback`. Privacy enforcement lives server-side via the
existing `_filter_notes_for_user` chain — none of these renderers
fetch or scrub data themselves.

| File | Role | Surface | What it proves | Editable? |
| --- | --- | --- | --- | --- |
| `01-composer-empty-dark.png` | Coach | Observation composer (empty state) | "Tactical board · No board yet" + "+ Add tactical board" affordance + helper paragraph render correctly when the observation has no `tactical_board_json` | Coach editable (entry point) |
| `02-composer-saved-dark.png` | Coach | Observation composer (preview state) | "Attached" pill + Edit / Remove buttons + read-only SVG preview render correctly when an existing observation already carries a board | Coach editable (Edit / Remove) |
| `03-editor-fresh-dark.png` | Coach | Tactical board editor (empty pitch) | Editor toolbar (+ Player, + Ball, + Arrow, + Zone, + Label), TWO toolbar inputs ("Next player #" + "Label text"), Delete-selected (disabled) + Clear-board buttons, helper text, and full soccer pitch with all standard markings (touchlines, halfway, centre circle + spot, both penalty + goal areas, penalty spots + arcs, goals, corner arcs) all paint as expected. Section-head Cancel + Done buttons use the new self-styled `.tb-section-btn` (no `.btn-secondary` global). | Coach editable |
| `03b-editor-local-confirm-dark.png` | Coach | Tactical board editor — local confirm bar | Clicking Clear board surfaces a local in-section confirm bar inline above the toolbar (NOT a global app modal) so the parent observation `formModal` is never closed and coach-typed fields are preserved. Pre-fix this used `confirmAction()` which would have cancelled the parent. | Coach editable |
| `04-feedback-card-dark.png` | Viewer | My Feedback note card | Read-only SVG board preview embedded inside the feedback card with tone pill + ⌬ Board indicator + structured copy. The viewer cannot mutate the board. | Viewer read-only |
| `05-coach-notes-row-dark.png` | Coach | Coach > Notes row | Compact SVG thumbnail tile (16:9) on the left + ⌬ Board indicator next to the Observation context pill in the row head + Edit / Delete actions on the right. Replaces the clipboard glyph used for observations without a board. | Coach editable (Edit) |
| `06-editor-light.png` | Coach | Tactical board editor (light mode, mid-edit) | The editor surface, toolbar, and SVG renderer remain readable in light theme. The yellow shape stroke + label pill stay legible against the green grass; the toolbar buttons and label input adopt the light card palette. | Coach editable |
| `07-mobile-composer-saved-dark.png` | Coach | Composer @ 390 px width (preview state) | The board section collapses cleanly on a phone-class viewport: the head wraps, the action buttons stack to the bottom, the SVG preview maintains aspect ratio and doesn't overflow the card. | Coach editable |
| `08-mobile-editor-dark.png` | Coach | Editor @ 390 px width | Toolbar groups wrap to multiple rows (5 add-tools across two rows; right-aligned Delete / Clear group sits below); the label input goes full-width; the SVG pitch fills the available width. | Coach editable |
| `09-player-dev-row-dark.png` | Coach + Viewer (shared layout) | Player Development Profile recent-notes list | Observation note rows in the development profile pick up the same SVG thumbnail tile + ⌬ Board indicator pattern used in Coach > Notes. Layout is unchanged for observations without a board. | Read-only render in this surface |

## Sample board scene

The seed scene used across the screenshots demonstrates every kind in
the schema:

```json
{
  "pitch_kind": "soccer_full",
  "tokens": [
    {"kind": "player", "x": 0.18, "y": 0.5,  "label": "1"},
    {"kind": "player", "x": 0.32, "y": 0.3,  "label": "4"},
    {"kind": "player", "x": 0.32, "y": 0.7,  "label": "5"},
    {"kind": "player", "x": 0.5,  "y": 0.5,  "label": "6"},
    {"kind": "player", "x": 0.62, "y": 0.3,  "label": "8"},
    {"kind": "player", "x": 0.62, "y": 0.7,  "label": "10"},
    {"kind": "player", "x": 0.78, "y": 0.5,  "label": "9"},
    {"kind": "ball",   "x": 0.55, "y": 0.5}
  ],
  "shapes": [
    {"kind": "arrow", "x1": 0.5, "y1": 0.5, "x2": 0.78, "y2": 0.5},
    {"kind": "zone",  "x":  0.7, "y":  0.3, "w":  0.2,  "h":  0.4},
    {"kind": "label", "x":  0.8, "y":  0.15, "text": "Press here"}
  ]
}
```
