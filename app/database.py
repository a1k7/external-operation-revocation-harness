"""SQLAlchemy engine, session factory, and FastAPI dependency."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import DATABASE_URL


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


# `check_same_thread=False` is required for SQLite when used across FastAPI
# worker threads. Safe here because we use short-lived sessions.
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
    future=True,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency that yields a scoped DB session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def session_scope() -> Generator[Session, None, None]:
    """Transactional session context manager for non-FastAPI use (scripts, tests)."""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def init_db() -> None:
    """Create all tables. Imported models register themselves on Base.metadata."""
    # Import models so their table metadata is registered before create_all.
    from app import models  # noqa: F401

    Base.metadata.create_all(bind=engine)