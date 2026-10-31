"""Encapsulates the seven mandatory demonstration scenarios.

Each scenario is deterministic — no random sleeps, no reliance on wall clock
beyond the `simulated_settle_at` boundary which we explicitly advance via
`external_receiver.advance_simulated_time`.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import (
    authorization_service,
    evidence_ledger,
    external_receiver,
    operation_dispatcher,
    outcome_verification,
)
from app.models import IdempotencyKey, Operation, ReceiverOperation
from app.schemas import DispatchStatus, VerifiedOutcome


class ScenarioError(Exception):
    """Raised on unknown scenario or invalid setup."""


SCENARIOS = {
    "scenario_1": "Revocation before dispatch",
    "scenario_2": "Revocation after dispatch but before completion",
    "scenario_3": "Operation completes before cancellation takes effect",
    "scenario_4": "Receiver returns an inconclusive response",
    "scenario_5": "Duplicate request with the same idempotency key",
    "scenario_6": "Receiver accepts cancellation but has not reached terminal state",
    "scenario_7": "Authorization revoked while multiple operations are pending",
}


def list_scenarios() -> list[dict[str, str]]:
    return [{"key": k, "title": v} for k, v in SCENARIOS.items()]


def _log(
    db: Session,
    *,
    event_type: str,
    subject_type: str,
    subject_id: str,
    payload: dict[str, Any],
) -> None:
    evidence_ledger.append_event(
        db,
        event_type=event_type,
        subject_type=subject_type,
        subject_id=subject_id,
        payload=payload,
    )


def _grant(db: Session, *, agent_id: str, resource: str) -> Any:
    auth = authorization_service.grant(db, agent_id=agent_id, resource=resource)
    _log(
        db,
        event_type="AUTHORIZATION_GRANTED",
        subject_type="authorization",
        subject_id=str(auth.id),
        payload={
            "authorization_id": auth.id,
            "agent_id": auth.agent_id,
            "resource": auth.resource,
            "version": auth.version,
        },
    )
    return auth


def _revoke(db: Session, *, authorization_id: int, reason: str) -> Any:
    auth = authorization_service.revoke(db, authorization_id=authorization_id, reason=reason)
    _log(
        db,
        event_type="AUTHORIZATION_REVOKED",
        subject_type="authorization",
        subject_id=str(auth.id),
        payload={
            "authorization_id": auth.id,
            "reason": reason,
            "version": auth.version,
            "revoked_at": auth.revoked_at.isoformat() if auth.revoked_at else None,
        },
    )
    return auth


def _dispatch(
    db: Session,
    *,
    authorization_id: int,
    idempotency_key: str,
    amount_cents: int,
    force_inconclusive: bool = False,
    simulated_settle_seconds: int = 60,
) -> tuple[Operation, str]:
    op, status = operation_dispatcher.dispatch_operation(
        db,
        authorization_id=authorization_id,
        idempotency_key=idempotency_key,
        amount_cents=amount_cents,
        force_inconclusive=force_inconclusive,
        simulated_settle_seconds=simulated_settle_seconds,
    )
    if status == DispatchStatus.BLOCKED_REVOKED.value:
        _log(
            db,
            event_type="OPERATION_BLOCKED_REVOKED",
            subject_type="operation",
            subject_id=op.operation_uid,
            payload={
                "operation_uid": op.operation_uid,
                "dispatch_error": op.dispatch_error,
            },
        )
    elif status == DispatchStatus.DUPLICATE.value:
        _log(
            db,
            event_type="IDEMPOTENT_DUPLICATE",
            subject_type="operation",
            subject_id=op.operation_uid,
            payload={
                "operation_uid": op.operation_uid,
                "idempotency_key": idempotency_key,
            },
        )
    else:
        _log(
            db,
            event_type="OPERATION_DISPATCHED",
            subject_type="operation",
            subject_id=op.operation_uid,
            payload={
                "operation_uid": op.operation_uid,
                "authorization_id": authorization_id,
                "authorization_version_used": op.authorization_version_used,
                "amount_cents": amount_cents,
                "idempotency_key": idempotency_key,
            },
        )
    return op, status


def _cancel(db: Session, *, operation_uid: str) -> external_receiver.ReceiverSnapshot:
    snap = external_receiver.request_cancellation(db, operation_uid)
    _log(
        db,
        event_type="CANCELLATION_RESPONSE",
        subject_type="operation",
        subject_id=operation_uid,
        payload={
            "operation_uid": operation_uid,
            "receiver_state": snap.state,
            "cancellation_requested": snap.cancellation_requested,
            "cancellation_acknowledged": snap.cancellation_acknowledged,
            "cancellation_rejected_reason": snap.cancellation_rejected_reason,
            "last_receiver_response": snap.last_response,
        },
    )
    return snap


def _advance(db: Session, *, operation_uid: str, seconds: int) -> external_receiver.ReceiverSnapshot:
    snap = external_receiver.advance_simulated_time(db, operation_uid, seconds)
    _log(
        db,
        event_type="RECEIVER_TIME_ADVANCED",
        subject_type="operation",
        subject_id=operation_uid,
        payload={
            "operation_uid": operation_uid,
            "advanced_by_seconds": seconds,
            "receiver_state": snap.state,
        },
    )
    return snap


def _verify(db: Session, *, operation_uid: str) -> dict[str, Any]:
    outcome, snap, detail, verified_at = outcome_verification.verify_outcome(db, operation_uid)
    _log(
        db,
        event_type="OUTCOME_VERIFIED",
        subject_type="operation",
        subject_id=operation_uid,
        payload={
            "operation_uid": operation_uid,
            "verified_outcome": outcome.value,
            "receiver_state_observed": snap.state,
            "detail": detail,
            "verified_at": verified_at.isoformat(),
        },
    )
    return {
        "operation_uid": operation_uid,
        "verified_outcome": outcome.value,
        "receiver_state": snap.state,
        "detail": detail,
        "verified_at": verified_at.isoformat(),
    }


def _unique_key(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def run_scenario_1(db: Session) -> dict[str, Any]:
    """Revocation before dispatch: operation must NOT be dispatched.

    No receiver record is created, so no verification call is made.
    """
    auth = _grant(db, agent_id="agent-1", resource="refund")
    _revoke(db, authorization_id=auth.id, reason="revoked before dispatch")
    op, status = _dispatch(
        db,
        authorization_id=auth.id,
        idempotency_key=_unique_key("s1"),
        amount_cents=1000,
    )
    return {
        "scenario": "scenario_1",
        "title": SCENARIOS["scenario_1"],
        "operation_uid": op.operation_uid,
        "dispatch_status": status,
        "expected": DispatchStatus.BLOCKED_REVOKED.value,
        "passed": status == DispatchStatus.BLOCKED_REVOKED.value,
        "detail": op.dispatch_error,
    }


def run_scenario_2(db: Session) -> dict[str, Any]:
    """Revocation after dispatch: cancellation requested, verified terminal."""
    auth = _grant(db, agent_id="agent-2", resource="refund")
    op, status = _dispatch(
        db,
        authorization_id=auth.id,
        idempotency_key=_unique_key("s2"),
        amount_cents=2500,
        simulated_settle_seconds=60,
    )
    if status != DispatchStatus.DISPATCHED.value:
        raise ScenarioError(f"scenario_2 expected DISPATCHED, got {status}")
    _revoke(db, authorization_id=auth.id, reason="revoked while op in flight")
    _cancel(db, operation_uid=op.operation_uid)
    _advance(db, operation_uid=op.operation_uid, seconds=300)
    result = _verify(db, operation_uid=op.operation_uid)
    return {
        "scenario": "scenario_2",
        "title": SCENARIOS["scenario_2"],
        "operation_uid": op.operation_uid,
        "dispatch_status": status,
        "expected": VerifiedOutcome.CANCELLATION_CONFIRMED.value,
        "passed": result["verified_outcome"] == VerifiedOutcome.CANCELLATION_CONFIRMED.value,
        "verification": result,
    }


def run_scenario_3(db: Session) -> dict[str, Any]:
    """Operation completes before cancellation: report COMPLETION_CONFIRMED."""
    auth = _grant(db, agent_id="agent-3", resource="refund")
    op, status = _dispatch(
        db,
        authorization_id=auth.id,
        idempotency_key=_unique_key("s3"),
        amount_cents=750,
        simulated_settle_seconds=60,
    )
    if status != DispatchStatus.DISPATCHED.value:
        raise ScenarioError(f"scenario_3 expected DISPATCHED, got {status}")
    _advance(db, operation_uid=op.operation_uid, seconds=300)
    _cancel(db, operation_uid=op.operation_uid)  # should be rejected
    _revoke(db, authorization_id=auth.id, reason="too late; op already completed")
    result = _verify(db, operation_uid=op.operation_uid)
    return {
        "scenario": "scenario_3",
        "title": SCENARIOS["scenario_3"],
        "operation_uid": op.operation_uid,
        "dispatch_status": status,
        "expected": VerifiedOutcome.COMPLETION_CONFIRMED.value,
        "passed": result["verified_outcome"] == VerifiedOutcome.COMPLETION_CONFIRMED.value,
        "verification": result,
    }


def run_scenario_4(db: Session) -> dict[str, Any]:
    """Receiver returns inconclusive: must be OUTCOME_UNKNOWN."""
    auth = _grant(db, agent_id="agent-4", resource="refund")
    op, status = _dispatch(
        db,
        authorization_id=auth.id,
        idempotency_key=_unique_key("s4"),
        amount_cents=500,
        simulated_settle_seconds=60,
        force_inconclusive=True,
    )
    if status != DispatchStatus.DISPATCHED.value:
        raise ScenarioError(f"scenario_4 expected DISPATCHED, got {status}")
    _advance(db, operation_uid=op.operation_uid, seconds=300)
    _revoke(db, authorization_id=auth.id, reason="revoked while outcome unknown")
    result = _verify(db, operation_uid=op.operation_uid)
    return {
        "scenario": "scenario_4",
        "title": SCENARIOS["scenario_4"],
        "operation_uid": op.operation_uid,
        "dispatch_status": status,
        "expected": VerifiedOutcome.OUTCOME_UNKNOWN.value,
        "passed": result["verified_outcome"] == VerifiedOutcome.OUTCOME_UNKNOWN.value,
        "verification": result,
    }


def run_scenario_5(db: Session) -> dict[str, Any]:
    """Duplicate idempotency key: exactly one financial side effect."""
    auth = _grant(db, agent_id="agent-5", resource="refund")
    key = _unique_key("s5-dupe")
    op_first, status_first = _dispatch(
        db,
        authorization_id=auth.id,
        idempotency_key=key,
        amount_cents=1500,
        simulated_settle_seconds=60,
    )
    op_second, status_second = _dispatch(
        db,
        authorization_id=auth.id,
        idempotency_key=key,
        amount_cents=1500,
        simulated_settle_seconds=60,
    )
    distinct_ops = len(
        list(
            db.scalars(
                select(Operation).where(Operation.idempotency_key == key)
            )
        )
    )
    receiver_row = db.scalar(
        select(ReceiverOperation)
        .join(Operation, Operation.id == ReceiverOperation.operation_id)
        .where(Operation.idempotency_key == key)
    )
    passed = (
        status_first == DispatchStatus.DISPATCHED.value
        and status_second == DispatchStatus.DUPLICATE.value
        and op_first.operation_uid == op_second.operation_uid
        and distinct_ops == 1
        and receiver_row is not None
    )
    return {
        "scenario": "scenario_5",
        "title": SCENARIOS["scenario_5"],
        "operation_uid": op_first.operation_uid,
        "first_status": status_first,
        "second_status": status_second,
        "expected": DispatchStatus.DUPLICATE.value,
        "passed": passed,
        "distinct_operations": distinct_ops,
    }


def run_scenario_6(db: Session) -> dict[str, Any]:
    """Cancellation acknowledged but not terminal: must NOT be CONFIRMED."""
    auth = _grant(db, agent_id="agent-6", resource="refund")
    op, status = _dispatch(
        db,
        authorization_id=auth.id,
        idempotency_key=_unique_key("s6"),
        amount_cents=900,
        simulated_settle_seconds=600,
    )
    if status != DispatchStatus.DISPATCHED.value:
        raise ScenarioError(f"scenario_6 expected DISPATCHED, got {status}")
    _revoke(db, authorization_id=auth.id, reason="revoked while pending")
    _cancel(db, operation_uid=op.operation_uid)
    result = _verify(db, operation_uid=op.operation_uid)
    return {
        "scenario": "scenario_6",
        "title": SCENARIOS["scenario_6"],
        "operation_uid": op.operation_uid,
        "dispatch_status": status,
        "expected": VerifiedOutcome.CANCELLATION_ACKNOWLEDGED.value,
        "passed": result["verified_outcome"]
        == VerifiedOutcome.CANCELLATION_ACKNOWLEDGED.value,
        "not_confirmed": result["verified_outcome"]
        != VerifiedOutcome.CANCELLATION_CONFIRMED.value,
        "verification": result,
    }


def run_scenario_7(db: Session) -> dict[str, Any]:
    """Multiple pending ops when auth revoked: each evaluated independently."""
    auth = _grant(db, agent_id="agent-7", resource="refund")
    op_a, _ = _dispatch(
        db,
        authorization_id=auth.id,
        idempotency_key=_unique_key("s7-a"),
        amount_cents=100,
        simulated_settle_seconds=60,
    )
    op_b, _ = _dispatch(
        db,
        authorization_id=auth.id,
        idempotency_key=_unique_key("s7-b"),
        amount_cents=200,
        simulated_settle_seconds=60,
    )
    op_c, _ = _dispatch(
        db,
        authorization_id=auth.id,
        idempotency_key=_unique_key("s7-c"),
        amount_cents=300,
        simulated_settle_seconds=60,
        force_inconclusive=True,
    )
    _revoke(db, authorization_id=auth.id, reason="bulk revoke while 3 ops pending")

    _cancel(db, operation_uid=op_a.operation_uid)
    _advance(db, operation_uid=op_a.operation_uid, seconds=300)
    result_a = _verify(db, operation_uid=op_a.operation_uid)

    _advance(db, operation_uid=op_b.operation_uid, seconds=300)
    result_b = _verify(db, operation_uid=op_b.operation_uid)

    _advance(db, operation_uid=op_c.operation_uid, seconds=300)
    result_c = _verify(db, operation_uid=op_c.operation_uid)

    expected = {
        op_a.operation_uid: VerifiedOutcome.CANCELLATION_CONFIRMED.value,
        op_b.operation_uid: VerifiedOutcome.COMPLETION_CONFIRMED.value,
        op_c.operation_uid: VerifiedOutcome.OUTCOME_UNKNOWN.value,
    }
    observed = {
        op_a.operation_uid: result_a["verified_outcome"],
        op_b.operation_uid: result_b["verified_outcome"],
        op_c.operation_uid: result_c["verified_outcome"],
    }
    return {
        "scenario": "scenario_7",
        "title": SCENARIOS["scenario_7"],
        "operation_uids": list(expected.keys()),
        "expected": expected,
        "observed": observed,
        "passed": expected == observed,
        "verifications": [result_a, result_b, result_c],
    }


SCENARIO_FUNCS = {
    "scenario_1": run_scenario_1,
    "scenario_2": run_scenario_2,
    "scenario_3": run_scenario_3,
    "scenario_4": run_scenario_4,
    "scenario_5": run_scenario_5,
    "scenario_6": run_scenario_6,
    "scenario_7": run_scenario_7,
}


def run_scenario(db: Session, scenario: str) -> dict[str, Any]:
    if scenario not in SCENARIO_FUNCS:
        raise ScenarioError(f"Unknown scenario {scenario!r}")
    return SCENARIO_FUNCS[scenario](db)