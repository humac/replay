# Replay Agent Skills

Portable, repo-local skill pack for any coding agent (Claude Code, Codex, Cursor, Gemini) that
works on the Replay codebase — a single-team VOD + live-streaming platform built as a no-build
vanilla-JS SPA over FastAPI + SQLite.

This pack complements [`AGENTS.md`](../AGENTS.md) (the repo source of truth) with safety rails,
search recipes, and validation gates an agent should load before editing.

## Skills in this pack

| File | One-liner |
|---|---|
| [`replay-repo-navigation.md`](replay-repo-navigation.md) | No-build vanilla-JS architecture orientation. Where things live and how `window.app` is assembled. |
| [`vanilla-js-mixin-pattern.md`](vanilla-js-mixin-pattern.md) | How to add state and methods safely without introducing a build step. |
| [`css-responsive-accessibility.md`](css-responsive-accessibility.md) | CSS Grid / Flexbox, pointer-aware media queries, ARIA, focus rings, no native browser chrome. |
| [`testing-and-qa.md`](testing-and-qa.md) | Static checks, pytest commands, the Playwright smoke spec, manual regression checklist. |
| [`pr-review-checklist.md`](pr-review-checklist.md) | Paste-ready PR description template. |

## Recommended load order

For **any** task in this repo:

1. `replay-repo-navigation.md` — orient.
2. Then load whichever others match the work:
   - editing JS → `vanilla-js-mixin-pattern.md`
   - editing `styles.css` / layout / a11y → `css-responsive-accessibility.md`
   - before declaring done → `testing-and-qa.md` and `pr-review-checklist.md`

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
- **Do not regress the public `/match/{slug}` viewer or `/live` playback.**
- **Do not change role gating.** Use `app.canEdit()` / `app.isAdmin()` / `app.hasRole()` and
  `_auth.has_role()` / `_auth.require_role()`.
- **Do not change the schema** unless a task explicitly says so and includes a migration. The
  schema is a single squashed migration pinned at `PRAGMA user_version = 1`.
- **No native browser chrome inside styled components** — style or hide scrollbars, selects,
  range thumbs, and inputs.
