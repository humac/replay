from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_postgres_migration_adr_records_phase6_architecture_decisions():
    adr = (ROOT / "docs" / "postgres-migration-adr.md").read_text()

    for required in [
        "Postgres as the production database backend",
        "Alembic as the forward migration runner",
        "SQLite remains supported for local/dev",
        "_migrate_v0 through _migrate_v16",
        "No `pgvector` is required for the AI drafting MVP",
        "FOR UPDATE SKIP LOCKED",
        "SQLite-to-Postgres migration command",
    ]:
        assert required in adr


def test_deployment_docs_link_database_backend_plan():
    deployment = (ROOT / "docs" / "DEPLOYMENT.md").read_text()

    assert "postgres-migration-adr.md" in deployment
    assert "DATABASE_URL" in deployment
    assert "REPLAY_DB_BACKEND" in deployment
    assert "planned configuration, not live runtime switches" in deployment
