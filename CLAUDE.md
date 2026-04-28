# Claude Instructions

Read `AGENTS.md` first and treat it as the shared project source of truth.

Additional guidance for Claude in this repo:

- Favor direct, minimal edits over speculative rewrites.
- Check the current file contents before editing because this repo is often changed iteratively.
- When fixing UI behavior, inspect `index.html` and the relevant JS module in `js/` (views, admin-views, player, uploads, api, utils, live, admin). `script.js` is the entry point that assembles all mixins into `window.app`. Public view rendering (season, game, score reveal, team stats) is in `js/views.js`; admin renderers and match form actions are in `js/admin-views.js`.
- The admin/uploader surface lives in a single `#admin-view` shell with sub-routes: `/admin/overview`, `/admin/matches`, `/admin/live`, `/admin/streams`, `/admin/users`, `/admin/settings`, `/admin/system`. Routing, sidebar render, status-strip polling, and role gating are in `js/admin.js`. Existing renderers (`renderSettingsForm`, `renderLiveSettingsCard`, `refreshActiveStreams`, `renderUsersList`, `refreshAdminDiagnostics`) are reused unchanged — only the DOM containers moved.
- When fixing public-domain behavior, consider cache and proxy behavior before assuming application logic is broken.
- When adding or modifying API endpoints, update Pydantic models in `models.py` and add tests in `tests/`.
- Match URLs use slug-based deep links (`/match/{slug}`, `/match/{slug}/first-half`). The Watch Live page deep-links to `/live`.
- Live streaming runs through a `mediamtx` sidecar in compose. Camera-facing surface is RTMP at port 1935; browsers play LL-HLS via the proxy at `/api/live/hls/*`. Never expose MediaMTX's 8888/9997 ports publicly — they stay on the internal compose network.
- When setting video status to `"error"`, always pass `error_info` dict with `error_code`, `reason`, `details` to `_set_video_status()` so errors are persisted to the `video_errors` table.
- Admin recovery endpoints live under `/api/admin/matches/{id}/...` — retry, regenerate-hls, verify, errors.
- Active streaming connections are tracked in `streams.py` and surfaced via `/api/admin/streams` (+ kill/unblock endpoints). Use `streams.client_ip(request)` whenever you need the real client IP — direct `request.client.host` reads through Cloudflare/CF Tunnel return loopback. Note: `client_ip()` only honors forwarded headers when `TRUSTED_PROXY=cloudflare` (the default); bare deployments should set `TRUSTED_PROXY=none` so only the direct peer address is used.
- Performance tuning knobs (transcode concurrency, hwaccel choice, HLS segment duration, upload limits, ABR ladder) are stored in the `settings` table — not hardcoded constants. Read live values via the `current_*()` helpers in `server.py` (e.g. `current_transcode_concurrency()`, `current_replay_hwaccel()`); each helper resolves through `settings.load_unlocked()`. Schema and validation lives in `settings.TUNING_KNOBS`. When adding a new knob: add it to `TUNING_KNOBS`, add a default to `DEFAULT_APP_SETTINGS`, add a `current_*()` helper if needed, surface it in `js/admin-views.js` via `renderTuningKnobsCard()`, and update the relevant `current_*()` consumer call sites.
- The transcode semaphore is a `ResizableSemaphore` (defined in `server.py`); `PUT /api/admin/settings` calls `TRANSCODE_SEMAPHORE.resize()` when `transcode_concurrency` changes so the change is live without a restart. Don't replace it with a plain `asyncio.Semaphore`.
- HLS cache headers must stay aligned with `live.py`'s proxy policy: playlists `public, max-age=60, must-revalidate`, segments `public, max-age=31536000, immutable`. The `Caddyfile` mirrors these — keep both in sync if the policy changes.
- The Caddy reverse proxy serves VOD HLS segments directly from the `/data` bind-mount; everything else is proxied to the replay app on `:8090`. Keep the URL pattern `^/api/matches/{id}/hls/{slot}/...` stable so the Caddy regex routes match.
- The Performance Tuning panel polls `/api/admin/performance` every 5 s while `/admin/system` is active. Add new signals by extending `_host_signals()` / `_disk_pools()` / the response payload — the frontend tile list in `renderPerformanceTuning()` is a flat array, easy to extend.
- Use the `lifespan` async context manager for startup/shutdown tasks (not `@app.on_event`).
- Deployment and troubleshooting docs live in `docs/DEPLOYMENT.md` and `docs/TROUBLESHOOTING.md`.

After every code change, update the relevant markdown files to stay in sync:

- `ROADMAP.md` — mark completed items, add descriptions of what was done.
- `AGENTS.md` — update Key Files, Editing Guidance, or Stack if new files/conventions were added.
- `CLAUDE.md` — update if validation commands or editing guidance changed.

Primary validation:

```bash
python3 -m py_compile server.py && python3 -m py_compile media.py && python3 -m py_compile models.py && python3 -m py_compile db.py && python3 -m py_compile auth.py && python3 -m py_compile settings.py && python3 -m py_compile uploads.py && python3 -m py_compile log.py && python3 -m py_compile live.py && python3 -m py_compile streams.py
pytest tests/ -v
```
