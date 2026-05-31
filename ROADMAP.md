# Replay — Roadmap

## v1.0.0 — what it is

Replay is a single-team match video platform:

- **VOD library** — chunked resumable upload → ffmpeg transcode → multi-variant HLS ladder, with a direct MP4 fallback for download and casting. Matches are a flat, global library grouped by a season **label** in the public view.
- **Live streaming** — RTMP ingest via a MediaMTX sidecar, repackaged to LL-HLS and reverse-proxied so viewers play it same-origin at `/live` with sub-5s latency.
- **Admin console** — `/admin/{overview,matches,live,performance,users,settings}` for match management, upload recovery, live stream config, performance tuning, admin-managed user accounts (roles `admin` / `uploader` / `viewer`), and branding.
- **Stack** — FastAPI + SQLite (single migration, `PRAGMA user_version = 1`) + a no-build vanilla-JS SPA, fronted by Caddy with a MediaMTX sidecar for live ingest. Transcodes run through an in-process durable queue.

## Scope boundaries

Replay is intentionally a single-team VOD + live product. The following are **out of scope** and not planned — listed so contributors don't accidentally reintroduce them:

- Coaching / player-feedback features (notes, clips, telestration, tactical boards, player development, AI drafting).
- Multi-tenancy (teams, seasons-as-tenants, memberships, invites, per-tenant scoping). "Season" and "team" exist only as match-grouping labels and home/away names on a match record.
- Account self-service (public signup, profile self-edit, password reset, email verification). User accounts are admin-managed.
- Alternate database backends. SQLite is the only supported store.

## Forward-looking ideas (VOD / live)

These are candidate enhancements, not commitments. They build on the existing spoiler-safe public viewing model (scores hidden by default).

- **Match discovery** — feature the latest ready match and current live match on the season page; richer filters by date range, opponent, venue, and video availability; server-side paginated search instead of the bounded match payload.
- **Shareable moments** — timestamp deep links such as `/match/{slug}/first-half?t=12m34s` and metadata-driven highlight chips (seek links, not generated video files) on the match and season pages.
- **Match-day live experience** — upgrade `/live` into a match-day page with kickoff time, venue, an admin-controlled announcement banner, and a clear post-match recording lifecycle (pending upload → processing → ready).
- **Analytics** — per-match watch time and unique-viewer counts surfaced in the admin overview.
- **Delivery** — a CDN cache-priming step for live HLS segments to cut origin pulls further, and optionally per-match ABR ladders instead of a single global preset.
