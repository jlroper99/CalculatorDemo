"""PostGIS-backed fixtures. Tests skip without a database unless BIKERADAR_REQUIRE_DB=1 (CI)."""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from alembic import command
from bikeradar.api.app import app
from bikeradar.db import get_session
from tests.helpers import FIXTURE

DEFAULT_TEST_URL = "postgresql+psycopg://bikeradar:bikeradar@localhost:5432/bikeradar_test"
ALEMBIC_INI = FIXTURE.parents[1] / "api" / "alembic.ini"


@pytest.fixture(scope="session")
def database_url() -> str:
    return os.environ.get("BIKERADAR_TEST_DATABASE_URL") or DEFAULT_TEST_URL


@pytest.fixture(scope="session")
def engine(database_url: str) -> Iterator[Engine]:
    eng = create_engine(database_url)
    try:
        with eng.connect():
            pass
    except OperationalError as exc:
        if os.environ.get("BIKERADAR_REQUIRE_DB") == "1":
            raise
        pytest.skip(f"no PostGIS test database ({exc.orig}); run `make db-up` first")
    cfg = Config(str(ALEMBIC_INI))
    cfg.attributes["database_url"] = database_url
    # Exercise the migrations in both directions on every run.
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    yield eng
    eng.dispose()


@pytest.fixture
def session(engine: Engine) -> Iterator[Session]:
    with engine.begin() as conn:
        conn.execute(text("TRUNCATE rides RESTART IDENTITY CASCADE"))
    with sessionmaker(bind=engine, expire_on_commit=False)() as s:
        yield s


@pytest.fixture
def client(session: Session) -> Iterator[TestClient]:
    def override() -> Iterator[Session]:
        yield session

    app.dependency_overrides[get_session] = override
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
