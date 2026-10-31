"""Shared pytest fixtures.

The fixture set uses an isolated in-memory SQLite database per test to avoid
touching the on-disk demo database. `StaticPool` is used so that all sessions
in a single test share the same in-memory database.
"""

from __future__ import annotations

# Set before any `app.*` import so config picks it up at import time.
import os

os.environ.setdefault("REVOCATION_HARNESS_DB_URL", "sqlite:///:memory:")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app import models  # noqa: E402,F401
from app.database import Base, get_db  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture()
def engine():
    """Fresh in-memory SQLite engine shared across the whole test."""
    eng = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(eng)
    try:
        yield eng
    finally:
        Base.metadata.drop_all(eng)
        eng.dispose()


@pytest.fixture()
def session_factory(engine):
    """A session factory bound to the per-test in-memory engine."""
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


@pytest.fixture()
def db(session_factory):
    """A single ORM session. Commits on success, rolls back on exception."""
    session = session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@pytest.fixture()
def client(session_factory):
    """FastAPI TestClient with `get_db` overridden to the per-test session."""

    def _override():
        s = session_factory()
        try:
            yield s
            s.commit()
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    app.dependency_overrides[get_db] = _override
    try:
        with TestClient(app) as c:
            yield c
    finally:
        app.dependency_overrides.clear()