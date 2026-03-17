# Claude Instructions

Read `AGENTS.md` first and treat it as the shared project source of truth.

Additional guidance for Claude in this repo:

- Favor direct, minimal edits over speculative rewrites.
- Check the current file contents before editing because this repo is often changed iteratively.
- When fixing UI behavior, inspect both `index.html` and `script.js`; many issues here are caused by interaction between markup and SPA state.
- When fixing public-domain behavior, consider cache and proxy behavior before assuming application logic is broken.

Primary validation:

```bash
python3 -m py_compile server.py
```
