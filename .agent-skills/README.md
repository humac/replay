# Replay Agent Skills

Portable, repo-local skill pack for any coding agent (Claude Code, Codex, Cursor, Gemini) that
works on the Replay codebase, especially the multi-sprint Coach Review UI/UX redesign.

The single source of truth for the redesign target is
[`docs/archive/coach-review-ui-ux-implementation-plan.md`](../docs/archive/coach-review-ui-ux-implementation-plan.md).
This pack does not duplicate that document — it complements it with safety rails, search
recipes, and validation gates an agent should load before editing.

## Skills in this pack

| File | One-liner |
|---|---|
| [`replay-repo-navigation.md`](replay-repo-navigation.md) | No-build vanilla-JS architecture orientation. Where things live and how `window.app` is assembled. |
| [`coach-review-ui-cockpit.md`](coach-review-ui-cockpit.md) | Target layout, sprint order, and the selectors / methods that must survive the redesign. |
| [`vanilla-js-mixin-pattern.md`](vanilla-js-mixin-pattern.md) | How to add state and methods safely without introducing a build step. |
| [`css-responsive-accessibility.md`](css-responsive-accessibility.md) | CSS Grid / Flexbox, pointer-aware media queries, ARIA, focus rings. |
| [`video-hls-canvas-overlay.md`](video-hls-canvas-overlay.md) | Keep the drawing canvas aligned over `<video>` through resize, seek, and HLS lifecycle. |
| [`coaching-data-privacy.md`](coaching-data-privacy.md) | Roles, visibility ladder, My Feedback leakage rules. |
| [`testing-and-qa.md`](testing-and-qa.md) | Static checks, pytest commands, manual regression checklist, screenshot list. |
| [`pr-review-checklist.md`](pr-review-checklist.md) | Paste-ready PR description template. |

## Recommended load order

For **any** task in this repo, load first:

1. `replay-repo-navigation.md` — orient.
2. `coach-review-ui-cockpit.md` *(only for Coach Review work)* — set the target.

Then load whichever of the others matches the active sprint:

| Sprint | Also load |
|---|---|
| 0 (audit) | `testing-and-qa.md`, `pr-review-checklist.md` |
| 1 (layout) | `css-responsive-accessibility.md`, `video-hls-canvas-overlay.md`, `vanilla-js-mixin-pattern.md` |
| 2 (top bar) | `vanilla-js-mixin-pattern.md`, `css-responsive-accessibility.md`, `video-hls-canvas-overlay.md` |
| 3 (toolbar) | `vanilla-js-mixin-pattern.md`, `css-responsive-accessibility.md` |
| 4 (note composer) | `vanilla-js-mixin-pattern.md`, `coaching-data-privacy.md` |
| 5 (timeline rail) | `vanilla-js-mixin-pattern.md`, `css-responsive-accessibility.md`, `coaching-data-privacy.md` |
| 6 (focus mode) | `css-responsive-accessibility.md`, `vanilla-js-mixin-pattern.md`, `video-hls-canvas-overlay.md` |
| 7 (shortcuts) | `vanilla-js-mixin-pattern.md` |
| 8 (a11y polish) | `css-responsive-accessibility.md` |
| 9 (QA + docs) | `testing-and-qa.md`, `pr-review-checklist.md` |

Always re-read `testing-and-qa.md` before declaring done.

## Skill file structure

Every file uses the same shape so they're easy to scan:

```
# <Skill name>
## Purpose
## When to use it
## Key repo files
## Important functions / selectors
## Constraints
## Commands / checks to run
## Common failure modes
## Done criteria
```

## Hard guardrails (apply across all skills)

- **No frontend build step.** No React, Vue, Svelte, Vite, Webpack, Rollup, esbuild, Tailwind,
  shadcn, JSX, or `npm run build` — ever.
- **Do not burn drawings into MP4.** Drawings are JSON metadata on `coaching_notes`.
- **Do not leak private content into `/feedback`.** My Feedback is scoped to linked players +
  team-visible content the user is allowed to see.
- **Do not regress the public `/match/{slug}` viewer.** Coach affordances stay inside `/coach`.
- **Do not change role gating.** Use `app.canCoach()` / `app.hasRole()` and
  `_auth.has_role()` / `_auth.require_role()`.
- **Do not change the `coaching_notes` / drawing schemas** unless a sprint explicitly says so
  and includes a backend migration.
