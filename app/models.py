"""SQLAlchemy ORM models for authorizations, operations, receiver state,
idempotency keys, and the hash-chained evidence ledger.

Timezone note: SQLite does NOT preserve timezone information. We use a
custom `UTCDateTime` type that always stores UTC-naive values and always
returns UTC-aware datetimes. Without this, comparisons like
`now < ro.simulated_settle_at` fail with
"can't compare offset-naive and offset-aware datetimes".
"""

from __future__ import annotations

import datetime as dt
from typing import Optional

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    TypeDecorator,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class UTCDateTime(TypeDecorator):
    """Store naive-UTC in the DB, always return tz-aware UTC in Python."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=dt.timezone.utc)
        return value.astimezone(dt.timezone.utc).replace(tzinfo=None)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=dt.timezone.utc)
        return value.astimezone(dt.timezone.utc)


class Authorization(Base):
    __tablename__ = "authorizations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    agent_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    resource: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="GRANTED")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    granted_at: Mapped[dt.datetime] = mapped_column(UTCDateTime(), default=utcnow)
    revoked_at: Mapped[Optional[dt.datetime]] = mapped_column(
        UTCDateTime(), nullable=True
    )
    revocation_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    operations: Mapped[list["Operation"]] = relationship(back_populates="authorization")


class Operation(Base):
    __tablename__ = "operations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    operation_uid: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)

    authorization_id: Mapped[int] = mapped_column(ForeignKey("authorizations.id"))
    authorization_version_used: Mapped[int] = mapped_column(Integer, nullable=False)

    agent_id: Mapped[str] = mapped_column(String(64), nullable=False)
    resource: Mapped[str] = mapped_column(String(128), nullable=False)
    amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)

    dispatch_status: Mapped[str] = mapped_column(String(32), nullable=False, default="CREATED")
    dispatch_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    dispatched_at: Mapped[Optional[dt.datetime]] = mapped_column(
        UTCDateTime(), nullable=True
    )

    created_at: Mapped[dt.datetime] = mapped_column(UTCDateTime(), default=utcnow)

    authorization: Mapped[Authorization] = relationship(back_populates="operations")
    receiver_state: Mapped[Optional["ReceiverOperation"]] = relationship(
        back_populates="operation", uselist=False
    )


class ReceiverOperation(Base):
    """Independent record of the *simulated external receiver* state."""

    __tablename__ = "receiver_operations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    operation_id: Mapped[int] = mapped_column(ForeignKey("operations.id"), unique=True)
    receiver_ref: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)

    receiver_state: Mapped[str] = mapped_column(
        String(32), nullable=False, default="ACK_PENDING"
    )

    simulated_settle_at: Mapped[dt.datetime] = mapped_column(UTCDateTime())

    cancellation_requested: Mapped[bool] = mapped_column(default=False)
    cancellation_acknowledged: Mapped[bool] = mapped_column(default=False)
    cancellation_rejected_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    cancellation_requested_at: Mapped[Optional[dt.datetime]] = mapped_column(
        UTCDateTime(), nullable=True
    )
    cancellation_acknowledged_at: Mapped[Optional[dt.datetime]] = mapped_column(
        UTCDateTime(), nullable=True
    )

    forced_inconclusive: Mapped[bool] = mapped_column(default=False)

    last_receiver_response: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    updated_at: Mapped[dt.datetime] = mapped_column(
        UTCDateTime(), default=utcnow, onupdate=utcnow
    )

    operation: Mapped[Operation] = relationship(back_populates="receiver_state")


class IdempotencyKey(Base):
    __tablename__ = "idempotency_keys"
    __table_args__ = (UniqueConstraint("key", "scope", name="uq_idem_key_scope"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(128), nullable=False)
    scope: Mapped[str] = mapped_column(String(64), nullable=False, default="dispatch")
    operation_uid: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(UTCDateTime(), default=utcnow)


class EvidenceEvent(Base):
    """Append-only, hash-chained evidence ledger."""

    __tablename__ = "evidence_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_uid: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    subject_type: Mapped[str] = mapped_column(String(32), nullable=False)
    subject_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    payload_json: Mapped[str] = mapped_column(Text, nullable=False)

    prev_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    event_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)

    occurred_at: Mapped[dt.datetime] = mapped_column(UTCDateTime(), default=utcnow)
    recorded_at: Mapped[dt.datetime] = mapped_column(UTCDateTime(), default=utcnow)