"""Dedicated CRUD service managing incident persistence and state transitions."""

from datetime import datetime, timezone
from typing import List, Optional, Tuple
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.database.models import Incident, IncidentStatus
from backend.app.logging_config import logger
from backend.app.schemas.incident import (
    IncidentCreate,
    IncidentResolveRequest,
    IncidentRetainResponse,
    IncidentUpdate,
)


class IncidentService:
    """Service layer encapsulating all database interactions for incidents."""

    @staticmethod
    async def create_incident(session: AsyncSession, data: IncidentCreate) -> Incident:
        """Creates and persists a new incident record."""
        incident = Incident(
            title=data.title,
            description=data.description,
            severity=data.severity.value if hasattr(data.severity, "value") else str(data.severity),
            service=data.service,
            environment=data.environment.value if hasattr(data.environment, "value") else str(data.environment),
            status=IncidentStatus.OPEN.value,
            logs=data.logs,
            symptoms=data.symptoms or [],
            suspected_root_cause=data.suspected_root_cause,
            runbook_id=data.runbook_id,
            recommended_actions=[],
            outcome="pending",
            is_retained=False,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        session.add(incident)
        await session.flush()
        await session.refresh(incident)
        logger.info(f"Incident created: {incident.id} - '{incident.title}' (Service: {incident.service})")
        return incident

    @staticmethod
    async def get_incident(session: AsyncSession, incident_id: str) -> Optional[Incident]:
        """Retrieves a single incident by unique ID."""
        stmt = select(Incident).where(Incident.id == incident_id)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    async def list_incidents(
        session: AsyncSession,
        status: Optional[str] = None,
        severity: Optional[str] = None,
        service: Optional[str] = None,
        skip: int = 0,
        limit: int = 100,
    ) -> Tuple[List[Incident], int]:
        """Lists incidents with optional filtering by status, severity, or service."""
        base_stmt = select(Incident)

        if status:
            base_stmt = base_stmt.where(Incident.status == status.lower())
        if severity:
            base_stmt = base_stmt.where(Incident.severity == severity.lower())
        if service:
            base_stmt = base_stmt.where(Incident.service.ilike(f"%{service}%"))

        # Compute total count matching filter
        count_stmt = select(func.count()).select_from(base_stmt.subquery())
        count_result = await session.execute(count_stmt)
        total = count_result.scalar_one()

        # Fetch paginated items ordered newest first
        items_stmt = base_stmt.order_by(Incident.created_at.desc()).offset(skip).limit(limit)
        items_result = await session.execute(items_stmt)
        items = list(items_result.scalars().all())

        return items, total

    @staticmethod
    async def update_incident(
        session: AsyncSession,
        incident: Incident,
        data: IncidentUpdate,
    ) -> Incident:
        """Updates attributes of an existing incident and manages timestamp transitions."""
        update_data = data.model_dump(exclude_unset=True)

        for key, value in update_data.items():
            if value is not None:
                # Convert enums to their primitive string value for database storage
                val_to_set = value.value if hasattr(value, "value") else value
                setattr(incident, key, val_to_set)

        # Automatic lifecycle timestamp management
        if "status" in update_data:
            new_status = update_data["status"]
            status_val = new_status.value if hasattr(new_status, "value") else str(new_status)
            if status_val in [IncidentStatus.RESOLVED.value, IncidentStatus.CLOSED.value]:
                if incident.resolved_at is None:
                    incident.resolved_at = datetime.now(timezone.utc)
            elif status_val in [IncidentStatus.OPEN.value, IncidentStatus.INVESTIGATING.value]:
                # If incident is reopened, clear resolution timestamp
                incident.resolved_at = None

        incident.updated_at = datetime.now(timezone.utc)
        await session.flush()
        await session.refresh(incident)
        logger.info(f"Incident updated: {incident.id} (Status: {incident.status}, Retained: {incident.is_retained})")
        return incident

    @staticmethod
    async def resolve_incident(
        session: AsyncSession,
        incident_id: str,
        data: IncidentResolveRequest,
    ) -> Incident:
        """Records explicit human engineer verification of root cause, resolution, and outcome."""
        from fastapi import HTTPException, status
        from backend.app.services.runbook_service import runbook_service

        incident = await IncidentService.get_incident(session, incident_id)
        if not incident:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Incident with ID '{incident_id}' not found",
            )

        # Validate runbook_id if supplied
        if data.runbook_id:
            rb = runbook_service.get_runbook(data.runbook_id)
            if not rb:
                raise HTTPException(
                    status_code=422,
                    detail=f"Unknown runbook_id '{data.runbook_id}'. Must be a registered operational runbook.",
                )
            incident.runbook_id = data.runbook_id.strip().upper()

        # Update confirmed human post-mortem fields
        incident.confirmed_root_cause = data.confirmed_root_cause.strip()
        incident.resolution = data.resolution.strip()
        incident.outcome = data.outcome.value if hasattr(data.outcome, "value") else str(data.outcome)
        incident.status = IncidentStatus.RESOLVED.value
        incident.resolved_at = datetime.now(timezone.utc)
        incident.updated_at = datetime.now(timezone.utc)

        await session.flush()
        await session.refresh(incident)
        logger.info(
            f"Incident {incident.id} marked RESOLVED by engineer confirmation (Outcome: {incident.outcome}, Runbook: {incident.runbook_id})"
        )
        return incident

    @staticmethod
    async def retain_incident(
        session: AsyncSession,
        incident_id: str,
    ) -> IncidentRetainResponse:
        """Stores a resolved incident's post-mortem operational lessons into Hindsight memory.

        Enforces resolution state prerequisites and protects against duplicate retention.
        """
        from fastapi import HTTPException, status
        from backend.app.config import settings
        from backend.app.memory.hindsight_service import hindsight_service

        incident = await IncidentService.get_incident(session, incident_id)
        if not incident:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Incident with ID '{incident_id}' not found",
            )

        # 1. Idempotency check: prevent duplicate retention
        if incident.is_retained:
            logger.info(f"Incident {incident_id} is already retained in Hindsight. Skipping duplicate retention.")
            return IncidentRetainResponse(
                incident_id=incident.id,
                success=True,
                already_retained=True,
                bank_id=settings.HINDSIGHT_BANK_ID,
                items_count=1,
                details="Incident experience is already retained in Hindsight memory bank. Skipping duplicate retention.",
            )

        # 2. Enforce resolved lifecycle state
        if incident.status not in [IncidentStatus.RESOLVED.value, IncidentStatus.CLOSED.value] or not incident.resolved_at:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Incident {incident_id} has status '{incident.status}'. "
                    "Only incidents confirmed as RESOLVED can be retained into organizational memory."
                ),
            )

        # 3. Call Hindsight retention service
        hindsight_result = await hindsight_service.retain_incident_experience(incident)

        if hindsight_result.success:
            incident.is_retained = True
            await session.flush()
            await session.refresh(incident)
            logger.info(f"Incident {incident_id} successfully retained in Hindsight memory bank '{settings.HINDSIGHT_BANK_ID}'.")
            return IncidentRetainResponse(
                incident_id=incident.id,
                success=True,
                already_retained=False,
                bank_id=hindsight_result.bank_id,
                items_count=hindsight_result.items_count,
                operation_id=hindsight_result.operation_id,
                details=hindsight_result.details,
            )
        else:
            incident.is_retained = False
            await session.flush()
            await session.refresh(incident)
            logger.warning(f"Incident {incident_id} retention failed: {hindsight_result.details}")
            return IncidentRetainResponse(
                incident_id=incident.id,
                success=False,
                already_retained=False,
                bank_id=hindsight_result.bank_id,
                items_count=0,
                error=hindsight_result.error,
                details=hindsight_result.details,
            )


incident_service = IncidentService()

