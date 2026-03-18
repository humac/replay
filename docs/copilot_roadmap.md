# Replay Enhancement Roadmap

Repository: `humac/replay`  
Repository URL: `https://github.com/humac/replay`

## Overview

This document captures a phased enhancement roadmap and a suggested GitHub Projects board layout for the `replay` repository.

`replay` is a standalone match viewer and video archive built as a small FastAPI + vanilla JavaScript application. It already includes:

- match creation and editing
- video uploads
- resumable chunked uploads
- HLS generation
- direct MP4 playback
- Chromecast / AirPlay support
- admin settings
- diagnostics
- SQLite + filesystem storage

The goal of this roadmap is to improve:

- reliability
- maintainability
- frontend structure
- media pipeline resilience
- archive usability
- security and operational readiness

---

## Current Architecture Summary

### Backend
- `server.py` is the core backend entrypoint and currently appears to handle:
  - API routing
  - auth
  - uploads
  - media processing
  - HLS generation
  - database initialization/access
  - static/media serving

### Frontend
- `index.html` is the SPA shell
- `script.js` holds most frontend behavior
- `styles.css` contains the full UI styling

### Storage
- SQLite database: `replay.db`
- Filesystem storage for:
  - uploaded videos
  - HLS assets
  - app assets
  - team logos

### Runtime / Infra
- FastAPI + uvicorn
- Dockerfile + docker-compose
- ffmpeg / ffprobe
- no frontend build step

---

## Key Strengths

- Strong feature completeness for a small app
- Minimal operational complexity
- Straightforward deploy model
- Well-aligned documentation and repo guidance
- Clear focus on preserving a no-build-step SPA

---

## Main Risks / Gaps

- `server.py` is monolithic
- `script.js` is monolithic
- testing appears absent or minimal
- schema evolution will get harder without migrations
- media workflow recovery can likely be improved
- operational hardening and observability should be expanded

---

# Phased Milestone Plan

## Milestone 1 — Reliability Baseline

**Goal:** make the current app safer to change without altering core behavior.

### Outcomes
- Basic automated test coverage exists
- CI runs on every push/PR
- backend contracts are clearer
- failures are easier to diagnose

### Scope
1. **Add backend test suite**
   - API smoke tests for match CRUD
   - auth/access tests for admin-only routes
   - upload session lifecycle tests
   - settings persistence tests
   - temp data-dir based test fixtures

2. **Add CI workflow**
   - Python install
   - dependency install
   - `python3 -m py_compile server.py`
   - test execution
   - optional Docker build smoke check

3. **Introduce request/response schemas**
   - Pydantic models for match payloads
   - models for settings, diagnostics, and upload-session responses
   - normalize validation and error responses

4. **Add structured logging**
   - include match ID, upload session ID, slot, and processing state
   - consistent error logging around ffmpeg, uploads, and DB operations

### Deliverables
- `tests/` directory
- `.github/workflows/ci.yml`
- extracted schemas/models
- improved logs with stable event naming

### Exit criteria
- core routes have automated coverage
- CI passes on clean checkout
- invalid payloads fail predictably
- logs are useful for tracing upload/transcode failures

---

## Milestone 2 — Backend Maintainability

**Goal:** reduce risk in `server.py` by separating concerns.

### Outcomes
- backend logic is modular
- upload/media code is easier to test
- DB access is less intertwined with route handling

### Scope
1. **Refactor `server.py`**
   - keep `server.py` as entrypoint and route registration
   - extract modules for:
     - auth
     - DB access
     - uploads
     - media processing
     - settings
     - diagnostics

2. **Introduce lightweight service boundaries**
   - route layer handles HTTP concerns
   - service layer handles business logic
   - persistence helpers isolate SQLite usage

3. **Prepare for schema evolution**
   - introduce a migration mechanism
   - track DB schema version
   - move startup schema creation toward versioned migrations

### Deliverables
- smaller backend modules
- migration strategy in repo
- reduced duplication in route handlers

### Exit criteria
- `server.py` is substantially smaller
- major operations can be tested without routing through everything
- DB changes no longer depend on ad hoc startup SQL only

---

## Milestone 3 — Frontend Structure and UX Resilience

**Goal:** keep the no-build-step SPA, but make the frontend easier to extend.

### Outcomes
- frontend logic is easier to navigate
- async flows feel more predictable to users
- upload/playback regressions are easier to isolate

### Scope
1. **Split `script.js` into logical modules**
   - API client
   - app state
   - uploads
   - player
   - navigation/history
   - season view rendering
   - settings view logic

2. **Centralize UI feedback**
   - consistent loading states
   - success/error banners or toasts
   - clearer processing and retry messaging

3. **Improve defensive UI behavior**
   - safer handling of missing media/assets
   - better empty/error states
   - clearer admin/public state transitions

### Deliverables
- frontend JS module split
- shared error/display helpers
- more consistent async UX

### Exit criteria
- major frontend features are separated by responsibility
- upload and playback failures are surfaced clearly
- common UI states are consistent across views

---

## Milestone 4 — Media Pipeline Hardening

**Goal:** make uploads, processing, and playback more recoverable and operationally safe.

### Outcomes
- media processing states are explicit
- failures can be retried without manual repair
- uploads are validated earlier

### Scope
1. **Formalize processing state machine**
   - states such as:
     - created
     - uploading
     - uploaded
     - queued
     - processing
     - ready
     - failed

2. **Add retry/recovery actions**
   - retry failed transcode
   - regenerate HLS for an existing MP4
   - clean orphaned partial uploads
   - verify asset integrity per match

3. **Improve media validation**
   - validate container/codec with `ffprobe`
   - detect malformed or unsupported uploads
   - reject inconsistent slot/file states
   - strengthen disk headroom checks

4. **Expand admin diagnostics**
   - active jobs
   - stale sessions
   - failed items
   - missing HLS assets
   - disk usage summaries

### Deliverables
- explicit status model
- admin recovery actions
- stronger upload validation
- richer diagnostics

### Exit criteria
- failed processing can be retried from the UI or API
- media state is diagnosable without inspecting files manually
- invalid uploads fail early with actionable messages

---

## Milestone 5 — Archive Usability Enhancements

**Goal:** make the match archive easier to browse and use over time.

### Outcomes
- users can find content faster
- the archive scales beyond a small match list
- playback becomes more polished

### Scope
1. **Improve browse/search/filtering**
   - search by team/opponent/location
   - sort by newest/oldest
   - filter by ready/processing
   - optional season/competition grouping

2. **Enhance metadata model**
   - competition
   - season
   - notes
   - venue refinements
   - optional tags

3. **Playback quality-of-life**
   - remember playback position
   - remember speed preference
   - keyboard shortcuts
   - next/previous navigation
   - more visible stream/status indicators

### Deliverables
- richer season/archive browsing
- enhanced match metadata
- smoother replay experience

### Exit criteria
- finding a past match is materially easier
- replay experience feels more polished for repeat users
- metadata supports larger archives

---

## Milestone 6 — Security and Operational Readiness

**Goal:** harden admin functions and make the app more production-friendly.

### Outcomes
- admin actions are safer
- deployments are easier to monitor and recover
- backups and maintenance are more straightforward

### Scope
1. **Auth/session hardening**
   - review session lifetime
   - secure cookie settings
   - login throttling or brute-force protection
   - audit logging for admin actions

2. **Backup/export tooling**
   - DB export/import guidance or scripts
   - media consistency checks
   - backup/restore documentation

3. **Container/runtime improvements**
   - document CPU-only vs GPU-oriented deployment paths
   - evaluate whether CUDA image should be optional
   - tighten healthcheck and startup readiness behavior

4. **Operational docs**
   - deployment guide
   - upgrade/migration guide
   - troubleshooting guide for uploads/transcodes/HLS

### Deliverables
- hardened auth/session behavior
- backup and restore documentation/tooling
- improved deployment docs
- more portable runtime story

### Exit criteria
- admin operations are better protected
- maintenance tasks are documented
- deployment choices are clearer for different environments

---

# Recommended Sequencing

## Phase 1
- Milestone 1
- Milestone 2

## Phase 2
- Milestone 3
- Milestone 4

## Phase 3
- Milestone 5
- Milestone 6

---

# Suggested GitHub Projects Board Layout

## Project name
**Replay Enhancement Roadmap**

## Recommended views
1. **Board view by Status**
2. **Table view by Milestone**
3. **Table view by Area**
4. **Roadmap view by Milestone**

## Suggested custom fields

### Status
- Inbox
- Ready
- In Progress
- In Review
- Blocked
- Done

### Priority
- P0
- P1
- P2
- P3

### Milestone
- M1 Reliability Baseline
- M2 Backend Maintainability
- M3 Frontend Structure and UX Resilience
- M4 Media Pipeline Hardening
- M5 Archive Usability Enhancements
- M6 Security and Operational Readiness

### Area
- Backend
- Frontend
- Media
- Database
- CI/CD
- Security
- Docs
- UX

### Effort
- XS
- S
- M
- L
- XL

### Type
- Feature
- Refactor
- Bug
- Test
- Docs
- Ops

### Optional fields
- Risk
- Dependencies
- Target Phase
- Acceptance Criteria Met

---

# Suggested Labels

## Priority
- `priority/p0`
- `priority/p1`
- `priority/p2`
- `priority/p3`

## Area
- `area/backend`
- `area/frontend`
- `area/media`
- `area/database`
- `area/ci`
- `area/security`
- `area/docs`
- `area/ux`

## Type
- `type/feature`
- `type/refactor`
- `type/test`
- `type/ops`
- `type/docs`
- `type/bug`

## Milestone
- `milestone/m1`
- `milestone/m2`
- `milestone/m3`
- `milestone/m4`
- `milestone/m5`
- `milestone/m6`

---

# Suggested Board Columns

- Inbox
- Ready
- In Progress
- In Review
- Blocked
- Done

---

# Suggested Backlog by Milestone

## M1 — Reliability Baseline

### Issues
- Add pytest-based test harness
- Add temp data directory fixtures for API tests
- Add match CRUD API tests
- Add upload session lifecycle tests
- Add GitHub Actions CI workflow
- Add admin auth/access tests
- Add settings persistence tests
- Add request/response validation models
- Extract DB helpers from `server.py`
- Extract upload session service from `server.py`

### Suggested priorities
- **P0**
  - Add pytest-based test harness
  - Add match CRUD API tests
  - Add upload session lifecycle tests
  - Add GitHub Actions CI workflow
- **P1**
  - Add admin auth/access tests
  - Add settings persistence tests
  - Add request/response validation models
  - Add structured logging

---

## M2 — Backend Maintainability

### Issues
- Extract DB helpers from `server.py`
- Extract auth service from `server.py`
- Extract upload session service
- Extract media processing service
- Extract settings service
- Introduce route-level schemas consistently
- Add migration/versioning mechanism for SQLite schema changes

### Suggested priorities
- **P0**
  - Extract DB helpers
  - Extract upload session service
  - Extract media processing service
- **P1**
  - Extract auth service
  - Extract settings service
  - Add migration/versioning mechanism

---

## M3 — Frontend Structure and UX Resilience

### Issues
- Split `script.js` into ES modules
- Extract API client from `script.js`
- Extract player logic from `script.js`
- Extract uploads flow from `script.js`
- Extract season view rendering
- Add centralized async error handling
- Add consistent loading and success/error notifications
- Improve empty and failure states in core views

### Suggested priorities
- **P0**
  - Extract API client
  - Extract uploads flow
  - Extract player logic
- **P1**
  - Extract season rendering
  - Add centralized async error handling
  - Add notifications/loading states

---

## M4 — Media Pipeline Hardening

### Issues
- Define explicit upload/media processing state model
- Persist failure reasons for media jobs
- Add retry failed transcode action
- Add regenerate-HLS action for existing MP4s
- Add ffprobe-based upload validation
- Add orphaned upload cleanup improvements
- Extend admin diagnostics with processing and failure details
- Add asset integrity check for match media

### Suggested priorities
- **P0**
  - Define explicit processing state model
  - Add retry failed transcode action
  - Add ffprobe-based upload validation
- **P1**
  - Add regenerate-HLS action
  - Extend admin diagnostics
  - Add asset integrity checks

---

## M5 — Archive Usability Enhancements

### Issues
- Add search for matches
- Add sort controls for match list
- Add filter by status
- Add season/competition metadata fields
- Add playback resume position
- Add saved playback speed preference
- Add keyboard shortcuts
- Add next/previous match navigation

### Suggested priorities
- **P1**
  - Add search for matches
  - Add sort controls
  - Add playback resume
- **P2**
  - Add season/competition metadata
  - Add keyboard shortcuts
  - Add next/previous navigation

---

## M6 — Security and Operational Readiness

### Issues
- Review and harden admin session behavior
- Add secure cookie/session settings
- Add login throttling or rate limiting
- Add audit logging for admin actions
- Add backup and restore documentation
- Add DB/filesystem consistency check tooling
- Document CPU-only deployment path
- Improve troubleshooting guide for uploads/transcodes/HLS

### Suggested priorities
- **P0**
  - Harden admin session behavior
  - Add secure cookie/session settings
- **P1**
  - Add audit logging
  - Add backup/restore documentation
  - Document deployment paths
- **P2**
  - Add DB/filesystem consistency tooling
  - Improve troubleshooting guide

---

# Dependency Guidance

## Foundational ordering
- Milestone 1 should come before most other work
- Milestone 2 should come before deeper backend/media hardening
- Milestone 3 should come before larger UX feature work
- Milestone 6 can start in parallel for documentation and session review, but backend cleanup will help

## Strong dependency chains
- Tests + CI before major refactors
- Backend modularization before pipeline expansion
- Frontend modularization before archive UX expansion

---

# Recommended Initial “Ready” Queue

1. Add pytest-based test harness
2. Add temp data directory fixtures for API tests
3. Add match CRUD API tests
4. Add upload session lifecycle tests
5. Add GitHub Actions CI workflow
6. Add admin auth/access tests
7. Add settings persistence tests
8. Add request/response validation models
9. Extract DB helpers from `server.py`
10. Extract upload session service from `server.py`

---

# Suggested Project Rhythm

## Weekly
- Move 3–5 issues into Ready
- Keep only 1–2 P0 issues in progress at once
- Review blocked items explicitly

## At milestone close
Confirm:
- acceptance criteria are met
- docs are updated
- tests were added where applicable
- upload/playback flows were not regressed

---

# Recommended First Milestone to Start With

## Milestone 1 — Reliability Baseline

This is the best starting milestone because it unlocks safer progress on every later phase:

- tests
- CI
- schemas
- logging

---

# Suggested File Placement

This roadmap is stored as:

- `docs/copilot_roadmap.md`

---

# Notes

This roadmap intentionally preserves the current architectural direction:

- FastAPI backend
- vanilla JS frontend
- no frontend build step
- SQLite + filesystem persistence

It is designed to improve maintainability and resilience without forcing a framework migration.