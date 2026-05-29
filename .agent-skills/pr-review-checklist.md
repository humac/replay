# PR review checklist

## Purpose

Paste-ready PR description template for any Replay change. Reviewers should be able to replay
the manual checks from the PR alone, without re-running the work.

## When to use it

- Drafting any PR that touches the frontend mixins, `index.html`, `styles.css`, the backend
  routers/services, or the tests.
- Reviewing such a PR — use the checklist to verify completeness.

## Template — copy into PR description

```markdown
## Summary
<2–4 sentences on what changed and why, focused on the user-visible result.>

## Changed files
- `<file>` — <one-line summary>
- ...

## Before / after screenshots
| View | Before | After |
|---|---|---|
| Desktop 1440 px | ![before](url) | ![after](url) |
| Mobile 390 px | — | ![after](url) |

(Only when the change is user-visible.)

## Manual regression notes
Identity passes:
- [ ] admin
- [ ] uploader (or `uploader,admin`)
- [ ] viewer (signed-in)
- [ ] anonymous (logged out)

Public season + match:
- [ ] Season grid renders; scores hidden by default
- [ ] All / Home / Away filters + search narrow the grid
- [ ] `/match/{slug}` plays; slot toggle switches HLS playlist
- [ ] HLS native (Safari) + HLS.js + MP4 fallback all work
- [ ] VOD heartbeat keeps streaming; admin kill stops it

Live:
- [ ] `/live` shows offline message when idle; attaches to LL-HLS when active

Admin console:
- [ ] `/admin/matches` library + Add/Edit modal + per-slot recovery actions
- [ ] `/admin/live` reveal/rotate key + viewers/throughput
- [ ] `/admin/performance` host signals + tuning knobs save
- [ ] `/admin/users` create/disable/delete
- [ ] `/admin/settings` branding/labels/toggles
- [ ] Uploader-only account sees only Matches

Responsive (no horizontal overflow):
- [ ] 390 px
- [ ] 768 px
- [ ] 1024 px
- [ ] 1440 px
- [ ] 1920 px

## Accessibility notes
- [ ] Every icon button has both `aria-label` and `title`
- [ ] Toggle buttons use `aria-pressed`; tabs use `role="tab"` + `aria-selected`
- [ ] Visible `:focus-visible` rings on compact controls
- [ ] Touch tap targets ≥44 px under `@media (pointer: coarse)`
- [ ] No `outline: none` without a focus replacement
- [ ] No native browser chrome inside styled components (no raw `<select multiple>`,
      unstyled scrollbars, or default range thumbs)

## Validation commands run
```bash
node --check script.js js/admin.js js/player.js js/api.js
python3 -m py_compile server.py media.py models.py db.py auth.py settings.py uploads.py live.py streams.py log.py   # only if .py changed
ADMIN_PASS=admin LIVE_AUTH_ALLOW_INSECURE=1 python3 -m pytest tests/ -q
```

All green: <yes/no>

## Known risks
- <e.g. cache/proxy behavior for index.html or /static/*>
- <e.g. HLS lifecycle when switching between live and VOD views>
```

## Common failure modes for the PR itself

- **Missing identity passes.** Reviewers can't verify role gating without all four roles.
- **Missing screenshots.** PR descriptions without before/after at multiple widths cannot be
  reviewed for layout regressions.
- **Stale "Validation commands run" block.** Paste the actual output (or "all green") —
  don't claim green if something failed.
- **No `Known risks`.** Every change has at least one. Listing them helps the reviewer focus.

## Done criteria

The PR description is complete when:

- Every section in the template is filled in (no placeholder `<...>`).
- Every checkbox is checked or explicitly explained.
- The validation commands block shows real, recent output.
- The reviewer doesn't need to ask "did you test on mobile?" — it's already answered.
