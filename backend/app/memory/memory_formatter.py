"""Deterministic formatter converting resolved incidents into operational agent memories."""

from typing import Dict, List, Optional, Tuple
from backend.app.database.models import Incident, IncidentOutcome


def validate_incident_for_retention(incident: Incident) -> Tuple[bool, Optional[str]]:
    """Validates that an incident possesses confirmed post-mortem details required for memory retention.

    Only well-documented, resolved incidents with verified root causes and resolutions
    are permitted into the Hindsight organizational memory bank.
    """
    if not incident.confirmed_root_cause or not incident.confirmed_root_cause.strip():
        return False, "Cannot retain incident: 'confirmed_root_cause' is missing or empty."

    if not incident.resolution or not incident.resolution.strip():
        return False, "Cannot retain incident: 'resolution' is missing or empty."

    outcome = str(incident.outcome).lower()
    if outcome == IncidentOutcome.PENDING.value or outcome == "pending":
        return False, "Cannot retain incident: resolution 'outcome' is still pending."

    return True, None


def format_incident_for_memory(incident: Incident) -> str:
    """Formats a resolved incident into a rich, structured natural-language operational memory text.

    Explicitly frames the text as a HISTORICAL INCIDENT EXPERIENCE to ensure future AI reasoning
    treats it as historical evidence rather than current ground truth.
    """
    symptoms_str = ", ".join(incident.symptoms) if incident.symptoms else "None recorded"
    logs_snippet = (
        incident.logs.strip()
        if incident.logs and incident.logs.strip()
        else "No raw error traces recorded"
    )

    # Derive high-level lesson learned
    lesson = (
        f"When '{incident.service}' in '{incident.environment}' presents symptoms [{symptoms_str}], "
        f"historical operational precedent established the confirmed root cause was '{incident.confirmed_root_cause}'. "
        f"Resolution followed runbook '{incident.runbook_id or 'ad-hoc'}' with outcome '{str(incident.outcome).upper()}': "
        f"{incident.resolution.strip()}."
    )

    return (
        f"[HISTORICAL INCIDENT EXPERIENCE RECORD]\n"
        f"Incident ID: {incident.id}\n"
        f"Title: {incident.title}\n"
        f"Service: {incident.service}\n"
        f"Environment: {incident.environment}\n"
        f"Severity: {str(incident.severity).upper()}\n\n"
        f"-- Historical Symptoms & Error Logs --\n"
        f"Observed Symptoms: {symptoms_str}\n"
        f"Error Logs / Signatures:\n{logs_snippet}\n\n"
        f"-- Root Cause Analysis --\n"
        f"Initial Suspected Root Cause: {incident.suspected_root_cause or 'Not specified during intake'}\n"
        f"CONFIRMED Root Cause: {incident.confirmed_root_cause.strip()}\n\n"
        f"-- Remediation & Runbook Outcome --\n"
        f"Runbook ID: {incident.runbook_id or 'None'}\n"
        f"Resolution Executed: {incident.resolution.strip()}\n"
        f"Outcome: {str(incident.outcome).upper()}\n\n"
        f"-- Operational Lessons Learned --\n"
        f"{lesson}\n\n"
        f"[OPERATIONAL CONTEXT NOTE]: This record represents past empirical evidence from incident {incident.id}. "
        f"It must be corroborated against current incident telemetry. Remediation requires human verification."
    )


def extract_incident_memory_metadata(incident: Incident) -> Dict[str, str]:
    """Builds a metadata dictionary for Hindsight indexing and temporal/entity tracking."""
    return {
        "incident_id": str(incident.id),
        "service": str(incident.service),
        "environment": str(incident.environment),
        "severity": str(incident.severity),
        "runbook_id": str(incident.runbook_id or ""),
        "outcome": str(incident.outcome),
        "type": "incident_experience",
    }


def build_recall_query(
    service: str,
    environment: str,
    symptoms: List[str],
    logs: Optional[str] = None,
    title: Optional[str] = None,
) -> str:
    """Builds a dense, semantically relevant search query for Hindsight multi-strategy recall."""
    parts = []
    if service:
        parts.append(service)
    if environment:
        parts.append(environment)
    if title:
        parts.append(title)
    if symptoms:
        parts.append(" ".join(symptoms))

    # Include significant log tokens (first 2 lines or up to 200 chars)
    if logs and logs.strip():
        first_lines = " ".join([line.strip() for line in logs.strip().splitlines()[:2] if line.strip()])
        if first_lines:
            parts.append(first_lines[:200])

    return " ".join(parts).strip()
