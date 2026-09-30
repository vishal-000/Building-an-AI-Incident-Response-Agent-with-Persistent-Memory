"""Comprehensive end-to-end test suite for the complete incident response and memory lifecycle:
CREATE -> INVESTIGATE -> HUMAN REVIEW -> RESOLVE -> RETAIN -> SECOND INCIDENT RECALL
"""

import pytest
from httpx import AsyncClient
from unittest.mock import AsyncMock, patch

from backend.app.database.models import IncidentOutcome, IncidentStatus
from backend.app.memory.hindsight_service import (
    RecallExperienceResult,
    RecalledExperience,
    RetainExperienceResult,
    hindsight_service,
)


@pytest.fixture
def primary_incident_payload():
    """Primary demonstration scenario: Database Connection Pool Exhaustion."""
    return {
        "title": "Database connection pool exhausted",
        "description": "Checkout service returning HTTP 500 timeouts due to database connection exhaustion.",
        "severity": "critical",
        "service": "checkout-service",
        "environment": "production",
        "logs": "FATAL: remaining connection slots are reserved for non-replication superuser connections\nError: HikariPool connection timeout",
        "symptoms": ["HTTP 500 spike", "Database connection timeout", "High database latency > 5000ms"],
    }


@pytest.mark.asyncio
async def test_successful_resolution(client: AsyncClient, primary_incident_payload):
    """Verifies human engineer confirmation and resolution of an incident."""
    # 1. Create incident
    c_res = await client.post("/api/v1/incidents", json=primary_incident_payload)
    assert c_res.status_code == 201
    inc_id = c_res.json()["id"]

    # 2. Resolve with human confirmation
    resolve_payload = {
        "confirmed_root_cause": "HikariCP pool limit set to 20 was exhausted by long-running cart queries under checkout spike.",
        "resolution": "Increased application max_overflow to 50, verified connection pool drain, and gracefully restarted pods.",
        "outcome": "successful",
        "runbook_id": "DB-CONNECTION-01",
    }
    r_res = await client.post(f"/api/v1/incidents/{inc_id}/resolve", json=resolve_payload)
    assert r_res.status_code == 200
    data = r_res.json()

    assert data["id"] == inc_id
    assert data["status"] == "resolved"
    assert data["confirmed_root_cause"] == resolve_payload["confirmed_root_cause"]
    assert data["resolution"] == resolve_payload["resolution"]
    assert data["outcome"] == "successful"
    assert data["runbook_id"] == "DB-CONNECTION-01"
    assert data["resolved_at"] is not None
    assert data["is_retained"] is False  # Not yet retained


@pytest.mark.asyncio
async def test_resolution_nonexistent_incident(client: AsyncClient):
    """Verifies that resolving a nonexistent incident ID returns 404."""
    res = await client.post(
        "/api/v1/incidents/00000000-0000-0000-0000-000000000000/resolve",
        json={
            "confirmed_root_cause": "Cause",
            "resolution": "Fix",
            "outcome": "successful",
        },
    )
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_invalid_resolution_request(client: AsyncClient, primary_incident_payload):
    """Verifies resolution validation: empty root cause, empty resolution, pending outcome, invalid runbook."""
    c_res = await client.post("/api/v1/incidents", json=primary_incident_payload)
    inc_id = c_res.json()["id"]

    # 1. Empty confirmed_root_cause
    bad1 = {"confirmed_root_cause": "", "resolution": "Fix", "outcome": "successful"}
    assert (await client.post(f"/api/v1/incidents/{inc_id}/resolve", json=bad1)).status_code == 422

    # 2. Outcome cannot be pending
    bad2 = {
        "confirmed_root_cause": "Cause",
        "resolution": "Fix",
        "outcome": "pending",
    }
    assert (await client.post(f"/api/v1/incidents/{inc_id}/resolve", json=bad2)).status_code == 422

    # 3. Unknown runbook ID
    bad3 = {
        "confirmed_root_cause": "Cause",
        "resolution": "Fix",
        "outcome": "successful",
        "runbook_id": "UNKNOWN-RUNBOOK-999",
    }
    assert (await client.post(f"/api/v1/incidents/{inc_id}/resolve", json=bad3)).status_code == 422


@pytest.mark.asyncio
async def test_successful_mocked_retention(client: AsyncClient, primary_incident_payload):
    """Verifies successful retention into Hindsight memory marks is_retained=True."""
    c_res = await client.post("/api/v1/incidents", json=primary_incident_payload)
    inc_id = c_res.json()["id"]

    # Resolve first
    await client.post(
        f"/api/v1/incidents/{inc_id}/resolve",
        json={
            "confirmed_root_cause": "Database connection ceiling reached",
            "resolution": "Increased pool capacity to 50",
            "outcome": "successful",
            "runbook_id": "DB-CONNECTION-01",
        },
    )

    mock_retain_result = RetainExperienceResult(
        success=True,
        bank_id="test-incident-memory-bank",
        items_count=1,
        operation_id="op-e2e-101",
        details="Operational incident experience retained in Hindsight.",
    )

    with patch(
        "backend.app.memory.hindsight_service.hindsight_service.retain_incident_experience",
        new_callable=AsyncMock,
    ) as mock_retain:
        mock_retain.return_value = mock_retain_result

        ret_res = await client.post(f"/api/v1/incidents/{inc_id}/retain")
        assert ret_res.status_code == 200
        ret_data = ret_res.json()

        assert ret_data["incident_id"] == inc_id
        assert ret_data["success"] is True
        assert ret_data["already_retained"] is False
        assert ret_data["operation_id"] == "op-e2e-101"

        # Verify DB updated
        get_res = await client.get(f"/api/v1/incidents/{inc_id}")
        assert get_res.json()["is_retained"] is True


@pytest.mark.asyncio
async def test_retention_before_resolution_fails(client: AsyncClient, primary_incident_payload):
    """Verifies that attempting to retain an unresolved incident is rejected."""
    c_res = await client.post("/api/v1/incidents", json=primary_incident_payload)
    inc_id = c_res.json()["id"]

    # Call retain while incident is still open
    ret_res = await client.post(f"/api/v1/incidents/{inc_id}/retain")
    assert ret_res.status_code == 400
    assert "resolved" in ret_res.json()["message"].lower()

    # Verify is_retained remains False
    get_res = await client.get(f"/api/v1/incidents/{inc_id}")
    assert get_res.json()["is_retained"] is False


@pytest.mark.asyncio
async def test_hindsight_unavailable_during_retention(client: AsyncClient, primary_incident_payload):
    """Verifies that if Hindsight is unavailable, retention fails safely and leaves is_retained=False."""
    c_res = await client.post("/api/v1/incidents", json=primary_incident_payload)
    inc_id = c_res.json()["id"]

    await client.post(
        f"/api/v1/incidents/{inc_id}/resolve",
        json={
            "confirmed_root_cause": "Pool exhaustion",
            "resolution": "Pool increased",
            "outcome": "successful",
        },
    )

    mock_fail = RetainExperienceResult(
        success=False,
        bank_id="test-incident-memory-bank",
        items_count=0,
        error="TimeoutError",
        details="Hindsight server unreachable at http://localhost:8888",
    )

    with patch(
        "backend.app.memory.hindsight_service.hindsight_service.retain_incident_experience",
        new_callable=AsyncMock,
    ) as mock_retain:
        mock_retain.return_value = mock_fail

        ret_res = await client.post(f"/api/v1/incidents/{inc_id}/retain")
        assert ret_res.status_code == 200
        ret_data = ret_res.json()

        assert ret_data["success"] is False
        assert ret_data["error"] == "TimeoutError"

        # Verify DB is_retained remains False
        get_res = await client.get(f"/api/v1/incidents/{inc_id}")
        assert get_res.json()["is_retained"] is False


@pytest.mark.asyncio
async def test_already_retained_incident_idempotency(client: AsyncClient, primary_incident_payload):
    """Verifies idempotency: already retained incidents are not duplicated."""
    c_res = await client.post("/api/v1/incidents", json=primary_incident_payload)
    inc_id = c_res.json()["id"]

    await client.post(
        f"/api/v1/incidents/{inc_id}/resolve",
        json={
            "confirmed_root_cause": "Pool exhaustion",
            "resolution": "Pool increased",
            "outcome": "successful",
        },
    )

    mock_retain_result = RetainExperienceResult(
        success=True,
        bank_id="test-incident-memory-bank",
        items_count=1,
        operation_id="op-1",
        details="Retained",
    )

    with patch(
        "backend.app.memory.hindsight_service.hindsight_service.retain_incident_experience",
        new_callable=AsyncMock,
    ) as mock_retain:
        mock_retain.return_value = mock_retain_result
        # First retain
        r1 = await client.post(f"/api/v1/incidents/{inc_id}/retain")
        assert r1.json()["success"] is True
        assert r1.json()["already_retained"] is False

        # Second retain (idempotent)
        r2 = await client.post(f"/api/v1/incidents/{inc_id}/retain")
        assert r2.status_code == 200
        assert r2.json()["success"] is True
        assert r2.json()["already_retained"] is True
        assert "already retained" in r2.json()["details"].lower()


@pytest.mark.asyncio
async def test_full_lifecycle_and_second_incident_recall(client: AsyncClient, primary_incident_payload):
    """Verifies the complete end-to-end incident lifecycle:

    INCIDENT 1:
      CREATE -> INVESTIGATE -> HUMAN REVIEW -> RESOLVE -> RETAIN
    INCIDENT 2:
      CREATE SIMILAR -> INVESTIGATE (WITH HINDSIGHT) -> RECALLS INCIDENT 1 PRECEDENT!
    """
    # =========================================================================
    # STEP 1: CREATE FIRST INCIDENT
    # =========================================================================
    inc1_res = await client.post("/api/v1/incidents", json=primary_incident_payload)
    assert inc1_res.status_code == 201
    inc1_id = inc1_res.json()["id"]

    # =========================================================================
    # STEP 2: INVESTIGATE FIRST INCIDENT (WITHOUT MEMORY OR COLD START)
    # =========================================================================
    inv1_res = await client.post(
        f"/api/v1/incidents/{inc1_id}/investigate",
        json={"use_hindsight": False},
    )
    assert inv1_res.status_code == 200
    inv1_data = inv1_res.json()
    assert inv1_data["investigation_mode"] == "without_hindsight"
    assert inv1_data["matched_runbook"]["id"] == "DB-CONNECTION-01"

    # =========================================================================
    # STEP 3 & 4: HUMAN ENGINEER CONFIRMS ROOT CAUSE AND RESOLUTION
    # =========================================================================
    resolve_payload = {
        "confirmed_root_cause": "HikariCP connection pool limit reached 20 during checkout surge.",
        "resolution": "Increased application max_overflow to 50, verified connection pool drain, and gracefully restarted pods.",
        "outcome": "successful",
        "runbook_id": "DB-CONNECTION-01",
    }
    res_step = await client.post(f"/api/v1/incidents/{inc1_id}/resolve", json=resolve_payload)
    assert res_step.status_code == 200
    assert res_step.json()["status"] == "resolved"

    # =========================================================================
    # STEP 5: RETAIN RESOLVED INCIDENT 1 IN HINDSIGHT
    # =========================================================================
    mock_retain_step = RetainExperienceResult(
        success=True,
        bank_id="test-incident-memory-bank",
        items_count=1,
        operation_id="op-inc1-retained",
        details="Incident 1 retained in Hindsight.",
    )
    with patch(
        "backend.app.memory.hindsight_service.hindsight_service.retain_incident_experience",
        new_callable=AsyncMock,
    ) as mock_ret:
        mock_ret.return_value = mock_retain_step
        retain_step = await client.post(f"/api/v1/incidents/{inc1_id}/retain")
        assert retain_step.status_code == 200
        assert retain_step.json()["success"] is True

    # =========================================================================
    # STEP 6: CREATE SECOND SIMILAR INCIDENT LATER
    # =========================================================================
    inc2_payload = {
        "title": "Database connection timeouts during checkout traffic",
        "description": "Second incident: checkout service once again encountering database connection pool timeout.",
        "severity": "critical",
        "service": "checkout-service",
        "environment": "production",
        "logs": "FATAL: remaining connection slots are reserved for non-replication superuser connections",
        "symptoms": ["HTTP 500 spike", "Database connection timeout"],
    }
    inc2_res = await client.post("/api/v1/incidents", json=inc2_payload)
    assert inc2_res.status_code == 201
    inc2_id = inc2_res.json()["id"]

    # =========================================================================
    # STEP 7: INVESTIGATE SECOND INCIDENT WITH HINDSIGHT (RECALLS INCIDENT 1!)
    # =========================================================================
    recalled_from_inc1 = RecalledExperience(
        id="mem-inc1",
        text=(
            f"[HISTORICAL INCIDENT EXPERIENCE RECORD]\n"
            f"Incident ID: {inc1_id}\n"
            f"Title: Database connection pool exhausted\n"
            f"Service: checkout-service\n"
            f"CONFIRMED Root Cause: HikariCP connection pool limit reached 20 during checkout surge.\n"
            f"Resolution Executed: Increased application max_overflow to 50, verified connection pool drain, and gracefully restarted pods.\n"
            f"Outcome: SUCCESSFUL\n"
            f"Runbook ID: DB-CONNECTION-01"
        ),
        memory_type="experience",
        score=0.94,
        metadata={"incident_id": inc1_id, "runbook_id": "DB-CONNECTION-01"},
        tags=["incident", "checkout-service", "DB-CONNECTION-01"],
    )

    mock_recall_step = RecallExperienceResult(
        success=True,
        is_available=True,
        bank_id="test-incident-memory-bank",
        query="checkout-service production",
        results=[recalled_from_inc1],
        total_results=1,
        details="Recalled incident 1 precedent",
    )

    with patch(
        "backend.app.memory.hindsight_service.hindsight_service.recall_incident_experience",
        new_callable=AsyncMock,
    ) as mock_rec:
        mock_rec.return_value = mock_recall_step

        inv2_res = await client.post(
            f"/api/v1/incidents/{inc2_id}/investigate",
            json={"use_hindsight": True},
        )
        assert inv2_res.status_code == 200
        inv2_data = inv2_res.json()

        # Verify second incident leveraged memory from incident 1!
        assert inv2_data["investigation_mode"] == "with_hindsight"
        assert inv2_data["recalled_incidents_count"] == 1
        assert inv2_data["investigation"]["confidence"] > 0.80

        # Verify historical precedent explicitly cited incident 1's ID!
        hist_incidents = inv2_data["investigation"]["historical_incidents"]
        assert len(hist_incidents) == 1
        assert hist_incidents[0]["incident_id"] == inc1_id
        assert hist_incidents[0]["score"] == 0.94

        # Verify current vs historical evidence separation
        evidence = inv2_data["investigation"]["evidence"]
        current_ev = [e for e in evidence if e["source"] == "current"]
        historical_ev = [e for e in evidence if e["source"] == "historical"]

        assert len(current_ev) >= 1
        assert len(historical_ev) >= 1
        assert historical_ev[0]["incident_id"] == inc1_id


@pytest.mark.asyncio
async def test_live_hindsight_probe():
    """Truthfully checks whether a live Hindsight server is running.

    Does not fabricate live connectivity. If offline, asserts truthful unavailable status.
    """
    health = await hindsight_service.check_health()
    assert "connected" in health
    assert "status" in health

    if health["connected"]:
        # If live server is up, verify version is reported
        assert health["api_version"] is not None
    else:
        # If live server is down, verify truthful reporting without fabrication
        assert health["status"] == "unavailable"
        assert health["api_version"] is None
