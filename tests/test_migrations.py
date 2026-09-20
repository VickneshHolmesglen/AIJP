"""Alembic migrations, tested on throwaway databases (the shared test database is left alone)."""

import threading
import uuid
from collections.abc import Iterator

import pytest
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from sqlalchemy import Engine, create_engine, inspect, text

from app import migrate
from app.models import Base

pytestmark = pytest.mark.integration


@pytest.fixture
def scratch(db_engine: Engine) -> Iterator[Engine]:
    """An empty, uniquely named database, dropped afterwards."""
    name = f"aijp_mig_{uuid.uuid4().hex[:8]}"
    admin = db_engine.execution_options(isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{name}"'))
    engine = create_engine(db_engine.url.set(database=name))
    try:
        yield engine
    finally:
        engine.dispose()
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))


def _diff(engine: Engine) -> list[object]:
    """Differences between the migrated database and the SQLAlchemy models (excluding the two
    indexes that are deliberately not modelled)."""
    with engine.connect() as conn:
        context = MigrationContext.configure(
            conn,
            opts={
                "compare_type": True,
                "include_object": migrate.include_object,
            },
        )
        return compare_metadata(context, Base.metadata)


def test_fresh_database_migrates_to_head_and_matches_the_models(scratch: Engine) -> None:
    migrate.upgrade(scratch)
    assert migrate.current_revision(scratch) == migrate.head_revision()
    # The drift guard: change a model without writing a migration and this fails.
    assert _diff(scratch) == []
    with scratch.connect() as conn:
        indexes = {i["name"] for i in inspect(conn).get_indexes("chunks")}
    assert {"ix_chunks_embedding_hnsw", "ix_chunks_fts"} <= indexes


def test_upgrade_is_idempotent(scratch: Engine) -> None:
    migrate.upgrade(scratch)
    migrate.upgrade(scratch)
    assert migrate.current_revision(scratch) == migrate.head_revision()


def test_downgrade_to_base_removes_every_table(scratch: Engine) -> None:
    from alembic import command

    migrate.upgrade(scratch)
    with scratch.connect() as conn:
        command.downgrade(migrate._config(conn), "base")
        conn.commit()
    with scratch.connect() as conn:
        assert set(inspect(conn).get_table_names()) == {"alembic_version"}


def _upgrade_to(engine: Engine, revision: str) -> None:
    from alembic import command

    with engine.connect() as conn:
        command.upgrade(migrate._config(conn), revision)
        conn.commit()


def _downgrade_to(engine: Engine, revision: str) -> None:
    from alembic import command

    with engine.connect() as conn:
        command.downgrade(migrate._config(conn), revision)
        conn.commit()


NEW_PROJECT = "INSERT INTO projects (id, slug, name) VALUES (gen_random_uuid(), 'x', 'X')"
DELETE_X_DOCS = (
    "DELETE FROM documents WHERE project_id IN (SELECT id FROM projects WHERE slug = 'x')"
)
LEGACY_ROWS = (
    "INSERT INTO documents (id, filename, source_path, file_type, size_bytes, sha256) "
    "VALUES ('00000000-0000-0000-0000-0000000000d1', 'a.md', 'a.md', 'md', 3, 'aa')",
    "INSERT INTO chunks (id, document_id, chunk_index, content) "
    "VALUES (gen_random_uuid(), '00000000-0000-0000-0000-0000000000d1', 0, 'hello')",
    "INSERT INTO agent_runs (id, workflow, input, status) "
    "VALUES ('00000000-0000-0000-0000-0000000000a1', 'consistency_check', '{}', 'completed')",
    "INSERT INTO tasks (id, title, description, evidence, status) "
    "VALUES (gen_random_uuid(), 'keep me', 'd', '[]', 'open')",
    "INSERT INTO api_keys (id, name, role, key_prefix, key_hash) "
    "VALUES (gen_random_uuid(), 'old key', 'reader', 'abcd1234', 'h')",
)


def test_legacy_database_is_adopted_without_losing_data(scratch: Engine) -> None:
    """A database made by the pre-Alembic code: the revision-0001 tables, no version table, and
    the columns that were only ever added by hand-written ALTERs missing."""
    _upgrade_to(scratch, "0001")
    with scratch.begin() as conn:
        for statement in LEGACY_ROWS:
            conn.execute(text(statement))
        conn.execute(text("DROP TABLE alembic_version"))
        conn.execute(text("ALTER TABLE tasks DROP COLUMN created_by"))
        conn.execute(text("ALTER TABLE agent_actions DROP COLUMN decided_by"))
        conn.execute(text("ALTER TABLE agent_runs DROP COLUMN requested_by"))
    assert migrate.current_revision(scratch) is None

    migrate.upgrade(scratch)

    assert migrate.current_revision(scratch) == migrate.head_revision()
    with scratch.connect() as conn:
        assert conn.execute(text("SELECT title, created_by FROM tasks")).one() == ("keep me", None)
    # The dropped columns came back and the schema now matches the models exactly.
    assert _diff(scratch) == []


def test_projects_migration_moves_existing_data_into_the_default_project(scratch: Engine) -> None:
    _upgrade_to(scratch, "0001")
    with scratch.begin() as conn:
        for statement in LEGACY_ROWS:
            conn.execute(text(statement))

    _upgrade_to(scratch, "0002")

    with scratch.connect() as conn:
        default = conn.execute(text("SELECT id FROM projects WHERE slug = 'default'")).scalar_one()
        for table in ("documents", "agent_runs", "tasks"):
            owners = conn.execute(text(f"SELECT DISTINCT project_id FROM {table}")).scalars().all()
            assert owners == [default], f"{table} rows must all move to the default project"
        # Existing keys keep working everywhere: NULL means "every project".
        assert conn.execute(text("SELECT project_id FROM api_keys")).scalar_one() is None
        assert conn.execute(text("SELECT count(*) FROM chunks")).scalar_one() == 1  # untouched
    assert _diff(scratch) == []


def test_after_the_migration_the_same_file_can_live_in_two_projects_but_not_twice(
    scratch: Engine,
) -> None:
    from sqlalchemy.exc import IntegrityError

    _upgrade_to(scratch, "0002")
    insert = (
        "INSERT INTO documents (id, project_id, filename, source_path, file_type, size_bytes, "
        "sha256) VALUES (gen_random_uuid(), :p, 'a.md', 'a.md', 'md', 3, 'same')"
    )
    with scratch.begin() as conn:
        conn.execute(
            text("INSERT INTO projects (id, slug, name) VALUES (gen_random_uuid(), 'x', 'X')")
        )
        first, second = conn.execute(text("SELECT id FROM projects")).scalars().all()
        conn.execute(text(insert), {"p": first})
        conn.execute(text(insert), {"p": second})  # another project: allowed
    with pytest.raises(IntegrityError), scratch.begin() as conn:
        conn.execute(text(insert), {"p": first})  # the same project twice: refused


def test_downgrade_is_refused_while_a_file_exists_in_two_projects(scratch: Engine) -> None:
    _upgrade_to(scratch, "0002")
    insert = (
        "INSERT INTO documents (id, project_id, filename, source_path, file_type, size_bytes, "
        "sha256) VALUES (gen_random_uuid(), :p, 'a.md', 'a.md', 'md', 3, 'same')"
    )
    with scratch.begin() as conn:
        conn.execute(
            text("INSERT INTO projects (id, slug, name) VALUES (gen_random_uuid(), 'x', 'X')")
        )
        for (project,) in conn.execute(text("SELECT id FROM projects")).all():
            conn.execute(text(insert), {"p": project})
    with pytest.raises(Exception, match="more than one project"):
        _downgrade_to(scratch, "0001")
    assert migrate.current_revision(scratch) == "0002"  # nothing was half-applied
    with scratch.begin() as conn:
        conn.execute(text(DELETE_X_DOCS))
    _downgrade_to(scratch, "0001")
    assert migrate.current_revision(scratch) == "0001"


def test_concurrent_starters_do_not_race(scratch: Engine) -> None:
    errors: list[BaseException] = []

    def start() -> None:
        try:
            migrate.upgrade(scratch)
        except BaseException as exc:  # noqa: BLE001 - collected and asserted below
            errors.append(exc)

    threads = [threading.Thread(target=start) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    assert migrate.current_revision(scratch) == migrate.head_revision()


def test_check_command_reports_an_out_of_date_database(
    scratch: Engine, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(migrate, "get_engine", lambda: scratch)
    assert migrate.main(["check"]) == 1
    assert migrate.main(["upgrade"]) == 0
    assert migrate.main(["check"]) == 0
    assert migrate.head_revision() in capsys.readouterr().out
