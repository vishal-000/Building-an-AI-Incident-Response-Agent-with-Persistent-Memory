"""Runbook directory and detail REST endpoints."""

from typing import List
from fastapi import APIRouter, HTTPException, status
from backend.app.schemas.runbook import Runbook
from backend.app.services.runbook_service import runbook_service

router = APIRouter(prefix="/runbooks", tags=["Runbooks"])


@router.get(
    "",
    response_model=List[Runbook],
    status_code=status.HTTP_200_OK,
    summary="List all standard operational runbooks",
)
async def list_runbooks():
    """Retrieves all standard operational runbooks available in the system."""
    return runbook_service.list_runbooks()


@router.get(
    "/{runbook_id}",
    response_model=Runbook,
    status_code=status.HTTP_200_OK,
    summary="Get runbook details by ID",
)
async def get_runbook(runbook_id: str):
    """Retrieves a specific runbook by identifier (e.g. DB-CONNECTION-01)."""
    rb = runbook_service.get_runbook(runbook_id)
    if not rb:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Runbook with ID '{runbook_id}' not found",
        )
    return rb
