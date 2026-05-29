# CSS responsive & accessibility

## Purpose

Codify the CSS patterns and accessibility expectations for Replay so desktop-compact controls
don't harm tablet/mobile users and keyboard/AT users stay first-class.

## When to use it

- Any change that edits `styles.css`.
- Any time you introduce a new interactive control (button, chip, slider, input).
- Reviewing a PR that changes layout density.

## Key repo files

- `styles.css` — single large stylesheet with dark + light themes via CSS custom properties.
  Co-locate new rules with the section they belong to.
- `index.html` — interactive elements that need ARIA / focus styles live here and inside
  `<template>` blocks (`match-form-template`, the focused playback modal template).
- `js/admin-views.js` / `js/views.js` — renderer template strings that emit `aria-label`,
  `aria-pressed`, `title`. ARIA must be set both in `innerHTML` and on any custom chips.

## Patterns

### Layout

CSS Grid for multi-column shells. Use `minmax(0, 1fr)` on the flexible column to prevent
content from forcing horizontal scroll:

```css
.example-grid {
    display: grid;
    grid-template-columns: minmax(0, 1fr) 340px;
    gap: 0.85rem;
    align-items: start;
}

.example-grid .media {
    min-width: 0;            /* Prevent media from blowing out the grid */
}

@media (max-width: 1023px) {
    .example-grid {
        grid-template-columns: minmax(0, 1fr);  /* single column */
    }
}
```

Flexbox for toolbars/rails. Keep wrap on, never a scrollbar on a wrapping toolbar; only an
intentional horizontal rail should scroll, and it must be themed:

```css
.toolbar-row {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.5rem;
}

.scroll-rail {
    display: flex;
    gap: 0.5rem;
    overflow-x: auto;        /* horizontal scroll allowed only here */
    scrollbar-width: thin;
    scrollbar-color: var(--scroll-thumb, rgba(255, 255, 255, 0.18)) transparent;
}
.scroll-rail::-webkit-scrollbar { height: 6px; }
.scroll-rail::-webkit-scrollbar-thumb {
    background: var(--scroll-thumb, rgba(255, 255, 255, 0.18));
    border-radius: 3px;
}
```

### Pointer-aware sizing

Compact buttons on mouse, ≥44 px tap targets on touch:

```css
@media (pointer: fine) and (min-width: 900px) {
    .icon-btn {
        width: 34px;
        height: 34px;
        padding: 0;
        border-radius: 8px;
    }
    .icon-btn .label { display: none; }
}

@media (pointer: coarse), (max-width: 899px) {
    .icon-btn {
        min-width: 44px;
        min-height: 44px;
    }
}
```

### Theme tokens

The repo already exposes CSS custom properties for both dark and light themes (light mode is
gated by `[data-theme="light"]`). Do **not** hardcode hex values for backgrounds, borders,
text — use `var(--text-muted)`, `var(--font-heading)`, etc. New tokens go near the top of
`styles.css` where `:root` is defined.

## Accessibility constraints

### Required attributes

- Every icon-only button: **both** `aria-label="..."` and `title="..."` (label for AT, title
  for hover tooltip).
- Toggle buttons: `aria-pressed="true|false"`.
- Tab-like navigation: `role="tab"` + `aria-selected="true|false"`. Existing tab strips
  (e.g. the admin sub-nav) already do this; preserve it.
- Form controls: every `<input>`, `<select>`, `<textarea>` needs an associated `<label>` or
  `aria-label`. Placeholder text alone is not a label.
- Decorative icons: `aria-hidden="true"`.

### Focus

- Never `outline: none` without a `:focus-visible` replacement.
- Focus rings must remain visible on the new compact 34 px controls. A 2 px box-shadow ring
  in an accent color works at any size.
- Skip-links and the existing `:focus-visible` styles in the repo are the model — reuse them.

### Native chrome

Repo rule (also in `CLAUDE.md`): **never expose native browser chrome inside styled
components.** Practically this means:

- No raw `<select multiple>` boxes — use a custom chip selector.
- Style `<input type="range">` thumb and track or hide in favor of a custom slider.
- No unstyled scrollbars on horizontal rails — theme via `scrollbar-width`,
  `scrollbar-color`, and `::-webkit-scrollbar*`.
- No native checkbox/radio appearance for toggles — use a custom styled control.
- File inputs use the existing inline-label pattern in the match form (`'f-home-logo'` etc.).

### Touch + keyboard parity

- Every action reachable by mouse must be reachable by keyboard.
- Global keyboard shortcuts must not interfere with form inputs (`input, textarea, select,
  [contenteditable]`). Guard at handler entry.

## Test widths

Test every layout-affecting change at **all five**: 390, 768, 1024, 1440, 1920 px.

- 390 px — iPhone-class, single column, touch.
- 768 px — small tablet portrait.
- 1024 px — small laptop / iPad landscape; a common breakpoint where multi-column shells
  switch to side-by-side.
- 1440 px — typical desktop.
- 1920 px — wide monitor.

Use Chrome DevTools Responsive mode (Cmd+Shift+M) or Chrome MCP `resize_window` for
automation.

## Commands / checks to run

```bash
# Audit hardcoded colors (should all be tokens)
rg -n "#[0-9a-fA-F]{3,6}\b" styles.css | rg -v "var\(" | head -40

# Audit aria attributes on renderers / forms
rg -n "aria-label|aria-pressed|aria-selected|role=" js/ index.html

# Audit any `outline: none` without a focus replacement nearby
rg -n "outline:\s*none|outline:\s*0" styles.css
```

Tools available without install:

- Chrome DevTools "Issues" tab — flags missing labels and contrast problems.
- Chrome DevTools Lighthouse → Accessibility audit (no install needed).
- macOS VoiceOver (Cmd+F5) — verify reading order.

Optional install:

- `axe-core` browser extension or `@axe-core/cli` (`npx @axe-core/cli`) for a scripted gate.

## Common failure modes

- **Horizontal overflow at 1024 px.** Caused by a flex/grid child lacking `min-width: 0`, by a
  too-wide fixed column, or by an unwrapping toolbar row. Fix with `flex-wrap: wrap` on the
  toolbar and `min-width: 0` on the media column.
- **Pointer-coarse devices stuck with 28 px controls.** Forgetting the `@media (pointer:
  coarse)` override leaves desktop sizing on tablets. Always pair the two media queries.
- **Focus rings hidden by `outline: none`.** Pair with `:focus-visible { box-shadow: 0 0 0
  2px var(--accent); }` or rely on the existing repo `*:focus-visible` rule.
- **Native scrollbar on the toolbar.** If the toolbar overflows horizontally, wrap rather
  than scroll.
- **Hardcoded hex colors.** Themes will look wrong on the opposite mode. Use tokens.
- **Overlay blocks underlying content.** When a modal/overlay is shown, ensure it has
  `position: fixed` and a backdrop, and Escape closes it.

## Done criteria

- Layout works at 390 / 768 / 1024 / 1440 / 1920 px without horizontal overflow (except the
  intentional timeline rail).
- Every interactive element shows a visible focus ring on Tab.
- Touch tap targets ≥44 px under `@media (pointer: coarse)`.
- No `outline: none` without an accompanying `:focus-visible` replacement.
- No native browser chrome inside styled components.
- All icon buttons have `aria-label` and `title`; toggles have `aria-pressed`; tabs have
  `aria-selected`.
- Lighthouse Accessibility score ≥95 on the changed view.
