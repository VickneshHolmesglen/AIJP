"""Manage API keys from the command line.

    uv run python -m app.keys create --name alice --role approver
    uv run python -m app.keys list
    uv run python -m app.keys revoke alice          # by name or by 8-character prefix

In the compose stack:
    docker compose exec api python -m app.keys create --name alice --role approver

Key management is deliberately CLI-only: there are no HTTP endpoints for creating or revoking keys,
so no API credential, however privileged, can mint another. Whoever can run this command already
holds the database credentials.
"""

import argparse
import getpass
import sys
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import projects
from app.audit import record_event
from app.auth import Principal, Role, create_key, revoke_keys
from app.db import get_engine, init_db
from app.models import ApiKey


def _operator() -> Principal:
    """Audit identity for CLI actions: the OS user running the command."""
    return Principal(f"cli:{getpass.getuser()}", Role.approver, None, None)


def _fmt(when: datetime | None) -> str:
    return when.strftime("%Y-%m-%d %H:%M") if when else "-"


def cmd_create(session: Session, args: argparse.Namespace) -> int:
    expires = datetime.now(UTC) + timedelta(days=args.expires_days) if args.expires_days else None
    project_id = None
    if args.project:
        project = projects.resolve(session, args.project)
        if project is None:
            print(
                f"error: no project '{args.project}' (create it: python -m app.projects)",
                file=sys.stderr,
            )
            return 1
        project_id = project.id
    try:
        key, token = create_key(session, args.name, Role[args.role], expires, project_id)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    record_event(
        session,
        _operator(),
        "key.create",
        key.key_prefix,
        name=key.name,
        role=key.role,
        project=args.project or "(all)",
        expires=_fmt(expires),
    )
    if args.token_only:
        print(token)
    else:
        scope = f"project '{args.project}'" if args.project else "every project"
        print(f"Created a {key.role} key for '{key.name}' (prefix {key.key_prefix}), for {scope}.")
        print("Copy the token now. It is stored only as a hash and cannot be shown again:\n")
        print(f"  {token}\n")
        print("Use it as:  Authorization: Bearer <token>   (the web UI asks for it at sign-in)")
    return 0


def cmd_list(session: Session, args: argparse.Namespace) -> int:
    keys = list(session.scalars(select(ApiKey).order_by(ApiKey.created_at)))
    if not keys:
        print("No keys. Create one with:  python -m app.keys create --name NAME --role approver")
        return 0
    now = datetime.now(UTC)
    slugs = {p.id: p.slug for p in projects.list_projects(session)}
    print(
        f"{'PREFIX':<10}{'NAME':<24}{'ROLE':<10}{'PROJECT':<16}{'STATUS':<9}"
        f"{'EXPIRES':<18}LAST USED"
    )
    for k in keys:
        status = (
            "revoked"
            if k.revoked_at
            else "expired"
            if k.expires_at and k.expires_at <= now
            else "active"
        )
        print(
            f"{k.key_prefix:<10}{k.name[:22]:<24}{k.role:<10}"
            f"{(slugs.get(k.project_id, '?') if k.project_id else '(all)'):<16}{status:<9}"
            f"{_fmt(k.expires_at):<18}{_fmt(k.last_used_at)}"
        )
    return 0


def cmd_revoke(session: Session, args: argparse.Namespace) -> int:
    revoked = revoke_keys(session, args.identifier)
    if not revoked:
        print(f"error: no active key with prefix or name '{args.identifier}'", file=sys.stderr)
        return 1
    for key in revoked:
        record_event(session, _operator(), "key.revoke", key.key_prefix, name=key.name)
        print(f"Revoked '{key.name}' (prefix {key.key_prefix}).")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.keys", description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)

    create = sub.add_parser("create", help="create a key and print its token once")
    create.add_argument("--name", required=True, help="the person or service this key identifies")
    create.add_argument("--role", required=True, choices=[r.name for r in Role])
    create.add_argument("--expires-days", type=int, help="expire after this many days")
    create.add_argument("--project", help="confine the key to this project (default: all)")
    create.add_argument("--token-only", action="store_true", help="print only the token (scripts)")
    create.set_defaults(func=cmd_create)

    sub.add_parser("list", help="list keys (never the secrets)").set_defaults(func=cmd_list)

    revoke = sub.add_parser("revoke", help="revoke by name or prefix; effective immediately")
    revoke.add_argument("identifier")
    revoke.set_defaults(func=cmd_revoke)

    args = parser.parse_args(argv)
    if getattr(args, "expires_days", None) is not None and args.expires_days < 1:
        parser.error("--expires-days must be at least 1")
    init_db(get_engine())  # so the first `create` works on a fresh database
    with Session(get_engine(), expire_on_commit=False) as session:
        return int(args.func(session, args))


if __name__ == "__main__":
    sys.exit(main())
