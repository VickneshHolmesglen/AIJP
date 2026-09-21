import os
from collections.abc import Iterator

# Milestone 12 made authentication default-on. The older suites exercise endpoint behaviour, not
# access control, so they run with it off; tests/test_auth.py switches it on per test.
os.environ.setdefault("AIJP_AUTH_ENABLED", "false")
# Escalation is on by default in production; the older suites use one scripted model and must not
# reach a real Ollama for a second, thinking call. tests/test_escalation.py turns it on per test.
os.environ.setdefault("AIJP_LLM_ESCALATION", "off")

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker

from app.config import Settings, get_settings
from app.db import get_session, init_db
from app.main import app
from app.models import Base

TEST_DATABASE_URL = os.environ.get(
    "AIJP_TEST_DATABASE_URL", "postgresql+psycopg://aijp:aijp@127.0.0.1:5432/aijp_test"
)


@pytest.fixture(scope="session")
def db_engine() -> Iterator[Engine]:
    """Test database; integration tests skip cleanly when PostgreSQL is not running."""
    engine = create_engine(TEST_DATABASE_URL, connect_args={"connect_timeout": 3})
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        engine.dispose()
        pytest.skip(f"PostgreSQL not available at test URL ({type(exc).__name__})")
    init_db(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def client(db_engine: Engine) -> Iterator[TestClient]:
    for table in reversed(Base.metadata.sorted_tables):
        with db_engine.begin() as conn:
            conn.execute(table.delete())

    factory = sessionmaker(db_engine, expire_on_commit=False)

    def override_session() -> Iterator[object]:
        with factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_settings] = lambda: Settings(
        max_upload_bytes=50_000, chunk_max_chars=300, chunk_overlap_chars=60
    )
    # No lifespan: the fixture already initialised the schema.
    yield TestClient(app)
    app.dependency_overrides.clear()
