"""Health check endpoint evaluating application, database, Hindsight, and LLM readiness."""

import time
from datetime import datetime, timezone
from typing import Any, Dict
from fastapi import APIRouter, status

from backend.app.agent.llm_provider import check_llm_health
from backend.app.config import settings
from backend.app.database.session import check_db_health
from backend.app.memory.hindsight_service import hindsight_service

router = APIRouter(prefix="/health", tags=["Health"])

START_TIME = time.time()


@router.get(
    "",
    status_code=status.HTTP_200_OK,
    summary="Comprehensive system health and readiness check",
    response_description="Detailed operational health status of all core subsystems",
)
async def get_health() -> Dict[str, Any]:
    """Inspects all subsystems:

    - Application: Process status, uptime, environment, version
    - Database: Live connectivity and query execution latency
    - Hindsight: Live API readiness using official Hindsight client
    - LLM Provider: Configured provider credentials and readiness
    """
    uptime_seconds = round(time.time() - START_TIME, 2)

    # 1. Database live connectivity check
    db_result = await check_db_health()

    # 2. Hindsight memory server live connectivity check
    hindsight_result = await hindsight_service.check_health()

    # 3. LLM provider readiness check
    llm_result = check_llm_health()

    # 4. Determine overall system health state
    # - "unhealthy": Database is offline
    # - "degraded": Database is ok, but Hindsight or LLM provider is not ready
    # - "healthy": All subsystems operational
    if not db_result.get("connected", False):
        overall_status = "unhealthy"
    elif not hindsight_result.get("connected", False) or not llm_result.get("ready", False):
        overall_status = "degraded"
    else:
        overall_status = "healthy"

    return {
        "status": overall_status,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "version": "0.1.0",
        "environment": settings.ENVIRONMENT,
        "services": {
            "application": {
                "status": "healthy",
                "uptime_seconds": uptime_seconds,
                "environment": settings.ENVIRONMENT,
                "version": "0.1.0",
            },
            "database": db_result,
            "hindsight": hindsight_result,
            "llm": llm_result,
        },
    }
