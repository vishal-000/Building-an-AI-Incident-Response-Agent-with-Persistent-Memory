"""Pydantic schemas for incident creation, updates, and responses."""

from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.app.database.models import (
    IncidentEnvironment,
    IncidentOutcome,
    IncidentSeverity,
    IncidentStatus,
)


class IncidentBase(BaseModel):
    """Shared core attributes for incidents."""

    title: str = Field(..., min_length=3, max_length=255, description="Brief incident title")
    description: str = Field(..., min_length=5, description="Detailed problem description")
    severity: IncidentSeverity = Field(
        default=IncidentSeverity.MEDIUM,
        description="Severity level: critical, high, medium, low",
    )
    service: str = Field(..., min_length=1, max_length=100, description="Affected service name")
    environment: IncidentEnvironment = Field(
        default=IncidentEnvironment.PRODUCTION,
        description="Environment: production, staging, development",
    )
    logs: Optional[str] = Field(default=None, description="Raw error traces or application logs")
    symptoms: List[str] = Field(
        default_factory=list,
        description="Key observed symptoms (e.g. ['Connection timeout', 'High latency'])",
    )


class IncidentCreate(IncidentBase):
    """Payload schema for registering a new incident."""

    suspected_root_cause: Optional[str] = Field(
        default=None,
        description="Initial hypothesis for root cause if available",
    )
    runbook_id: Optional[str] = Field(
        default=None,
        description="Associated runbook identifier if already identified",
    )


class IncidentUpdate(BaseModel):
    """Payload schema for updating an incident.

    Server-managed timestamps (created_at, updated_at, resolved_at) cannot be
    arbitrarily overwritten by client payloads.
    """

    model_config = ConfigDict(extra="forbid")

    title: Optional[str] = Field(default=None, min_length=3, max_length=255)
    description: Optional[str] = Field(default=None, min_length=5)
    severity: Optional[IncidentSeverity] = None
    service: Optional[str] = Field(default=None, min_length=1, max_length=100)
    environment: Optional[IncidentEnvironment] = None
    status: Optional[IncidentStatus] = None
    logs: Optional[str] = None
    symptoms: Optional[List[str]] = None
    suspected_root_cause: Optional[str] = None
    confirmed_root_cause: Optional[str] = None
    recommended_actions: Optional[List[Dict[str, Any]]] = None
    resolution: Optional[str] = None
    runbook_id: Optional[str] = None
    outcome: Optional[IncidentOutcome] = None
    is_retained: Optional[bool] = None


class IncidentResponse(IncidentBase):
    """Complete incident entity returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    status: IncidentStatus
    suspected_root_cause: Optional[str] = None
    confirmed_root_cause: Optional[str] = None
    recommended_actions: List[Dict[str, Any]] = Field(default_factory=list)
    resolution: Optional[str] = None
    runbook_id: Optional[str] = None
    outcome: IncidentOutcome
    is_retained: bool
    created_at: datetime
    resolved_at: Optional[datetime] = None
    updated_at: datetime


class IncidentListResponse(BaseModel):
    """Paginated or filtered list of incidents with count metadata."""

    items: List[IncidentResponse]
    total: int


class IncidentResolveRequest(BaseModel):
    """Payload representing explicit human confirmation of root cause and resolution."""

    model_config = ConfigDict(extra="forbid")

    confirmed_root_cause: str = Field(
        ...,
        min_length=3,
        description="Human-confirmed post-mortem root cause",
    )
    resolution: str = Field(
        ...,
        min_length=3,
        description="Actual operational remediation executed",
    )
    outcome: IncidentOutcome = Field(
        default=IncidentOutcome.SUCCESSFUL,
        description="Remediation efficacy: successful, partially_successful, unsuccessful",
    )
    runbook_id: Optional[str] = Field(
        default=None,
        description="Standard runbook applied if applicable (e.g. DB-CONNECTION-01)",
    )

    @field_validator("outcome")
    @classmethod
    def validate_outcome_not_pending(cls, v: IncidentOutcome) -> IncidentOutcome:
        if v == IncidentOutcome.PENDING:
            raise ValueError("Resolution outcome cannot be 'pending'. Must be 'successful', 'partially_successful', or 'unsuccessful'.")
        return v


class IncidentRetainResponse(BaseModel):
    """API response for an operational memory retention request into Hindsight."""

    incident_id: str
    success: bool
    already_retained: bool = False
    bank_id: str
    items_count: int = 0
    operation_id: Optional[str] = None
    error: Optional[str] = None
    details: str

