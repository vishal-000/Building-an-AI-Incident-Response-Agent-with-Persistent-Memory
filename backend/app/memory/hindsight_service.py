"""Official Hindsight Agent Memory service integration implementing RETAIN and RECALL."""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
from hindsight_client import Hindsight

from backend.app.config import settings
from backend.app.database.models import Incident
from backend.app.logging_config import logger
from backend.app.memory.memory_formatter import (
    extract_incident_memory_metadata,
    format_incident_for_memory,
    validate_incident_for_retention,
)


class RecalledExperience(BaseModel):
    """Structured representation of a single operational memory retrieved from Hindsight.

    Explicitly models historical evidence without fabricating non-existent scores or metadata.
    """

    id: str = Field(description="Memory unit identifier from Hindsight")
    text: str = Field(description="Historical memory text and operational context")
    memory_type: str = Field(default="experience", description="Memory type classification (e.g. experience, observation, fact)")
    score: Optional[float] = Field(default=None, description="Actual retrieval relevance score if provided by Hindsight; None if not provided")
    metadata: Optional[Dict[str, Any]] = Field(default=None, description="Indexed metadata attributes")
    context: Optional[str] = Field(default=None, description="Contextual anchor if provided by Hindsight")
    tags: Optional[List[str]] = Field(default=None, description="Tags associated with the memory unit")


class RecallExperienceResult(BaseModel):
    """Result envelope for a Hindsight recall query."""

    success: bool
    is_available: bool
    bank_id: str
    query: str
    results: List[RecalledExperience] = Field(default_factory=list)
    total_results: int = 0
    error: Optional[str] = None
    details: str


class RetainExperienceResult(BaseModel):
    """Result envelope for an operational experience retention operation."""

    success: bool
    bank_id: str
    items_count: int = 0
    operation_id: Optional[str] = None
    error: Optional[str] = None
    details: str


class HindsightService:
    """Wrapper around the official Hindsight SDK for memory operations and health monitoring."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        bank_id: Optional[str] = None,
    ):
        self.base_url = (base_url or settings.HINDSIGHT_BASE_URL).rstrip("/")
        self.api_key = api_key or settings.HINDSIGHT_API_KEY
        self.bank_id = bank_id or settings.HINDSIGHT_BANK_ID

    def _create_client(self, timeout: float = 5.0) -> Hindsight:
        """Instantiates the official Hindsight client with specified timeout."""
        return Hindsight(
            base_url=self.base_url,
            api_key=self.api_key,
            timeout=timeout,
        )

    async def check_health(self) -> Dict[str, Any]:
        """Performs a live readiness check against the Hindsight server using aget_version().

        Accurately reports whether the external Hindsight instance is reachable.
        Does NOT pretend Hindsight is healthy simply because the URL is set.
        """
        client = self._create_client(timeout=2.0)
        try:
            version_info = await client.aget_version()
            api_version = getattr(version_info, "api_version", "unknown")
            features = getattr(version_info, "features", [])
            return {
                "status": "connected",
                "connected": True,
                "base_url": self.base_url,
                "bank_id": self.bank_id,
                "api_version": api_version,
                "features": features,
                "details": f"Connected to Hindsight server (API v{api_version})",
            }
        except Exception as exc:
            err_msg = str(exc) or type(exc).__name__
            logger.warning(
                f"Hindsight server health check failed at {self.base_url}: {err_msg}"
            )
            return {
                "status": "unavailable",
                "connected": False,
                "base_url": self.base_url,
                "bank_id": self.bank_id,
                "api_version": None,
                "error": type(exc).__name__,
                "details": (
                    f"Hindsight memory server unreachable at {self.base_url} ({type(exc).__name__}). "
                    "Agent will operate in baseline mode until memory service is active."
                ),
            }
        finally:
            try:
                await client.aclose()
            except Exception:
                pass

    async def retain_incident_experience(
        self,
        incident: Incident,
    ) -> RetainExperienceResult:
        """Stores a resolved incident's post-mortem operational lessons into Hindsight memory.

        Enforces strict resolution validation:
        - Confirmed root cause must be present
        - Resolution must be present
        - Outcome must not be pending

        Sets incident.is_retained = True ONLY on confirmed successful retention.
        Never pretends an incident was retained if the service call fails.
        """
        # 1. Enforce resolution data completeness
        is_valid, validation_error = validate_incident_for_retention(incident)
        if not is_valid:
            logger.warning(f"Retention precondition rejected for incident {incident.id}: {validation_error}")
            return RetainExperienceResult(
                success=False,
                bank_id=self.bank_id,
                items_count=0,
                error="precondition_failed",
                details=validation_error or "Incident data incomplete for retention.",
            )

        # 2. Format operational memory content and metadata
        memory_content = format_incident_for_memory(incident)
        metadata = extract_incident_memory_metadata(incident)
        tags = [
            "incident",
            str(incident.service),
            str(incident.environment),
            str(incident.severity),
        ]
        if incident.runbook_id:
            tags.append(str(incident.runbook_id))

        client = self._create_client(timeout=10.0)
        try:
            logger.info(
                f"Executing Hindsight RETAIN for incident {incident.id} into bank '{self.bank_id}'..."
            )
            # Invoke official Hindsight SDK aretain
            retain_resp = await client.aretain(
                bank_id=self.bank_id,
                content=memory_content,
                metadata=metadata,
                tags=tags,
            )

            if getattr(retain_resp, "success", False):
                # Update incident state in local database
                incident.is_retained = True
                logger.info(
                    f"Successfully retained incident {incident.id} in Hindsight bank '{self.bank_id}' "
                    f"(items: {retain_resp.items_count}, op: {retain_resp.operation_id})"
                )
                return RetainExperienceResult(
                    success=True,
                    bank_id=self.bank_id,
                    items_count=retain_resp.items_count,
                    operation_id=retain_resp.operation_id,
                    details="Operational incident experience successfully retained in Hindsight.",
                )
            else:
                incident.is_retained = False
                logger.error(f"Hindsight aretain returned failure for incident {incident.id}")
                return RetainExperienceResult(
                    success=False,
                    bank_id=self.bank_id,
                    items_count=0,
                    error="hindsight_retain_unsuccessful",
                    details="Hindsight server did not acknowledge successful memory retention.",
                )

        except Exception as exc:
            incident.is_retained = False
            err_type = type(exc).__name__
            logger.error(
                f"Hindsight retention call failed for incident {incident.id} at {self.base_url}: {exc}"
            )
            return RetainExperienceResult(
                success=False,
                bank_id=self.bank_id,
                items_count=0,
                error=err_type,
                details=f"Hindsight retention failed ({err_type}): {exc}",
            )
        finally:
            try:
                await client.aclose()
            except Exception:
                pass

    async def recall_incident_experience(
        self,
        query: str,
        max_tokens: int = 4096,
    ) -> RecallExperienceResult:
        """Retrieves relevant historical operational memories from Hindsight using multi-strategy search.

        Returns authentic recall results without fabricating scores, IDs, or synthetic memories.
        If Hindsight is unreachable, returns success=False and is_available=False.
        """
        if not query or not query.strip():
            return RecallExperienceResult(
                success=True,
                is_available=True,
                bank_id=self.bank_id,
                query="",
                results=[],
                total_results=0,
                details="Empty recall query; no memories requested.",
            )

        client = self._create_client(timeout=10.0)
        try:
            logger.info(f"Executing Hindsight RECALL against bank '{self.bank_id}' with query: '{query[:100]}...'")
            recall_resp = await client.arecall(
                bank_id=self.bank_id,
                query=query.strip(),
                max_tokens=max_tokens,
            )

            recalled_items: List[RecalledExperience] = []
            raw_results = getattr(recall_resp, "results", []) or []

            for item in raw_results:
                # Safely extract score only if provided by Hindsight
                score_val: Optional[float] = None
                raw_scores = getattr(item, "scores", None)
                if raw_scores is not None:
                    if hasattr(raw_scores, "final"):
                        score_val = raw_scores.final
                    elif isinstance(raw_scores, dict):
                        score_val = raw_scores.get("final")

                recalled_items.append(
                    RecalledExperience(
                        id=str(getattr(item, "id", "")),
                        text=str(getattr(item, "text", "")),
                        memory_type=str(getattr(item, "type", "experience")),
                        score=score_val,
                        metadata=getattr(item, "metadata", None),
                        context=getattr(item, "context", None),
                        tags=getattr(item, "tags", None),
                    )
                )

            logger.info(
                f"Hindsight recall completed: {len(recalled_items)} historical memories retrieved from '{self.bank_id}'"
            )
            return RecallExperienceResult(
                success=True,
                is_available=True,
                bank_id=self.bank_id,
                query=query,
                results=recalled_items,
                total_results=len(recalled_items),
                details=f"Retrieved {len(recalled_items)} historical experiences from Hindsight.",
            )

        except Exception as exc:
            err_type = type(exc).__name__
            logger.warning(f"Hindsight recall failed at {self.base_url} ({err_type}): {exc}")
            return RecallExperienceResult(
                success=False,
                is_available=False,
                bank_id=self.bank_id,
                query=query,
                results=[],
                total_results=0,
                error=err_type,
                details=f"Hindsight memory recall unavailable ({err_type}): {exc}",
            )
        finally:
            try:
                await client.aclose()
            except Exception:
                pass


# Global singleton service instance
hindsight_service = HindsightService()
