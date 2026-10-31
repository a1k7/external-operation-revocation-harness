"""Tests for the authorization service."""

from __future__ import annotations

from sqlalchemy import select

from app import authorization_service
from app.models import Authorization


def test_grant_creates_version_1(db):
    auth = authorization_service.grant(db, agent_id="agent-a", resource="refund")
    db.flush()

    assert auth.status == "GRANTED"
    assert auth.version == 1
    assert auth.revoked_at is None
    assert auth.granted_at is not None


def test_revoke_sets_status_and_increments_version(db):
    auth = authorization_service.grant(db, agent_id="agent-b", resource="refund")
    db.flush()

    authorization_service.revoke(db, authorization_id=auth.id, reason="manual")

    assert auth.status == "REVOKED"
    assert auth.version == 2
    assert auth.revoked_at is not None


def test_revoke_is_idempotent(db):
    auth = authorization_service.grant(db, agent_id="agent-c", resource="refund")
    db.flush()

    authorization_service.revoke(db, authorization_id=auth.id, reason="first")
    first_revoked_at = auth.revoked_at
    first_version = auth.version

    authorization_service.revoke(db, authorization_id=auth.id, reason="second")

    assert auth.status == "REVOKED"
    assert auth.version == first_version
    assert auth.revoked_at == first_revoked_at
    assert auth.revocation_reason == "first"


def test_revoke_records_reason_and_timestamp(db):
    auth = authorization_service.grant(db, agent_id="agent-d", resource="refund")
    db.flush()

    authorization_service.revoke(
        db, authorization_id=auth.id, reason="policy violation"
    )

    stored = db.scalar(select(Authorization).where(Authorization.id == auth.id))
    assert stored.revocation_reason == "policy violation"
    assert stored.revoked_at is not None