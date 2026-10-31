"""Tests for the simulated external receiver state machine."""

from __future__ import annotations

from app import authorization_service, external_receiver, operation_dispatcher


def _make_op(db, *, settle_seconds: int = 60, inconclusive: bool = False):
    auth = authorization_service.grant(db, agent_id="agent-r", resource="refund")
    op, _ = operation_dispatcher.dispatch_operation(
        db,
        authorization_id=auth.id,
        idempotency_key=f"idem-{settle_seconds}-{inconclusive}",
        amount_cents=100,
        simulated_settle_seconds=settle_seconds,
        force_inconclusive=inconclusive,
    )
    return op


def test_initial_state_is_ack_pending(db):
    op = _make_op(db)
    snap = external_receiver.poll_receiver(db, op.operation_uid)
    assert snap.state == "ACK_PENDING"
    assert snap.cancellation_requested is False
    assert snap.cancellation_acknowledged is False


def test_settles_to_completed_when_advanced(db):
    op = _make_op(db, settle_seconds=60)
    snap = external_receiver.advance_simulated_time(db, op.operation_uid, 300)
    assert snap.state == "COMPLETED"


def test_cancel_before_settle_results_in_cancelled(db):
    op = _make_op(db, settle_seconds=600)
    snap = external_receiver.request_cancellation(db, op.operation_uid)
    assert snap.cancellation_requested is True
    assert snap.cancellation_acknowledged is True
    assert snap.state == "ACK_PENDING"

    snap = external_receiver.advance_simulated_time(db, op.operation_uid, 1000)
    assert snap.state == "CANCELLED"


def test_cancel_after_settle_rejected(db):
    op = _make_op(db, settle_seconds=60)
    external_receiver.advance_simulated_time(db, op.operation_uid, 300)

    snap = external_receiver.request_cancellation(db, op.operation_uid)
    assert snap.state == "COMPLETED"
    assert snap.cancellation_rejected_reason == "operation already completed"


def test_forced_inconclusive_state(db):
    op = _make_op(db, settle_seconds=60, inconclusive=True)
    snap = external_receiver.advance_simulated_time(db, op.operation_uid, 300)
    assert snap.state == "INCONCLUSIVE"