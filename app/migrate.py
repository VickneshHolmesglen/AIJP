"""Applies database migrations (Alembic) at startup and from the command line.

    python -m app.migrate upgrade    # apply everything pending (the app also does this at startup)
    python -m app.migrate current    # which revision the database is at
    python -m app.migrate check      # exit 1 if the database is not at the latest revision

Three situations are handled:
  * an empty database: all migrations run;
  * a database created by the pre-Alembic code (`create_all` plus additive ALTERs): it has tables
    but no `alembic_version`. Its missing columns are added, then it is stamped as the baseline;
  * an already-versioned database: pending migrations run.

A PostgreSQL advisory lock serialises concurrent starters (two replicas booting together), so
migrations never race.
"""

import argparse
import sys
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, inspect, text

from app.db import get_engine

BASELINE = "0001"
_MIGRATIONS_DIR = Path(__file__).parent / "migrations"
_LOCK_KEY = 7_261_998_001  # arbitrary constant shared by every process of this application

# What the pre-Alembic code added to existing databases after their first `create_all`.
_LEGACY_ADDITIVE = (
    "ALTER TABLE agent_runs ADD COLUMN IF NOT EXISTS requested_by VARCHAR(100)",
    "ALTER TABLE agent_actions ADD COLUMN IF NOT EXISTS decided_by VARCHAR(100)",
    "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS created_by VARCHAR(100)",
)


# Two indexes are created by the migrations but are not declared on the models (an HNSW operator
# class and a functional GIN expression). Comparing models with the database must ignore them, or
# autogenerate would propose dropping them.
UNMODELLED_INDEXES = frozenset({"ix_chunks_embedding_hnsw", "ix_chunks_fts"})


def include_object(
    obj: object, name: str | None, type_: str, reflected: bool, compare_to: object
) -> bool:
    return not (type_ == "index" and name in UNMODELLED_INDEXES)


def _config(connection: object) -> Config:
    config = Config()
    config.set_main_option("script_location", str(_MIGRATIONS_DIR))
    config.attributes["connection"] = connection
    return config


def head_revision() -> str:
    head = ScriptDirectory(str(_MIGRATIONS_DIR)).get_current_head()
    assert head is not None
    return head


def current_revision(engine: Engine) -> str | None:
    with engine.connect() as conn:
        return MigrationContext.configure(conn).get_current_revision()


def upgrade(engine: Engine) -> None:
    """Bring the database to the latest revision. Safe to call on every start."""
    with engine.connect() as conn:
        conn.execute(text("SELECT pg_advisory_lock(:key)"), {"key": _LOCK_KEY})
        try:
            conn.commit()
            config = _config(conn)
            tables = set(inspect(conn).get_table_names())
            versioned = "alembic_version" in tables
            if not versioned and "documents" in tables:
                for statement in _LEGACY_ADDITIVE:
                    conn.execute(text(statement))
                conn.commit()
                command.stamp(config, BASELINE)
                conn.commit()
            command.upgrade(config, "head")
            conn.commit()
        finally:
            conn.rollback()
            conn.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": _LOCK_KEY})
            conn.commit()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.migrate", description=__doc__)
    parser.add_argument("action", choices=["upgrade", "current", "check"])
    args = parser.parse_args(argv)
    engine = get_engine()
    if args.action == "upgrade":
        upgrade(engine)
        print(f"database is at {current_revision(engine)}")
        return 0
    current = current_revision(engine)
    print(f"database: {current}  latest: {head_revision()}")
    if args.action == "check" and current != head_revision():
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
