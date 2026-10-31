"""Authorization service: grant, revoke, and version management.

Key guarantees:
- Every revoke increments the version (monotonic).
- Timestamps and reasons are persisted.
- Revocation is idempotent by version: re-revoking an already-revoked authorization
  does not increment the version again; it returns the existing revoked state.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Authorization, utcnow
from app.schemas import AuthorizationStatus


class AuthorizationError(Exception):
    """Raised on invalid authorization operations."""


def _get(db: Session, authorization_id: int) -> Authorization:
    auth = db.get(Authorization, authorization_id)
    if auth is None:
        raise AuthorizationError(f"Authorization {authorization_id} not found")
    return auth


def grant(db: Session, agent_id: str, resource: str) -> Authorization:
    """Create a new authorization with version=1."""
    auth = Authorization(
        agent_id=agent_id,
        resource=resource,
        status=AuthorizationStatus.GRANTED.value,
        version=1,
        granted_at=utcnow(),
    )
    db.add(auth)
    db.flush()
    return auth


def revoke(db: Session, authorization_id: int, reason: str) -> Authorization:
    """Revoke an authorization; idempotent if already revoked."""
    auth = _get(db, authorization_id)
    if auth.status == AuthorizationStatus.REVOKED.value:
        return auth
    auth.status = AuthorizationStatus.REVOKED.value
    auth.revoked_at = utcnow()
    auth.revocation_reason = reason
    auth.version += 1
    db.flush()
    return auth


def get_authorization(db: Session, authorization_id: int) -> Authorization:
    return _get(db, authorization_id)


def is_authorized(auth: Authorization, version_at_dispatch: int) -> bool:
    """Return True if the authorization is still valid *and* the version
    captured at dispatch time has not been superseded by revocation."""
    return (
        auth.status == AuthorizationStatus.GRANTED.value
        and auth.version == version_at_dispatch
    )


def list_authorizations(db: Session) -> list[Authorization]:
    return list(db.scalars(select(Authorization).order_by(Authorization.id)))