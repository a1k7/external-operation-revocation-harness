"""Tests for the outcome verification engine.

These tests exercise the classifier against all five possible outcomes and
confirm the "never assume" rule: no Acknowledged or Requested state is ever
upgraded to Confirmed.
"""

from __future__ import annotations

from app import (
    authorization_service,
    external_receiver,
    operation_dispatcher,
    outcome_verification,
)
from app.schemas import VerifiedOutcome


def _make_op(db, *, settle_seconds: int = 60, inconclusive: bool = False):
    auth = authorization_service.grant(db, agent_id="agent-v", resource="refund")
    op, _ = operation_dispatcher.dispatch_operation(
        db,
        authorization_id=auth.id,
        idempotency_key=f"idem-v-{settle_seconds}-{inconclusive}",
        amount_cents=100,
        simulated_settle_seconds=settle_seconds,
        force_inconclusive=inconclusive,
    )
    return op


def test_completed_classified_as_completion_confirmed(db):
    op = _make_op(db)
    external_receiver.advance_simulated_time(db, op.operation_uid, 300)

    outcome, snap, _detail, _t = outcome_verification.verify_outcome(
        db, op.operation_uid
    )
    assert outcome == VerifiedOutcome.COMPLETION_CONFIRMED
    assert snap.state == "COMPLETED"


def test_cancelled_with_ack_classified_as_cancellation_confirmed(db):
    op = _make_op(db, settle_seconds=600)
    external_receiver.request_cancellation(db, op.operation_uid)
    external_receiver.advance_simulated_time(db, op.operation_uid, 1000)

    outcome, snap, _detail, _t = outcome_verification.verify_outcome(
        db, op.operation_uid
    )
    assert outcome == VerifiedOutcome.CANCELLATION_CONFIRMED
    assert snap.state == "CANCELLED"


def test_pending_cancellation_acknowledged(db):
    op = _make_op(db, settle_seconds=600)
    external_receiver.request_cancellation(db, op.operation_uid)

    outcome, snap, _detail, _t = outcome_verification.verify_outcome(
        db, op.operation_uid
    )
    assert outcome == VerifiedOutcome.CANCELLATION_ACKNOWLEDGED
    assert outcome != VerifiedOutcome.CANCELLATION_CONFIRMED
    assert snap.state == "ACK_PENDING"


def test_inconclusive_classified_unknown(db):
    op = _make_op(db, settle_seconds=60, inconclusive=True)
    external_receiver.advance_simulated_time(db, op.operation_uid, 300)

    outcome, snap, _detail, _t = outcome_verification.verify_outcome(
        db, op.operation_uid
    )
    assert outcome == VerifiedOutcome.OUTCOME_UNKNOWN
    assert snap.state == "INCONCLUSIVE"


def test_pending_without_cancellation_is_unknown(db):
    op = _make_op(db, settle_seconds=600)
    outcome, _snap, _detail, _t = outcome_verification.verify_outcome(
        db, op.operation_uid
    )
    assert outcome == VerifiedOutcome.OUTCOME_UNKNOWN