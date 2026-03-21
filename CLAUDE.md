# Claude Instructions

Read `AGENTS.md` first and treat it as the shared project source of truth.

Additional guidance for Claude in this repo:

- Favor direct, minimal edits over speculative rewrites.
- Check the current file contents before editing because this repo is often changed iteratively.
- When fixing UI behavior, inspect `index.html` and the relevant JS module in `js/` (views, player, uploads, api, utils). `script.js` is the entry point that assembles all mixins into `window.app`.
- When fixing public-domain behavior, consider cache and proxy behavior before assuming application logic is broken.
- When adding or modifying API endpoints, update Pydantic models in `models.py` and add tests in `tests/`.
- Match URLs use slug-based deep links (`/match/{slug}`, `/match/{slug}/first-half`).
- When setting video status to `"error"`, always pass `error_info` dict with `error_code`, `reason`, `details` to `_set_video_status()` so errors are persisted to the `video_errors` table.
- Admin recovery endpoints live under `/api/admin/matches/{id}/...` — retry, regenerate-hls, verify, errors.
- Use the `lifespan` async context manager for startup/shutdown tasks (not `@app.on_event`).
- Deployment and troubleshooting docs live in `docs/DEPLOYMENT.md` and `docs/TROUBLESHOOTING.md`.

After every code change, update the relevant markdown files to stay in sync:

- `ROADMAP.md` — mark completed items, add descriptions of what was done.
- `AGENTS.md` — update Key Files, Editing Guidance, or Stack if new files/conventions were added.
- `CLAUDE.md` — update if validation commands or editing guidance changed.

Primary validation:

```bash
python3 -m py_compile server.py && python3 -m py_compile media.py && python3 -m py_compile models.py && python3 -m py_compile db.py && python3 -m py_compile auth.py && python3 -m py_compile settings.py && python3 -m py_compile uploads.py && python3 -m py_compile log.py
pytest tests/ -v
```
