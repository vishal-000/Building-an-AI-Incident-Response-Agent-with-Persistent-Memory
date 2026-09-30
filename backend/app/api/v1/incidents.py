"""Incident management REST API endpoints."""

from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.database.session import get_db
from backend.app.schemas.incident import (
    IncidentCreate,
    IncidentListResponse,
    IncidentResolveRequest,
    IncidentResponse,
    IncidentRetainResponse,
    IncidentUpdate,
)
from backend.app.schemas.investigation import (
    InvestigationRequest,
    InvestigationResponse,
)
from backend.app.services.incident_service import incident_service

router = APIRouter(prefix="/incidents", tags=["Incidents"])


@router.post(
    "",
    response_model=IncidentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new incident",
)
async def create_incident(
    payload: IncidentCreate,
    db: AsyncSession = Depends(get_db),
):
    """Creates a new incident record in the database."""
    incident = await incident_service.create_incident(db, payload)
    return incident


@router.get(
    "",
    response_model=IncidentListResponse,
    status_code=status.HTTP_200_OK,
    summary="List incidents with filtering",
)
async def list_incidents(
    status: Optional[str] = Query(None, description="Filter by status (open, investigating, resolved, etc.)"),
    severity: Optional[str] = Query(None, description="Filter by severity (critical, high, medium, low)"),
    service: Optional[str] = Query(None, description="Filter by affected service name"),
    skip: int = Query(0, ge=0, description="Offset for pagination"),
    limit: int = Query(50, ge=1, le=100, description="Page limit"),
    db: AsyncSession = Depends(get_db),
):
    """Retrieves a list of incidents ordered by creation time, supporting filters."""
    items, total = await incident_service.list_incidents(
        session=db,
        status=status,
        severity=severity,
        service=service,
        skip=skip,
        limit=limit,
    )
    return {"items": items, "total": total}


@router.get(
    "/{incident_id}",
    response_model=IncidentResponse,
    status_code=status.HTTP_200_OK,
    summary="Get incident details by ID",
)
async def get_incident(
    incident_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Fetches full incident information by ID."""
    incident = await incident_service.get_incident(db, incident_id)
    if not incident:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Incident with ID '{incident_id}' not found",
        )
    return incident


@router.patch(
    "/{incident_id}",
    response_model=IncidentResponse,
    status_code=status.HTTP_200_OK,
    summary="Update incident attributes",
)
async def update_incident(
    incident_id: str,
    payload: IncidentUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Updates attributes of an existing incident.

    Server-managed timestamps cannot be modified directly.
    """
    incident = await incident_service.get_incident(db, incident_id)
    if not incident:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Incident with ID '{incident_id}' not found",
        )

    updated = await incident_service.update_incident(db, incident, payload)
    return updated


@router.post(
    "/{incident_id}/investigate",
    response_model=InvestigationResponse,
    status_code=status.HTTP_200_OK,
    summary="Trigger AI investigation for an incident",
)
async def investigate_incident(
    incident_id: str,
    payload: InvestigationRequest = InvestigationRequest(),
    db: AsyncSession = Depends(get_db),
):
    """Executes AI incident investigation.

    Supports two explicit operational modes:
    - use_hindsight=true: WITH HINDSIGHT MEMORY (retrieves past operational experience from Hindsight)
    - use_hindsight=false: WITHOUT HINDSIGHT MEMORY (stateless baseline troubleshooting)
    """
    from backend.app.agent.investigator import investigation_service

    result = await investigation_service.investigate_incident(
        session=db,
        incident_id=incident_id,
        use_hindsight=payload.use_hindsight,
    )
    return result


@router.post(
    "/{incident_id}/resolve",
    response_model=IncidentResponse,
    status_code=status.HTTP_200_OK,
    summary="Record human engineer confirmation and resolve incident",
)
async def resolve_incident(
    incident_id: str,
    payload: IncidentResolveRequest,
    db: AsyncSession = Depends(get_db),
):
    """Records human engineer confirmation of the verified root cause, resolution steps,

    applied runbook, and resolution outcome.
    """
    resolved_incident = await incident_service.resolve_incident(
        session=db,
        incident_id=incident_id,
        data=payload,
    )
    return resolved_incident


@router.post(
    "/{incident_id}/retain",
    response_model=IncidentRetainResponse,
    status_code=status.HTTP_200_OK,
    summary="Retain resolved operational incident experience into Hindsight memory",
)
async def retain_incident(
    incident_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Commits a confirmed, resolved incident's post-mortem experience into Hindsight agent memory.

    Enforces resolution prerequisites and guards against duplicate retention.
    """
    result = await incident_service.retain_incident(
        session=db,
        incident_id=incident_id,
    )
    return result
