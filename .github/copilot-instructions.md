# GitHub Copilot Instructions For Replay

Use `AGENTS.md` as the shared project guide for this repository.

Repo-specific instructions:

- This is a FastAPI backend with a vanilla HTML/CSS/JS SPA.
- There is no frontend build step.
- Keep edits minimal and consistent with the current architecture.
- Do not add framework migrations or large abstractions unless explicitly requested.
- For backend changes, keep the API surface compatible where possible.
- For frontend changes, preserve existing SPA helpers for navigation, upload state, and playback.
- Be careful around Cloudflare/public caching behavior for `index.html` and `/static/*` assets.
- Do not commit `.env.local` or other local-only files.

Preferred validation:

```bash
python3 -m py_compile server.py
```
