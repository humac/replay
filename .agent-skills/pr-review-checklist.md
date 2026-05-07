# PR review checklist

## Purpose

Paste-ready PR description template for any Coach Review sprint PR. Every section is
required; reviewers should be able to replay the manual checks from the PR alone, without
re-running the work.

## When to use it

- Drafting any PR that touches `js/coaching.js`, `index.html` Coach/Feedback templates,
  `styles.css` Coach Review block, or `tests/test_coaching.py`.
- Reviewing such a PR — use the checklist to verify completeness.

## Template — copy into PR description

```markdown
## Sprint
Sprint <N> of `docs/archive/coach-review-ui-ux-implementation-plan.md`
Bundled into PR<X> per the plan's PR breakdown (PR1 = S1+S2, PR2 = S3+S4, PR3 = S5+S6,
PR4 = S7+S8+S9).

## Summary
<2–4 sentences on what changed and why, focused on the user-visible result.>

## Changed files
- `js/coaching.js` — <one-line summary>
- `styles.css` — <one-line summary>
- `index.html` — <one-line summary>
- `tests/test_coaching.py` — <only if changed>
- `docs/...` — <only if doc updated>

## Before / after screenshots
| View | Before | After |
|---|---|---|
| Desktop 1440 px | ![before](url) | ![after](url) |
| Wide 1920 px | — | ![after](url) |
| Laptop 1024 px | — | ![after](url) |
| Mobile 390 px | — | ![after](url) |
| Focus mode (S6+) | — | ![after](url) |
| Timeline rail w/ many notes (S5+) | — | ![after](url) |
| Drawing overlay during freeze frame | — | ![after](url) |
| Note composer "More details" expanded (S4+) | — | ![after](url) |

## Manual regression notes
Identity passes:
- [ ] admin
- [ ] coach (or `coach,uploader`)
- [ ] viewer (signed-in, not linked to a player)
- [ ] family/player (linked via `player_user_links`)
- [ ] anonymous (logged out)

Coach Review:
- [ ] `/coach?tab=review` opens with Review selected
- [ ] Match dropdown loads matches I can coach
- [ ] Slot selector switches between Full / First / Second
- [ ] Drawing canvas toggles on/off
- [ ] All 9 telestrator tools work (freehand, arrow, circle, zone, label, spotlight, dim,
      formation, select)
- [ ] Formation: 3–16 anchors accepted; collinear set rejected
- [ ] Note save uses current timestamp + drawing payload
- [ ] Saved note appears in the timeline rail
- [ ] Clicking a note seeks and restores its drawing
- [ ] Save Note from top bar (S2+) saves the same payload as the form
- [ ] Focus mode toggle (S6+) and Escape to exit
- [ ] Keyboard shortcuts (S7+) only fire outside form fields

Cross-surface:
- [ ] Coach > Playlists > Preview opens the focused modal (NOT `/match/{slug}`)
- [ ] My Feedback unchanged: no `private` content leaks; modal player works
- [ ] Public `/match/{slug}` unchanged (no coach panel, no canvas, no toggle)
- [ ] Coach deep-link `Coach this match in Review →` lands on the right match + slot

Responsive (no horizontal overflow except the timeline rail):
- [ ] 390 px
- [ ] 768 px
- [ ] 1024 px
- [ ] 1440 px
- [ ] 1920 px

## Accessibility notes
- [ ] Every icon button has both `aria-label` and `title`
- [ ] Tool toggles use `aria-pressed`
- [ ] Subnav uses `role="tab"` + `aria-selected`
- [ ] Visible `:focus-visible` rings on compact controls (34 px)
- [ ] Touch tap targets ≥44 px under `@media (pointer: coarse)`
- [ ] No `outline: none` without a focus replacement
- [ ] No native browser chrome inside styled components (no raw `<select multiple>`,
      unstyled scrollbars, or default range thumbs)
- [ ] Lighthouse Accessibility score on `/coach?tab=review` ≥95
      (paste score: <number>)

## Mobile / desktop testing
- [ ] Tested on a touch device (or DevTools touch emulation)
- [ ] Tested with mouse + keyboard
- [ ] Tested on Safari + Chrome (HLS native vs HLS.js paths)
- [ ] VoiceOver / NVDA quick pass through the cockpit

## Validation commands run
```bash
node --check script.js js/coaching.js js/player.js js/api.js
python3 -m py_compile server.py media.py models.py db.py auth.py settings.py uploads.py live.py streams.py log.py   # only if .py changed
pytest tests/test_coaching.py -v
pytest tests/ -v --cov --cov-report=term-missing --cov-fail-under=60
```

All green: <yes/no>

## Known risks
- <e.g. ResizeObserver fallback for canvas alignment when wrapper resizes without window
  resize>
- <e.g. focus-mode CSS layering — verify it doesn't bleed into the admin shell when the
  user navigates between views without a full reload>
- <e.g. timeline rail visibility filter must not regress private-note leakage>
```

## Common failure modes for the PR itself

- **Missing identity passes.** Reviewers can't verify privacy without all four roles.
- **Missing screenshots.** PR descriptions without before/after at multiple widths cannot be
  reviewed for layout regressions.
- **Stale "Validation commands run" block.** Paste the actual output (or "all green") —
  don't claim green if something failed.
- **No `Known risks`.** Every layout change has at least one risk. Listing them helps the
  reviewer focus.

## Done criteria

The PR description is complete when:

- Every section in the template is filled in (no placeholder `<...>`).
- Every checkbox is checked or explicitly explained.
- Screenshots cover all listed widths and modes.
- The validation commands block shows real, recent output.
- The reviewer doesn't need to ask "did you test on mobile?" — it's already answered.
