# Gemini Instructions

Read `AGENTS.md` first for the shared project context.

Additional guidance for Gemini in this repo:

- Keep recommendations practical and implementation-focused.
- Prefer preserving the current FastAPI + vanilla JS structure.
- Avoid suggesting build tools or framework migrations unless explicitly requested.
- Be careful with file-upload, HLS, and casting flows because they have cross-cutting frontend/backend behavior.

Useful commands:

```bash
pip install -r requirements.txt
python server.py
python3 -m py_compile server.py
docker compose up --build
```
