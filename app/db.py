from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings


@lru_cache
def get_engine() -> Engine:
    return create_engine(get_settings().database_url, pool_pre_ping=True)


def init_db(engine: Engine) -> None:
    """Bring the schema up to date by applying pending Alembic migrations (see app/migrate.py).

    Imported here, not at the top, because app.migrate itself imports get_engine from this module.
    """
    from app.migrate import upgrade

    upgrade(engine)


def get_session() -> Iterator[Session]:
    with sessionmaker(get_engine(), expire_on_commit=False)() as session:
        yield session
