# Replay Pre-AI Platform Delivery Plan

> **For Hermes:** Use `subagent-driven-development` to implement this plan one PR at a time. Each implementation PR must use TDD where behavior changes, add privacy canaries before UI expansion, and pass two-stage review: spec compliance first, code quality second.

**Goal:** Deliver the platform foundation required for a safe coach-side AI drafting assistant: multi-team/season tenancy, scoped authorization, modular backend/frontend surfaces, Postgres-ready durable jobs, minimal team AI governance settings, and then a bounded AI drafting MVP.

**Architecture:** Ship the pre-AI architecture track first: additive team/season schema, scoped query enforcement, service/router extraction, active scope UI, vanilla-JS module split, Postgres + durable jobs, and minimal per-team settings. Defer broad account/onboarding hardening and storage-provider abstraction until after the AI drafting MVP unless those become the product priority.

**Tech Stack:** FastAPI routes in `server.py` moving to `routers/*`, service modules under `services/*`, SQLite migrations in `db.py` through the tenancy phase, later Alembic/psycopg Postgres lane, vanilla JS mixins under `js/` with no build step, Playwright evidence in `tests/e2e/`, and pytest/httpx backend tests in `tests/`.

---

## Delivery Positioning

This plan merges the earlier broad platform hardening roadmap with the architecture-first pre-AI roadmap. The result is the delivery path we should follow if the next major feature is the **coach-side AI drafting assistant**.

The early phases intentionally favor architecture that prevents data leakage and reduces codebase risk before AI lands. Product onboarding/account-hardening remains in the plan, but moves after the pre-AI architecture path unless onboarding becomes a higher priority than AI.

## Current State From Exploration

- **DB:** SQLite with homegrown idempotent `schema_version` migrations in `db.py`; current migrations are `_migrate_v0` through `_migrate_v13`. Do not use `pragma user_version`.
- **Recent coaching schema:** `_migrate_v12` added `player_goals`, goal status history, and goal reflections. `_migrate_v13` added `coaching_match_summaries` and summary join tables. Phase 9 Coach Engagement Dashboard shipped without new tables and aggregates existing notes/playlists/reviews/players/matches.
- **Tenancy:** No tenant column exists yet. Tenancy starts at `_migrate_v14`.
- **Roles:** `users.role` is a comma-separated capability string, e.g. `coach,uploader`; use `_auth.has_role` / `_auth.require_role` and frontend `app.hasRole()` / `app.canCoach()` instead of direct equality.
- **Viewer scoping:** Family/player feedback is currently scoped mainly through `player_user_links`.
- **Visibility ladder:** `_filter_notes_for_user`, `_filter_clips_for_user`, `_filter_playlists_for_user`, goal/summary equivalents, and `_strip_private_fields` enforce visibility and scrub `coach_private_note`. `coach_private_note` exists on both `coaching_notes` and `player_goals`; both must remain scrubbed from viewer/family surfaces and AI context.
- **Storage:** `media.py` paths are currently match-keyed under video/original directories, not team-prefixed.
- **Background jobs:** `_spawn_task`, in-memory transcode task dictionaries, and `ResizableSemaphore` gate background work. There is no durable job table.
- **Frontend:** Zero build step. `script.js` assembles mixins into `window.app`. `js/coaching.js` is large and spans Coach + My Feedback surfaces. `js/tactical-board.js` is the cleanest existing isolated module pattern.
- **Repo guardrail:** `.agent-skills/README.md` says no frontend build step — no React, Vue, Svelte, Vite, Webpack, Rollup, esbuild, Tailwind, shadcn, JSX, or TypeScript build pipeline.

## Product Scope Decisions

### Locked for this delivery plan

- **Tenancy depth:** Multi-team within one implicit club. Add `teams` and `seasons`; defer `organizations` until a second club exists.
- **Season scope:** Add `season_id` where it materially affects filtering/history: at minimum matches and players, plus coaching objects where they can be season-specific. Join tables inherit tenancy through parent FKs unless direct filtering requires otherwise.
- **Postgres timing:** Postgres readiness and durable jobs land before AI so the assistant does not launch on a transitional storage/job model.
- **AI shape:** Coach-side drafting assistant, not a broad copilot/chat product. Stateless prompts first. No embeddings, no retrieval, no `pgvector`, no GPU workers, no player-side chat, and no autonomous publishing.
- **Frontend modernization:** Split vanilla-JS mixins only. No framework and no build step.
- **Security invariant:** AI context and draft targets never include `coach_private_note` from notes or goals.

### Deferred unless product priority changes

- Public self-service signup.
- MFA.
- Full email/provider integration beyond dev/admin-visible token delivery.
- Multi-club `organizations` table.
- Object storage/S3/R2 migration.
- React/Svelte/Vue or any frontend build step.
- Player-side AI chat, retrieval, embeddings, auto-analysis, or GPU-worker pipelines.
- Billing, mobile apps, public marketing site.

## Default Scope Contract

Until multi-team UI is fully active:

- Existing single-team deployments behave as before.
- Requests without explicit `team_id` / `season_id` resolve to the deterministic default team and active/default season when unambiguous.
- Existing coach/admin/viewer routes remain backwards compatible during migration.
- Once a user has multiple eligible teams, the app must use a saved/selected active team or return a clear selection-required response.
- System/global admin recovery operations remain possible through explicit global-admin paths, but normal scoped resources should require scoped membership.

## Authorization Model

`users.role` remains for legacy/global compatibility. Team resources use `team_user_memberships.role`.

### Role Precedence

- `users.role` containing `admin` is a **global/system recovery role**, not a blanket bypass for every normal team-scoped route.
- Team resources should require `team_user_memberships` for the target team unless the route intentionally calls a global-admin override helper.
- Scoped membership roles control team resources.
- Legacy `users.role` values such as `coach`, `viewer`, and `uploader` are compatibility fallbacks during migration only; new authorization paths should prefer team memberships.

### Role Matrix

- **Global/system admin:** recovery and cross-team ops routes; can explicitly manage all teams through global-admin endpoints.
- **Team admin:** manage roster, memberships, invites, team settings, and team data for assigned team(s).
- **Coach:** manage coaching objects for assigned team/season.
- **Assistant coach:** view/write coaching objects according to exact implementation permissions; no membership/admin settings by default.
- **Guardian:** view linked player feedback/goals/summaries only within scoped team/season.
- **Player:** view own feedback/goals if player login is enabled.
- **Viewer:** legacy/basic read role; no coach/admin APIs.

## Scope Resolution Rules

Every scoped API should use a central resolver. Target contract:

```python
resolve_scope(request, user, *, team=None, team_id=None, season_id=None, require_role=None)
```

The resolver returns:

- current user
- team
- season, when applicable
- membership
- effective scoped role
- `is_global_admin`

Resolution order:

1. If explicit `team` slug / `team_id` / `season_id` is provided, validate membership and resource scope.
2. Else use saved/selected active team (`users.last_team_id`) and selected/active season when available.
3. Else if the user has exactly one eligible team/season, use it.
4. Else return clear `400` / `409` requiring team/season selection.
5. Viewer/family endpoints should return empty results or `404` for unrelated/cross-team resources where probing risk exists.

## Migration And Backfill Contract

Every migration must be idempotent and preserve legacy single-team data.

Required pattern:

1. Add tables/columns additively where SQLite allows.
2. Keep new tenant columns nullable during first backfill migration.
3. Create one deterministic default team and season.
4. Backfill users into default memberships.
5. Attach existing matches, players, player links, notes, clips, playlists, goals, summaries, reviews, thumbnails/source relationships, and engagement inputs to default scope.
6. Backfill scoped coaching data from linked match/player scope where possible; otherwise use default team/season.
7. Add indexes after data exists.
8. Verify row counts and scoped counts before/after migration in tests.
9. Flip required columns to NOT NULL only after verified backfill, likely via a follow-up rebuild migration on SQLite.

Default names:

- `Default Team` or a team name derived from existing branding/settings.
- `Default Season`.

## Release Gates

- Do not start AI drafting implementation until Phases 1-7 are complete or explicitly waived.
- Do not add AI context-builder access to any table until that table has team-scope tests.
- Do not launch AI before `coach_private_note` canary tests pass for both notes and goals.
- Do not add UI that calls a scoped endpoint before direct-object-access tests exist for that endpoint.
- Do not move production to Postgres until scoped privacy tests and SQLite/Postgres migration validation are green.
- Keep current single-team default behavior working through every PR.
- Every token-like feature must store hashes only, never raw tokens.
- Every behavior PR must update relevant docs/roadmaps/helper notes before merge.
- Validation-only runs on `main` must restore unintended screenshot/capture drift before reporting completion.

---

## Phase 1 — Team/Season Tenancy Data Model

**Objective:** Add team/season tenancy to the data model with deterministic single-team backfill and no user-visible behavior change.

### PR 1.1: Team, Season, Membership Tables

**Files:**

- Modify: `db.py`
- Modify: `auth.py`
- Create: `tenancy.py` or `services/scopes.py` if the service package exists at that point
- Test: `tests/test_tenancy.py`
- Update: `docs/_seed/seed.py` if seed data needs team/season records

**Schema target:**

- `teams`: `id`, `name`, `slug UNIQUE`, `game_format`, `created_at`.
- `seasons`: `id`, `team_id`, `name`, `starts_on`, `ends_on`, `created_at`.
- `team_user_memberships`: `id`, `team_id`, `user_id`, `role`, `created_at`; unique on `(team_id, user_id, role)`.
- `users.last_team_id` nullable.

**Implementation notes:**

- Use `_migrate_v14` for additive tables/columns/backfill.
- Create one default team and one default season.
- Backfill users whose role contains `admin`, `coach`, `viewer`, or player/family capabilities into appropriate default memberships.
- Add helpers to fetch default team/season and user memberships.
- Defer `organizations`; do not add `organization_id` yet.

**Tests:**

- Migration is idempotent.
- Default team/season created once.
- Existing users get expected default memberships.
- Existing global admin role remains available for recovery/global endpoints.
- `users.last_team_id` can be null for legacy users.

### PR 1.2: Tenant Columns On Core Tables

**Files:**

- Modify: `db.py`
- Modify: relevant DB helper functions in `db.py`
- Test: `tests/test_tenancy.py`, focused additions to `tests/test_coaching.py`

**Schema target:**

- Add `team_id` to `matches`, `players`, `player_user_links`, `coaching_notes`, `coaching_clips`, `coaching_playlists`, `player_goals`, and `coaching_match_summaries`.
- Add `season_id` to `matches` and `players`.
- Add `season_id` to coaching objects that need explicit season filtering; otherwise derive via match/player where unambiguous.
- Do not add tenant columns to join tables that inherit scope through parent FK unless direct filtering requires it.

**Player-link decision:**

`player_user_links` are team-scoped and season-independent for the first implementation. If future season-specific guardianship is required, add nullable `season_id`; `NULL` means the link applies across seasons for that team.

**Backfill rules:**

- Existing rows get default `team_id`.
- Existing matches get default `season_id`.
- Existing players get default `season_id` unless the implementation intentionally leaves player season optional.
- Coaching objects linked to a match inherit match team/season.
- Coaching objects linked only to a player inherit player team and default/active season.
- Observation-style/no-match objects fall back to default team/season.

**Tests:**

- Existing row counts preserved.
- Existing single-team list endpoints behave the same.
- Cross-table team/season backfill is consistent.
- Re-running migration does not duplicate or corrupt scope rows.

### PR 1.3: Enforce Non-Null Scope Where Safe

**Files:**

- Modify: `db.py`
- Test: `tests/test_tenancy.py`

**Implementation notes:**

- Use `_migrate_v15` to enforce NOT NULL / rebuild tables where SQLite requires rebuilds.
- Only enforce NOT NULL after tests prove all legacy rows backfill correctly.
- Add indexes for frequent filters, e.g. `(team_id)`, `(team_id, season_id)`, `(team_id, player_id)`, `(team_id, match_id)` where relevant.

**Tests:**

- Fresh DB creates required schema.
- Existing DB migrates cleanly from pre-tenancy state.
- Tenant columns are non-null where contract says they are non-null.
- Migration remains idempotent.

---

## Phase 2 — Tenant-Scoped Query Enforcement

**Objective:** Make cross-team data leakage hard to write by accident before any multi-team UI or AI context builder exists.

### PR 2.1: Scope Resolver And Team Role Helpers

**Files:**

- Create/modify: `tenancy.py` or `services/scopes.py`
- Modify: `auth.py`
- Test: `tests/test_tenancy.py`

**Key changes:**

- Add `current_team(request)` or `resolve_scope(...)`.
- Resolve active team from `?team=<slug>` / `team_id`, then `users.last_team_id`, then only membership if exactly one.
- Add `_require_team_role(team_id, *roles)`.
- Add explicit `_require_global_admin` for recovery/cross-team ops.
- A user without membership for the target team gets `403` even if `users.role` says `coach`; global admin override must be explicit.

**Tests:**

- Coach with Team A membership can access Team A.
- Coach without Team B membership cannot access Team B.
- Multi-team user without selected scope gets selection-required response.
- Global admin override path works only through explicit helper.

### PR 2.2: Visibility Helpers Accept Team Scope

**Files:**

- Modify initially: `server.py`
- Later extraction target: `services/visibility.py`
- Test: `tests/test_coaching.py`, `tests/test_tenancy.py`

**Key changes:**

- Update `_filter_notes_for_user(notes, user, team_id)`.
- Update `_filter_clips_for_user(clips, user, team_id)`.
- Update `_filter_playlists_for_user(playlists, user, team_id)`.
- Update goal and match-summary visibility helpers with the same team-scope contract.
- Keep visibility and payload scrubbing separate.
- Scrub `coach_private_note` for both notes and goals.

**Tests:**

- Coach for Team A cannot read or CRUD Team B notes/clips/playlists/goals/summaries.
- Viewer linked to Team A player cannot see Team B player data.
- Private notes remain excluded from viewer/family surfaces.
- `coach_private_note` is not present in viewer/family payloads for notes or goals.

### PR 2.3: Scoped Endpoint Enforcement

**Files:**

- Modify: `server.py`
- Modify: `db.py` list/get helpers as needed
- Test: `tests/test_coaching.py`, `tests/test_tenancy.py`

**Key changes:**

- Resolve team at top of `/api/coach/*` and `/api/my-feedback/*` handlers.
- Pass `team_id` into DB queries and visibility helpers.
- Add optional `team_id` / `team` / `season_id` query parameters where needed.
- Viewer/family endpoints return empty or `404` for unrelated scoped resources.
- Direct object routes must validate the object belongs to the resolved team.

**Tests:**

- Direct-object access fails across teams for notes, clips, playlists, goals, summaries, thumbnails, development profiles, engagement source pickers.
- Existing single-team behavior remains unchanged.
- Wrong-team `?team=` values without membership return `403` / selection-safe errors.

### PR 2.4: Engagement Dashboard Team Scope

**Files:**

- Modify: `server.py`
- Modify: `db.py`
- Test: `tests/test_coaching.py`

**Key changes:**

- `_build_coach_engagement_dashboard` must accept/pass `team_id`.
- DB calls used by engagement aggregation gain optional `team_id=` keyword with backward-compatible default only where still needed.
- Add strict team filtering to players, notes, playlists, reviews, and matches used by engagement.

**Must preserve Phase 9 privacy invariants:**

1. Reviews scope to selected player's linked users via `linked_user_ids_by_player`.
2. `visibility == "private"` notes remain excluded from metrics.
3. Playlist attribution is computed from underlying matched notes, not unioned filters.

**Tests:**

- Team A coach cannot see Team B engagement metrics by passing `?team=B` without membership.
- Private notes remain excluded after team filtering.
- Playlist attribution invariant remains unchanged.
- Existing Phase 9 tests still pass.

### PR 2.5: Strict Tenancy Test Mode

**Files:**

- Modify: `db.py` or test fixtures
- Modify: `tests/conftest.py` if present
- Test: targeted strict-mode tests

**Key changes:**

- Add `REPLAY_STRICT_TENANCY=1` mode enabled by default in tests.
- In strict mode, tenant-aware query helpers that should receive `team_id` fail loudly when omitted.
- Keep production/backward-compatible defaults only where explicitly documented.

**Tests:**

- Strict mode catches omitted `team_id` in representative helper calls.
- Non-strict legacy fallback still works where needed for transition.

---

## Phase 3 — Backend Router And Service Split

**Objective:** Shrink `server.py` and centralize policy before AI endpoints land.

### PR 3.1: Extract Visibility Service

**Files:**

- Create: `services/visibility.py`
- Modify: `server.py`
- Test: `tests/test_coaching.py`, `tests/test_tenancy.py`

**Key changes:**

- Move `_filter_*_for_user`, `_strip_private_fields`, and `_can_view_*` helpers to `services/visibility.py`.
- Preserve behavior exactly except for already-tested team enforcement.
- Keep scrubbing separate from visibility.

**Tests:**

- Existing privacy suite remains green.
- Notes/goals `coach_private_note` canaries pass.
- Cross-team variants pass.

### PR 3.2: Extract Engagement, Thumbnails, Activity Services

**Files:**

- Create: `services/engagement.py`
- Create: `services/thumbnails.py`
- Create: `services/activity.py`
- Create: `services/media_paths.py` if useful as a wrapper around `media.py`
- Modify: `server.py`
- Test: focused affected tests plus full `tests/test_coaching.py`

**Key changes:**

- Move `_build_coach_engagement_dashboard` and helpers into `services/engagement.py`.
- Move thumbnail spawn/regenerate helpers into `services/thumbnails.py`.
- Move activity label/log wrappers into `services/activity.py`.
- Keep behavior unchanged.

**Tests:**

- Engagement tests pass.
- Thumbnail direct-access/privacy tests pass.
- Activity event tests, if present, pass.

### PR 3.3: Router Split By Domain

**Files:**

- Create: `routers/auth.py`
- Create: `routers/matches.py`
- Create: `routers/uploads.py`
- Create: `routers/live.py`
- Create: `routers/admin.py`
- Create: `routers/coach_notes.py`
- Create: `routers/coach_clips.py`
- Create: `routers/coach_playlists.py`
- Create: `routers/coach_review.py`
- Create: `routers/coach_observations.py`
- Create: `routers/coach_goals.py`
- Create: `routers/coach_summaries.py`
- Create: `routers/coach_engagement.py`
- Create: `routers/feedback.py`
- Modify: `server.py`
- Test: full suite and Playwright captures

**Key changes:**

- Move routes into APIRouters one domain at a time.
- `server.py` should shrink toward app factory/lifespan/middleware/router includes/SPA shell.
- Preserve route paths, response shapes, auth behavior, and CORS/middleware behavior.

**Tests:**

- Run full pytest after each router move or small batch.
- Route path compatibility tests remain green.
- Playwright phase captures still pass after frontend-visible route moves.

---

## Phase 4 — Active Team/Season Selection

**Objective:** Add explicit active scope before onboarding or AI UX depends on implicit defaults.

### PR 4.1: `/api/me` Scope Summary Minimal API

**Files:**

- Modify: `server.py` or `routers/auth.py`
- Modify: `db.py`
- Test: `tests/test_tenancy.py`

**Key changes:**

- Add or extend `GET /api/me` to return current user, memberships/available teams, available seasons, and active scope.
- Do not add full profile management yet.
- Do not allow users to edit roles/memberships through this endpoint.

**Tests:**

- Single-team user gets one active scope.
- Multi-team user gets all eligible teams without sensitive user data.
- Viewer/family memberships do not expose unrelated player data.

### PR 4.2: Active Scope Persistence

**Files:**

- Modify: `server.py` or relevant router
- Modify: `db.py`
- Test: `tests/test_tenancy.py`

**Key changes:**

- Add endpoint to update `users.last_team_id` and optional last season preference if implemented.
- Validate membership before saving.
- If membership is revoked later, active scope becomes invalid and requires reselection.

**Tests:**

- User can save a team they belong to.
- User cannot save a team they do not belong to.
- Invalid active scope produces selection-required response.

### PR 4.3: Active Team/Season Selector UI

**Files:**

- Modify: `js/coaching.js` initially, or extracted modules if already split
- Modify: `js/api.js`
- Modify: `index.html` if templates are needed
- Modify: `styles.css`
- Test: `tests/e2e/*` captures where appropriate

**Key changes:**

- Add visible active team/season selector for multi-team coach/admin users.
- Keep single-team UX simple.
- Include selected team/season in scoped API calls.
- Clear stale data before reloading scoped bundles to prevent cross-team flashes.

**Tests:**

- Switching teams changes roster/content.
- Switching seasons changes match/coaching content where season-scoped.
- No stale cross-team data remains after switch.
- Single-team default behavior remains unchanged.

---

## Phase 5 — Frontend Modularization, No Framework

**Objective:** Split the coach/frontend code before adding AI UI. Preserve `window.app` mixin behavior and keep zero build step.

### PR 5.1: API And Shared State Extraction

**Files:**

- Modify: `js/coaching.js`
- Modify: `js/api.js`
- Create: `js/coaching/state.js` if useful
- Test: `node --check`, Playwright smoke/captures

**Key changes:**

- Move shared coaching API wrappers and active scope helpers into smaller modules.
- Preserve existing `app.*` handlers and route behavior.
- No behavior changes.

**Tests:**

- `node --check` for all touched JS.
- No missing `app.*` handlers.
- Existing coach workspace smoke tests pass.

### PR 5.2: Split Coaching Domain Modules

**Files:**

- Create: `js/coaching/roster.js`
- Create: `js/coaching/notes.js`
- Create: `js/coaching/clips.js`
- Create: `js/coaching/playlists.js`
- Create: `js/coaching/review.js`
- Create: `js/coaching/observations.js`
- Create: `js/coaching/development.js`
- Create: `js/coaching/goals.js`
- Create: `js/coaching/match-summaries.js`
- Create: `js/coaching/engagement.js`
- Create: `js/coaching/feedback.js`
- Create: `js/coaching/feedback-player.js`
- Create: `js/coaching/thumbnails.js`
- Move/rename: `js/coaching-templates.js` to `js/coaching/templates.js` if practical
- Modify: `script.js`
- Modify: `index.html` script tags
- Test: JS checks and Playwright captures

**Key changes:**

- Follow `js/tactical-board.js` mixin style.
- Keep one `window.app` assembly path.
- Do not add Vite or any build tool.
- Preserve inline handlers and templates.

**Tests:**

- `node --check script.js js/**/*.js` or explicit touched-file checks.
- Coach Review, observations, goals, summaries, engagement, and My Feedback smoke/captures pass.
- No missing handlers or null/undefined UI states.

### PR 5.3: CSS Split Only If Safe

**Files:**

- Modify/split: `styles.css`
- Potential creates: `styles/base.css`, `styles/admin.css`, `styles/coaching.css`, `styles/feedback.css`, `styles/tactical-board.css`
- Modify: `index.html`
- Test: visual captures

**Key changes:**

- Split CSS only if it can be done without build tooling.
- Preserve dark/light theme support.
- Avoid unthemed controls, raw browser chrome, and horizontal overflow regressions.

**Tests:**

- Playwright captures for admin, coach, feedback, review/tactical board.
- Manual light/dark smoke when UI changed.

---

## Phase 6 — Postgres Readiness And Durable Jobs

**Objective:** Move database/job architecture to the target shape before AI drafting assistant launches.

### PR 6.1: Database Backend ADR And Alembic Plan

**Files:**

- Create: `docs/postgres-migration-adr.md` or similar
- Modify: `docs/DEPLOYMENT.md`
- Test/validation: documentation review plus existing SQLite tests

**Key decisions to document:**

- Adopt Alembic for migrations going forward or define why not.
- Keep SQLite as local/dev/single-laptop backend only if feasible.
- Use Postgres with `psycopg` v3 and connection pooling for production.
- Define how `_migrate_v0..v15` maps to a baseline.
- Confirm no `pgvector` for drafting MVP.

### PR 6.2: Postgres Compose And Test Lane

**Files:**

- Modify: `docker-compose-intel.yml`
- Modify: CI config if present
- Modify: `pytest.ini` or test configuration
- Modify: `db.py` / config as needed
- Test: SQLite + Postgres lanes where practical

**Key changes:**

- Add optional Postgres service.
- Add `REPLAY_DB_BACKEND=sqlite|postgres` or `DATABASE_URL` design.
- Add test lane for core DB behavior against Postgres where practical.

**Tests:**

- Existing SQLite tests remain green.
- Core DB tests pass against Postgres lane.
- Dialect-specific behavior is documented.

### PR 6.3: Durable Background Jobs

**Files:**

- Modify: `db.py` / Alembic migrations
- Modify: `server.py` / services using background tasks
- Test: new `tests/test_jobs.py` or equivalent

**Schema target:**

- `background_jobs`: `id`, `kind`, `payload_json`, `status`, `attempts`, `scheduled_at`, `started_at`, `finished_at`, `error_text`, `team_id`, timestamps.

**Key changes:**

- Add durable job lifecycle helpers.
- Keep existing transcode execution path initially, but record status where useful.
- Reuse this table for AI drafting jobs instead of making an AI-only queue.
- Make job access team-scoped.

**Tests:**

- Job status lifecycle.
- Retry/attempt fields update correctly.
- Team A user cannot inspect Team B jobs.
- Existing background transcode behavior still works.

### PR 6.4: SQLite To Postgres Migration Command

**Files:**

- Create: migration/export script under `scripts/` or `tools/`
- Modify: `docs/DEPLOYMENT.md`
- Test: migration smoke tests / dev DB row-count diff

**Key changes:**

- One-shot migration reads SQLite and writes Postgres in dependency order.
- Validate row counts, foreign keys, scope columns, and privacy canaries after import.

**Tests/validation:**

- Dev DB migrates successfully.
- Row counts match per table.
- Foreign keys validate.
- Cross-team privacy tests pass against migrated Postgres data.

---

## Phase 7 — Minimal Team Settings For AI Governance

**Objective:** Add a per-team settings registry focused on safe AI rollout and a few critical coaching defaults. Defer the full settings UI catalog until after AI unless needed.

### PR 7.1: Team Settings Schema And Registry

**Files:**

- Modify: `db.py` / Alembic migrations
- Create: `services/team_settings.py`
- Test: `tests/test_team_settings.py`

**Schema target:**

- `team_settings`: `team_id`, `key`, `value_json`, `updated_at`, `updated_by`; unique `(team_id, key)`.

**Registry pattern:**

- Closed `TEAM_SETTING_SCHEMAS`, similar to global `TUNING_KNOBS` in `settings.py`.
- Validate types, enums, ranges, max lengths.
- Audit writes through existing activity/settings audit patterns where appropriate.

**Initial keys:**

- `ai.drafting_enabled`: bool, default false.
- `ai.allowed_draft_targets`: array enum of `player_summary`, `what_happened`, `why_it_matters`, `what_to_do_next`, `clip_title`, `clip_description`, `goal_description`, `goal_success_criteria`, `summary_team_positives`, `summary_team_improvements`, `summary_training_focus`.
- `ai.tone`: enum `direct`, `encouraging`, `technical`.
- `ai.never_draft_for_visibilities`: array enum `private`, `player`.
- `notes.default_visibility`: optional early coaching default if easy.
- `summaries.default_visibility`: optional early coaching default if easy.
- `goals.default_visibility`: optional early coaching default if easy.

**Permanent exclusions:**

- No setting may allow drafting or context inclusion for `coach_private_note`.

**Tests:**

- Valid setting writes pass.
- Invalid key/type/range/enum returns `422`.
- Team A coach cannot read/write Team B settings.
- Raw JSON cannot smuggle unsupported AI targets.

### PR 7.2: Team Settings API And Minimal UI

**Files:**

- Create: `routers/team_settings.py` or include in coach/admin router
- Modify: `js/coaching/settings.js` if frontend modules are split
- Modify: `index.html`
- Modify: `styles.css`
- Test: `tests/test_team_settings.py`, Playwright if UI added

**Key changes:**

- Add `GET /api/coach/team/settings`.
- Add `PATCH /api/coach/team/settings`.
- Require team admin or coach role on active team for AI settings; decide if only team admin can toggle `ai.drafting_enabled`.
- Add minimal Coach > Settings surface if needed before AI; hide AI group until provider is configured if appropriate.

**Tests:**

- Scoped read/write enforcement.
- PATCH validates each key.
- UI visible only to eligible roles.
- Settings are loaded with active team and change when team switches.

### Future Full Team Settings Phase

After AI MVP, expand the registry/UI to cover:

- notes and observations defaults
- review composer defaults
- tactical board defaults
- coach templates
- playlists and review sessions
- player development and feedback
- roster/player linking
- player goals
- match summaries
- engagement dashboard defaults

Do not block AI MVP on the full catalog unless product needs require it.

---

## Phase 8 — AI Drafting Assistant MVP

**Objective:** Ship a bounded coach-side drafting assistant that uses scoped context and produces coach-private drafts only.

### PR 8.1: AI Drafting Run Model And Audit

**Files:**

- Modify: migrations / `db.py` or Alembic
- Create: `services/ai_drafting.py`
- Test: `tests/test_ai_drafting.py`

**Key changes:**

- Prefer reusing `background_jobs` for slow runs and adding a small `ai_drafting_runs` audit table if needed.
- Include required `team_id`, optional `season_id`, `created_by_user_id`, draft target, provider, model, input/output token counts if available, status, error code/message, timestamps, and evidence references.
- Do not add chat threads/messages unless there is a clear product need.

**Tests:**

- Runs are team-scoped.
- Audit rows persist success/failure.
- Team A cannot access Team B runs.

### PR 8.2: Privacy-Safe Context Builder

**Files:**

- Create: `services/ai_context.py`
- Modify: `services/visibility.py` if needed
- Test: `tests/test_ai_drafting.py`, privacy canaries

**Key changes:**

- Build context only through scoped DB queries and `services/visibility.py`.
- Support evidence references from notes, clips, playlists, goals, summaries, engagement, and development profile only when allowed.
- Prefer compact evidence references over raw full dumps.
- Exclude `coach_private_note` always.
- Exclude private notes/playlist descriptions/tactical board JSON unless explicitly reviewed and allowed for a coach-private draft target.

**Tests:**

- `coach_private_note` from notes never appears.
- `coach_private_note` from goals never appears.
- Cross-team notes/goals/clips/playlists/summaries never appear.
- Unlinked player data never appears.
- Disallowed draft target is rejected by team settings.

### PR 8.3: Provider Interface And Mock Provider

**Files:**

- Create: `services/ai_providers.py`
- Create/modify: settings/config docs
- Test: `tests/test_ai_drafting.py`

**Key changes:**

- Add provider abstraction.
- Add mock provider first for tests.
- Add timeout/error handling.
- Record failed run states.
- Keep no streaming infra in MVP.

**Tests:**

- Successful mock draft.
- Provider failure recorded.
- Timeout/error returns safe response.
- Retry-safe state transitions.

### PR 8.4: Drafting API

**Files:**

- Create: `routers/coach_ai.py`
- Modify: router registration
- Test: `tests/test_ai_drafting.py`

**Key changes:**

- Add `/api/coach/ai/draft` or similarly narrow endpoint.
- Input includes target field, resource references, active scope, and optional coach prompt.
- Enforce `ai.drafting_enabled` and `ai.allowed_draft_targets`.
- For short prompts, return synchronously; for long prompts, enqueue `background_jobs` and return job/run id.
- Generated output remains a draft and is not visible to players/family until explicitly saved into a normal scoped coaching object.

**Tests:**

- Coach-only access.
- Team settings opt-in required.
- Disallowed target rejected.
- Cross-team resource reference rejected.
- Draft output not visible in `/api/my-feedback/*` until explicitly saved through existing endpoints.

### PR 8.5: Drafting UI

**Files:**

- Create: `js/coaching/ai.js`
- Modify: `script.js`
- Modify: `index.html`
- Modify: `styles.css`
- Test: Playwright captures/smoke

**Key changes:**

- Add minimal drafting controls near existing composer/editor surfaces, not a broad chat UI.
- Support draft target selection, optional instruction, evidence selection, and insert/replace into editable field.
- Clearly label AI output as draft.
- No automatic publish/save.

**Tests:**

- Coach can draft allowed field.
- UI hidden/disabled when team setting disabled.
- Player/family cannot access AI UI or draft endpoint.
- Active team switch clears AI draft/evidence state.

---

## Phase 9 — Account And Onboarding Hardening

**Objective:** Add product onboarding/account flows after the architecture and AI MVP unless product priority moves this earlier.

### PR 9.1: User Profile Schema And `/api/me` Full Profile

**Files:**

- Modify: `db.py` / migrations
- Modify: relevant auth/profile router
- Test: `tests/test_auth.py` or new `tests/test_profiles.py`

**Key changes:**

- Prefer companion `user_profiles` table.
- Add email, normalized email, email verification timestamp, first/last name, phone, timezone, locale, preferred contact method.
- Preserve username-only legacy accounts.
- Extend `/api/me` profile payload without exposing sensitive data.

**Tests:**

- Email normalization and uniqueness.
- Nullable email allowed for legacy users.
- User cannot edit role/memberships via profile.

### PR 9.2: Password, Session, Email Verification, Reset

**Files:**

- Modify: auth/session tables and routers
- Test: `tests/test_auth.py`

**Key changes:**

- Durable `user_sessions` storing token hashes only.
- Password change endpoint.
- Password reset tokens and email verification tokens store hashes only.
- Dev/admin-visible token delivery is acceptable until SMTP/email provider is configured.
- Password change/reset revokes sessions.

**Tests:**

- Token hashes stored, raw tokens never stored.
- Expired/reused tokens rejected.
- Disabled user/session cannot continue.
- Password reset revokes existing sessions.

### PR 9.3: Team Member Management And Invites

**Files:**

- Modify/create team member routers/UI
- Test: `tests/test_team_members.py` or equivalent

**Key changes:**

- Team member list UI/API.
- Grant/revoke memberships.
- Staff and guardian invites by email.
- Invite fields: `team_id`, optional `season_id`, `normalized_email`, `role`, `status`, `token_hash`, `expires_at`, `accepted_at`, `revoked_at`, `created_by_user_id`, metadata for player links.
- Prevent removing last team admin unless global admin override exists.

**Tests:**

- Role differs by team.
- Revoked membership loses access.
- Invites cannot be replayed.
- Existing-user and new-user invite acceptance.
- Last-admin protection.

### PR 9.4: CSV Roster Import And Guardian Linking

**Files:**

- Modify/create roster import endpoints/UI
- Test: `tests/test_roster_import.py` or equivalent

**Key changes:**

- Preview/commit split:
  - `POST /api/coach/players/import/preview`
  - `POST /api/coach/players/import/commit`
- Preview performs no DB writes.
- Support duplicate detection, partial failures, re-import behavior.
- Guardian emails create/link invites/accounts.
- One guardian can link to multiple players.

**Tests:**

- Valid preview/commit.
- Preview creates no records.
- Duplicate guardian email links same account/invite.
- Wrong-team/stale import links blocked.
- Family sees only linked players.

---

## Phase 10 — Storage Provider Boundary, Conditional

**Objective:** Prepare media paths for hosted/object storage only when needed.

Trigger this phase when:

- A second team needs its own media partition beyond DB-level privacy.
- Hosted/object storage deploy is scheduled.
- Local disk layout becomes operationally painful.

**Files:**

- Create: `services/storage.py`
- Modify: `media.py`
- Modify: `docs/DEPLOYMENT.md`
- Test: media path and thumbnail/privacy tests

**Key changes:**

- Introduce `StorageProvider` interface: local first, S3/R2 later.
- Make new media object keys team-aware, e.g. `teams/<team_id>/matches/<match_id>/...`.
- Keep current filesystem paths resolving during migration.
- Do not weaken thumbnail/media visibility checks.

**Tests:**

- Existing media paths still resolve.
- New provider returns deterministic scoped keys.
- Thumbnail/media direct-access privacy canaries pass.

---

## Required Validation

### Per PR Baseline

Run focused tests first, then baseline checks before review:

```bash
python3 -m py_compile server.py media.py models.py db.py auth.py settings.py uploads.py log.py live.py streams.py docs/_seed/seed.py
node --check script.js js/coaching.js js/player.js js/api.js
pytest tests/test_coaching.py -v
pytest tests/ -v
```

If frontend files are split, replace/add explicit checks for touched modules, for example:

```bash
node --check script.js js/api.js js/coaching/*.js js/tactical-board.js
```

### Coverage / Full Integration Gate

For major phase closeout:

```bash
pytest tests/ -v --cov --cov-report=term-missing
```

Do not regress below the existing CI threshold.

### Playwright / Capture Gate

When touching Coach, My Feedback, Review, Engagement, or shared CSS:

```bash
cd tests/e2e
npm test
npm run capture-phase-7
npm run capture-phase-8
npm run capture-phase-9
```

On `main`, restore unintentional generated screenshot/capture diffs unless Huy explicitly asks to keep or commit them.

### Tenancy-Specific Validation

After Phases 1-2:

```bash
REPLAY_STRICT_TENANCY=1 pytest tests/test_tenancy.py -v
REPLAY_STRICT_TENANCY=1 pytest tests/test_coaching.py -v
```

Required canaries:

- Non-member coach cannot read/write another team's notes.
- Non-member coach cannot access another team's clips/playlists/goals/summaries.
- Viewer linked to Team A player cannot see Team B player.
- Team A coach cannot see Team B engagement metrics.
- Direct IDs and thumbnails do not bypass scope.

### Postgres Validation

After Phase 6:

```bash
REPLAY_DB_BACKEND=sqlite pytest tests/ -v
REPLAY_DB_BACKEND=postgres pytest tests/ -v
```

Also run one SQLite-to-Postgres dev migration and verify:

- row counts match per table
- foreign keys validate
- scoped tenant columns are non-null where required
- privacy canaries pass against migrated Postgres data

### AI Privacy Validation

Before enabling AI outside mock/provider tests:

```bash
pytest tests/test_ai_drafting.py -v
pytest tests/test_coaching.py -v -k "private or visibility or thumbnail or feedback or engagement"
```

Required canaries:

- `coach_private_note` from `coaching_notes` never enters AI context.
- `coach_private_note` from `player_goals` never enters AI context.
- Cross-team objects never enter AI context.
- Disallowed draft targets are rejected.
- AI output is not visible to players/family until explicitly saved/published through existing scoped endpoints.

### Manual Smoke Checklist

After each phase closeout:

1. Seed a fresh data dir with `docs/_seed/seed.py`.
2. Login as coach/admin.
3. Click through Coach > Roster, Notes, Clips, Playlists, Summaries, Review, Engagement.
4. Login as viewer/family linked to a player.
5. Click through `/feedback` notes/clips/playlists/development/goals/summaries.
6. Verify `coach_private_note` is invisible on every viewer surface.
7. For multi-team phases, switch teams and confirm old team data disappears before new data loads.
8. Check browser console for JS errors.

## Documentation Closeout Contract

As phases land, update relevant living docs when behavior, commands, architecture, or validation changes:

- `ROADMAP.md` if present
- `AGENTS.md`
- `CLAUDE.md`
- `.agent-skills/README.md`
- `docs/DEPLOYMENT.md`
- `docs/TROUBLESHOOTING.md`
- `docs/user-guide.md`
- `docs/admin-guide.md`
- `docs/coach-guide.md`
- `docs/coaching-analysis-feature-roadmap.md`
- this plan, if phase ordering changes

Completion reports for each PR must state:

- files changed
- tests/checks run and results
- privacy canaries added/updated
- docs updated or why not
- generated artifacts restored or intentionally kept
- remaining known gaps

## Execution Notes

Implement one PR/task at a time. For code changes:

1. Write failing focused test.
2. Run it and confirm the expected failure.
3. Implement the smallest safe change.
4. Run focused test and baseline checks.
5. Update docs/helper notes.
6. Review diff for scope creep.
7. Run spec-compliance review.
8. Run code-quality/security/privacy review.
9. Only then proceed to the next PR.
