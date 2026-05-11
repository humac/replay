from __future__ import annotations

import argparse
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Protocol

try:  # pragma: no cover - exercised by live migration use, not unit smoke tests
    import psycopg
    from psycopg import sql
    from psycopg.rows import dict_row
except Exception:  # pragma: no cover
    psycopg = None
    sql = None
    dict_row = None


SQLITE_INTERNAL_PREFIX = "sqlite_"
_SCOPE_TABLES = {
    "matches",
    "seasons",
    "team_user_memberships",
    "players",
    "player_user_links",
    "coaching_notes",
    "coaching_clips",
    "coaching_playlists",
    "player_goals",
    "player_goal_reflections",
    "match_summaries",
    "coaching_match_summaries",
    "background_jobs",
    "team_settings",
    "ai_drafting_runs",
}
_PRIVACY_CANARY_TABLES = {"coaching_notes", "ai_drafting_runs"}
_AI_DRAFTING_PRIVATE_MARKERS = (
    "raw_prompt",
    "provider_output",
    "private_source_text",
    "coach_private_note",
    "private_phase8_raw_prompt_canary",
)


def quote_ident(identifier: str) -> str:
    if not identifier or "\x00" in identifier:
        raise ValueError("invalid SQL identifier")
    return '"' + identifier.replace('"', '""') + '"'


def sqlite_tables(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        """
        SELECT name FROM sqlite_master
        WHERE type = 'table' AND name NOT LIKE ?
        ORDER BY name
        """,
        (f"{SQLITE_INTERNAL_PREFIX}%",),
    ).fetchall()
    return [str(row[0]) for row in rows]


def sqlite_foreign_keys(conn: sqlite3.Connection, table: str) -> list[dict[str, Any]]:
    rows = conn.execute(f"PRAGMA foreign_key_list({quote_ident(table)})").fetchall()
    keys: list[dict[str, Any]] = []
    for row in rows:
        keys.append(
            {
                "table": table,
                "column": row[3],
                "parent_table": row[2],
                "parent_column": row[4],
            }
        )
    return keys


def sqlite_table_order(conn: sqlite3.Connection) -> list[str]:
    """Return user tables with FK parents before children."""
    tables = sqlite_tables(conn)
    table_set = set(tables)
    deps = {table: {fk["parent_table"] for fk in sqlite_foreign_keys(conn, table) if fk["parent_table"] in table_set} for table in tables}
    ordered: list[str] = []
    remaining = set(tables)
    while remaining:
        ready = sorted(table for table in remaining if not (deps[table] & remaining))
        if not ready:
            # Cycles are not expected in Replay, but keep deterministic progress.
            ready = [sorted(remaining)[0]]
        for table in ready:
            ordered.append(table)
            remaining.remove(table)
    return ordered


def _postgres_type(sqlite_decl: str) -> str:
    decl = (sqlite_decl or "TEXT").upper()
    if "INT" in decl:
        return "BIGINT"
    if any(token in decl for token in ("REAL", "FLOA", "DOUB")):
        return "DOUBLE PRECISION"
    if "BLOB" in decl:
        return "BYTEA"
    if any(token in decl for token in ("CHAR", "CLOB", "TEXT", "DATE", "TIME", "JSON")):
        return "TEXT"
    if "BOOL" in decl:
        return "BOOLEAN"
    return "TEXT"


def postgres_create_table_sql(conn: sqlite3.Connection, table: str) -> str:
    columns = conn.execute(f"PRAGMA table_info({quote_ident(table)})").fetchall()
    if not columns:
        raise ValueError(f"unknown SQLite table: {table}")
    pk_columns = [(int(col[5] or 0), col[1]) for col in columns if int(col[5] or 0)]
    composite_pk = len(pk_columns) > 1
    parts: list[str] = []
    for col in columns:
        name = col[1]
        pg_type = _postgres_type(col[2])
        part = f"{quote_ident(name)} {pg_type}"
        if int(col[5] or 0) and not composite_pk:
            part += " PRIMARY KEY"
        if int(col[3] or 0):
            part += " NOT NULL"
        parts.append(part)
    if composite_pk:
        ordered_pk = [name for _, name in sorted(pk_columns)]
        parts.append("PRIMARY KEY (" + ", ".join(quote_ident(name) for name in ordered_pk) + ")")
    return f"CREATE TABLE IF NOT EXISTS {quote_ident(table)} (\n  " + ",\n  ".join(parts) + "\n)"


class ValidationTarget(Protocol):
    def count_rows(self, table: str) -> int: ...
    def count_null(self, table: str, column: str) -> int: ...
    def team_distribution(self, table: str) -> dict[str, int]: ...
    def count_privacy_canaries(self, table: str) -> int: ...
    def count_orphans(self, table: str, column: str, parent_table: str, parent_column: str) -> int: ...


@dataclass
class InMemoryPostgresMirror:
    tables: dict[str, list[dict[str, Any]]]

    @classmethod
    def from_sqlite(cls, conn: sqlite3.Connection) -> "InMemoryPostgresMirror":
        tables: dict[str, list[dict[str, Any]]] = {}
        for table in sqlite_tables(conn):
            rows = conn.execute(f"SELECT * FROM {quote_ident(table)}").fetchall()
            tables[table] = [dict(row) for row in rows]
        return cls(tables)

    def delete_row(self, table: str, column: str, value: Any) -> None:
        self.tables[table] = [row for row in self.tables.get(table, []) if row.get(column) != value]

    def count_rows(self, table: str) -> int:
        return len(self.tables.get(table, []))

    def count_null(self, table: str, column: str) -> int:
        return sum(1 for row in self.tables.get(table, []) if row.get(column) is None)

    def team_distribution(self, table: str) -> dict[str, int]:
        counts: dict[str, int] = {}
        for row in self.tables.get(table, []):
            team_id = row.get("team_id")
            key = "__NULL__" if team_id is None else str(team_id)
            counts[key] = counts.get(key, 0) + 1
        return dict(sorted(counts.items()))

    def count_privacy_canaries(self, table: str) -> int:
        rows = self.tables.get(table, [])
        if table == "ai_drafting_runs":
            return sum(1 for row in rows if _ai_drafting_row_has_private_payload(row))
        return sum(
            1
            for row in rows
            if row.get("visibility") == "private" and bool(row.get("coach_private_note"))
        )

    def count_orphans(self, table: str, column: str, parent_table: str, parent_column: str) -> int:
        parents = {row.get(parent_column) for row in self.tables.get(parent_table, [])}
        return sum(
            1
            for row in self.tables.get(table, [])
            if row.get(column) is not None and row.get(column) not in parents
        )


class PsycopgValidationTarget:
    def __init__(self, conn):
        self.conn = conn

    def count_rows(self, table: str) -> int:
        with self.conn.cursor() as cur:
            cur.execute(sql.SQL("SELECT count(*) AS c FROM {}").format(sql.Identifier(table)))
            return int(cur.fetchone()["c"])

    def count_null(self, table: str, column: str) -> int:
        with self.conn.cursor() as cur:
            cur.execute(
                sql.SQL("SELECT count(*) AS c FROM {} WHERE {} IS NULL").format(sql.Identifier(table), sql.Identifier(column))
            )
            return int(cur.fetchone()["c"])

    def team_distribution(self, table: str) -> dict[str, int]:
        with self.conn.cursor() as cur:
            cur.execute(
                sql.SQL("SELECT team_id, count(*) AS c FROM {} GROUP BY team_id ORDER BY team_id NULLS FIRST").format(sql.Identifier(table))
            )
            return {"__NULL__" if row["team_id"] is None else str(row["team_id"]): int(row["c"]) for row in cur.fetchall()}

    def count_privacy_canaries(self, table: str) -> int:
        with self.conn.cursor() as cur:
            if table == "ai_drafting_runs":
                cur.execute(
                    sql.SQL(
                        """
                        SELECT count(*) AS c FROM {}
                        WHERE lower(coalesce(evidence_refs_json, '') || ' ' || coalesce(error_code, '') || ' ' || coalesce(error_message, '') || ' ' || coalesce(provider, '') || ' ' || coalesce(model, ''))
                        LIKE ANY(%s)
                        """
                    ).format(sql.Identifier(table)),
                    ([f"%{marker}%" for marker in _AI_DRAFTING_PRIVATE_MARKERS],),
                )
            else:
                cur.execute(
                    sql.SQL("SELECT count(*) AS c FROM {} WHERE visibility = %s AND coach_private_note IS NOT NULL AND coach_private_note <> ''").format(sql.Identifier(table)),
                    ("private",),
                )
            return int(cur.fetchone()["c"])

    def count_orphans(self, table: str, column: str, parent_table: str, parent_column: str) -> int:
        with self.conn.cursor() as cur:
            cur.execute(
                sql.SQL(
                    "SELECT count(*) AS c FROM {child} c LEFT JOIN {parent} p ON c.{child_col} = p.{parent_col} "
                    "WHERE c.{child_col} IS NOT NULL AND p.{parent_col} IS NULL"
                ).format(
                    child=sql.Identifier(table),
                    parent=sql.Identifier(parent_table),
                    child_col=sql.Identifier(column),
                    parent_col=sql.Identifier(parent_column),
                )
            )
            return int(cur.fetchone()["c"])


def _sqlite_count(conn: sqlite3.Connection, table: str) -> int:
    return int(conn.execute(f"SELECT count(*) FROM {quote_ident(table)}").fetchone()[0])


def _sqlite_count_null(conn: sqlite3.Connection, table: str, column: str) -> int:
    return int(conn.execute(f"SELECT count(*) FROM {quote_ident(table)} WHERE {quote_ident(column)} IS NULL").fetchone()[0])


def _sqlite_team_distribution(conn: sqlite3.Connection, table: str) -> dict[str, int]:
    rows = conn.execute(
        f"SELECT team_id, count(*) AS c FROM {quote_ident(table)} GROUP BY team_id ORDER BY team_id"
    ).fetchall()
    return {"__NULL__" if row[0] is None else str(row[0]): int(row[1]) for row in rows}


def _ai_drafting_row_has_private_payload(row: dict[str, Any] | sqlite3.Row) -> bool:
    haystack = " ".join(
        str(row[key] or "")
        for key in ("evidence_refs_json", "error_code", "error_message", "provider", "model")
        if key in row.keys()
    ).lower()
    return any(marker in haystack for marker in _AI_DRAFTING_PRIVATE_MARKERS)


def _sqlite_privacy_canaries(conn: sqlite3.Connection, table: str) -> int:
    if table == "ai_drafting_runs":
        rows = conn.execute(
            f"SELECT evidence_refs_json, error_code, error_message, provider, model FROM {quote_ident(table)}"
        ).fetchall()
        return sum(1 for row in rows if _ai_drafting_row_has_private_payload(row))
    return int(
        conn.execute(
            f"SELECT count(*) FROM {quote_ident(table)} WHERE visibility = ? AND coach_private_note IS NOT NULL AND coach_private_note <> ''",
            ("private",),
        ).fetchone()[0]
    )


def validate_migration(sqlite_conn: sqlite3.Connection, pg_target: ValidationTarget, tables: Iterable[str]) -> dict[str, Any]:
    table_list = list(tables)
    row_counts = {table: {"sqlite": _sqlite_count(sqlite_conn, table), "postgres": pg_target.count_rows(table)} for table in table_list}
    scope_columns: dict[str, dict[str, Any]] = {}
    for table in table_list:
        cols = {row[1] for row in sqlite_conn.execute(f"PRAGMA table_info({quote_ident(table)})")}
        if table in _SCOPE_TABLES and "team_id" in cols:
            scope_columns[table] = {
                "sqlite_null_team_id": _sqlite_count_null(sqlite_conn, table, "team_id"),
                "postgres_null_team_id": pg_target.count_null(table, "team_id"),
                "sqlite_team_distribution": _sqlite_team_distribution(sqlite_conn, table),
                "postgres_team_distribution": pg_target.team_distribution(table),
            }
    fk_issues = []
    for table in table_list:
        for fk in sqlite_foreign_keys(sqlite_conn, table):
            if fk["parent_table"] not in table_list:
                continue
            orphans = pg_target.count_orphans(table, fk["column"], fk["parent_table"], fk["parent_column"])
            if orphans:
                fk_issues.append({**fk, "postgres_orphans": orphans})
    privacy_canaries = {}
    for table in table_list:
        if table in _PRIVACY_CANARY_TABLES:
            privacy_canaries[f"{table}_private_payloads"] = {
                "sqlite": _sqlite_privacy_canaries(sqlite_conn, table),
                "postgres": pg_target.count_privacy_canaries(table),
            }
    return {
        "row_counts": row_counts,
        "scope_columns": scope_columns,
        "foreign_keys": fk_issues,
        "privacy_canaries": privacy_canaries,
    }


def _assert_validation_clean(summary: dict[str, Any]) -> None:
    mismatched = [table for table, counts in summary["row_counts"].items() if counts["sqlite"] != counts["postgres"]]
    scope_bad = [
        table
        for table, counts in summary["scope_columns"].items()
        if counts["sqlite_null_team_id"] != counts["postgres_null_team_id"]
        or counts["sqlite_team_distribution"] != counts["postgres_team_distribution"]
    ]
    privacy_bad = [name for name, counts in summary["privacy_canaries"].items() if counts["sqlite"] != counts["postgres"]]
    if mismatched or scope_bad or privacy_bad or summary["foreign_keys"]:
        raise RuntimeError(
            "migration validation failed: "
            + json.dumps({"row_count_mismatches": mismatched, "scope_mismatches": scope_bad, "privacy_mismatches": privacy_bad, "foreign_keys": summary["foreign_keys"]}, sort_keys=True)
        )


def migrate(sqlite_path: Path, database_url: str, *, create_schema: bool = False, truncate: bool = False) -> dict[str, Any]:
    if psycopg is None:
        raise RuntimeError("psycopg is required for live Postgres migration")
    if not sqlite_path.is_file():
        raise FileNotFoundError(f"SQLite database not found: {sqlite_path}")
    sqlite_uri = f"file:{sqlite_path.resolve()}?mode=ro"
    sqlite_conn = sqlite3.connect(sqlite_uri, uri=True)
    sqlite_conn.row_factory = sqlite3.Row
    tables = sqlite_table_order(sqlite_conn)
    with psycopg.connect(database_url, row_factory=dict_row) as pg_conn:
        with pg_conn.cursor() as cur:
            if create_schema:
                for table in tables:
                    cur.execute(postgres_create_table_sql(sqlite_conn, table))
            if truncate:
                for table in reversed(tables):
                    cur.execute(sql.SQL("TRUNCATE TABLE {} RESTART IDENTITY CASCADE").format(sql.Identifier(table)))
            for table in tables:
                rows = sqlite_conn.execute(f"SELECT * FROM {quote_ident(table)}").fetchall()
                if not rows:
                    continue
                columns = list(rows[0].keys())
                stmt = sql.SQL("INSERT INTO {} ({}) VALUES ({})").format(
                    sql.Identifier(table),
                    sql.SQL(", ").join(sql.Identifier(c) for c in columns),
                    sql.SQL(", ").join(sql.Placeholder() for _ in columns),
                )
                for row in rows:
                    cur.execute(stmt, tuple(row[c] for c in columns))
            summary = validate_migration(sqlite_conn, PsycopgValidationTarget(pg_conn), tables)
            _assert_validation_clean(summary)
        pg_conn.commit()
        return {"tables": tables, "validation": summary}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="One-shot Replay SQLite to Postgres migration helper")
    parser.add_argument("--sqlite", required=True, type=Path, help="Path to replay.db SQLite file")
    parser.add_argument("--database-url", required=True, help="Postgres database URL")
    parser.add_argument("--create-schema", action="store_true", help="Bootstrap compatible Postgres tables from SQLite schema first")
    parser.add_argument("--truncate", action="store_true", help="Truncate target tables before importing")
    parser.add_argument("--output-json", action="store_true", help="Print machine-readable JSON summary")
    args = parser.parse_args(argv)
    result = migrate(args.sqlite, args.database_url, create_schema=args.create_schema, truncate=args.truncate)
    if args.output_json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(f"Migrated {len(result['tables'])} tables from {args.sqlite} to Postgres")
        print(json.dumps(result["validation"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
