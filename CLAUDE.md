# Claude Instructions

Read `AGENTS.md` first and treat it as the shared project source of truth.

Replay is a **single-team VOD + live-streaming** web app: upload match videos →
ffmpeg transcode → multi-variant HLS playback, plus live streaming through a
MediaMTX sidecar, an admin console, and admin-managed user accounts
(roles: `admin` / `uploader` / `viewer`). It is a no-build vanilla-JS SPA on a
FastAPI + SQLite backend. There is **no** coaching/feedback subsystem, no
multi-tenancy (teams/seasons/memberships/invites), no account self-service
(profile/password-reset/email-verification), and no Postgres lane — those were
all removed. Don't reintroduce them without an explicit request.

## General

- Favor direct, minimal edits over speculative rewrites.
- Check current file contents before editing — this repo changes iteratively.
- After a code change, update the relevant markdown (`AGENTS.md`, `README.md`,
  `ROADMAP.md`, and this file) so docs stay in sync.

## Frontend (no-build vanilla JS)

- `script.js` is the entry point; it imports per-domain mixins from `js/*.js`
  and spreads them into the global `window.app`. Methods call peers as
  `this.x()` — no bundler, no transpile step.
- Mixins: `js/utils.js`, `js/api.js`, `js/player.js`, `js/uploads.js`,
  `js/views.js` (public season + game/match rendering), `js/admin-views.js`
  (admin renderers + match form actions + user CRUD modals), `js/admin.js`
  (admin shell routing/sidebar/status polling), `js/live.js`, `js/ui.js`
  (toasts + `formModal`).
- Public view rendering (season grid, game/match view, score reveal, team
  stats) is in `js/views.js`. "Season" and home/away "team" here are just
  match-grouping labels + names on a match record — not a multi-tenant concept.
- The admin/uploader surface is a single `#admin-view` shell with sub-routes:
  `/admin/overview`, `/admin/matches`, `/admin/live`, `/admin/performance`,
  `/admin/users`, `/admin/settings`. Routing, sidebar render, status-strip
  polling, and role gating live in `js/admin.js` (`ADMIN_NAV_GROUPS`,
  `SECTION_META`, `LEGACY_SECTION_REDIRECTS`).
- The Matches tab is a library table (`renderMatchLibraryTable()` in
  `js/admin-views.js`), not an inline form. Add/Edit go through a modal cloned
  from `<template id="match-form-template">` in `index.html`, mounted via
  `app.formModal({ body, onSubmit, … })` in `js/ui.js`. Per-slot recovery
  (Verify, Regen HLS, Re-transcode, Force Re-transcode, Logs, Regenerate
  Thumbnail) lives in the row's expanded diagnostics panel.
- `/admin/live` is the broadcast cockpit: ingest/key form + live throughput
  sparkline + encoder load + active live viewers + stream blocks.
  `startLiveConsolePolling` (5 s) drives the read rail.
- `/admin/performance` stacks Encoder & Host (`renderPerformanceTuning`),
  Tuning Knobs (`renderTuningKnobsCard`), and Disk & Diagnostics (collapsed
  `<details>` accordions: `#diag-errors`, `#diag-uploads`, `#diag-transcodes`,
  `#diag-sessions`, `#diag-audit`).
- Admin overview "Recent Activity" renders `diagnostics.recent_activity` from
  the persisted SQLite `activity_events` table (`db.log_activity_event`). Keep
  it an operational feed (uploads, transcodes, HLS regen, match/user/settings/
  admin actions, live/VOD-HLS session start/end/kill). Don't repurpose
  `video_errors` as the feed; don't log HLS segment polls / heartbeat noise.
- Button tiers: `.btn-primary / .btn-secondary / .btn-danger` (form submits,
  primary CTAs); `.btn-head` (buttons inside an `.admin-panel-head` action
  row); `.mini-action-btn` (row-level actions). Use `.btn-head`, not
  `.btn-secondary`, for section-head actions.
- Visible controls must be themed in both dark and light modes. Avoid raw
  browser chrome (native multi-selects, unstyled range sliders, number
  spinners, default checkboxes/radios, file inputs, unthemed scrollbars). Long
  values like RTMP URLs should wrap within their card, not overflow.
- Split CSS modules load after `styles.css` in `index.html`;
  `settings.render_index_html()` must version every static stylesheet link it
  serves so caches don't keep stale UI. Keep `_STATIC_EXPORT_PATHS` in
  `server.py` in sync with the static files index.html references.

## Backend (FastAPI + SQLite)

- Route handlers live in focused router modules under `routers/`:
  - `routers/auth.py` — `POST /api/login`, `POST /api/logout`,
    `GET /api/auth/check`. Durable sessions live in `user_sessions`; tokens are
    stored hashed-only and revoked on logout. The env-admin break-glass path
    (`ADMIN_PASS`) must keep working without a database user row.
  - `routers/admin.py` — `/api/users*` admin CRUD (admin creates/edits/
    deletes/enables users; `GET /api/users/{id}` returns one user). Admin
    password change revokes the target's sessions via `db.revoke_user_sessions`.
  - `routers/admin_ops.py` — `/api/admin/diagnostics`, `/api/admin/performance`
    (+ capture), `/api/admin/backfill-hls`, `/api/admin/export-database`,
    `/api/transcode-progress`.
  - `routers/matches.py` — `/api/matches*` CRUD + admin recovery
    (`/api/admin/matches/{id}/{retry,regenerate-hls,regenerate-thumbnail,
    verify,errors}`) + VOD HLS proxy (`/api/matches/{id}/hls/{slot}/...`) +
    thumbnail + logo serving + match heartbeat. Matches are a flat global
    library — no team/season scoping.
  - `routers/uploads.py` — chunked upload session lifecycle
    (`/api/uploads/sessions*`) and the match-video upload entry points.
  - `routers/live.py` — `/api/live/{status,hls/...,auth}` +
    `/api/admin/{live/...,streams/...}`.
  - `routers/settings.py` — public `/api/settings`, admin
    `/api/admin/settings` GET/PUT, `/api/admin/settings/asset`,
    `/api/app-assets/{kind}`. (No email/notification routes.)
- `server.py` retains FastAPI app construction + lifespan, the SPA HTML shell
  routes (`/`, `/match*`, `/live`, `/admin*`, `/static/{filepath:path}`), the
  transcode pipeline, and shared helpers imported lazily by routers to avoid
  circular imports.
- When adding/modifying an API endpoint, update Pydantic models in `models.py`
  and add tests in `tests/`.
- Match slug deep links: `/match/{slug}`, `/match/{slug}/{slot}`. Watch Live is
  `/live`.

## Database

- SQLite only. `db.connect()` is the single connection path. The schema is a
  **single squashed migration** `_migrate_v1` (PRAGMA `user_version = 1`); the
  runner applies it on a fresh DB. Tables: `users`, `user_sessions`, `matches`,
  `video_errors`, `activity_events`, `background_jobs`, `settings`,
  `settings_audit`, `upload_sessions`, `schema_version`.
- A DB from the pre-v1 multi-team schema (`user_version > 1`) is **folded down
  in place** on startup by `_fold_legacy_to_v1()` in `db.py`: it drops the
  coaching / team / account tables and the `team_id`/`season_id` columns on
  `matches`/`users`, preserving all kept rows, then restamps to v1. The fold is
  idempotent. If you add a column/table to the v1 schema, update
  `_LEGACY_TABLES_TO_DROP` / `_LEGACY_COLUMNS_TO_DROP` only if a legacy DB could
  carry an incompatible version of it.
- When setting a video slot to `"error"`, always pass an `error_info` dict with
  `error_code` / `reason` / `details` to `_set_video_status()` so it is
  persisted to `video_errors`.

## Transcode + durable jobs

- Transcodes run **in-process** but are tracked through the durable
  `background_jobs` queue (`services/jobs.py`): `_spawn_transcode` enqueues a
  job with a constant `team_id="default"` partition key, then runs the ffmpeg
  work via `_spawn_task`. `lifespan` runs stuck-job recovery every 30 s. There
  is no user-facing `/api/jobs*` surface.
- Performance tuning knobs (transcode concurrency, hwaccel, HLS segment
  duration, upload limits, ABR ladder) live in the `settings` table — not
  hardcoded. Read live values via the `current_*()` helpers in `server.py`
  (e.g. `current_transcode_concurrency()`); schema/validation is in
  `settings.TUNING_KNOBS`. Adding a knob: add to `TUNING_KNOBS`, add a default
  to `DEFAULT_APP_SETTINGS`, add a `current_*()` helper if needed, surface it in
  `renderTuningKnobsCard()`, and update consumers.
- The transcode semaphore is a `ResizableSemaphore`; `PUT /api/admin/settings`
  calls `TRANSCODE_SEMAPHORE.resize()` when `transcode_concurrency` changes so
  it takes effect live. Tuning saves go through `handleTuningSubmit()` (PUTs
  only `collectTuningKnobs()`), NOT `handleSettingsSubmit()`.
- Use the `lifespan` async context manager for startup/shutdown, not
  `@app.on_event`.

## Media storage + HLS

- HLS variants + thumbnails go on `VIDEOS_DIR` (hot/SSD); raw uploads +
  finished MP4s go on `ORIGINALS_DIR` (cold pool when `REPLAY_ORIGINALS_DIR` is
  set, else aliased to `VIDEOS_DIR`). Media lives in the flat layout
  `<root>/<match_id>/...`. Route slot paths through the `_slot_*_path()` /
  `_find_slot_raw_path()` helpers in `server.py` (or the `media.py` helpers) —
  don't construct `VIDEOS_DIR / match_id / f"{slot}.mp4"` directly.
- HLS cache headers must stay aligned with the proxy policy: playlists
  `public, max-age=60, must-revalidate`; segments
  `public, max-age=31536000, immutable`. The `Caddyfile` mirrors these — keep
  both in sync.
- Match-logo responses must emit `X-Content-Type-Options: nosniff`,
  `Content-Security-Policy: script-src 'none'`, and
  `Content-Disposition: inline` (defense-in-depth against stored XSS via
  uploaded SVGs). Keep `server.py` (`serve_logo`), `Caddyfile`, and the inlined
  Caddyfile in `docker-compose-intel.yml` in sync.
- VOD HLS segments are served by Caddy directly from the bind-mount, bypassing
  FastAPI, so `js/player.js` POSTs `/api/matches/{id}/heartbeat?slot=…` every
  10 s to keep the streams-registry session warm. A 403 heartbeat (admin kill)
  stops the player.
- Admin recovery endpoints: `/api/admin/matches/{id}/{retry,regenerate-hls,
  verify,errors}`.

## Live streaming

- Live runs through a `mediamtx` sidecar in compose. Camera ingest is RTMP at
  port 1936; browsers play LL-HLS via the proxy at `/api/live/hls/*`. Never
  expose MediaMTX's 8888/9997 ports publicly — they stay on the internal compose
  network.
- Live auth: `/api/live/auth` fails closed (503) when `LIVE_AUTH_SECRET` is
  unset unless `LIVE_AUTH_ALLOW_INSECURE=1` (dev only). The shared secret
  travels as the password half of HTTP Basic Auth in MediaMTX's
  `authHTTPAddress`; the handler accepts both `Authorization: Basic …` and the
  legacy `X-Internal-Secret:` header — keep both paths working.
- Active streaming connections are tracked in `streams.py` and surfaced via
  `/api/admin/streams` (+ kill/unblock). Use `streams.client_ip(request)` for
  the real client IP — `request.client.host` reads loopback through a CF Tunnel.
  `client_ip()` honors forwarded headers only when `TRUSTED_PROXY=cloudflare`
  (default); bare deployments should set `TRUSTED_PROXY=none`.

## Caching / proxy

- When fixing public-domain behavior, consider cache + proxy behavior before
  assuming application logic is broken.

## Validation

Primary:

```bash
python3 -m py_compile server.py media.py models.py db.py auth.py settings.py uploads.py log.py live.py streams.py
ADMIN_PASS=admin LIVE_AUTH_ALLOW_INSECURE=1 python3 -m pytest tests/ -q
```

- `tests/conftest.py` defaults `ADMIN_PASS` to `admin` via `setdefault` and the
  `auth_headers` fixture logs in as `admin`/`admin` — run pytest with
  `ADMIN_PASS=admin` (passing a different value breaks the fixture). Tests
  cover auth/sessions, users, matches, uploads, media, db, settings, jobs,
  live, streams, models, and a route-inventory pin
  (`tests/fixtures/route-inventory.txt`, regenerate via
  `python3 scripts/dump_routes.py`).
- `pytest.ini` pins pytest-asyncio fixture loop scope to `function` and filters
  dependency-owned Python 3.14 asyncio deprecations.
- Auth token cap is configurable via `MAX_ACTIVE_TOKENS` (default 1000).
- CI gates coverage at 60% via `pytest-cov` (`.coveragerc` excludes `tests/`).
  `pytest-cov` may not be installed locally — run plain `pytest` locally; CI
  computes coverage.
- E2E: `tests/e2e/vod-smoke.spec.js` is a Playwright smoke spec (public
  surface renders, removed surfaces 404, admin console boots, matches API
  responds). Run from `tests/e2e/` with `PLAYWRIGHT_BASE_URL` + `ADMIN_PASS`
  against a running server: `npm test`.

## Docs

- Deployment + troubleshooting: `docs/DEPLOYMENT.md`, `docs/TROUBLESHOOTING.md`.
- User + admin guides: `docs/user-guide.md`, `docs/admin-guide.md`.
- Screenshots of kept surfaces live under `docs/screenshots/`.
