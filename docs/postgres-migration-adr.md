# ADR: Postgres Readiness And Alembic Migration Plan

- **Status:** Accepted for platform hardening Phase 6.1
- **Date:** 2026-05-10
- **Owners:** Replay platform maintainers

## Context

Replay currently uses SQLite with homegrown, idempotent migration functions in `db.py` (`_migrate_v0` through `_migrate_v16`). That model has worked for a single-node homelab deployment, but upcoming durable background jobs and AI drafting need stronger concurrency semantics, row-level locking, and operational migration discipline.

The near-term goal is not to remove SQLite from local development. The goal is to define the target database architecture before adding job leasing, AI run audit tables, provider governance, and tenant-sensitive context builders.

## Decision

Replay will adopt **Postgres as the production database backend** and **Alembic as the forward migration runner**.

SQLite remains supported for local/dev and single-laptop validation as long as practical, but it is no longer the production architecture target once the Postgres lane lands.

## Target architecture

- Production uses Postgres via `psycopg` v3.
- Runtime configuration accepts either:
  - `DATABASE_URL`, preferred for production and CI, or
  - `REPLAY_DB_BACKEND=sqlite|postgres` plus backend-specific path/host variables if a later PR keeps split config.
- SQLite remains the default when no database URL/backend is configured.
- Alembic owns all migrations after the baseline revision.
- Both Postgres and SQLite dev lanes invoke Alembic so schema drift is visible early.
- No `pgvector` is required for the AI drafting MVP. Context construction remains structured SQL and application-side prompt assembly.

## Baseline mapping

The existing `db.py` migration chain `_migrate_v0 through _migrate_v16` becomes the **Alembic baseline schema**.

The first Alembic revision should create the schema equivalent to a fresh SQLite database after all current homegrown migrations have run. That baseline must include, at minimum:

- core media tables (`matches`, upload sessions, stream/error/activity/supporting tables),
- users and role/team-season scoping tables,
- coaching notes/clips/playlists/reviews/development/goals/summaries/engagement tables,
- live-stream settings/state tables,
- current indexes, uniqueness constraints, and privacy/scope foreign-key intent that SQLite can represent today.

The baseline revision should be named clearly, for example `0001_sqlite_v16_baseline`.

## Migration contract after baseline

After Alembic is introduced:

1. New schema changes are authored as Alembic revisions only.
2. `db.py` no longer grows new `_migrate_v*` functions.
3. The existing homegrown migration path becomes a compatibility shim:
   - existing SQLite installations can still boot and reach the v16 baseline;
   - once at baseline, startup invokes Alembic to upgrade to head;
   - in a later cleanup PR, the old `_MIGRATIONS` path can be frozen behind an explicit legacy bootstrap helper.
4. CI runs schema tests against SQLite and, where available, Postgres.
5. Any feature relying on production concurrency (jobs, leasing, AI drafting retries) must document SQLite limitations and pass the Postgres lane before being considered production-ready.

## Concurrency and data-type guidance

- Job leasing should use Postgres row locks (`FOR UPDATE SKIP LOCKED`) in production.
- SQLite job leasing may use `BEGIN IMMEDIATE` to serialize local workers but is not the production concurrency model.
- JSON-like payloads use `JSONB` on Postgres and text-encoded JSON on SQLite unless a later compatibility layer standardizes richer SQLAlchemy types.
- Timestamps should be stored in UTC and exposed in ISO 8601.
- IDs may remain integer primary keys; Postgres migrations can use `BIGSERIAL`/identity for high-volume job/run tables.

## Operational migration path

Phase 6.4 will add a one-shot SQLite-to-Postgres migration command. That command must:

1. read SQLite tables in dependency order,
2. write Postgres rows inside controlled transactions,
3. preserve primary keys where practical so file paths, match links, and audit references stay stable,
4. validate row counts per table,
5. validate foreign keys and scope columns,
6. run tenant/privacy canaries against the imported database,
7. produce a human-readable report before production cutover.

## Rejected alternatives

### Keep homegrown migrations indefinitely

Rejected. The current function chain is simple but does not give us branching, offline review, downgrade/repair discipline, or a common migration runner across SQLite and Postgres.

### Move directly to a Postgres-only app

Rejected for the near term. Local development and quick validation benefit from SQLite, and the current deployment history requires a controlled transition.

### Add `pgvector` now

Rejected for the AI drafting MVP. The roadmap needs deterministic scoped evidence references and privacy canaries first. Vector search can be revisited after provider governance, context policy, and audit foundations are in place.

## Consequences

- Phase 6.2 must add the actual Postgres service/test lane and dependency wiring.
- Phase 6.3 durable jobs should target Postgres semantics first while keeping SQLite tests honest for local development.
- Phase 8 AI drafting should reuse durable jobs and audit tables rather than adding a separate queue.
- Deployment docs must call out that SQLite is local/single-node while Postgres is the production target.
