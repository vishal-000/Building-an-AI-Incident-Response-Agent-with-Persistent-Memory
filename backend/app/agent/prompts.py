"""Prompts and instructions for structured AI incident investigation."""

import json
from typing import Any, Dict, List, Optional
from backend.app.memory.hindsight_service import RecalledExperience
from backend.app.schemas.runbook import Runbook

INVESTIGATION_SYSTEM_PROMPT = """You are an expert SRE / DevOps Incident Response Investigator assisting human engineers.
Your role is to analyze current production telemetry, evaluate historical organizational operational memory retrieved from Hindsight (when available), and generate a structured root-cause hypothesis and remediation plan.

CRITICAL ARCHITECTURAL RULES:
1. STRICT SEPARATION OF SOURCES:
   - "current": Observations derived directly from current incident error logs, stack traces, and symptoms.
   - "historical": Operational precedents recalled from Hindsight memory bank.
   You must NEVER confuse historical experience with current observations.

2. EVIDENCE, NOT ABSOLUTE TRUTH:
   - Historical memories provide empirical precedent, NOT guaranteed truth.
   - Formulate hypotheses such as: "Resembles historical incident X, where confirmed cause was Y."

3. NO FABRICATION:
   - Do NOT fabricate historical incident IDs. Only cite incident IDs that were explicitly provided in the Historical Context.
   - If no historical memories are provided (baseline mode), the 'historical_incidents' array MUST be empty [].

4. HUMAN VERIFICATION & SAFETY:
   - Never recommend unverified destructive production actions.
   - Every recommended action MUST include a specific verification check.

5. OUTPUT FORMAT:
   You must output ONLY a valid JSON object matching this schema:
   {
     "summary": "Concise executive overview of the incident",
     "likely_root_cause": "Hypothesized root cause synthesized from telemetry and evidence",
     "confidence": 0.85,  // float between 0.0 and 1.0
     "evidence": [
       {
         "source": "current",
         "description": "Log shows 'remaining connection slots are reserved'",
         "incident_id": null
       },
       {
         "source": "historical",
         "description": "Precedent from INC-104 confirmed pool exhaustion solved by pool resizing",
         "incident_id": "INC-104"
       }
     ],
     "historical_incidents": [
       {
         "incident_id": "INC-104",
         "title": "PostgreSQL connection pool exhausted",
         "relevance": "Identical error signature under high checkout load"
       }
     ],
     "recommended_actions": [
       {
         "step": "Check active database connections using pg_stat_activity",
         "verification": "Confirm whether connections exceed 90% threshold"
       }
     ],
     "runbook_id": "DB-CONNECTION-01",
     "risk_notes": "Do not kill connections without verifying transaction state"
   }
"""


def format_investigation_user_prompt(
    incident_data: Dict[str, Any],
    historical_memories: List[RecalledExperience],
    use_hindsight: bool,
    matched_runbook: Optional[Runbook] = None,
) -> str:
    """Formats prompt separating current observations from recalled historical operational experience."""
    # Current incident section
    prompt = f"=== CURRENT INCIDENT TELEMETRY ===\n"
    prompt += f"Incident ID: {incident_data.get('id')}\n"
    prompt += f"Title: {incident_data.get('title')}\n"
    prompt += f"Service: {incident_data.get('service')}\n"
    prompt += f"Environment: {incident_data.get('environment')}\n"
    prompt += f"Severity: {incident_data.get('severity')}\n"
    prompt += f"Symptoms: {', '.join(incident_data.get('symptoms', []))}\n"
    prompt += f"Raw Logs / Traces:\n{incident_data.get('logs') or 'No raw logs provided'}\n\n"

    # Historical context section
    if use_hindsight and historical_memories:
        prompt += f"=== RECALLED HISTORICAL EXPERIENCES (HINDSIGHT MEMORY) ===\n"
        prompt += (
            f"The following {len(historical_memories)} historical operational experiences were retrieved "
            f"from Hindsight agent memory. Evaluate them as empirical precedent:\n\n"
        )
        for idx, mem in enumerate(historical_memories, 1):
            score_str = f" (Similarity Score: {mem.score})" if mem.score is not None else ""
            prompt += f"--- Historical Memory #{idx} [ID: {mem.id}]{score_str} ---\n"
            prompt += f"{mem.text}\n\n"
    elif use_hindsight and not historical_memories:
        prompt += "=== RECALLED HISTORICAL EXPERIENCES (HINDSIGHT MEMORY) ===\n"
        prompt += "Hindsight memory recall completed, but no relevant past incidents were found in the memory bank.\n\n"
    else:
        prompt += "=== MEMORY MODE: DISABLED (BASELINE MODE) ===\n"
        prompt += "Do not use organizational memory. Perform a first-principles diagnosis based solely on current telemetry.\n\n"

    # Standard runbook candidate
    if matched_runbook:
        prompt += f"=== MATCHED STANDARD RUNBOOK CANDIDATE ===\n"
        prompt += f"Runbook ID: {matched_runbook.id} - {matched_runbook.title}\n"
        prompt += f"Remediation Steps:\n" + "\n".join([f"- {s}" for s in matched_runbook.remediation_steps]) + "\n"
        prompt += f"Verification Checks:\n" + "\n".join([f"- {v}" for v in matched_runbook.verification_checks]) + "\n"
        prompt += f"Risk Notes: {matched_runbook.risk_notes}\n\n"

    prompt += "Analyze the incident now and return the structured JSON report."
    return prompt
