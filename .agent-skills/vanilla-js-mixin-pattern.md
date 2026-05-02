# Vanilla JS mixin pattern

## Purpose

Explain how Replay assembles `window.app` from per-domain mixin modules and how to add state,
methods, and event handlers without breaking the no-build promise.

## When to use it

- Adding a new method, state field, or event listener to the frontend.
- Considering a refactor that "feels like it would be cleaner with a framework."
- Splitting an oversized mixin into a new module.

## Key repo files

- `script.js` — top-level state object, `init()`, history routing, event binding, mixin
  spread.
- `js/utils.js`, `js/api.js`, `js/player.js`, `js/uploads.js`, `js/views.js`,
  `js/admin-views.js`, `js/admin.js`, `js/ui.js`, `js/live.js`, `js/coaching.js` — every
  mixin exports `export const xMixin = { ... }`.

## Pattern at a glance

```js
// js/coaching.js
export const coachingMixin = {
    _coachVideoId: 'coach-review-video',     // private state field
    _coachDrawing: null,
    setCoachTab(name) { /* ... uses `this.someOtherMixinMethod()` ... */ },
};

// script.js
import { coachingMixin } from './js/coaching.js';

const app = {
    matches: [],                              // top-level state
    activeMatchId: null,
    async init() { /* lifecycle */ },
    bindEvents() { /* one-time wiring */ },
    ...utilsMixin,
    ...apiMixin,
    ...playerMixin,
    ...coachingMixin,
};

window.app = app;
```

A few non-negotiable rules baked into this pattern:

1. **`this` resolves to `app` everywhere.** Mixin methods can call any other mixin's method
   via `this.foo()`. State on the top-level literal is accessed via `this.matches`,
   `this.activeMatchId`, etc.
2. **Inline handlers in `index.html` rely on the global.** `<select onchange="app.handleX()">`
   only works because `window.app = app`. Renaming a method without updating HTML breaks
   silently — there is no compiler.
3. **Object-spread merges keys; later wins.** If two mixins define a method with the same
   name, the one spread later overrides earlier ones. Avoid name collisions.
4. **Each mixin file is a plain ES module.** Browser loads `script.js` as
   `<script type="module">`. No transpilation.

## Constraints (hard guardrails)

**No frontend build step. Ever.** Do NOT introduce:

- React, Vue, Svelte, Solid, Preact, Lit, or any component framework
- Vite, Webpack, Rollup, esbuild, Parcel, Snowpack, or any bundler
- Tailwind, shadcn/ui, MUI, Chakra, or any framework-coupled design system
- TypeScript build (you may use JSDoc `@type` annotations — those don't transpile)
- JSX, Babel, or any source transform
- A root-level `package.json` adding `"build"` / `"dev"` scripts

**No framework rewrites.** Do not migrate `js/coaching.js` or any other mixin to a component
framework, even gradually. The repo deliberately ships static assets the browser interprets
directly.

**Adding state**:

- Top-level state goes in the object literal in `script.js` (e.g. `activeMatchId`, `matches`).
- Mixin-private state lives on the mixin object literal as a `_camelCase` field
  (e.g. `_coachVideoId`, `_coachDrawing`). Use `this._foo` to access.
- Don't sprinkle `let coachDrawing` at module scope inside `js/coaching.js` — there's no way
  to reach it from other mixins or inline handlers.

**Adding a new mixin file**:

1. Export `export const newThingMixin = { ... }`.
2. `import` it in `script.js`.
3. Add it to the spread block, **after** any mixin whose methods it depends on overriding-wise.
4. Document the new file in `AGENTS.md` (Key Files section) and update `CLAUDE.md` if
   editing-guidance changes.

**Removing or renaming a public method**:

```bash
# Always grep first
rg -n "app\.<oldName>\b" index.html js/ docs/
```

If the name appears in `index.html` or any HTML template, update both call sites and the
definition in the same diff. Don't leave a half-renamed method.

## Commands / checks to run

```bash
# Syntax check after editing any JS file
node --check script.js
node --check js/coaching.js
node --check js/player.js
node --check js/api.js

# Find every place a public method is called
rg -n "app\.setCoachTab\b" index.html js/
rg -n "app\.\w+\(" index.html | sort -u | head -50

# Find collisions between mixin keys
rg -n "^\s+(\w+)\(" js/ | awk -F: '{print $3}' | sort | uniq -c | sort -rn | head
```

## Common failure modes

- **Top-level `this`.** Inside a mixin object literal, `this` outside a method is undefined
  in strict mode. Don't try to compute defaults from sibling fields at literal definition
  time — do it inside a method.
- **Arrow callbacks losing `this`.** Inside `addEventListener('click', () => this.foo())` the
  arrow keeps `this`. Inside a `function() { this.foo() }`, it does not. Pick one and stick
  with it.
- **State in two mixins.** Defining `_coachDrawing` in both `coachingMixin` and a new mixin
  causes whichever spreads later to clobber. Audit `_coach*` fields with `rg`.
- **Forgetting to add the import in `script.js`.** A new mixin file that nothing imports
  silently does nothing.
- **Adding a `package.json`.** Resist tooling that wants one. If a tool absolutely needs it,
  keep it under `tests/` or `tools/` and exclude from `index.html` loading.
- **Reordering the spread.** Many mixins declare overlapping helpers (`_savePosition`,
  `formatDuration`); reordering swaps which one wins.

## Done criteria

- New methods discoverable via `rg "app\.<methodName>"` in `index.html` (if HTML calls it) and
  in `js/`.
- No new build tools added (no `package.json`, no `node_modules` in repo, no `.babelrc`,
  `vite.config.*`, `webpack.config.*`, `tsconfig.json` build).
- `node --check` passes for every touched JS file.
- The single global `window.app` still has every previously-exposed method.
