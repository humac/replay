#!/usr/bin/env python3
"""Dump the current FastAPI route inventory to stdout.

Used by ``tests/test_route_inventory.py`` to verify that mechanical router
extractions (PR 3.3 follow-through) preserve the public surface byte-for-byte.

Run from repo root:

    ADMIN_PASS=dummy python3 scripts/dump_routes.py
"""
from __future__ import annotations

import sys
from pathlib import Path


def main() -> int:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from server import app  # late import so PYTHONPATH is set

    lines: list[str] = []
    for route in app.routes:
        methods = sorted(getattr(route, "methods", None) or [])
        path = getattr(route, "path", None) or str(route)
        methods_str = ",".join(methods) if methods else "-"
        lines.append(f"{methods_str} {path}")
    for line in sorted(lines):
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
