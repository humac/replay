from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_intel_compose_declares_optional_postgres_service():
    compose = (ROOT / "docker-compose-intel.yml").read_text()

    assert "postgres:" in compose
    assert "postgres:16" in compose
    assert "profiles:" in compose
    assert "pg_isready" in compose
    assert "replay_postgres:" in compose
    assert "127.0.0.1:${POSTGRES_PORT:-5432}:5432" in compose
    assert "DATABASE_URL" in compose
    assert "REPLAY_DB_BACKEND" in compose


def test_ci_has_narrow_postgres_lane_not_full_runtime_claim():
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text()

    assert "postgres-lane" in ci
    assert "postgres:16" in ci
    assert "DATABASE_URL" in ci
    assert "REPLAY_RUN_LIVE_POSTGRES_TESTS" in ci
    assert "REPLAY_DB_BACKEND" in ci
    assert "tests/test_postgres_lane.py" in ci
    assert "pytest tests/ -v --cov" in ci
