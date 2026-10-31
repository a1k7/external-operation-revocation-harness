"""HTTP API surface for the demonstration dashboard."""

from __future__ import annotations

import datetime as dt
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import (
    authorization_service,
    evidence_ledger,
    external_receiver,
    operation_dispatcher,
    outcome_verification,
    scenario_runner,
)
from app.database import get_db
from app.models import Authorization, Operation, ReceiverOperation, utcnow
from app.schemas import (
    AuthorizationResponse,
    CancellationResponse,
    DispatchOperationRequest,
    DispatchOperationResponse,
    EvidenceChainStatus,
    EvidenceEventResponse,
    GrantAuthorizationRequest,
    RequestCancellationRequest,
    RevokeAuthorizationRequest,
    ScenarioRunRequest,
    VerificationResponse,
)

router = APIRouter(prefix="/api")

# ---------- Health ----------
@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "time": utcnow().isoformat()}

# ---------- Authorizations ----------
@router.post("/authorizations", response_model=AuthorizationResponse)
def post_authorization(body: GrantAuthorizationRequest, db: Session = Depends(get_db)) -> AuthorizationResponse:
    auth = authorization_service.grant(db, agent_id=body.agent_id, resource=body.resource)
    evidence_ledger.append_event(
        db, event_type="AUTHORIZATION_GRANTED", subject_type="authorization", subject_id=str(auth.id),
        payload={"authorization_id": auth.id, "agent_id": auth.agent_id, "resource": auth.resource, "version": auth.version},
    )
    db.commit()
    return AuthorizationResponse.model_validate(auth)

@router.post("/authorizations/{authorization_id}/revoke", response_model=AuthorizationResponse)
def post_revoke(authorization_id: int, body: RevokeAuthorizationRequest, db: Session = Depends(get_db)) -> AuthorizationResponse:
    try:
        auth = authorization_service.revoke(db, authorization_id=authorization_id, reason=body.reason)
    except authorization_service.AuthorizationError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    evidence_ledger.append_event(
        db, event_type="AUTHORIZATION_REVOKED", subject_type="authorization", subject_id=str(auth.id),
        payload={"authorization_id": auth.id, "reason": body.reason, "version": auth.version, "revoked_at": auth.revoked_at.isoformat() if auth.revoked_at else None},
    )
    db.commit()
    return AuthorizationResponse.model_validate(auth)

@router.get("/authorizations", response_model=list[AuthorizationResponse])
def get_authorizations(db: Session = Depends(get_db)) -> list[AuthorizationResponse]:
    items = authorization_service.list_authorizations(db)
    return [AuthorizationResponse.model_validate(a) for a in items]

@router.get("/authorizations/{authorization_id}", response_model=AuthorizationResponse)
def get_authorization(authorization_id: int, db: Session = Depends(get_db)) -> AuthorizationResponse:
    try:
        auth = authorization_service.get_authorization(db, authorization_id)
    except authorization_service.AuthorizationError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return AuthorizationResponse.model_validate(auth)

# ---------- Operations ----------
@router.post("/operations/dispatch", response_model=DispatchOperationResponse)
def post_dispatch(body: DispatchOperationRequest, db: Session = Depends(get_db)) -> DispatchOperationResponse:
    try:
        op, status = operation_dispatcher.dispatch_operation(
            db, authorization_id=body.authorization_id, idempotency_key=body.idempotency_key,
            amount_cents=body.amount_cents, force_inconclusive=body.force_inconclusive,
            simulated_settle_seconds=body.simulated_settle_seconds,
        )
    except authorization_service.AuthorizationError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except operation_dispatcher.DispatchError as exc:
        raise HTTPException(status_code=409, detail=str(exc))

    ro = db.scalar(select(ReceiverOperation).where(ReceiverOperation.operation_id == op.id))
    if status == "BLOCKED_REVOKED":
        evidence_ledger.append_event(db, event_type="OPERATION_BLOCKED_REVOKED", subject_type="operation", subject_id=op.operation_uid, payload={"operation_uid": op.operation_uid, "error": op.dispatch_error})
    elif status == "DUPLICATE":
        evidence_ledger.append_event(db, event_type="IDEMPOTENT_DUPLICATE", subject_type="operation", subject_id=op.operation_uid, payload={"operation_uid": op.operation_uid, "idempotency_key": body.idempotency_key})
    else:
        evidence_ledger.append_event(db, event_type="OPERATION_DISPATCHED", subject_type="operation", subject_id=op.operation_uid, payload={"operation_uid": op.operation_uid, "authorization_id": body.authorization_id, "authorization_version_used": op.authorization_version_used, "amount_cents": body.amount_cents, "idempotency_key": body.idempotency_key})
    
    db.commit()
    return DispatchOperationResponse(
        operation_uid=op.operation_uid, dispatch_status=status, authorization_version_used=op.authorization_version_used,
        dispatched_at=op.dispatched_at, receiver_ref=ro.receiver_ref if ro else None,
        receiver_state=ro.receiver_state if ro else None, dispatch_error=op.dispatch_error,
    )

@router.post("/operations/{operation_uid}/cancel", response_model=CancellationResponse)
def post_cancel(operation_uid: str, body: RequestCancellationRequest, db: Session = Depends(get_db)) -> CancellationResponse:
    try:
        snap = external_receiver.request_cancellation(db, operation_uid)
    except external_receiver.ReceiverError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    evidence_ledger.append_event(
        db, event_type="CANCELLATION_RESPONSE", subject_type="operation", subject_id=operation_uid,
        payload={"operation_uid": operation_uid, "reason": body.reason, "receiver_state": snap.state, "cancellation_requested": snap.cancellation_requested, "cancellation_acknowledged": snap.cancellation_acknowledged, "cancellation_rejected_reason": snap.cancellation_rejected_reason, "last_receiver_response": snap.last_response},
    )
    db.commit()
    return CancellationResponse(
        operation_uid=operation_uid, cancellation_requested=snap.cancellation_requested,
        cancellation_acknowledged=snap.cancellation_acknowledged, receiver_state=snap.state,
        cancellation_rejected_reason=snap.cancellation_rejected_reason,
    )

@router.post("/operations/{operation_uid}/advance")
def post_advance(operation_uid: str, seconds: int = 300, db: Session = Depends(get_db)) -> dict[str, Any]:
    try:
        snap = external_receiver.advance_simulated_time(db, operation_uid, seconds)
    except external_receiver.ReceiverError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    evidence_ledger.append_event(db, event_type="RECEIVER_TIME_ADVANCED", subject_type="operation", subject_id=operation_uid, payload={"operation_uid": operation_uid, "advanced_by_seconds": seconds, "receiver_state": snap.state})
    db.commit()
    return {"operation_uid": operation_uid, "receiver_state": snap.state, "advanced_by_seconds": seconds}

@router.post("/operations/{operation_uid}/verify", response_model=VerificationResponse)
def post_verify(operation_uid: str, db: Session = Depends(get_db)) -> VerificationResponse:
    try:
        outcome, snap, detail, verified_at = outcome_verification.verify_outcome(db, operation_uid)
    except outcome_verification.VerificationError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    evidence_ledger.append_event(
        db, event_type="OUTCOME_VERIFIED", subject_type="operation", subject_id=operation_uid,
        payload={"operation_uid": operation_uid, "verified_outcome": outcome.value, "receiver_state_observed": snap.state, "detail": detail, "verified_at": verified_at.isoformat()},
    )
    db.commit()
    return VerificationResponse(
        operation_uid=operation_uid, verified_outcome=outcome.value,
        receiver_state_observed=snap.state, receiver_ref=snap.receiver_ref,
        verified_at=verified_at, detail=detail,
    )

def _summarise_operation(db: Session, op: Operation) -> dict[str, Any]:
    auth = db.get(Authorization, op.authorization_id)
    ro = db.scalar(select(ReceiverOperation).where(ReceiverOperation.operation_id == op.id))
    verified_outcome: str | None = None
    verified_detail: str | None = None
    receiver_state: str | None = None
    if ro is not None:
        snap = external_receiver.poll_receiver(db, op.operation_uid)
        receiver_state = snap.state
        verified_outcome, verified_detail = outcome_verification._classify(snap)
    return {
        "operation_uid": op.operation_uid, "authorization_id": op.authorization_id,
        "authorization_status": auth.status if auth else None,
        "authorization_version_used": op.authorization_version_used,
        "authorization_revoked_at": auth.revoked_at.isoformat() if auth and auth.revoked_at else None,
        "agent_id": op.agent_id, "resource": op.resource, "amount_cents": op.amount_cents,
        "idempotency_key": op.idempotency_key, "dispatch_status": op.dispatch_status,
        "dispatched_at": op.dispatched_at.isoformat() if op.dispatched_at else None,
        "dispatch_error": op.dispatch_error, "receiver_ref": ro.receiver_ref if ro else None,
        "receiver_state": receiver_state,
        "cancellation_requested": ro.cancellation_requested if ro else None,
        "cancellation_acknowledged": ro.cancellation_acknowledged if ro else None,
        "cancellation_rejected_reason": ro.cancellation_rejected_reason if ro else None,
        "verified_outcome": verified_outcome.value if verified_outcome else None,
        "verified_outcome_detail": verified_detail,
    }

@router.get("/operations")
def get_operations(db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    ops = operation_dispatcher.list_operations(db)
    summaries = [_summarise_operation(db, op) for op in ops]
    db.commit()
    return summaries

@router.get("/operations/{operation_uid}")
def get_operation_detail(operation_uid: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    try:
        op = operation_dispatcher.get_operation(db, operation_uid)
    except operation_dispatcher.DispatchError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    summary = _summarise_operation(db, op)
    db.commit()
    return summary

@router.get("/operations/{operation_uid}/evidence", response_model=list[EvidenceEventResponse])
def get_operation_evidence(operation_uid: str, db: Session = Depends(get_db)) -> list[EvidenceEventResponse]:
    try:
        op = operation_dispatcher.get_operation(db, operation_uid)
    except operation_dispatcher.DispatchError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    from app.models import EvidenceEvent
    events = list(db.scalars(
        select(EvidenceEvent).where(
            (EvidenceEvent.subject_id == operation_uid) | 
            ((EvidenceEvent.subject_type == "authorization") & (EvidenceEvent.subject_id == str(op.authorization_id)))
        ).order_by(EvidenceEvent.id)
    ))
    return [_event_to_response(e) for e in events]

# ---------- Evidence ----------
def _event_to_response(event) -> EvidenceEventResponse:
    import json
    return EvidenceEventResponse(
        event_uid=event.event_uid, event_type=event.event_type, subject_type=event.subject_type,
        subject_id=event.subject_id, payload=json.loads(event.payload_json),
        prev_hash=event.prev_hash, event_hash=event.event_hash,
        occurred_at=event.occurred_at, recorded_at=event.recorded_at,
    )

@router.get("/evidence", response_model=list[EvidenceEventResponse])
def get_evidence(db: Session = Depends(get_db)) -> list[EvidenceEventResponse]:
    events = evidence_ledger.list_events(db)
    return [_event_to_response(e) for e in events]

@router.get("/evidence/verify", response_model=EvidenceChainStatus)
def get_evidence_verify(db: Session = Depends(get_db)) -> EvidenceChainStatus:
    intact, broken = evidence_ledger.verify_chain(db)
    events = evidence_ledger.list_events(db)
    return EvidenceChainStatus(
        total_events=len(events), intact=intact,
        broken_at_event_uid=broken.event_uid if broken else None,
    )

# ---------- Scenarios ----------
@router.get("/scenarios")
def get_scenarios() -> list[dict[str, str]]:
    return scenario_runner.list_scenarios()

@router.post("/scenarios/run")
def post_run_scenario(body: ScenarioRunRequest, db: Session = Depends(get_db)) -> dict[str, Any]:
    try:
        result = scenario_runner.run_scenario(db, body.scenario)
    except scenario_runner.ScenarioError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    db.commit()
    return result