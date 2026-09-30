"""Comprehensive tests for Hindsight memory formatting, RETAIN, and RECALL operations."""

from datetime import datetime, timezone
import pytest
from unittest.mock import AsyncMock, patch

from hindsight_client import RecallResponse, RecallResult, RetainResponse
from hindsight_client_api.models.recall_scores import RecallScores

from backend.app.database.models import (
    Incident,
    IncidentEnvironment,
    IncidentOutcome,
    IncidentSeverity,
    IncidentStatus,
)
from backend.app.memory.hindsight_service import HindsightService
from backend.app.memory.memory_formatter import (
    build_recall_query,
    extract_incident_memory_metadata,
    format_incident_for_memory,
    validate_incident_for_retention,
)


@pytest.fixture
def resolved_incident():
    """Provides a fully resolved Incident model ready for retention."""
    return Incident(
        id="inc-db-4091",
        title="PostgreSQL connection pool exhausted",
        description="Checkout service failing with connection pool timeout under peak Black Friday load.",
        severity=IncidentSeverity.CRITICAL.value,
        service="checkout-service",
        environment=IncidentEnvironment.PRODUCTION.value,
        status=IncidentStatus.RESOLVED.value,
        logs="FATAL: remaining connection slots are reserved for non-replication superuser connections\nError: connection pool timeout",
        symptoms=["HTTP 500 spike", "Database latency > 5000ms", "Connection pool exhausted"],
        suspected_root_cause="Connection pool size too small for surging checkout traffic",
        confirmed_root_cause="HikariCP pool limit set to 20 was exhausted by long-running cart validation queries.",
        recommended_actions=[{"step": 1, "action": "Increase pool limit to 50"}],
        resolution="Increased HikariCP max pool size to 50 in production config, restarted checkout-service pods gracefully, and verified connection metrics normalized.",
        runbook_id="DB-CONNECTION-01",
        outcome=IncidentOutcome.SUCCESSFUL.value,
        is_retained=False,
        created_at=datetime.now(timezone.utc),
        resolved_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )


def test_memory_formatter_contains_required_historical_fields(resolved_incident: Incident):
    """Verifies that format_incident_for_memory contains all required historical operational fields

    and explicitly frames content as historical precedent rather than current truth.
    """
    memory_text = format_incident_for_memory(resolved_incident)

    # Historical branding
    assert "[HISTORICAL INCIDENT EXPERIENCE RECORD]" in memory_text
    assert "[OPERATIONAL CONTEXT NOTE]" in memory_text

    # Core metadata
    assert "Incident ID: inc-db-4091" in memory_text
    assert "Title: PostgreSQL connection pool exhausted" in memory_text
    assert "Service: checkout-service" in memory_text
    assert "Environment: production" in memory_text
    assert "Severity: CRITICAL" in memory_text

    # Telemetry and root cause
    assert "HTTP 500 spike" in memory_text
    assert "remaining connection slots are reserved" in memory_text
    assert "CONFIRMED Root Cause: HikariCP pool limit set to 20" in memory_text

    # Remediation and lessons
    assert "Runbook ID: DB-CONNECTION-01" in memory_text
    assert "Resolution Executed: Increased HikariCP max pool size to 50" in memory_text
    assert "Outcome: SUCCESSFUL" in memory_text
    assert "-- Operational Lessons Learned --" in memory_text


def test_validate_incident_for_retention(resolved_incident: Incident):
    """Verifies validation rules enforcing resolved data completeness prior to retention."""
    # 1. Complete incident passes
    valid, err = validate_incident_for_retention(resolved_incident)
    assert valid is True
    assert err is None

    # 2. Missing confirmed root cause fails
    resolved_incident.confirmed_root_cause = ""
    valid, err = validate_incident_for_retention(resolved_incident)
    assert valid is False
    assert "confirmed_root_cause" in err

    # 3. Missing resolution fails
    resolved_incident.confirmed_root_cause = "Verified cause"
    resolved_incident.resolution = "   "
    valid, err = validate_incident_for_retention(resolved_incident)
    assert valid is False
    assert "resolution" in err

    # 4. Pending outcome fails
    resolved_incident.resolution = "Applied fix"
    resolved_incident.outcome = IncidentOutcome.PENDING.value
    valid, err = validate_incident_for_retention(resolved_incident)
    assert valid is False
    assert "pending" in err


def test_build_recall_query():
    """Verifies dense recall query construction for Hindsight TEMPR search."""
    query = build_recall_query(
        service="checkout-service",
        environment="production",
        symptoms=["connection timeout", "pool exhausted"],
        logs="FATAL: remaining connection slots are reserved\nSecond line trace",
        title="DB connection pool failure",
    )
    assert "checkout-service" in query
    assert "production" in query
    assert "connection timeout" in query
    assert "remaining connection slots" in query


def test_extract_incident_memory_metadata(resolved_incident: Incident):
    """Verifies metadata extraction for Hindsight indexing."""
    meta = extract_incident_memory_metadata(resolved_incident)
    assert meta["incident_id"] == "inc-db-4091"
    assert meta["service"] == "checkout-service"
    assert meta["environment"] == "production"
    assert meta["runbook_id"] == "DB-CONNECTION-01"
    assert meta["outcome"] == "successful"


@pytest.mark.asyncio
async def test_retain_incident_experience_success(resolved_incident: Incident):
    """Verifies successful RETAIN call updates incident.is_retained = True and passes correct payload."""
    service = HindsightService(
        base_url="http://localhost:8888",
        bank_id="incident-memory-bank",
    )

    mock_retain_resp = RetainResponse(
        success=True,
        bank_id="incident-memory-bank",
        items_count=1,
        var_async=False,
        operation_id="op-retain-991",
    )

    with patch("backend.app.memory.hindsight_service.Hindsight") as mock_hindsight_cls:
        mock_client = AsyncMock()
        mock_client.aretain.return_value = mock_retain_resp
        mock_hindsight_cls.return_value = mock_client

        result = await service.retain_incident_experience(resolved_incident)

        assert result.success is True
        assert result.bank_id == "incident-memory-bank"
        assert result.items_count == 1
        assert result.operation_id == "op-retain-991"
        assert resolved_incident.is_retained is True

        # Verify exact parameters passed to Hindsight SDK
        mock_client.aretain.assert_called_once()
        _, kwargs = mock_client.aretain.call_args
        assert kwargs["bank_id"] == "incident-memory-bank"
        assert "[HISTORICAL INCIDENT EXPERIENCE RECORD]" in kwargs["content"]
        assert kwargs["metadata"]["incident_id"] == "inc-db-4091"
        assert "checkout-service" in kwargs["tags"]
        assert "DB-CONNECTION-01" in kwargs["tags"]


@pytest.mark.asyncio
async def test_retain_precondition_failure(resolved_incident: Incident):
    """Verifies that an unconfirmed incident fails retention locally without calling Hindsight."""
    resolved_incident.confirmed_root_cause = None

    service = HindsightService(base_url="http://localhost:8888")
    with patch("backend.app.memory.hindsight_service.Hindsight") as mock_hindsight_cls:
        result = await service.retain_incident_experience(resolved_incident)

        assert result.success is False
        assert result.error == "precondition_failed"
        assert resolved_incident.is_retained is False
        mock_hindsight_cls.assert_not_called()


@pytest.mark.asyncio
async def test_retain_service_failure(resolved_incident: Incident):
    """Verifies that network/service failures do NOT mark incident as retained."""
    service = HindsightService(base_url="http://localhost:8888")

    with patch("backend.app.memory.hindsight_service.Hindsight") as mock_hindsight_cls:
        mock_client = AsyncMock()
        mock_client.aretain.side_effect = TimeoutError("Connection to Hindsight server timed out")
        mock_hindsight_cls.return_value = mock_client

        result = await service.retain_incident_experience(resolved_incident)

        assert result.success is False
        assert result.error == "TimeoutError"
        assert "timed out" in result.details.lower()
        assert resolved_incident.is_retained is False


@pytest.mark.asyncio
async def test_recall_incident_experience_success_with_scores():
    """Verifies successful RECALL extracts genuine score and metadata from Hindsight response."""
    service = HindsightService(
        base_url="http://localhost:8888",
        bank_id="incident-memory-bank",
    )

    scores = RecallScores(final=0.91, reranker=0.95, semantic=0.88, keyword=0.75)
    result_item = RecallResult(
        id="mem-unit-77",
        text="[HISTORICAL INCIDENT EXPERIENCE RECORD] DB pool exhausted in checkout...",
        type="experience",
        scores=scores,
        metadata={"incident_id": "inc-100", "runbook_id": "DB-CONNECTION-01"},
        tags=["incident", "checkout-service"],
    )

    mock_recall_resp = RecallResponse(results=[result_item])

    with patch("backend.app.memory.hindsight_service.Hindsight") as mock_hindsight_cls:
        mock_client = AsyncMock()
        mock_client.arecall.return_value = mock_recall_resp
        mock_hindsight_cls.return_value = mock_client

        query = "checkout-service database connection pool exhausted"
        result = await service.recall_incident_experience(query)

        assert result.success is True
        assert result.is_available is True
        assert result.bank_id == "incident-memory-bank"
        assert result.total_results == 1

        recalled = result.results[0]
        assert recalled.id == "mem-unit-77"
        assert recalled.score == 0.91
        assert recalled.metadata["runbook_id"] == "DB-CONNECTION-01"
        assert "HISTORICAL INCIDENT" in recalled.text

        mock_client.arecall.assert_called_once_with(
            bank_id="incident-memory-bank",
            query=query,
            max_tokens=4096,
        )


@pytest.mark.asyncio
async def test_recall_no_fabricated_scores():
    """Verifies that when Hindsight does not provide scores, the system leaves score as None (no fabrications)."""
    service = HindsightService(base_url="http://localhost:8888")

    result_item = RecallResult(
        id="mem-unit-88",
        text="Historical memory without explicit score",
        type="experience",
        scores=None,
    )
    mock_recall_resp = RecallResponse(results=[result_item])

    with patch("backend.app.memory.hindsight_service.Hindsight") as mock_hindsight_cls:
        mock_client = AsyncMock()
        mock_client.arecall.return_value = mock_recall_resp
        mock_hindsight_cls.return_value = mock_client

        result = await service.recall_incident_experience("query without scores")

        assert result.success is True
        assert result.total_results == 1
        assert result.results[0].score is None  # Must remain None, never fabricated


@pytest.mark.asyncio
async def test_recall_service_unavailable():
    """Verifies that when Hindsight is unavailable, recall returns success=False and does NOT invent fake memories."""
    service = HindsightService(base_url="http://localhost:8888")

    with patch("backend.app.memory.hindsight_service.Hindsight") as mock_hindsight_cls:
        mock_client = AsyncMock()
        mock_client.arecall.side_effect = ConnectionRefusedError("Connection refused on port 8888")
        mock_hindsight_cls.return_value = mock_client

        result = await service.recall_incident_experience("some query")

        assert result.success is False
        assert result.is_available is False
        assert result.total_results == 0
        assert len(result.results) == 0
        assert result.error == "ConnectionRefusedError"
        assert "unavailable" in result.details.lower()
