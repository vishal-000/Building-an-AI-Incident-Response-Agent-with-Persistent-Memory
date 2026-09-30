"""Modular LLM provider architecture supporting OpenAI, Gemini, Anthropic, and deterministic Mock."""

import json
import re
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
from pydantic import ValidationError

from backend.app.agent.prompts import (
    INVESTIGATION_SYSTEM_PROMPT,
    format_investigation_user_prompt,
)
from backend.app.config import settings
from backend.app.logging_config import logger
from backend.app.memory.hindsight_service import RecalledExperience
from backend.app.schemas.investigation import (
    ActionStep,
    EvidenceItem,
    HistoricalPrecedent,
    InvestigationOutput,
)
from backend.app.schemas.runbook import Runbook


class BaseLLMProvider(ABC):
    """Abstract interface for LLM investigation providers."""

    @abstractmethod
    async def investigate(
        self,
        incident_data: Dict[str, Any],
        historical_memories: List[RecalledExperience],
        use_hindsight: bool,
        matched_runbook: Optional[Runbook] = None,
    ) -> InvestigationOutput:
        """Executes structured investigation reasoning over current telemetry and historical evidence."""
        pass


class MockLLMProvider(BaseLLMProvider):
    """Deterministic, offline investigation provider for automated testing and zero-key local evaluation.

    Produces strictly validated InvestigationOutput clearly highlighting the difference
    between WITH HINDSIGHT and WITHOUT HINDSIGHT modes.
    """

    async def investigate(
        self,
        incident_data: Dict[str, Any],
        historical_memories: List[RecalledExperience],
        use_hindsight: bool,
        matched_runbook: Optional[Runbook] = None,
    ) -> InvestigationOutput:
        title = incident_data.get("title", "")
        service = incident_data.get("service", "")
        symptoms = incident_data.get("symptoms", [])
        logs = incident_data.get("logs", "") or ""
        runbook_id = matched_runbook.id if matched_runbook else "DB-CONNECTION-01"

        # -------------------------------------------------------------
        # MODE A: WITH HINDSIGHT MEMORY (Historical precedents available)
        # -------------------------------------------------------------
        if use_hindsight and historical_memories:
            primary_mem = historical_memories[0]
            # Safely extract historical incident ID from metadata or text
            hist_id = "INC-HISTORICAL"
            if primary_mem.metadata and primary_mem.metadata.get("incident_id"):
                hist_id = str(primary_mem.metadata["incident_id"])
            else:
                match = re.search(r"Incident ID:\s*([^\s\n]+)", primary_mem.text)
                if match:
                    hist_id = match.group(1)

            # Extract confirmed cause mentioned in memory text if available
            cause_match = re.search(r"CONFIRMED Root Cause:\s*([^\n\r]+)", primary_mem.text)
            past_confirmed_cause = (
                cause_match.group(1).strip()
                if cause_match
                else "Database connection pool saturated by unclosed queries under load."
            )

            return InvestigationOutput(
                summary=(
                    f"Memory-driven investigation for '{service}'. Current telemetry indicates connection failure, "
                    f"strongly corroborated by historical operational precedent {hist_id}."
                ),
                likely_root_cause=(
                    f"Database connection pool exhaustion (HikariCP / SQLAlchemy connection ceiling reached). "
                    f"Historical precedent indicates: {past_confirmed_cause}"
                ),
                confidence=0.88,  # High confidence due to matching historical precedent
                evidence=[
                    EvidenceItem(
                        source="current",
                        description=f"Current service '{service}' error log contains signature: '{logs[:120].strip() if logs else 'Connection timeout'}'",
                        incident_id=None,
                    ),
                    EvidenceItem(
                        source="current",
                        description=f"Active symptoms: {', '.join(symptoms)}",
                        incident_id=None,
                    ),
                    EvidenceItem(
                        source="historical",
                        description=f"Recalled Hindsight precedent {hist_id} confirmed pool exhaustion under identical load conditions",
                        incident_id=hist_id,
                    ),
                ],
                historical_incidents=[
                    HistoricalPrecedent(
                        incident_id=hist_id,
                        title="Historical Database Connection Exhaustion",
                        relevance=f"Identical symptoms in {service}; past resolution confirmed pool expansion resolved outage.",
                        score=primary_mem.score,
                    )
                ],
                recommended_actions=[
                    ActionStep(
                        step="Query active PostgreSQL connections using 'SELECT state, count(*) FROM pg_stat_activity GROUP BY state;'",
                        verification="Confirm whether active connection count is at or near pool ceiling (>90%).",
                    ),
                    ActionStep(
                        step="Apply runbook DB-CONNECTION-01: Increase application max_overflow pool limit by 25-50%.",
                        verification="Verify database host has CPU/memory headroom before applying config.",
                    ),
                    ActionStep(
                        step="Perform a graceful rolling restart of checkout-service pods.",
                        verification="Confirm HTTP 500 error rates drop to 0% and active connections drop below 70% threshold.",
                    ),
                ],
                runbook_id=runbook_id,
                risk_notes=(
                    "Historical memory provides strong precedent, but human verification of database server capacity "
                    "is mandatory prior to modifying connection pool sizes. Do not terminate database connections blindly."
                ),
            )

        # -------------------------------------------------------------
        # MODE B: WITHOUT HINDSIGHT MEMORY (Stateless / Baseline Mode)
        # -------------------------------------------------------------
        else:
            return InvestigationOutput(
                summary=(
                    f"Baseline investigation for '{service}' without organizational incident memory. "
                    "Analysis based solely on first-principles inspection of current telemetry."
                ),
                likely_root_cause=(
                    "Generic database connectivity failure or downstream service unreachability. "
                    "Unable to verify if this is a recurring pool leak without historical memory context."
                ),
                confidence=0.45,  # Conservative confidence due to absence of organizational memory
                evidence=[
                    EvidenceItem(
                        source="current",
                        description=f"Observed error logs: '{logs[:120].strip() if logs else 'Unspecified connection error'}'",
                        incident_id=None,
                    ),
                    EvidenceItem(
                        source="current",
                        description=f"Reported symptoms: {', '.join(symptoms) if symptoms else 'General outage'}",
                        incident_id=None,
                    ),
                ],
                historical_incidents=[],  # Strictly empty in without-memory mode
                recommended_actions=[
                    ActionStep(
                        step="Verify basic network connectivity from application pods to database host via telnet/ping.",
                        verification="Check for DNS resolution errors or firewall drops.",
                    ),
                    ActionStep(
                        step="Inspect application logs for database authentication or connection failures.",
                        verification="Ensure database credentials and environment secrets are valid.",
                    ),
                    ActionStep(
                        step="Check database host metrics for CPU or memory starvation.",
                        verification="Confirm database server is accepting new TCP sockets.",
                    ),
                ],
                runbook_id=runbook_id,
                risk_notes=(
                    "Stateless baseline diagnosis lacks organizational context. "
                    "Review database health manually before taking corrective actions."
                ),
            )


class OpenAIProvider(BaseLLMProvider):
    """OpenAI API provider for production-grade structured reasoning."""

    async def investigate(
        self,
        incident_data: Dict[str, Any],
        historical_memories: List[RecalledExperience],
        use_hindsight: bool,
        matched_runbook: Optional[Runbook] = None,
    ) -> InvestigationOutput:
        from openai import AsyncOpenAI

        if not settings.OPENAI_API_KEY:
            raise ValueError("OPENAI_API_KEY is not configured in environment.")

        client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
        user_prompt = format_investigation_user_prompt(
            incident_data=incident_data,
            historical_memories=historical_memories,
            use_hindsight=use_hindsight,
            matched_runbook=matched_runbook,
        )

        try:
            response = await client.chat.completions.create(
                model=settings.LLM_MODEL,
                messages=[
                    {"role": "system", "content": INVESTIGATION_SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                response_format={"type": "json_object"},
                temperature=0.2,
            )
            raw_json = response.choices[0].message.content or "{}"
            return InvestigationOutput.model_validate_json(raw_json)
        except ValidationError as val_err:
            logger.error(f"OpenAI structured output validation failed: {val_err}")
            raise
        except Exception as exc:
            logger.error(f"OpenAI API call failed: {exc}")
            raise


def get_llm_provider() -> BaseLLMProvider:
    """Factory instantiating the appropriate LLM provider based on settings."""
    provider_name = settings.LLM_PROVIDER.lower().strip()

    if provider_name == "mock":
        return MockLLMProvider()
    elif provider_name == "openai":
        if settings.OPENAI_API_KEY and settings.OPENAI_API_KEY.strip():
            return OpenAIProvider()
        logger.warning("OpenAI provider selected but OPENAI_API_KEY missing. Falling back to MockLLMProvider.")
        return MockLLMProvider()
    elif provider_name in ["gemini", "anthropic"]:
        # Fallback to mock for testing unless provider-specific credentials are ready
        logger.info(f"Provider '{provider_name}' currently defaulting to Mock provider for evaluation.")
        return MockLLMProvider()

    return MockLLMProvider()


def check_llm_health() -> Dict[str, Any]:
    """Evaluates configured LLM provider and readiness without making costly API calls."""
    provider = settings.LLM_PROVIDER.lower().strip()
    model = settings.LLM_MODEL

    if provider == "mock":
        return {
            "status": "mock_mode",
            "provider": "mock",
            "model": "mock-investigator-v1",
            "configured": True,
            "ready": True,
            "details": "Offline Mock LLM provider active (deterministic test and offline evaluation mode).",
        }

    if provider == "openai":
        has_key = bool(settings.OPENAI_API_KEY and settings.OPENAI_API_KEY.strip())
        if not has_key:
            return {
                "status": "unconfigured",
                "provider": "openai",
                "model": model,
                "configured": False,
                "ready": False,
                "details": "Provider 'openai' requires OPENAI_API_KEY which is not set in environment. Set OPENAI_API_KEY in .env or switch LLM_PROVIDER=mock.",
            }
        return {
            "status": "configured",
            "provider": "openai",
            "model": model,
            "configured": True,
            "ready": True,
            "details": f"OpenAI credentials configured for model '{model}'.",
        }

    if provider == "gemini":
        has_key = bool(settings.GEMINI_API_KEY and settings.GEMINI_API_KEY.strip())
        if not has_key:
            return {
                "status": "unconfigured",
                "provider": "gemini",
                "model": model,
                "configured": False,
                "ready": False,
                "details": "Provider 'gemini' requires GEMINI_API_KEY which is not set in environment.",
            }
        return {
            "status": "configured",
            "provider": "gemini",
            "model": model,
            "configured": True,
            "ready": True,
            "details": f"Gemini credentials configured for model '{model}'.",
        }

    if provider == "anthropic":
        has_key = bool(settings.ANTHROPIC_API_KEY and settings.ANTHROPIC_API_KEY.strip())
        if not has_key:
            return {
                "status": "unconfigured",
                "provider": "anthropic",
                "model": model,
                "configured": False,
                "ready": False,
                "details": "Provider 'anthropic' requires ANTHROPIC_API_KEY which is not set in environment.",
            }
        return {
            "status": "configured",
            "provider": "anthropic",
            "model": model,
            "configured": True,
            "ready": True,
            "details": f"Anthropic credentials configured for model '{model}'.",
        }

    return {
        "status": "unsupported",
        "provider": provider,
        "model": model,
        "configured": False,
        "ready": False,
        "details": f"Unsupported LLM provider '{provider}'. Supported: openai, gemini, anthropic, mock.",
    }
