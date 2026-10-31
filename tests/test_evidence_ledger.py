"""Tests for the hash-chained evidence ledger."""

from __future__ import annotations

from sqlalchemy import select

from app import evidence_ledger
from app.models import EvidenceEvent


def test_append_events_chain_intact(db):
    evidence_ledger.append_event(
        db,
        event_type="AUTHORIZATION_GRANTED",
        subject_type="authorization",
        subject_id="1",
        payload={"authorization_id": 1},
    )
    evidence_ledger.append_event(
        db,
        event_type="OPERATION_DISPATCHED",
        subject_type="operation",
        subject_id="op-x",
        payload={"operation_uid": "op-x"},
    )

    intact, broken = evidence_ledger.verify_chain(db)
    assert intact is True
    assert broken is None

    events = evidence_ledger.list_events(db)
    assert len(events) == 2
    assert events[0].prev_hash == evidence_ledger.GENESIS_HASH
    assert events[1].prev_hash == events[0].event_hash


def test_tampering_breaks_chain(db):
    evidence_ledger.append_event(
        db,
        event_type="AUTHORIZATION_GRANTED",
        subject_type="authorization",
        subject_id="1",
        payload={"authorization_id": 1},
    )
    tampered = evidence_ledger.append_event(
        db,
        event_type="AUTHORIZATION_REVOKED",
        subject_type="authorization",
        subject_id="1",
        payload={"authorization_id": 1, "reason": "original"},
    )
    evidence_ledger.append_event(
        db,
        event_type="OPERATION_DISPATCHED",
        subject_type="operation",
        subject_id="op-y",
        payload={"operation_uid": "op-y"},
    )
    db.flush()

    # Tamper directly with the stored payload — no hash recomputation.
    stored = db.scalar(
        select(EvidenceEvent).where(EvidenceEvent.event_uid == tampered.event_uid)
    )
    stored.payload_json = '{"authorization_id":1,"reason":"forged"}'
    db.flush()

    intact, broken = evidence_ledger.verify_chain(db)
    assert intact is False
    assert broken is not None
    assert broken.event_uid == tampered.event_uid


def test_genesis_prev_hash_for_first_event(db):
    first = evidence_ledger.append_event(
        db,
        event_type="TEST",
        subject_type="test",
        subject_id="t1",
        payload={"n": 1},
    )
    assert first.prev_hash == "0" * 64