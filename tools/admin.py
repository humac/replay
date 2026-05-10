"""Administrative CLI for global-admin team/season/membership setup.

Usage examples:
  python -m tools.admin teams list
  python -m tools.admin teams create --name "U14 Girls" --slug u14-girls --game-format 9v9
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import db as _db
from services import teams as _teams


def _print(payload) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m tools.admin")
    sub = parser.add_subparsers(dest="resource", required=True)

    teams = sub.add_parser("teams")
    teams_sub = teams.add_subparsers(dest="action", required=True)
    teams_sub.add_parser("list")
    teams_create = teams_sub.add_parser("create")
    teams_create.add_argument("--name", required=True)
    teams_create.add_argument("--slug", required=True)
    teams_create.add_argument("--game-format", default="full")

    seasons = sub.add_parser("seasons")
    seasons_sub = seasons.add_subparsers(dest="action", required=True)
    seasons_create = seasons_sub.add_parser("create")
    seasons_create.add_argument("--team", required=True, help="Team slug")
    seasons_create.add_argument("--name", required=True)
    seasons_create.add_argument("--starts", default="")
    seasons_create.add_argument("--ends", default="")

    memberships = sub.add_parser("memberships")
    memberships_sub = memberships.add_subparsers(dest="action", required=True)
    grant = memberships_sub.add_parser("grant")
    grant.add_argument("--team", required=True, help="Team slug")
    grant.add_argument("--user", required=True, help="Username")
    grant.add_argument("--role", required=True)
    revoke = memberships_sub.add_parser("revoke")
    revoke.add_argument("--team", required=True, help="Team slug")
    revoke.add_argument("--user", required=True, help="Username")
    revoke.add_argument("--role", required=True)
    return parser


def _ensure_db_initialized() -> None:
    """Initialize migrations for standalone CLI use.

    Tests and in-process callers may already have configured db.init(...). In
    that case, keep the existing database target so the API and CLI share state.
    """
    if _db.DB_FILE != Path("replay.db"):
        return
    data_dir = Path(os.environ.get("REPLAY_DATA_DIR", "/tank/replay"))
    _db.init(data_dir, data_dir / "replay.db", data_dir / "app_assets")


def _team_by_slug_or_error(slug: str) -> dict:
    team = _teams.get_team_by_slug(slug)
    if team is None:
        raise _teams.TeamServiceError(404, "Team not found")
    return team


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    _ensure_db_initialized()
    try:
        if args.resource == "teams" and args.action == "list":
            _print(_teams.list_teams())
        elif args.resource == "teams" and args.action == "create":
            _print(_teams.create_team(name=args.name, slug=args.slug, game_format=args.game_format))
        elif args.resource == "seasons" and args.action == "create":
            team = _team_by_slug_or_error(args.team)
            _print(_teams.create_season(team_id=team["id"], name=args.name, starts_on=args.starts, ends_on=args.ends))
        elif args.resource == "memberships" and args.action == "grant":
            _print(_teams.grant_membership_by_username(team_slug=args.team, username=args.user, role=args.role))
        elif args.resource == "memberships" and args.action == "revoke":
            _print(_teams.revoke_membership_by_username(team_slug=args.team, username=args.user, role=args.role))
        else:
            parser.error("unsupported command")
        return 0
    except _teams.TeamServiceError as exc:
        print(f"error: {exc.detail}", file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
