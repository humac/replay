# Testing and QA

## Purpose

One runnable list of every static check, automated test, and manual regression step required
to declare a change done on the Replay VOD + live-streaming app.

## When to use it

- Start of a task — establish a green baseline.
- End of a task — gate the PR.
- Whenever you suspect a regression.

## Static checks

Run before declaring done. **All must be green.**

```bash
node --check script.js
node --check js/admin.js
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
ADMIN_PASS=admin LIVE_AUTH_ALLOW_INSECURE=1 python3 -m pytest tests/ -q
```

`tests/conftest.py` defaults `ADMIN_PASS` to `admin`. pytest-cov is **not** installed locally —
do not pass `--cov`. The repo's `pytest.ini` pins `asyncio_mode=auto` and fixture loop scope to
`function`, and narrowly filters Python 3.14 asyncio deprecations. Don't broaden the filter;
don't override the loop scope. Run `pytest` from the repo root so `pytest.ini` is respected.

## End-to-end (Playwright smoke)

There is a single Playwright smoke spec: `tests/e2e/vod-smoke.spec.js`. It covers the public
surface, the admin console, the matches API, and asserts that removed surfaces (e.g. `/coach`,
`/feedback`, `/api/me*`) return 404. The shared login helper is `tests/e2e/_login.js`.

```bash
cd tests/e2e && PLAYWRIGHT_BASE_URL=http://localhost:8091 ADMIN_PASS=admin npm test
```

Requires the app reachable at `PLAYWRIGHT_BASE_URL`. The folder is self-contained (its own
`package.json` + `node_modules`) so the repo root stays no-build.

## Manual regression checklist

Run through this in a real browser (Chrome + one other) at the end of a UI change. Failure on
any line is a blocker.

### Public season + match

- [ ] The season grid renders match cards grouped by season label; scores hidden by default.
- [ ] All Matches / Home / Away filters and the search box narrow the grid.
- [ ] Clicking a card opens `/match/{slug}` with the player + info panel.
- [ ] The slot toggle (Full / First Half / Second Half) switches the loaded HLS playlist.
- [ ] HLS playback works (native HLS on Safari, HLS.js elsewhere); MP4 fallback works.
- [ ] VOD heartbeat keeps streaming (the player posts `/api/matches/{id}/heartbeat?slot=…`
      every 10 s); an admin "kill" stops playback.
- [ ] Player keyboard shortcuts (space, arrows, F, M, 0–9, < / >) work outside form fields.
- [ ] AirPlay / Chromecast buttons appear and route the right source.

### Live

- [ ] `/live` shows the offline message when no stream is active.
- [ ] When a stream is active it auto-attaches to the LL-HLS feed via `/api/live/hls/*`.

### Admin console

- [ ] `/admin/overview` shows the status strip, KPI tiles, and Recent Activity feed.
- [ ] `/admin/matches` lists matches; Add / Edit open the modal; per-slot recovery actions
      (Verify, Regen HLS, Re-transcode, Logs, Regenerate Thumbnail) are in the expanded row.
- [ ] `/admin/live` reveals/rotates the stream key and shows viewers + throughput.
- [ ] `/admin/performance` shows host signals + tuning knobs; saving a knob persists.
- [ ] `/admin/users` creates/disables/deletes accounts (admin / uploader / viewer).
- [ ] `/admin/settings` updates branding, labels, and feature toggles.
- [ ] An uploader-only account sees only Matches under `/admin`.

### Responsive

- [ ] 390 px (mobile portrait): cards stack single-column; controls ≥44 px.
- [ ] 768 / 1024 / 1440 / 1920 px: no horizontal page overflow; admin tables/tiles reflow.

## Common failure modes

- **HLS won't play locally.** Make sure the `mediamtx` sidecar (or the prod-style Caddy +
  origin server) is up. MP4 fallback works through `getStreamUrls` for screenshot capture.
- **`pytest.ini` not respected.** Run `pytest` from the repo root, not from `tests/`.
- **Login flakes during E2E.** Login is rate-limited 5/IP/60s; `_login.js` retries on 429.

## Done criteria

A change is done when:

- All static + backend checks above pass.
- `ADMIN_PASS=admin LIVE_AUTH_ALLOW_INSECURE=1 python3 -m pytest tests/ -q` passes.
- The relevant manual regression lines are verified.
- No regressions in public season/match playback, `/live`, or the admin console.
