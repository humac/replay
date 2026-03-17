# Codex Instructions

Read `AGENTS.md` first for the shared repository rules and architecture.

Additional guidance for Codex in this repo:

- Prefer small, composable patches.
- Preserve existing endpoints and UI flows unless the task requires changing them.
- Avoid introducing extra dependencies unless there is a clear payoff.
- Keep changes readable in a repo with no build step and only a few top-level files.

Priority files for most tasks:

- `server.py`
- `script.js`
- `index.html`
- `styles.css`
