"""API v1 master router aggregating sub-routers."""

from fastapi import APIRouter
from backend.app.api.v1.health import router as health_router
from backend.app.api.v1.incidents import router as incidents_router
from backend.app.api.v1.runbooks import router as runbooks_router

api_v1_router = APIRouter(prefix="/api/v1")

# Mount core routes
api_v1_router.include_router(health_router)
api_v1_router.include_router(incidents_router)
api_v1_router.include_router(runbooks_router)
