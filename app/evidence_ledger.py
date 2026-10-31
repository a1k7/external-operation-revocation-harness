"""Hash-chained evidence ledger.

Each event embeds the hash of the previous event, so tampering with any stored
event invalidates the chain from that point forward.

Hashing uses a canonical UTC ISO string so that the hash is stable across
reloads, regardless of whether SQLite returned the timestamp as naive or aware.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import HASH_CHAIN_PEPPER
from app.models import EvidenceEvent, utcnow

GENESIS_HASH = "0" * 64


class EvidenceError(Exception):
    """Raised on ledger integrity violations."""


def _canonical(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _canonical_iso(value: dt.datetime) -> str:
    """UTC ISO with explicit +00:00 suffix, regardless of input tz."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=dt.timezone.utc)
    return value.astimezone(dt.timezone.utc).isoformat()


def _compute_hash(
    *,
    prev_hash: str,
    event_uid: str,
    event_type: str,
    subject_type: str,
    subject_id: str,
    payload_json: str,
    occurred_at_iso: str,
) -> str:
    material = "|".join(
        [
            HASH_CHAIN_PEPPER,
            prev_hash,
            event_uid,
            event_type,
            subject_type,
            subject_id,
            payload_json,
            occurred_at_iso,
        ]
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def append_event(
    db: Session,
    *,
    event_type: str,
    subject_type: str,
    subject_id: str,
    payload: dict[str, Any],
    occurred_at: dt.datetime | None = None,
) -> EvidenceEvent:
    """Append a new event to the hash-chained ledger."""
    last = db.scalar(select(EvidenceEvent).order_by(EvidenceEvent.id.desc()).limit(1))
    prev_hash = last.event_hash if last is not None else GENESIS_HASH

    occurred_at = occurred_at or utcnow()
    occurred_iso = _canonical_iso(occurred_at)
    event_uid = uuid.uuid4().hex
    payload_json = _canonical(payload)

    event_hash = _compute_hash(
        prev_hash=prev_hash,
        event_uid=event_uid,
        event_type=event_type,
        subject_type=subject_type,
        subject_id=subject_id,
        payload_json=payload_json,
        occurred_at_iso=occurred_iso,
    )

    event = EvidenceEvent(
        event_uid=event_uid,
        event_type=event_type,
        subject_type=subject_type,
        subject_id=subject_id,
        payload_json=payload_json,
        prev_hash=prev_hash,
        event_hash=event_hash,
        occurred_at=occurred_at,
        recorded_at=utcnow(),
    )
    db.add(event)
    db.flush()
    return event


def verify_chain(db: Session) -> tuple[bool, EvidenceEvent | None]:
    """Recompute hashes; return (intact, first_broken_event)."""
    events = list(db.scalars(select(EvidenceEvent).order_by(EvidenceEvent.id)))
    prev = GENESIS_HASH
    for event in events:
        expected = _compute_hash(
            prev_hash=event.prev_hash,
            event_uid=event.event_uid,
            event_type=event.event_type,
            subject_type=event.subject_type,
            subject_id=event.subject_id,
            payload_json=event.payload_json,
            occurred_at_iso=_canonical_iso(event.occurred_at),
        )
        if event.prev_hash != prev or event.event_hash != expected:
            return False, event
        prev = event.event_hash
    return True, None


def list_events_for_subject(db: Session, subject_id: str) -> list[EvidenceEvent]:
    return list(
        db.scalars(
            select(EvidenceEvent)
            .where(EvidenceEvent.subject_id == subject_id)
            .order_by(EvidenceEvent.id)
        )
    )


def list_events(db: Session) -> list[EvidenceEvent]:
    return list(db.scalars(select(EvidenceEvent).order_by(EvidenceEvent.id)))