"""Automated test suite for system health, database, Hindsight, and LLM readiness checks."""

import pytest
from httpx import AsyncClient
from unittest.mock import patch, AsyncMock


@pytest.mark.asyncio
async def test_root_endpoint(client: AsyncClient):
    """Tests the root endpoint returns 200 with service metadata and links."""
    response = await client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Incident Memory Agent API"
    assert data["version"] == "0.1.0"
    assert "health" in data
    assert "documentation" in data


@pytest.mark.asyncio
async def test_health_response_structure(client: AsyncClient):
    """Verifies that /api/v1/health returns the full required schema."""
    response = await client.get("/api/v1/health")
    assert response.status_code == 200
    data = response.json()

    # Core top-level fields
    assert "status" in data
    assert data["status"] in ["healthy", "degraded", "unhealthy"]
    assert "timestamp" in data
    assert "version" in data
    assert "environment" in data
    assert "services" in data

    services = data["services"]
    assert "application" in services
    assert "database" in services
    assert "hindsight" in services
    assert "llm" in services


@pytest.mark.asyncio
async def test_application_health(client: AsyncClient):
    """Verifies that the application process status reports healthy and records uptime."""
    response = await client.get("/api/v1/health")
    assert response.status_code == 200
    app_info = response.json()["services"]["application"]

    assert app_info["status"] == "healthy"
    assert isinstance(app_info["uptime_seconds"], (int, float))
    assert app_info["uptime_seconds"] >= 0
    assert app_info["version"] == "0.1.0"


@pytest.mark.asyncio
async def test_successful_database_health(client: AsyncClient):
    """Verifies that the database check succeeds against SQLite with measured latency."""
    response = await client.get("/api/v1/health")
    assert response.status_code == 200
    db_info = response.json()["services"]["database"]

    assert db_info["status"] == "connected"
    assert db_info["connected"] is True
    assert db_info["engine"] == "sqlite"
    assert isinstance(db_info["latency_ms"], (int, float))
    assert db_info["latency_ms"] >= 0


@pytest.mark.asyncio
async def test_database_failure_handling(client: AsyncClient):
    """Verifies that when database connectivity fails, status becomes 'unhealthy'."""
    mock_db_failure = {
        "status": "error",
        "connected": False,
        "engine": "sqlite",
        "latency_ms": 5.2,
        "error": "Connection refused / locked database",
        "details": "Database connection failed: Connection refused / locked database",
    }

    with patch("backend.app.api.v1.health.check_db_health", new_callable=AsyncMock) as mock_check:
        mock_check.return_value = mock_db_failure
        response = await client.get("/api/v1/health")
        assert response.status_code == 200
        data = response.json()

        assert data["status"] == "unhealthy"
        assert data["services"]["database"]["connected"] is False
        assert data["services"]["database"]["status"] == "error"


@pytest.mark.asyncio
async def test_hindsight_unavailable_state(client: AsyncClient):
    """Verifies that when the external Hindsight server is not reachable,

    it truthfully reports 'unavailable' rather than pretending to be connected.
    """
    # By default in isolated unit tests without a running Hindsight daemon on :8888,
    # the real client check will timeout or fail to connect.
    response = await client.get("/api/v1/health")
    assert response.status_code == 200
    hindsight_info = response.json()["services"]["hindsight"]

    assert hindsight_info["connected"] is False
    assert hindsight_info["status"] == "unavailable"
    assert hindsight_info["base_url"] == "http://localhost:8888"
    assert hindsight_info["bank_id"] == "test-incident-memory-bank"
    assert "unreachable" in hindsight_info["details"].lower() or "failed" in hindsight_info["details"].lower()


@pytest.mark.asyncio
async def test_hindsight_connected_state(client: AsyncClient):
    """Verifies that when Hindsight responds, the version and features are properly reported."""
    mock_hindsight_success = {
        "status": "connected",
        "connected": True,
        "base_url": "http://localhost:8888",
        "bank_id": "test-incident-memory-bank",
        "api_version": "0.10.2",
        "features": ["retain", "recall", "reflect"],
        "details": "Connected to Hindsight server (API v0.10.2)",
    }

    with patch("backend.app.memory.hindsight_service.hindsight_service.check_health", new_callable=AsyncMock) as mock_hs:
        mock_hs.return_value = mock_hindsight_success
        response = await client.get("/api/v1/health")
        assert response.status_code == 200
        hindsight_info = response.json()["services"]["hindsight"]

        assert hindsight_info["connected"] is True
        assert hindsight_info["status"] == "connected"
        assert hindsight_info["api_version"] == "0.10.2"


@pytest.mark.asyncio
async def test_llm_unconfigured_state(client: AsyncClient):
    """Verifies that an unconfigured provider (missing API key) is accurately identified."""
    with patch("backend.app.config.settings.LLM_PROVIDER", "openai"), \
         patch("backend.app.config.settings.OPENAI_API_KEY", None):
        response = await client.get("/api/v1/health")
        assert response.status_code == 200
        data = response.json()
        llm_info = data["services"]["llm"]

        assert llm_info["status"] == "unconfigured"
        assert llm_info["configured"] is False
        assert llm_info["ready"] is False
        assert data["status"] == "degraded"


@pytest.mark.asyncio
async def test_overall_health_when_all_healthy(client: AsyncClient):
    """Verifies that when DB, Hindsight, and LLM are all operational, overall status is 'healthy'."""
    mock_hindsight_success = {
        "status": "connected",
        "connected": True,
        "base_url": "http://localhost:8888",
        "bank_id": "test-incident-memory-bank",
        "api_version": "0.10.2",
        "features": ["retain", "recall"],
        "details": "Connected to Hindsight server",
    }

    with patch("backend.app.memory.hindsight_service.hindsight_service.check_health", new_callable=AsyncMock) as mock_hs:
        mock_hs.return_value = mock_hindsight_success
        # Default test env uses LLM_PROVIDER=mock (ready=True) and SQLite in-memory (connected=True)
        response = await client.get("/api/v1/health")
        assert response.status_code == 200
        data = response.json()

        assert data["status"] == "healthy"
        assert data["services"]["database"]["status"] == "connected"
        assert data["services"]["hindsight"]["status"] == "connected"
        assert data["services"]["llm"]["status"] == "mock_mode"
