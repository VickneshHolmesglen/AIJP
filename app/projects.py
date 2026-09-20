"""Projects: separate bodies of documents. Domain functions and a small management CLI.

    python -m app.projects create --slug shardfall --name "Shardfall"
    python -m app.projects list
    python -m app.projects delete SLUG --yes      # removes the project AND everything in it

Every document, agent run and task belongs to exactly one project, and retrieval always filters by
project, so one project's text can never appear in another's search results or answers. A `default`
project always exists; a database that predates projects has everything in it.
"""

import argparse
import re
import sys
import uuid
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import get_engine
from app.models import AgentRun, Document, Project, Task

DEFAULT_SLUG = "default"
_SLUG = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,38}[a-z0-9])?$")


class ProjectError(ValueError):
    """A project could not be created or changed. The message is safe to show to the user."""


def valid_slug(slug: str) -> str:
    if not isinstance(slug, str) or not _SLUG.fullmatch(slug):
        raise ProjectError(
            "slug must be 1-40 characters: lowercase letters, digits and hyphens, "
            "starting and ending with a letter or digit"
        )
    return slug


def valid_name(name: str) -> str:
    cleaned = " ".join(name.split()) if isinstance(name, str) and name.isprintable() else ""
    if not cleaned or len(cleaned) > 100:
        raise ProjectError("name must be 1-100 printable characters")
    return cleaned


def get_by_slug(session: Session, slug: str) -> Project | None:
    return session.scalar(select(Project).where(Project.slug == slug))


def get_or_create_default(session: Session) -> Project:
    """The `default` project, created if missing. Safe under concurrent starts: a lost race just
    re-reads the row the winner created."""
    project = get_by_slug(session, DEFAULT_SLUG)
    if project is not None:
        return project
    session.add(Project(slug=DEFAULT_SLUG, name="Default"))
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
    project = get_by_slug(session, DEFAULT_SLUG)
    assert project is not None
    return project


def resolve(session: Session, slug: str) -> Project | None:
    """The project named `slug`, or None. `default` is created on demand."""
    if slug == DEFAULT_SLUG:
        return get_or_create_default(session)
    return get_by_slug(session, slug)


def create_project(session: Session, slug: str, name: str) -> Project:
    slug, name = valid_slug(slug), valid_name(name)
    if get_by_slug(session, slug) is not None:
        raise ProjectError(f"a project with the slug '{slug}' already exists")
    project = Project(slug=slug, name=name)
    session.add(project)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise ProjectError(f"a project with the slug '{slug}' already exists") from None
    return project


def list_projects(session: Session, only: uuid.UUID | None = None) -> list[Project]:
    """All projects, or just `only` (what a project-scoped key is allowed to see)."""
    stmt = select(Project).order_by(Project.slug)
    if only is not None:
        stmt = stmt.where(Project.id == only)
    return list(session.scalars(stmt))


@dataclass(frozen=True)
class Counts:
    documents: int
    runs: int
    tasks: int


def counts(session: Session, project_id: uuid.UUID) -> Counts:
    def n(model: type[Document] | type[AgentRun] | type[Task]) -> int:
        stmt = select(func.count()).select_from(model).where(model.project_id == project_id)
        return session.scalar(stmt) or 0

    return Counts(n(Document), n(AgentRun), n(Task))


def delete_project(session: Session, slug: str) -> Counts:
    """Delete a project and, through the database's cascades, its documents, chunks, runs, tasks
    and scoped keys. Returns what was removed. The default project cannot be deleted."""
    if slug == DEFAULT_SLUG:
        raise ProjectError("the default project cannot be deleted")
    project = get_by_slug(session, slug)
    if project is None:
        raise ProjectError(f"no project '{slug}'")
    removed = counts(session, project.id)
    session.delete(project)
    session.commit()
    return removed


# ------------------------------------------------------------------ CLI


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.projects", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("create", help="create a project")
    create.add_argument("--slug", required=True)
    create.add_argument("--name", required=True)
    sub.add_parser("list", help="list projects")
    delete = sub.add_parser("delete", help="delete a project and everything in it")
    delete.add_argument("slug")
    delete.add_argument("--yes", action="store_true", help="confirm the deletion")
    args = parser.parse_args(argv)

    from app.db import init_db

    engine = get_engine()
    init_db(engine)  # so the first `create` works on a fresh database
    with Session(engine) as session:
        get_or_create_default(session)
        try:
            if args.command == "create":
                project = create_project(session, args.slug, args.name)
                print(f"created project '{project.slug}' ({project.name})")
            elif args.command == "list":
                print(f"{'SLUG':40}  {'DOCS':>5}  {'RUNS':>5}  {'TASKS':>5}  NAME")
                for p in list_projects(session):
                    c = counts(session, p.id)
                    print(f"{p.slug:40}  {c.documents:>5}  {c.runs:>5}  {c.tasks:>5}  {p.name}")
            else:
                if not args.yes:
                    print(
                        "error: this deletes the project and ALL its documents, runs and tasks; "
                        "re-run with --yes to confirm",
                        file=sys.stderr,
                    )
                    return 2
                removed = delete_project(session, args.slug)
                print(
                    f"deleted '{args.slug}': {removed.documents} documents, "
                    f"{removed.runs} runs, {removed.tasks} tasks"
                )
        except ProjectError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
