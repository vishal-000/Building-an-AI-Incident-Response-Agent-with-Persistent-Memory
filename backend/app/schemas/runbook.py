"""Pydantic schemas for operational runbooks."""

from typing import List
from pydantic import BaseModel, ConfigDict, Field


class Runbook(BaseModel):
    """Standard operating procedure / runbook for operational incident remediation."""

    model_config = ConfigDict(from_attributes=True)

    id: str = Field(description="Unique runbook identifier (e.g. DB-CONNECTION-01)")
    title: str = Field(description="Human-readable runbook title")
    category: str = Field(description="Incident domain (database, memory, network, deployment)")
    symptoms: List[str] = Field(description="Typical symptoms indicating this runbook applies")
    diagnostic_checks: List[str] = Field(description="Non-destructive diagnostic verification commands/steps")
    remediation_steps: List[str] = Field(description="Recommended step-by-step remediation procedures")
    verification_checks: List[str] = Field(description="Post-action checks to confirm system recovery")
    risk_notes: str = Field(description="Safety warnings and human verification guardrails")
