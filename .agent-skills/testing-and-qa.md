# Testing and QA

## Purpose

One runnable list of every static check, automated test, and manual regression step required
to declare a Coach Review sprint done. Pulled from `CLAUDE.md` and the implementation plan
so the agent doesn't have to re-derive it each sprint.

## When to use it

- Start of every sprint — establish a green baseline.
- End of every sprint — gate the PR.
- Whenever you suspect a regression.

## Static checks

Run before declaring any sprint done. **All must be green.**

```bash
node --check script.js
node --check js/coaching.js
node --check js/player.js
node --check js/api.js
```

If any other JS file changed, also `node --check` it.

## Backend checks (only if any `.py` file changed)

```bash
python3 -m py_compile server.py && \
python3 -m py_compile media.py && \
python3 -m py_compile models.py && \
python3 -m py_compile db.py && \
python3 -m py_compile auth.py && \
python3 -m py_compile settings.py && \
python3 -m py_compile uploads.py && \
python3 -m py_compile log.py && \
python3 -m py_compile live.py && \
python3 -m py_compile streams.py
```

## Tests

```bash
# Coaching-specific (always run)
pytest tests/test_coaching.py -v

# Full suite with coverage gate (run before merging)
pytest tests/ -v --cov --cov-report=term-missing --cov-fail-under=60
```

The repo's `pytest.ini` pins `asyncio_mode=auto` and fixture loop scope to `function`, and
narrowly filters Python 3.14 asyncio deprecations. Don't broaden the filter; don't override
the loop scope.

## Manual regression checklist

Run through this list in a real browser (Chrome + one other) at the end of every sprint and
paste the result into the PR description. Failure on any line is a sprint blocker.

### Coach Review (the redesign target)

- [ ] `/coach?tab=review` opens with the Review tab selected.
- [ ] Match dropdown lists all matches the user can coach.
- [ ] Selecting a match loads the Full slot video.
- [ ] Switching slot to First / Second loads the corresponding HLS playlist.
- [ ] Drawing canvas toggle (`Canvas On/Off`) works.
- [ ] Each drawing tool works: freehand, arrow, circle, zone, label, spotlight, dim,
      formation, select.
- [ ] Color swatch and width slider both apply to new drawings.
- [ ] Formation overlay accepts 3–16 anchors; collinear sets are rejected with a coach-
      readable error.
- [ ] Saving a note: title + category + selected players + current timestamp + drawing
      → POST `/api/coach/notes` 200; the note appears in the timeline rail (after Sprint 5).
- [ ] Clicking an existing note seeks to its timestamp and restores its drawing.
- [ ] Undo, Delete (selected), Clear all behave correctly on v2 drawings.
- [ ] Save Note from the top bar (after Sprint 2) saves the same payload as the form button.

### Coach Playlists / Notes tabs

- [ ] Coach > Notes tab lists notes.
- [ ] Coach > Playlists tab > Preview opens the focused modal (NOT `/match/{slug}`).
- [ ] Inside the focused modal preview, drawings render over the right freeze frames.

### My Feedback

- [ ] Logged in as a family/player linked to a roster player, `/feedback?tab=playlists` shows
      assigned playlists; `tab=notes` shows assigned notes.
- [ ] Private coach notes do **not** appear.
- [ ] Watch / Play opens the focused modal in-place; URL stays at `/feedback`.
- [ ] Mark Reviewed toggles state.

### Public match page

- [ ] `/match/{slug}` is unchanged: no coach panel, no canvas, no mode toggle.
- [ ] Coaches see the `Coach this match in Review →` header link, deep-linking with
      `&match=…&slot=…`.
- [ ] HLS playback works; native HLS on Safari, HLS.js elsewhere.
- [ ] VOD heartbeat keeps streaming (the public player calls
      `/api/matches/{id}/heartbeat?slot=…` every 10 s).

### Responsive

- [ ] 390 px (mobile portrait): Review tab stacks single-column; controls ≥44 px.
- [ ] 768 px: still stacks; right inspector below video.
- [ ] 1024 px: side-by-side appears; no horizontal page overflow.
- [ ] 1440 / 1920 px: video dominates; inspector capped at 320–360 px.

### Focus mode (Sprint 6+)

- [ ] Toggle expands the video/canvas; inspector collapses.
- [ ] Escape exits focus mode.
- [ ] Leaving the Review tab tears down focus-mode state.

### Keyboard shortcuts (Sprint 7+)

- [ ] Space play/pause works outside form fields.
- [ ] J / L seek; arrow keys nudge.
- [ ] S saves a note from anywhere in the Review tab.
- [ ] Tool letters (A, F, Z, C, T, D) switch tools.
- [ ] None of the shortcuts fire while typing in `<input>`, `<textarea>`, `<select>`, or
      `[contenteditable]`.

## Screenshots required in the PR description

Attach the following PNGs (file names match the labels):

| Label | What |
|---|---|
| `desktop-before.png` | Coach Review at 1440 px before this sprint |
| `desktop-after.png` | Coach Review at 1440 px after this sprint |
| `wide-1920.png` | Coach Review at 1920 px after |
| `laptop-1024.png` | Coach Review at 1024 px after |
| `mobile-390.png` | Coach Review at 390 px after |
| `focus-mode.png` | Focus mode on (Sprint 6+) |
| `timeline-rail.png` | Timeline rail with ≥6 notes |
| `drawing-overlay.png` | A v2 drawing painted over a freeze frame |
| `advanced-note-open.png` | Note composer with the More-details section expanded |

Capture method (no install required): use the Chrome MCP tool
`mcp__Claude_in_Chrome__computer` with `action: screenshot` after `resize_window` to each
target dimension, or DevTools "Capture screenshot" from the Device Mode toolbar.

## Tools available on demand (no pre-install needed)

Reach for these only when the listed sprint actually needs them. They run from `npx`,
DevTools, or Homebrew without touching the repo.

| Need | Command / location | When |
|---|---|---|
| Accessibility audit | Chrome DevTools → Lighthouse tab → "Accessibility" | Sprint 8, anytime you suspect a regression |
| A11y CLI (scriptable, exit-code gated) | `npx @axe-core/cli http://localhost:8090/coach?tab=review` | Sprint 8 if you want a CI-style gate |
| Performance / SEO / a11y combined | `npx lighthouse http://localhost:8090/coach?tab=review --view` | Rare; Lighthouse tab in DevTools is usually enough |
| Pixel-diff before/after composites | `brew install imagemagick && magick before.png after.png +append side-by-side.png` | Only when a reviewer asks for stitched composites |
| Image scripting in Python (resize, crop) | `pip install --user Pillow` (or use a venv) | Rare; only for batch screenshot work |
| End-to-end browser tests | `cd tests/e2e && npx playwright test` | Already installed (Sprint 9) |

Rule of thumb: if it's `npx`-able, don't add it as a repo dep. If it's a system tool
(`brew`, `pip --user`), install it the day you need it.

## Sprint 0 baseline data

Before Sprint 0 begins, seed:

- ≥1 full-match (single video) match
- ≥1 two-half match (`first_half` + `second_half`)
- ≥3 roster players
- ≥5 coaching notes spread across timestamps
- ≥1 playlist with 2+ items
- ≥1 family/player user linked via `player_user_links` (for the My Feedback regression
  pass)

Without this, a screenshot of an empty Review tab is meaningless.

## Common failure modes

- **HLS won't play locally.** Make sure the `mediamtx` sidecar (or the prod-style Caddy +
  origin server) is up. As a fallback for screenshot capture, MP4 fallback works through
  `getStreamUrls`.
- **`pytest.ini` not respected.** Run `pytest` from the repo root, not from `tests/`.
- **Coverage gate fails (60%).** A UI-only sprint shouldn't lower coverage; check that you
  haven't deleted Python that other tests cover.
- **Lighthouse a11y score < 95.** Usually missing `aria-label` on icon buttons or a
  contrast token regression. See [`css-responsive-accessibility.md`](css-responsive-accessibility.md).
- **Reaching for Playwright on Sprints 0–8.** Chrome MCP + DevTools is faster for one-off
  checks. Playwright (already installed under `tests/e2e/`) is for Sprint 9 when the manual
  checklist becomes painful — run with `cd tests/e2e && npx playwright test` against a
  reachable `PLAYWRIGHT_BASE_URL`.

## Done criteria

A sprint is done when:

- All static checks above pass.
- `pytest tests/test_coaching.py -v` and `pytest tests/ -v` both pass.
- The manual regression checklist is filled in (every box checked) in the PR description.
- All required screenshots are attached.
- No regressions in My Feedback, Coach Notes/Playlists, public `/match/{slug}`, or live
  playback.
