"""Investigation orchestrator coordinating Hindsight recall, runbook matching, and AI reasoning."""

from typing import Optional
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.agent.llm_provider import BaseLLMProvider, get_llm_provider
from backend.app.database.models import IncidentStatus
from backend.app.logging_config import logger
from backend.app.memory.hindsight_service import RecalledExperience, hindsight_service
from backend.app.memory.memory_formatter import build_recall_query
from backend.app.schemas.investigation import InvestigationResponse
from backend.app.services.incident_service import incident_service
from backend.app.services.runbook_service import runbook_service


class InvestigationService:
    """Orchestrates end-to-end incident investigation workflows."""

    @staticmethod
    async def investigate_incident(
        session: AsyncSession,
        incident_id: str,
        use_hindsight: bool = True,
        llm_provider: Optional[BaseLLMProvider] = None,
    ) -> InvestigationResponse:
        """Executes a structured investigation for an incident.

        Supports two distinct modes:
        - WITH HINDSIGHT: Recalls historical precedents from Hindsight, synthesizes current telemetry against
          historical evidence, and recommends runbook + actions.
        - WITHOUT HINDSIGHT: Evaluates only current telemetry in stateless baseline mode.
        """
        # 1. Fetch incident record
        incident = await incident_service.get_incident(session, incident_id)
        if not incident:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Incident '{incident_id}' not found for investigation",
            )

        incident_dict = {
            "id": incident.id,
            "title": incident.title,
            "service": incident.service,
            "environment": incident.environment,
            "severity": incident.severity,
            "symptoms": incident.symptoms or [],
            "logs": incident.logs,
        }

        mode_str = "with_hindsight" if use_hindsight else "without_hindsight"
        logger.info(f"Starting investigation for incident {incident_id} (Mode: {mode_str})...")

        # 2. Hindsight Memory Recall (if enabled)
        historical_memories: list[RecalledExperience] = []
        hindsight_available = False

        if use_hindsight:
            query = build_recall_query(
                service=incident.service,
                environment=incident.environment,
                symptoms=incident.symptoms or [],
                logs=incident.logs,
                title=incident.title,
            )
            recall_result = await hindsight_service.recall_incident_experience(query)
            hindsight_available = recall_result.is_available
            historical_memories = recall_result.results
            logger.info(
                f"Hindsight recall returned {len(historical_memories)} items (Available: {hindsight_available})"
            )
        else:
            logger.info("Hindsight recall skipped (stateless baseline mode requested).")

        # 3. Deterministic Runbook Matching
        matched_runbook = runbook_service.match_runbook(
            service=incident.service,
            title=incident.title,
            symptoms=incident.symptoms or [],
            logs=incident.logs,
        )
        if matched_runbook:
            logger.info(f"Matched standard runbook: {matched_runbook.id} - '{matched_runbook.title}'")

        # 4. LLM Investigation Reasoning
        provider = llm_provider or get_llm_provider()
        provider_name = provider.__class__.__name__

        investigation_output = await provider.investigate(
            incident_data=incident_dict,
            historical_memories=historical_memories,
            use_hindsight=use_hindsight,
            matched_runbook=matched_runbook,
        )

        # 5. Persist diagnostic hypothesis and action recommendations to incident record
        if incident.status == IncidentStatus.OPEN.value:
            incident.status = IncidentStatus.INVESTIGATING.value

        incident.suspected_root_cause = investigation_output.likely_root_cause
        incident.recommended_actions = [
            action.model_dump() for action in investigation_output.recommended_actions
        ]
        if investigation_output.runbook_id:
            incident.runbook_id = investigation_output.runbook_id

        await session.flush()
        await session.refresh(incident)

        return InvestigationResponse(
            incident_id=incident.id,
            investigation_mode="with_hindsight" if use_hindsight else "without_hindsight",
            hindsight_available=hindsight_available,
            recalled_incidents_count=len(historical_memories),
            investigation=investigation_output,
            matched_runbook=matched_runbook.model_dump() if matched_runbook else None,
            provider_used=provider_name,
            details=(
                f"Investigation completed using {provider_name} in {mode_str} mode. "
                f"Confidence: {investigation_output.confidence:.2f}."
            ),
        )


investigation_service = InvestigationService()
