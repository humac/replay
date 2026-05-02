# Coaching data privacy

## Purpose

Prevent privilege escalation, role-string mistakes, and feedback leakage during a frontend
redesign. The Coach Review redesign and any future coaching feature must preserve the
visibility ladder defined in `specs/coaching-platform-design.md`.

## When to use it

- Any change inside `js/coaching.js`.
- Any change to `/coach`, `/feedback`, `#coach-view`, `#feedback-view`.
- Anywhere that calls `app.canCoach()`, `app.hasRole()`, `app.isAdmin()`, or backend
  `_auth.has_role` / `_auth.require_role`.
- Any change that lists, queries, or filters `coaching_notes` or `coaching_playlists`.

## Key repo files

- `js/api.js` — `isAdmin`, `canCoach`, `canEdit`, `hasRole`, `userRoles`. Roles arrive on
  `/api/me` as a comma-separated string parsed into `userRoles` array.
- `js/coaching.js` — Coach workspace renderers + My Feedback modal player + role-gated
  surface toggles.
- `auth.py` — `has_role`, `require_role`. Roles can be comma-separated capability strings.
- `server.py` — route registration, role-gated endpoints under `/api/coach/*` and
  `/api/my-feedback*`.
- `db.py` — note + playlist queries; visibility filtering happens here.
- `models.py` — `CreateCoachingNoteRequest`, drawing payload validators, visibility enums.
- `specs/coaching-platform-design.md` — canonical definition of roles, visibility, and
  playlist boundary semantics.

## Roles (additive)

Roles are stored as comma-separated capability strings (e.g. `coach,uploader`). A user can
have any combination. **Never compare `userRole` directly with `===`.**

| Role | Inherits | Surface |
|---|---|---|
| `admin` | `coach`, `uploader`, `viewer` | everything |
| `coach` | (none) | `/coach`, `/api/coach/*` |
| `uploader` | (none) | match CRUD + uploads + admin matches/library |
| `viewer` | (none) | signed-in playback + team-visible feedback |

Anonymous users have no role and see only public match playback + live.

## Visibility ladder (per-note, per-playlist)

| Visibility | Who can see standalone |
|---|---|
| `private` | coach + admin only |
| `team` | any signed-in viewer |
| `player` | only users linked via `player_user_links` to a tagged player |
| `unlisted` | accessible by direct link only (still role-gated) |

### Playlist boundary rule

If a user can see a playlist (because it is `team`, `player`-tagged for them, or `unlisted`
shared with them), the **ordered note moments inside that playlist** become playable inside
the playlist session — even if those notes are `private` as standalone feedback.

This boundary applies only inside the playlist player session. Do not surface those moments
as standalone feedback rows in My Feedback.

## Hard rules

1. **`private` content must NEVER appear in `/feedback` or any My Feedback list.**
2. **My Feedback is scoped to**: linked players (`player_user_links`) plus team-visible
   content the user is allowed to see.
3. **Always use `app.canCoach()` / `app.hasRole('coach')`** — never `userRole === 'coach'`,
   which is wrong for `coach,uploader` users.
4. **Backend gates are authoritative.** `/api/coach/*` requires `admin|coach` via
   `_auth.require_role`; `/api/my-feedback*` filters by linked players in `db.py`. Don't
   rely on UI-only gating to keep data safe.
5. **The Coach Review tab is the ONE coaching authoring surface.** Do not re-introduce the
   removed in-match coach side panel (`#coach-match-panel`, `#coach-mode-bar`,
   `toggleCoachMode`).
6. **Coach Playlist Preview opens the focused modal**, not `/match/{slug}`. The modal
   rebinds `_coachCanvasId` and `_coachVideoId` for its lifetime. Do not regress this.
7. **Drawing payloads are not sensitive but the linked note is.** Don't render drawings from
   notes the current user is not allowed to see.

## API surface boundaries

Read-only reference for what the UI calls:

| Endpoint | Gated by | UI caller |
|---|---|---|
| `GET /api/coach/players` | coach\|admin | Roster tab |
| `GET /api/coach/notes` | coach\|admin | Notes / Review tabs (sees private) |
| `POST /api/coach/notes` | coach\|admin | Note save in Review |
| `GET /api/coach/playlists` | coach\|admin | Playlists tab + Review |
| `POST /api/coach/playlists/{id}/items` | coach\|admin | Playlist editor |
| `GET /api/my-feedback/notes` | signed-in viewer | `/feedback` Notes (filtered) |
| `GET /api/my-feedback/playlists` | signed-in viewer | `/feedback` Playlists (filtered) |
| `POST /api/my-feedback/{kind}/{id}/review` | signed-in viewer | "Mark reviewed" |

If you find yourself wanting to call `/api/coach/notes` from `/feedback`, stop — that leaks
private content. Use `/api/my-feedback/*` and let the backend filter.

## Commands / checks to run

```bash
# Find role checks (must be `hasRole` / `canCoach`, not `===`)
rg -n "userRole\s*===|userRole\s*==" js/        # SHOULD return nothing
rg -n "canCoach|hasRole|isAdmin|canEdit" js/

# Find visibility filtering
rg -n "visibility|private|player_user_links|require_role" server.py db.py auth.py

# Find My Feedback callers — should NOT call /api/coach/*
rg -n "/api/coach|/api/my-feedback" js/

# Backend tests for coaching role gates
pytest tests/test_coaching.py -v
```

## Common failure modes

- **Direct role string equality.** `if (this.userRole === 'coach')` is false for
  `coach,uploader` users → coach features hidden from valid coaches.
- **Reusing a Coach Review query in My Feedback.** Sprint 5 adds a timeline rail; if it
  copies the `/api/coach/notes` query for `/feedback`'s Notes tab, every player sees every
  private note for that match.
- **Showing "Open in Review" on My Feedback rows.** Players are not coaches; that link
  doesn't apply and confuses the surface boundary.
- **Forgetting role gating after a refactor.** Splitting a render into smaller methods can
  drop the `if (!this.canCoach()) return;` guard. Re-add it at the new entry points.
- **Re-adding the in-match coach panel.** Tempting if a coach asks for "draw on the public
  page" — but the panel was removed deliberately. Keep authoring in `/coach?tab=review`.
- **Allowing focus mode / shortcuts in `/feedback`.** Sprint 6+7 are scoped to Coach Review.
  Don't bind their listeners on Feedback view activation.

## Done criteria

For any UI change that touches Coach or Feedback:

1. Manual test pass logged in as **all four** identities:
   - admin
   - coach (or `coach,uploader`)
   - viewer (signed-in, not linked to a player)
   - family/player (linked to a roster player)
   - anonymous (logged out — confirms the public surface)
2. Each identity sees only what the visibility ladder allows.
3. `pytest tests/test_coaching.py -v` passes (covers role gating, roster links, note
   visibility, playlist item privacy, drawing validation, review tracking).
4. No new direct role-string comparisons (`rg "userRole\s*==="` returns nothing).
5. No `/feedback` code path calls `/api/coach/*`.
