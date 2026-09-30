"""Comprehensive test suite for runbook registry and deterministic matching."""

import pytest
from httpx import AsyncClient
from backend.app.services.runbook_service import runbook_service


def test_runbook_registry_lookup():
    """Verifies direct lookup of runbooks by ID."""
    db_rb = runbook_service.get_runbook("DB-CONNECTION-01")
    assert db_rb is not None
    assert db_rb.id == "DB-CONNECTION-01"
    assert "Database Connection" in db_rb.title
    assert db_rb.category == "database"
    assert len(db_rb.diagnostic_checks) >= 3
    assert len(db_rb.remediation_steps) >= 3
    assert len(db_rb.verification_checks) >= 2
    assert "human verification" in db_rb.risk_notes.lower()

    # Nonexistent runbook returns None
    assert runbook_service.get_runbook("NONEXISTENT-99") is None


def test_list_runbooks():
    """Verifies listing all available standard runbooks."""
    all_rb = runbook_service.list_runbooks()
    ids = [rb.id for rb in all_rb]
    assert "DB-CONNECTION-01" in ids
    assert "MEMORY-HIGH-01" in ids
    assert "SERVICE-UNAVAILABLE-01" in ids
    assert "DEPLOYMENT-FAILURE-01" in ids


def test_runbook_matching_database_connection_failure():
    """Verifies primary demo scenario: Database Connection Pool Exhaustion."""
    matched = runbook_service.match_runbook(
        service="checkout-service",
        title="Database connection timeout",
        symptoms=["HTTP 500 spike", "Database connection pool exhausted", "Latency > 5000ms"],
        logs="FATAL: remaining connection slots are reserved for non-replication superuser connections",
    )
    assert matched is not None
    assert matched.id == "DB-CONNECTION-01"


def test_runbook_matching_memory_exhaustion():
    """Verifies memory pressure matching."""
    matched = runbook_service.match_runbook(
        service="worker-service",
        title="Worker process terminated",
        symptoms=["OOMKilled", "memory usage > 90%"],
        logs="java.lang.OutOfMemoryError: Java heap space",
    )
    assert matched is not None
    assert matched.id == "MEMORY-HIGH-01"


def test_runbook_matching_service_unavailable():
    """Verifies HTTP 502/503 ingress gateway matching."""
    matched = runbook_service.match_runbook(
        service="api-gateway",
        title="Ingress returning errors",
        symptoms=["502 Bad Gateway", "upstream connect error"],
        logs="upstream connect error or disconnect/reset before headers",
    )
    assert matched is not None
    assert matched.id == "SERVICE-UNAVAILABLE-01"


def test_runbook_matching_deployment_failure():
    """Verifies CrashLoopBackOff deployment recovery matching."""
    matched = runbook_service.match_runbook(
        service="billing-api",
        title="Release v2.4 failed",
        symptoms=["CrashLoopBackOff", "failed deployment"],
        logs="Application startup exit code 1: missing required secret",
    )
    assert matched is not None
    assert matched.id == "DEPLOYMENT-FAILURE-01"


def test_runbook_matching_unmatched():
    """Verifies that an unclassified incident returns None without crashing."""
    matched = runbook_service.match_runbook(
        service="marketing-blog",
        title="Typo in footer link",
        symptoms=["User feedback on UI styling"],
        logs=None,
    )
    assert matched is None


@pytest.mark.asyncio
async def test_runbooks_api_endpoints(client: AsyncClient):
    """Verifies REST endpoints for runbook listing and retrieval."""
    # List runbooks
    list_res = await client.get("/api/v1/runbooks")
    assert list_res.status_code == 200
    rbs = list_res.json()
    assert len(rbs) >= 4
    assert any(r["id"] == "DB-CONNECTION-01" for r in rbs)

    # Get specific runbook
    get_res = await client.get("/api/v1/runbooks/DB-CONNECTION-01")
    assert get_res.status_code == 200
    rb_data = get_res.json()
    assert rb_data["id"] == "DB-CONNECTION-01"
    assert "remediation_steps" in rb_data

    # Nonexistent runbook 404
    missing_res = await client.get("/api/v1/runbooks/NONEXISTENT-99")
    assert missing_res.status_code == 404
