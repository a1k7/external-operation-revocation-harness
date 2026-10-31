"""Pydantic schemas for API contracts and internal DTOs."""

from __future__ import annotations

import datetime as dt
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


# ---------- Enums ----------

class AuthorizationStatus(str, Enum):
    GRANTED = "GRANTED"
    REVOKED = "REVOKED"


class DispatchStatus(str, Enum):
    CREATED = "CREATED"
    BLOCKED_REVOKED = "BLOCKED_REVOKED"
    DISPATCHED = "DISPATCHED"
    DUPLICATE = "DUPLICATE"


class VerifiedOutcome(str, Enum):
    CANCELLATION_REQUESTED = "CANCELLATION_REQUESTED"
    CANCELLATION_ACKNOWLEDGED = "CANCELLATION_ACKNOWLEDGED"
    CANCELLATION_CONFIRMED = "CANCELLATION_CONFIRMED"
    COMPLETION_CONFIRMED = "COMPLETION_CONFIRMED"
    OUTCOME_UNKNOWN = "OUTCOME_UNKNOWN"


# ---------- Authorization ----------

class GrantAuthorizationRequest(BaseModel):
    agent_id: str = Field(..., min_length=1, max_length=64)
    resource: str = Field(..., min_length=1, max_length=128)


class RevokeAuthorizationRequest(BaseModel):
    reason: str = Field(..., min_length=1, max_length=512)


class AuthorizationResponse(BaseModel):
    id: int
    agent_id: str
    resource: str
    status: AuthorizationStatus
    version: int
    granted_at: dt.datetime
    revoked_at: Optional[dt.datetime]
    revocation_reason: Optional[str]

    model_config = {"from_attributes": True}


# ---------- Dispatch ----------

class DispatchOperationRequest(BaseModel):
    authorization_id: int
    idempotency_key: str = Field(..., min_length=4, max_length=128)
    amount_cents: int = Field(..., gt=0)
    # Optional receiver flags for demonstration scenarios.
    force_inconclusive: bool = False
    simulated_settle_seconds: int = Field(default=60, ge=0)


class DispatchOperationResponse(BaseModel):
    operation_uid: str
    dispatch_status: DispatchStatus
    authorization_version_used: int
    dispatched_at: Optional[dt.datetime]
    receiver_ref: Optional[str]
    receiver_state: Optional[str]
    dispatch_error: Optional[str]


# ---------- Cancellation ----------

class RequestCancellationRequest(BaseModel):
    reason: str = Field(default="authorization revoked", max_length=512)


class CancellationResponse(BaseModel):
    operation_uid: str
    cancellation_requested: bool
    cancellation_acknowledged: bool
    receiver_state: str
    cancellation_rejected_reason: Optional[str]


# ---------- Verification ----------

class VerificationResponse(BaseModel):
    operation_uid: str
    verified_outcome: VerifiedOutcome
    receiver_state_observed: str
    receiver_ref: Optional[str]
    verified_at: dt.datetime
    detail: str


# ---------- Evidence ----------

class EvidenceEventResponse(BaseModel):
    event_uid: str
    event_type: str
    subject_type: str
    subject_id: str
    payload: dict[str, Any]
    prev_hash: str
    event_hash: str
    occurred_at: dt.datetime
    recorded_at: dt.datetime


class EvidenceChainStatus(BaseModel):
    total_events: int
    intact: bool
    broken_at_event_uid: Optional[str] = None


# ---------- Scenarios ----------

class ScenarioRunRequest(BaseModel):
    scenario: str = Field(..., description="One of scenario_1..scenario_7")


class ScenarioRunResponse(BaseModel):
    scenario: str
    title: str
    steps: list[dict[str, Any]]
    result: dict[str, Any]