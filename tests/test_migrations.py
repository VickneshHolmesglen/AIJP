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


def test_legacy_database_is_adopted_without_losing_data(scratch: Engine) -> None:
    """A database made by the pre-Alembic code: tables from create_all, no version table, and
    the columns that were only ever added by hand-written ALTERs missing."""
    with scratch.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    Base.metadata.create_all(scratch)
    with scratch.begin() as conn:
        conn.execute(text("ALTER TABLE tasks DROP COLUMN created_by"))
        conn.execute(text("ALTER TABLE agent_actions DROP COLUMN decided_by"))
        conn.execute(text("ALTER TABLE agent_runs DROP COLUMN requested_by"))
        conn.execute(
            text(
                "INSERT INTO tasks (id, title, description, evidence, status) "
                "VALUES (gen_random_uuid(), 'keep me', 'd', '[]', 'open')"
            )
        )
    assert migrate.current_revision(scratch) is None

    migrate.upgrade(scratch)

    assert migrate.current_revision(scratch) == migrate.head_revision()
    with scratch.connect() as conn:
        assert conn.execute(text("SELECT title, created_by FROM tasks")).one() == ("keep me", None)
    # The dropped columns came back and the schema now matches the models exactly.
    assert _diff(scratch) == []


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
