# Replay repo navigation

## Purpose

Orient a coding agent to the no-build vanilla-JS architecture of Replay before touching any
file. Replay is a FastAPI backend serving a single-page `index.html` with ES-module mixins
composed at runtime into `window.app`. There is no bundler, no transpiler, no `package.json` at
the repo root. Edits go straight to source files and are reloaded by refreshing the browser.

## When to use it

- The first turn of any task that edits this repo.
- Any time you are unsure which file owns a DOM id, CSS class, or `app.foo()` method.
- Before renaming or removing a public method on `window.app`.

## Key repo files

Top-level entry points and shells:

- `index.html` — single page shell containing all views (`#season-view`, `#admin-view`,
  `#live-view`, `#game-view`). Uses inline `onclick="app.fooBar()"` handlers extensively —
  these depend on the global `window.app`.
- `script.js` — ES module entry. Defines top-level state, lifecycle (`init`, history, nav
  binding), then **spreads every mixin** into a single object and assigns it to `window.app`.
- `styles.css` — single 6.4k-line stylesheet. Theme variables come from custom properties
  (`--text-muted`, `--font-heading`, etc.). No CSS preprocessor.

Frontend mixins (each exports `export const xMixin = { ... }`):

- `js/utils.js` — helpers (formatters, DOM utilities).
- `js/api.js` — auth, role helpers (`isAdmin`, `canEdit`, `hasRole`), token storage.
- `js/player.js` — HLS.js lifecycle, `getStreamUrls`, `loadPlaybackSource`, native HLS / MP4
  fallback, public match player keyboard shortcuts.
- `js/uploads.js` — chunked uploads, retry/resume, settings asset uploads.
- `js/views.js` — public season view, score reveal, team stats, public match view.
- `js/admin-views.js` — admin panel renderers (matches library, settings, performance,
  diagnostics, tuning knobs).
- `js/admin.js` — admin routing (`/admin/*` sub-sections), status strip polling, live console
  polling.
- `js/ui.js` — modal helper (`app.formModal`), other shared UI primitives.
- `js/live.js` — live page playback, viewer counts, ON-AIR pill.

Backend (read-only for UI work):

- `server.py` — FastAPI app, route registration, lifespan. Routers live under `routers/`,
  shared policy under `services/`.
- `auth.py` — role helpers (`require_role`, `has_role`).
- `db.py` — SQLite schema (single squashed `_migrate_v1`) and queries.
- `models.py` — Pydantic request/response models.
- `media.py`, `live.py`, `streams.py`, `settings.py`, `uploads.py`, `log.py` — domain modules.

Reference docs (load before non-trivial changes):

- `AGENTS.md` — repo source of truth: stack, conventions, key files, editing guidance.
- `CLAUDE.md` — Claude-specific guidance, validation commands.
- `docs/admin-guide.md`, `docs/user-guide.md`, `docs/DEPLOYMENT.md`, `docs/TROUBLESHOOTING.md`.

## Important functions / selectors

DOM ids that JS depends on (do not rename without grep):

- Public match: `#game-view`, `#game-video`.
- Public season: `#season-view`, the match grid, score-reveal chips.
- Live: `#live-view`, `#live-video`.
- Admin: `#admin-view`, `.admin-panel-head`, status strip ids, the
  `<template id="match-form-template">` clone used by Add/Edit Match.

`window.app` global helpers worth knowing:

- Roles: `app.isAdmin()`, `app.canEdit()`, `app.hasRole(role)`.
- History: `app.pushHistoryState`, `app.restoreHistoryState`.
- Modals: `app.formModal({ body, onSubmit })` mounts a template-cloned modal.
- HLS: `app.getStreamUrls(matchId, slot)`, `app.loadPlaybackSource(video, hls, mp4, token)`.

## Constraints

- **Read `AGENTS.md` first** for any unfamiliar area; it is the canonical source.
- **No build step.** The browser loads `script.js` as `<script type="module">`. Anything you
  add must work without transpilation.
- **Inline event handlers exist.** `index.html` calls `app.foo()` directly — never rename a
  public method without grepping `index.html` and templates.
- Do not change the order in which mixins are spread in `script.js`. Adding a mixin: append a
  new import and add it to the spread block; document it in `AGENTS.md`.

## Commands / checks to run

Quick orientation searches:

```bash
# Where is an admin/match thing defined?
rg -n "renderMatchLibraryTable|renderPerformanceTuning|renderTuningKnobsCard" js/ index.html styles.css

# What inline handlers exist? (these are public surface; renames break them)
rg -n "app\.\w+\(" index.html | head -40

# What DOM ids does a view depend on?
rg -n "id=\"game-|id=\"live-|id=\"admin-" index.html

# What roles gate a UI element?
rg -n "hasRole|isAdmin|canEdit" js/

# Validate JS syntax after an edit
node --check script.js
node --check js/admin.js
```

## Common failure modes

- **Renaming a public method silently breaks the UI.** `index.html` invokes `app.foo()` via
  inline `onchange` / `onclick`. There is no compile-time check.
- **Editing mixin spread order in `script.js`.** Earlier mixins win on key conflicts; reordering
  can swap which mixin's method wins.
- **Assuming a framework.** There is no React, JSX, Vue, or store. State is plain object
  fields on `window.app`; rendering is `innerHTML` + `getElementById`.
- **Adding a `package.json` at the repo root.** That introduces a perception of a build step
  and breaks the no-build promise. Don't.

## Done criteria

You can answer these from memory + a single `rg` search:

- For any DOM id under `#admin-view`, which `js/*.js` file owns it?
- For any `app.fooBar()` invocation in `index.html`, which mixin defines `fooBar`?
- Which file holds the role gate that hides `/admin` actions from viewers?

If yes, you're oriented enough to start work.
