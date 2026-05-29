# Replay — Roadmap

## What this is now

Replay is a single-team match video platform:

- **VOD library** — chunked resumable upload → ffmpeg transcode → multi-variant HLS ladder, with a direct MP4 fallback for download and casting. Matches are a flat, global library grouped by a season **label** in the public view.
- **Live streaming** — RTMP ingest via a MediaMTX sidecar, repackaged to LL-HLS and reverse-proxied so viewers play it same-origin at `/live` with sub-5s latency.
- **Admin console** — `/admin/{overview,matches,live,performance,users,settings}` for match management, upload recovery, live stream config, performance tuning, admin-managed user accounts, and branding.
- **Stack** — FastAPI + SQLite (single squashed migration, `PRAGMA user_version = 1`) + a no-build vanilla-JS SPA, fronted by Caddy with a MediaMTX sidecar for live ingest. Transcodes run through an in-process queue.

## Removed

An earlier iteration of this codebase carried a much larger surface that has since been removed. None of it is part of the product anymore:

- the coaching / player-feedback subsystem (rosters, notes/clips/playlists, telestration, tactical boards, player development profiles, player goals, match coaching summaries, the engagement dashboard, AI drafting, and the `/coach` + `/feedback` surfaces)
- multi-tenancy (teams, seasons, memberships, invites, active-scope selection) and `REPLAY_STRICT_TENANCY`
- account self-service (`/me` profile routes, password reset, email verification) and the email/notification settings
- the Postgres lane / multi-backend support (`REPLAY_DB_BACKEND`, `DATABASE_URL`)
- the durable-jobs user-facing API (the queue remains internal-only for transcodes)

User accounts are admin-managed only (roles `admin` / `uploader` / `viewer`), and the database schema has been squashed into a single clean v1 migration.

## Forward-looking ideas (VOD / live)

These are candidate enhancements, not commitments. They build on the existing spoiler-safe public viewing model (scores hidden by default).

- **Match discovery** — feature the latest ready match and current live match on the season page; richer filters by date range, opponent, venue, and video availability; server-side paginated search instead of the bounded match payload.
- **Shareable moments** — timestamp deep links such as `/match/{slug}/first-half?t=12m34s` and metadata-driven highlight chips (seek links, not generated video files) on the match and season pages.
- **Match-day live experience** — upgrade `/live` into a match-day page with kickoff time, venue, an admin-controlled announcement banner, and a clear post-match recording lifecycle (pending upload → processing → ready).
- **Analytics** — per-match watch time and unique-viewer counts surfaced in the admin overview.
- **Delivery** — a CDN cache-priming step for live HLS segments to cut origin pulls further, and optionally per-match ABR ladders instead of a single global preset.
