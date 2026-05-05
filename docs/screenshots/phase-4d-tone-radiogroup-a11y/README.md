# Phase 4d — Tone radiogroup keyboard a11y screenshots

Captured against the `replay-dev` Claude Preview at commit `ef93b77`
(Phase 4d branch). Each capture shows the active tone chip with
`:focus-visible` after the active chip received focus via JS — the
same visual state a keyboard user sees after Tabbing to the group.

## Inventory

| File | What it shows |
|---|---|
| `coach-review-tone-focused-dark.png` | Coach Review composer, dark mode, with the **Correction** tone chip focused (active + `:focus-visible` accent ring) |
| `coach-review-tone-focused-light.png` | Same surface, light mode |
| `notes-edit-modal-tone-focused-dark.png` | Notes Edit modal opened from the Notes tab; the tone group inside the modal has the active chip focused |
| `coach-review-tone-focused-mobile.png` | Coach Review tone group at 390 × 844 (mobile breakpoint) — confirms the chip group still wraps cleanly and tap targets remain ≥ 44 px |

## Behavior verified by these captures

- Active chip carries the visible accent ring (`:focus-visible` outline).
- Inactive chips are visible but do not carry the focus ring (they have `tabindex="-1"`, so a Tab press cannot reach them; arrow keys cycle within the group).
- Light + dark themes both show readable contrast on the active chip.
- Mobile layout preserves the chip set without wrapping into illegible 1-column layouts.

## Re-capturing

The screenshots are captured by the Playwright script at
`/tmp/replay-phase3b/qa_4d_screenshots.py` (kept locally, not in repo).
To re-capture, sync the worktree to the latest Phase 4d commit, mint an
admin token via `/api/login`, and re-run the script.
