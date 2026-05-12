"""Pytest regression for the public FastAPI route inventory.

PR-BE (backend router split) moves route handlers from server.py into
routers/*.py mechanically. This test pins the current set of routes (paths
and HTTP methods) so a misnamed @router.<method>(...) decorator or a
forgotten app.include_router() shows up as a test failure rather than a
silent prod regression.

If you intentionally change a route's path or methods, regenerate the
fixture with:

    ADMIN_PASS=dummy python3 scripts/dump_routes.py > tests/fixtures/route-inventory.txt

and include the diff alongside the route change in the same commit so
reviewers can confirm the change is deliberate.
"""
from __future__ import annotations

from pathlib import Path


FIXTURE = Path(__file__).resolve().parent / "fixtures" / "route-inventory.txt"


def _live_inventory() -> str:
    from server import app

    lines = []
    for route in app.routes:
        methods = sorted(getattr(route, "methods", None) or [])
        path = getattr(route, "path", None) or str(route)
        methods_str = ",".join(methods) if methods else "-"
        lines.append(f"{methods_str} {path}")
    return "\n".join(sorted(lines)) + "\n"


def test_public_route_inventory_matches_fixture():
    fixture = FIXTURE.read_text()
    live = _live_inventory()
    assert live == fixture, (
        "Public route inventory drift detected. If this is intentional, "
        "regenerate with: ADMIN_PASS=dummy python3 scripts/dump_routes.py > tests/fixtures/route-inventory.txt"
    )
