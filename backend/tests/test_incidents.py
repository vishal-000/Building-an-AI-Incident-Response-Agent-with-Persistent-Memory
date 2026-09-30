"""Comprehensive test suite for Incident model and CRUD REST APIs."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_create_incident_success(client: AsyncClient):
    """Verifies successful incident creation with expected defaults and server-managed fields."""
    payload = {
        "title": "Database connection pool exhausted",
        "description": "PostgreSQL connection pool reached maximum capacity under peak checkout load.",
        "severity": "critical",
        "service": "checkout-service",
        "environment": "production",
        "logs": "FATAL: remaining connection slots are reserved for non-replication superuser connections",
        "symptoms": ["HTTP 500 spike", "Database latency > 5000ms", "Connection pool timeout"],
        "suspected_root_cause": "Connection pool size too low for incoming traffic",
        "runbook_id": "DB-CONNECTION-01",
    }
    response = await client.post("/api/v1/incidents", json=payload)
    assert response.status_code == 201
    data = response.json()

    assert "id" in data
    assert len(data["id"]) > 10
    assert data["title"] == payload["title"]
    assert data["severity"] == "critical"
    assert data["service"] == "checkout-service"
    assert data["environment"] == "production"
    assert data["status"] == "open"
    assert data["outcome"] == "pending"
    assert data["is_retained"] is False
    assert data["symptoms"] == payload["symptoms"]
    assert data["created_at"] is not None
    assert data["updated_at"] is not None
    assert data["resolved_at"] is None


@pytest.mark.asyncio
async def test_create_incident_missing_required_fields(client: AsyncClient):
    """Verifies that missing required fields (title, description, service) return 422."""
    # Missing service
    payload = {
        "title": "Payment gateway latency",
        "description": "High latency on payment requests",
    }
    response = await client.post("/api/v1/incidents", json=payload)
    assert response.status_code == 422

    # Missing title
    payload_no_title = {
        "description": "Missing title test",
        "service": "billing",
    }
    response2 = await client.post("/api/v1/incidents", json=payload_no_title)
    assert response2.status_code == 422


@pytest.mark.asyncio
async def test_create_incident_invalid_enums(client: AsyncClient):
    """Verifies that invalid severity or environment enum values return 422."""
    payload = {
        "title": "Invalid enum test",
        "description": "Testing rejection of invalid enums",
        "service": "auth-service",
        "severity": "catastrophic",  # Invalid severity
        "environment": "mars-cluster",  # Invalid environment
    }
    response = await client.post("/api/v1/incidents", json=payload)
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_retrieve_incident_by_id(client: AsyncClient):
    """Verifies retrieving an existing incident by ID."""
    create_payload = {
        "title": "Redis cluster node failover",
        "description": "Primary Redis node went down, failover triggered.",
        "severity": "high",
        "service": "cache-service",
        "environment": "production",
    }
    create_res = await client.post("/api/v1/incidents", json=create_payload)
    assert create_res.status_code == 201
    created_id = create_res.json()["id"]

    get_res = await client.get(f"/api/v1/incidents/{created_id}")
    assert get_res.status_code == 200
    retrieved = get_res.json()
    assert retrieved["id"] == created_id
    assert retrieved["title"] == create_payload["title"]
    assert retrieved["service"] == "cache-service"


@pytest.mark.asyncio
async def test_retrieve_nonexistent_incident_returns_404(client: AsyncClient):
    """Verifies that requesting a nonexistent incident ID returns HTTP 404."""
    response = await client.get("/api/v1/incidents/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404
    data = response.json()
    assert data["error"] is True
    assert "not found" in data["message"].lower()


@pytest.mark.asyncio
async def test_list_and_filter_incidents(client: AsyncClient):
    """Verifies listing incidents and filtering by status, severity, and service."""
    # Seed 3 distinct incidents
    inc1 = {
        "title": "DB Connection Timeout",
        "description": "Pool timeout on database",
        "severity": "critical",
        "service": "orders-db",
        "environment": "production",
    }
    inc2 = {
        "title": "High Memory in Worker",
        "description": "OOM killer risk in celery worker",
        "severity": "high",
        "service": "worker-service",
        "environment": "production",
    }
    inc3 = {
        "title": "Minor CSS Build Warning",
        "description": "Asset pipeline warning",
        "severity": "low",
        "service": "frontend-web",
        "environment": "staging",
    }

    r1 = await client.post("/api/v1/incidents", json=inc1)
    r2 = await client.post("/api/v1/incidents", json=inc2)
    r3 = await client.post("/api/v1/incidents", json=inc3)
    assert r1.status_code == 201 and r2.status_code == 201 and r3.status_code == 201

    # Update inc2 to investigating status
    inc2_id = r2.json()["id"]
    await client.patch(f"/api/v1/incidents/{inc2_id}", json={"status": "investigating"})

    # 1. List all
    all_res = await client.get("/api/v1/incidents")
    assert all_res.status_code == 200
    all_data = all_res.json()
    assert all_data["total"] >= 3
    assert len(all_data["items"]) >= 3

    # 2. Filter by status
    status_res = await client.get("/api/v1/incidents?status=investigating")
    assert status_res.status_code == 200
    status_data = status_res.json()
    assert all(item["status"] == "investigating" for item in status_data["items"])
    assert any(item["id"] == inc2_id for item in status_data["items"])

    # 3. Filter by severity
    crit_res = await client.get("/api/v1/incidents?severity=critical")
    assert crit_res.status_code == 200
    crit_data = crit_res.json()
    assert all(item["severity"] == "critical" for item in crit_data["items"])

    # 4. Filter by service substring
    svc_res = await client.get("/api/v1/incidents?service=worker")
    assert svc_res.status_code == 200
    svc_data = svc_res.json()
    assert any(item["service"] == "worker-service" for item in svc_data["items"])


@pytest.mark.asyncio
async def test_update_incident_and_resolve_lifecycle(client: AsyncClient):
    """Verifies updating incident attributes and automatic resolution timestamp management."""
    # Create incident
    create_res = await client.post(
        "/api/v1/incidents",
        json={
            "title": "Connection leak in payment service",
            "description": "Connections not returned to pool",
            "severity": "high",
            "service": "payment-service",
        },
    )
    inc_id = create_res.json()["id"]

    # 1. Update status to investigating and set confirmed root cause
    update1 = {
        "status": "investigating",
        "confirmed_root_cause": "Missing session.close() in worker task",
        "recommended_actions": [{"step": 1, "action": "Restart worker pool"}],
    }
    patch1_res = await client.patch(f"/api/v1/incidents/{inc_id}", json=update1)
    assert patch1_res.status_code == 200
    data1 = patch1_res.json()
    assert data1["status"] == "investigating"
    assert data1["confirmed_root_cause"] == update1["confirmed_root_cause"]
    assert len(data1["recommended_actions"]) == 1
    assert data1["resolved_at"] is None

    # 2. Resolve incident
    update2 = {
        "status": "resolved",
        "resolution": "Applied hotfix commit #a1b2c3d and restarted service",
        "outcome": "successful",
    }
    patch2_res = await client.patch(f"/api/v1/incidents/{inc_id}", json=update2)
    assert patch2_res.status_code == 200
    data2 = patch2_res.json()
    assert data2["status"] == "resolved"
    assert data2["outcome"] == "successful"
    assert data2["resolution"] == update2["resolution"]
    assert data2["resolved_at"] is not None  # Server automatically set resolution time


@pytest.mark.asyncio
async def test_update_nonexistent_incident_returns_404(client: AsyncClient):
    """Verifies that patching a nonexistent ID returns HTTP 404."""
    res = await client.patch(
        "/api/v1/incidents/00000000-0000-0000-0000-000000000000",
        json={"status": "resolved"},
    )
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_update_rejects_extra_fields(client: AsyncClient):
    """Verifies that attempting to inject forbidden fields like created_at in update fails with 422."""
    create_res = await client.post(
        "/api/v1/incidents",
        json={
            "title": "Strict schema test",
            "description": "Testing forbidden extra fields",
            "service": "api-gateway",
        },
    )
    inc_id = create_res.json()["id"]

    # Client tries to forge created_at
    forge_res = await client.patch(
        f"/api/v1/incidents/{inc_id}",
        json={"created_at": "2020-01-01T00:00:00Z"},
    )
    assert forge_res.status_code == 422
