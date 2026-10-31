"""Outcome verification engine.

Independently polls the simulated external receiver and classifies the
outcome into exactly one of five categories. It never infers cancellation
success from a mere cancellation request or acknowledgment.

Classifier mapping:

Receiver state           | cancel_requested | cancel_ack | forced_inconclusive | Verified outcome
-------------------------|------------------|------------|---------------------|----------------------------
COMPLETED                | *                | *          | *                   | COMPLETION_CONFIRMED
CANCELLED                | true             | true       | false               | CANCELLATION_CONFIRMED
INCONCLUSIVE             | *                | *          | true                | OUTCOME_UNKNOWN
ACK_PENDING              | true             | true       | false               | CANCELLATION_ACKNOWLEDGED
ACK_PENDING              | true             | false      | *                   | CANCELLATION_REQUESTED
ACK_PENDING              | false            | false      | *                   | OUTCOME_UNKNOWN
any other                | *                | *          | *                   | OUTCOME_UNKNOWN
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy.orm import Session

from app import external_receiver
from app.models import utcnow
from app.schemas import VerifiedOutcome


class VerificationError(Exception):
    """Raised when the engine cannot even reach the receiver."""


def _classify(snapshot: external_receiver.ReceiverSnapshot) -> tuple[VerifiedOutcome, str]:
    state = snapshot.state

    if state == "COMPLETED":
        return VerifiedOutcome.COMPLETION_CONFIRMED, "receiver reported terminal COMPLETED"

    if state == "CANCELLED" and snapshot.cancellation_acknowledged:
        return VerifiedOutcome.CANCELLATION_CONFIRMED, "receiver reported terminal CANCELLED"

    if state == "CANCELLED" and not snapshot.cancellation_acknowledged:
        # Defensive: a receiver cannot be cancelled without prior acknowledgment.
        return VerifiedOutcome.OUTCOME_UNKNOWN, "terminal CANCELLED without acknowledgment"

    if state == "INCONCLUSIVE":
        return VerifiedOutcome.OUTCOME_UNKNOWN, "receiver returned inconclusive response"

    if state == "ACK_PENDING":
        if snapshot.cancellation_requested and snapshot.cancellation_acknowledged:
            return (
                VerifiedOutcome.CANCELLATION_ACKNOWLEDGED,
                "cancellation acknowledged but receiver not yet terminal",
            )
        if snapshot.cancellation_requested and not snapshot.cancellation_acknowledged:
            return (
                VerifiedOutcome.CANCELLATION_REQUESTED,
                "cancellation requested; not yet acknowledged",
            )
        return VerifiedOutcome.OUTCOME_UNKNOWN, "no dispatch-side cancellation requested yet"

    return VerifiedOutcome.OUTCOME_UNKNOWN, f"unrecognised receiver state: {state}"


def verify_outcome(
    db: Session, operation_uid: str, *, now: dt.datetime | None = None
) -> tuple[VerifiedOutcome, external_receiver.ReceiverSnapshot, str, dt.datetime]:
    """Poll the receiver and classify the verified outcome.

    Returns (outcome, snapshot, detail, verified_at).
    """
    now = now or utcnow()
    try:
        snapshot = external_receiver.poll_receiver(db, operation_uid, now=now)
    except external_receiver.ReceiverError as exc:
        raise VerificationError(str(exc)) from exc

    outcome, detail = _classify(snapshot)
    return outcome, snapshot, detail, now