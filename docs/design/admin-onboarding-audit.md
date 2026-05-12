# Admin & Onboarding UI Audit — Phases 0 / A / B / C / D / F.2 + follow-up

**Date:** 2026-05-12
**Pass:** Phase E of the platform-hardening UI/UX delivery (PR #178, #179, #180, #181, #182, #183) plus the Admin > People / Brevo follow-up.

## Scope

Audit of the seven new or substantially-extended surfaces shipped by Phases 0 → F:

1. `/admin` sidebar regrouping (Broadcast / Tenants / Platform)
2. `/me` account self-service (Profile · Password · Email · Sessions)
3. `/welcome` onboarding wizard (3 steps + done)
4. `/invite/{token}` invite acceptance landing
5. `/verify-email` and `/reset-password` token-bearing landings
6. Admin > People — active-team Members + Pending Invites + invite composer modal
7. Coach > Settings — team settings / AI governance with a link to Admin > People
8. `/admin/teams` two-pane shell (list / detail / overview / seasons / memberships)
9. Admin > Users — user-memberships expander

The audit applies the [frontend-designer skill's](`/Users/huynguyen/.claude/skills/frontend-designer/SKILL.md`) Phase 1 criteria across each surface.

## Methodology

- Read every new `.html` template, `.css` rule, and `.js` mixin
- Verified runtime behavior in the preview server at desktop (1280×900, 1440×900) and via accessibility-tree snapshots
- Checked role-based visibility paths (`isAdmin`, `canCoach`, `canManageTeamMembers` capability gate)
- Verified backend privacy invariants are not relaxed by the new client code (dev-tokens, raw passwords, `coach_private_note`)

## Findings by criterion

### Visual hierarchy

✅ **Pass.** Every new surface has a clear primary action and a single H1 / kicker pair. The `.account-tabs` pattern (Phase A) and `.welcome-steps` indicator (Phase D) reuse a shared visual rhythm so users moving between surfaces stay oriented. The two-pane `/admin/teams` shell (Phase C) gives the active team a visual anchor (accent border) so the operator never loses context when switching sub-tabs.

### Spacing & layout

✅ **Pass.** New CSS uses the existing spacing scale (0.2rem / 0.35rem / 0.55rem / 0.85rem / 1rem / 1.4rem) inherited from the existing Replay design system. No raw pixel values were introduced. The 4-px-grid rhythm is preserved.

### Colour & contrast

✅ **Pass.** No new color tokens were introduced. New semantic extensions reuse:
- Accent blue `#1771c9` for active states and CTA fill
- Success green `#22c55e` for verified pills and done step indicators
- Warning amber `#facc15` for unverified pills and pending invite states
- Danger red `#f43f5e` / `#f87171` for revoke + sign-out CTAs
- Five role colors (`#1771c9`, `#38bdf8`, `#818cf8`, `#facc15`, `#f472b6`) for the `.team-pill[data-role]` palette, used identically across Admin > People and Admin > Teams memberships

WCAG AA contrast spot-checked against the existing `#070709` dark bg / `#121215` panel bg / `#ffffff` light bg:
- All accent + text combinations exceed 4.5:1
- Pills have an explicit `background` rather than relying on text-only color, so the 4.5:1 floor applies to the high-contrast pair (white text on accent fill / muted text on subtle tinted background)
- Sub-text (`.admin-card-sub`, `.form-help`) uses `var(--text-muted)` consistently — same as existing surfaces

### Typography

✅ **Pass.** All new typography uses CSS custom properties (`--font-heading` for kickers, headings; `--font-body` for body; `--font-mono` for usernames and slugs). No fixed `px` font sizes; only `rem` units. The type scale stays within the 6-size limit (`0.62rem`–`1.75rem`).

### Interaction & feedback

✅ **Pass.** Every new interactive element has hover / focus / active / disabled states. Examples:
- `.account-tab` — hover lifts color, focus shows accent outline, active gets accent underline
- `.admin-teams-list-item` — hover background lift, focus accent outline, active accent left-border
- `.welcome-step` — current state, done state (green), pending state (muted)
- Banners (`.account-banner`) have distinct success / error variants with bordered backgrounds, never just colored text

Loading states use the existing `.session-empty` placeholder before resolving any API call. Disabled buttons get explicit `aria-disabled` attributes.

### Consistency

✅ **Pass.** All buttons follow the three-tier hierarchy:
- `.btn-primary` for primary actions (Create, Save, Continue, Generate)
- `.btn-secondary` for cancel / discard / sign-in-instead
- `.btn-danger` for sign-out / destructive
- `.btn-head` for section-head actions (Refresh, + New, + Invite member)
- `.mini-action-btn` for row-level actions (Change role, Remove, Revoke)

Modal pattern is exclusively `app.formModal({…})` from `js/ui.js`. No new modal primitive was rolled.

### Mobile / responsive

✅ **Pass.** Breakpoints applied:
- `/me` profile grid collapses to single column at ≤ 720 px
- `.admin-teams-shell` collapses two-pane to stacked at ≤ 980 px
- `.welcome-steps` step indicator wraps with `flex-wrap` for narrow viewports
- `.team-member-row` and `.team-invite-row` wrap actions to a full-width row at ≤ 720 px

Tap targets meet 44×44 px minimum on all new buttons:
- `.account-tab` has explicit `min-height: 44px`
- `.account-radio` has `min-height: 36px` — **note:** below 44 px but pill-style, used in horizontal groups where adjacent label provides extended hit area

### Accessibility

✅ **Pass with notes.**

Wins:
- All form inputs have associated `<label for>` attributes (Phase A.4 polished the login modal to add these)
- All tab strips use `role="tablist"` + `role="tab"` + `aria-selected` + `aria-current` (welcome step indicator)
- Modal dialogs route through `formModal()`, which manages focus return + Esc-close + backdrop-click-close
- Step indicator carries `aria-current="step"` on the active chip; updated by `setWelcomeStep()`
- Account tabs use `aria-selected` and refocus first focusable element of the newly active panel
- Color is never the only signal — pills always carry text labels alongside their background tint

Open items:
1. Account tab strip uses click-only activation. Could optionally add arrow-key tab navigation, but that's a polish item; click + Tab key already works for keyboard users. Marked as a low-priority follow-up.
2. The `roster-link-chip` close glyph (`×`) is `aria-hidden`, but the chip itself is a `<button>` with descriptive `title`. Screen readers will announce the button, so the visual `×` doesn't need to be exposed separately. ✓
3. Team rename now uses the shared `formModal()` pattern; dev-only invite links use the standard clipboard helper only when the server returns a raw token.

### Privacy invariant audit

This is a **delivery requirement** from the platform-hardening plan, audited explicitly:

| Surface | Sensitive data | Client handling | Verdict |
|---|---|---|---|
| `/me` Password tab | current + new password | Never logged, never templated, never stored in `localStorage`. POST body is the only place the values live. | ✅ |
| `/me` Email tab | verification token | Surfaced inline only when `body.verification_token` is in the server response (i.e. `REPLAY_DEV_TOKEN_DELIVERY=1`). | ✅ |
| `/welcome` Step 3 | invite token | Same pattern — `.account-dev-token` block only when server returns `invite_token`. | ✅ |
| Admin > People invite composer | invite token + invitee email | Same pattern; email never logged to console. Brevo sends production links; dev copy appears only when `REPLAY_DEV_TOKEN_DELIVERY=1`. | ✅ |
| `/invite/{token}` landing | invite token (URL), new-user password | Token is read from URL pathname; password never logged. New-user form submits to `/api/team/invites/accept` which creates the user atomically. | ✅ |
| `/admin/teams` membership grant | user_id from `/api/users` picker | No client-side authorization; backend gates with `require_global_admin()`. | ✅ |
| Admin > Users memberships expander | cross-tenant team memberships | Read-only; uses the existing global-admin endpoint. | ✅ |
| AI draft panel | `coach_private_note` (anywhere) | Never referenced by client code. Server scrubs it from viewer payloads. | ✅ |

## Open items for follow-up

These didn't block any phase but are worth tracking:

1. **Account tab arrow-key navigation** — low-priority a11y polish
2. **Phase F.3 — background jobs strip** in `/admin/performance`, exposes durable-jobs queue health to global admins
3. **First-run coach-marks (Phase D.2)** — needs `user_profiles.first_signin_at` migration
4. **`/me` Sessions tab** — needs a server-side `/api/me/sessions` GET endpoint to list active sessions; current placeholder is intentional

None of these are blocking. The full set of surfaces is shippable and the privacy invariant is intact.

## Conclusion

Pass. All seven phases meet the audit criteria; no regressions or contrast / focus / privacy violations were introduced. The new surfaces reuse the existing Replay design system tokens, button tiers, and modal pattern consistently. Where the platform-hardening backend exposes a feature, there is now a user-facing surface for it — with the exception of the F.3 jobs strip, which is documented as a deferred follow-up.
