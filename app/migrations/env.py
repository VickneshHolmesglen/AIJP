"""Alembic environment.

Two ways in: the application passes an open connection (`app/migrate.py`, so migrations share its
engine and advisory lock), and the `alembic` CLI passes nothing, in which case the URL comes from
the same settings the app uses.
"""

from alembic import context
from sqlalchemy import Connection, create_engine, pool

from app.config import get_settings
from app.migrate import include_object
from app.models import Base

config = context.config
target_metadata = Base.metadata


def _configure(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        include_object=include_object,
        compare_type=True,
    )


def run_migrations_online() -> None:
    supplied = config.attributes.get("connection")
    if supplied is not None:
        _configure(supplied)
        with context.begin_transaction():
            context.run_migrations()
        return
    engine = create_engine(get_settings().database_url, poolclass=pool.NullPool)
    with engine.connect() as connection:
        _configure(connection)
        with context.begin_transaction():
            context.run_migrations()


run_migrations_online()
