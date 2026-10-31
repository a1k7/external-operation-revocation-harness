"""Operation dispatcher: creates operations, captures authorization version,
sends to the simulated receiver, and enforces idempotency.

Design:
- The dispatcher *re-checks* authorization at dispatch time, using the version
  observed at creation. If the authorization has since been revoked (version
  incremented or status=REVOKED), the operation is BLOCKED_REVOKED.
- Idempotency keys are globally unique per scope="dispatch". Reusing a key
  returns the existing operation without a second receiver side effect.
"""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import authorization_service, external_receiver
from app.models import IdempotencyKey, Operation, utcnow
from app.schemas import DispatchStatus


class DispatchError(Exception):
    """Raised on invalid dispatch attempts."""


def _existing_by_idempotency(
    db: Session, idempotency_key: str
) -> Operation | None:
    key_row = db.scalar(
        select(IdempotencyKey).where(
            IdempotencyKey.key == idempotency_key,
            IdempotencyKey.scope == "dispatch",
        )
    )
    if key_row is None:
        return None
    return db.scalar(
        select(Operation).where(Operation.operation_uid == key_row.operation_uid)
    )


def dispatch_operation(
    db: Session,
    *,
    authorization_id: int,
    idempotency_key: str,
    amount_cents: int,
    force_inconclusive: bool = False,
    simulated_settle_seconds: int = 60,
) -> tuple[Operation, str]:
    """Create and dispatch an operation. Returns (operation, dispatch_status)."""
    if amount_cents <= 0:
        raise DispatchError("amount_cents must be > 0")

    # Idempotency: if the key was already used, return the existing operation.
    existing = _existing_by_idempotency(db, idempotency_key)
    if existing is not None:
        return existing, DispatchStatus.DUPLICATE.value

    auth = authorization_service.get_authorization(db, authorization_id)

    operation_uid = uuid.uuid4().hex

    # Capture the authorization version at creation time.
    captured_version = auth.version

    operation = Operation(
        operation_uid=operation_uid,
        idempotency_key=idempotency_key,
        authorization_id=auth.id,
        authorization_version_used=captured_version,
        agent_id=auth.agent_id,
        resource=auth.resource,
        amount_cents=amount_cents,
        dispatch_status=DispatchStatus.CREATED.value,
    )
    db.add(operation)

    # Record idempotency key in the same transaction, atomically with operation.
    try:
        db.add(
            IdempotencyKey(
                key=idempotency_key,
                scope="dispatch",
                operation_uid=operation_uid,
            )
        )
        db.flush()
    except IntegrityError:
        db.rollback()
        # Another writer won the race; fetch and return it.
        existing = _existing_by_idempotency(db, idempotency_key)
        if existing is None:
            raise DispatchError("Idempotency conflict but existing operation not found")
        return existing, DispatchStatus.DUPLICATE.value

    # Re-check authorization: revocation may have happened between create and now.
    if not authorization_service.is_authorized(auth, captured_version):
        operation.dispatch_status = DispatchStatus.BLOCKED_REVOKED.value
        operation.dispatch_error = (
            f"authorization revoked before dispatch (auth version now {auth.version}, "
            f"captured {captured_version})"
        )
        db.flush()
        return operation, DispatchStatus.BLOCKED_REVOKED.value

    # Dispatch to simulated receiver.
    try:
        external_receiver.create_receiver_operation(
            db,
            operation=operation,
            simulated_settle_seconds=simulated_settle_seconds,
            force_inconclusive=force_inconclusive,
        )
    except Exception as exc:  # noqa: BLE001 — simulated boundary
        operation.dispatch_status = DispatchStatus.CREATED.value
        operation.dispatch_error = f"receiver dispatch failed: {exc}"
        db.flush()
        raise DispatchError(f"Receiver dispatch failed: {exc}") from exc

    operation.dispatch_status = DispatchStatus.DISPATCHED.value
    operation.dispatched_at = utcnow()
    db.flush()
    return operation, DispatchStatus.DISPATCHED.value


def get_operation(db: Session, operation_uid: str) -> Operation:
    op = db.scalar(select(Operation).where(Operation.operation_uid == operation_uid))
    if op is None:
        raise DispatchError(f"Unknown operation_uid {operation_uid}")
    return op


def list_operations(db: Session) -> list[Operation]:
    return list(db.scalars(select(Operation).order_by(Operation.id)))