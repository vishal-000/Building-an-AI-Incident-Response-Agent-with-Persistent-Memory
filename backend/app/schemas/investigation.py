"""Pydantic validation schemas for AI incident investigation and structured outputs."""

from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field


class EvidenceItem(BaseModel):
    """Specific piece of evidence supporting the investigation hypothesis."""

    source: Literal["current", "historical"] = Field(
        description="Source of the evidence: 'current' telemetry or 'historical' Hindsight memory"
    )
    description: str = Field(description="Concrete observation, log excerpt, or historical precedent")
    incident_id: Optional[str] = Field(
        default=None,
        description="Referenced historical incident ID if source is 'historical'",
    )


class HistoricalPrecedent(BaseModel):
    """Historical incident cited from Hindsight memory as relevant precedent."""

    incident_id: str = Field(description="Identifier of the historical incident")
    title: str = Field(description="Historical incident title")
    relevance: str = Field(description="Explanation of how this historical case informs current diagnosis")
    score: Optional[float] = Field(default=None, description="Hindsight similarity/retrieval score if available")


class ActionStep(BaseModel):
    """Recommended remediation step requiring human verification before execution."""

    step: str = Field(description="Detailed operational recommendation")
    verification: str = Field(description="Pre/post verification check to confirm safety and efficacy")


class InvestigationOutput(BaseModel):
    """Structured AI investigation report with strict probability bounds and evidence attribution."""

    model_config = ConfigDict(extra="forbid")

    summary: str = Field(description="Executive summary of the incident investigation")
    likely_root_cause: str = Field(description="Hypothesized root cause synthesized from telemetry and memory")
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="Confidence score bounded between 0.0 (unclear) and 1.0 (certain)",
    )
    evidence: List[EvidenceItem] = Field(
        min_length=1,
        description="List of concrete current and historical evidence items",
    )
    historical_incidents: List[HistoricalPrecedent] = Field(
        default_factory=list,
        description="Historical incidents from Hindsight cited as precedent",
    )
    recommended_actions: List[ActionStep] = Field(
        min_length=1,
        description="Actionable remediation steps with verification checks",
    )
    runbook_id: Optional[str] = Field(
        default=None,
        description="Identifier of the recommended standard runbook",
    )
    risk_notes: Optional[str] = Field(
        default=None,
        description="Critical risk guardrails and human verification requirements",
    )


class InvestigationRequest(BaseModel):
    """Payload to initiate an AI incident investigation."""

    use_hindsight: bool = Field(
        default=True,
        description="If True, queries Hindsight agent memory for historical context; if False, runs stateless baseline",
    )


class InvestigationResponse(BaseModel):
    """Comprehensive API response for an incident investigation."""

    incident_id: str
    investigation_mode: Literal["with_hindsight", "without_hindsight"]
    hindsight_available: bool
    recalled_incidents_count: int
    investigation: InvestigationOutput
    matched_runbook: Optional[Dict[str, Any]] = None
    provider_used: str
    details: str
