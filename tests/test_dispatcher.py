"""Tests for the operation dispatcher."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app import authorization_service, operation_dispatcher
from app.models import Operation, ReceiverOperation


def test_dispatch_after_grant_succeeds(db):
    auth = authorization_service.grant(db, agent_id="agent-1", resource="refund")

    op, status = operation_dispatcher.dispatch_operation(
        db,
        authorization_id=auth.id,
        idempotency_key="idem-1",
        amount_cents=1000,
    )

    assert status == "DISPATCHED"
    assert op.dispatch_status == "DISPATCHED"
    assert op.authorization_version_used == 1
    assert op.dispatched_at is not None

    ro = db.scalar(
        select(ReceiverOperation).where(ReceiverOperation.operation_id == op.id)
    )
    assert ro is not None
    assert ro.receiver_state == "ACK_PENDING"


def test_dispatch_blocked_when_revoked_before(db):
    auth = authorization_service.grant(db, agent_id="agent-2", resource="refund")
    authorization_service.revoke(db, authorization_id=auth.id, reason="revoked")

    op, status = operation_dispatcher.dispatch_operation(
        db,
        authorization_id=auth.id,
        idempotency_key="idem-2",
        amount_cents=500,
    )

    assert status == "BLOCKED_REVOKED"
    assert op.dispatch_status == "BLOCKED_REVOKED"
    assert "revoked" in (op.dispatch_error or "").lower()

    ro = db.scalar(
        select(ReceiverOperation).where(ReceiverOperation.operation_id == op.id)
    )
    assert ro is None


def test_dispatch_with_duplicate_key_returns_same_op(db):
    auth = authorization_service.grant(db, agent_id="agent-3", resource="refund")

    op1, status1 = operation_dispatcher.dispatch_operation(
        db,
        authorization_id=auth.id,
        idempotency_key="idem-3",
        amount_cents=200,
    )
    op2, status2 = operation_dispatcher.dispatch_operation(
        db,
        authorization_id=auth.id,
        idempotency_key="idem-3",
        amount_cents=200,
    )

    assert status1 == "DISPATCHED"
    assert status2 == "DUPLICATE"
    assert op1.operation_uid == op2.operation_uid

    ops = list(db.scalars(select(Operation).where(Operation.idempotency_key == "idem-3")))
    assert len(ops) == 1

    ros = list(db.scalars(select(ReceiverOperation)))
    assert len(ros) == 1


def test_dispatch_creates_receiver_operation_with_settle_time(db):
    auth = authorization_service.grant(db, agent_id="agent-4", resource="refund")

    op, _ = operation_dispatcher.dispatch_operation(
        db,
        authorization_id=auth.id,
        idempotency_key="idem-4",
        amount_cents=999,
        simulated_settle_seconds=120,
    )

    ro = db.scalar(
        select(ReceiverOperation).where(ReceiverOperation.operation_id == op.id)
    )
    assert ro.receiver_ref.startswith("RCV-")
    assert ro.simulated_settle_at > op.dispatched_at
    assert ro.forced_inconclusive is False