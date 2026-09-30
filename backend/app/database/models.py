"""SQLAlchemy ORM models for Incident Memory Agent."""

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from sqlalchemy import Boolean, DateTime, String, Text, JSON
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.database.session import Base


class IncidentSeverity(str, Enum):
    """Severity levels for incidents."""
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class IncidentEnvironment(str, Enum):
    """Deployment environments."""
    PRODUCTION = "production"
    STAGING = "staging"
    DEVELOPMENT = "development"


class IncidentStatus(str, Enum):
    """Lifecycle statuses for incidents."""
    OPEN = "open"
    INVESTIGATING = "investigating"
    MITIGATED = "mitigated"
    RESOLVED = "resolved"
    CLOSED = "closed"


class IncidentOutcome(str, Enum):
    """Resolution outcome assessment."""
    PENDING = "pending"
    SUCCESSFUL = "successful"
    PARTIALLY_SUCCESSFUL = "partially_successful"
    UNSUCCESSFUL = "unsuccessful"


class Incident(Base):
    """SQLAlchemy model representing a production incident and its operational lifecycle."""

    __tablename__ = "incidents"

    # Primary key identifier (UUID string)
    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        index=True,
    )

    # Core metadata
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[str] = mapped_column(
        String(30),
        default=IncidentSeverity.MEDIUM.value,
        index=True,
        nullable=False,
    )
    service: Mapped[str] = mapped_column(String(100), index=True, nullable=False)
    environment: Mapped[str] = mapped_column(
        String(50),
        default=IncidentEnvironment.PRODUCTION.value,
        index=True,
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(50),
        default=IncidentStatus.OPEN.value,
        index=True,
        nullable=False,
    )

    # Telemetry and observations
    logs: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    symptoms: Mapped[List[str]] = mapped_column(
        JSON,
        default=list,
        nullable=False,
    )

    # Diagnostic and root cause analysis
    suspected_root_cause: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    confirmed_root_cause: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Action recommendations and remediation
    recommended_actions: Mapped[List[Dict[str, Any]]] = mapped_column(
        JSON,
        default=list,
        nullable=False,
    )
    resolution: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    runbook_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, index=True)
    outcome: Mapped[str] = mapped_column(
        String(50),
        default=IncidentOutcome.PENDING.value,
        index=True,
        nullable=False,
    )

    # Memory state tracking
    is_retained: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        index=True,
        nullable=False,
    )

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    resolved_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
