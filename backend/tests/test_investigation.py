"""Comprehensive test suite for AI investigation engine, dual-mode reasoning, and runbook matching."""

import pytest
from unittest.mock import AsyncMock, patch
from httpx import AsyncClient
from pydantic import ValidationError

from backend.app.agent.llm_provider import MockLLMProvider
from backend.app.memory.hindsight_service import RecallExperienceResult, RecalledExperience
from backend.app.schemas.investigation import (
    ActionStep,
    EvidenceItem,
    HistoricalPrecedent,
    InvestigationOutput,
)
from backend.app.services.runbook_service import RUNBOOK_REGISTRY


@pytest.fixture
def sample_incident_data():
    """Provides standard database connection failure incident telemetry."""
    return {
        "id": "inc-current-001",
        "title": "Database connection timeout in checkout",
        "service": "checkout-service",
        "environment": "production",
        "severity": "critical",
        "symptoms": ["HTTP 500 spike", "Database connection pool exhausted", "Latency > 5000ms"],
        "logs": "FATAL: remaining connection slots are reserved for non-replication superuser connections",
    }


@pytest.fixture
def sample_historical_memory():
    """Provides a realistic recalled historical memory unit from Hindsight."""
    return RecalledExperience(
        id="mem-unit-4091",
        text=(
            "[HISTORICAL INCIDENT EXPERIENCE RECORD]\n"
            "Incident ID: INC-104\n"
            "Title: PostgreSQL connection pool exhausted\n"
            "Service: checkout-service\n"
            "Environment: production\n"
            "Severity: CRITICAL\n\n"
            "Observed Symptoms: HTTP 500 spike, Connection pool exhausted\n"
            "CONFIRMED Root Cause: HikariCP connection pool limit reached 20 during flash sale.\n"
            "Resolution Executed: Increased pool max_overflow to 50 and restarted checkout pods.\n"
            "Outcome: SUCCESSFUL\n"
            "Runbook ID: DB-CONNECTION-01"
        ),
        memory_type="experience",
        score=0.92,
        metadata={"incident_id": "INC-104", "runbook_id": "DB-CONNECTION-01"},
        tags=["incident", "checkout-service", "DB-CONNECTION-01"],
    )


def test_investigation_output_schema_validation():
    """Verifies that valid investigation outputs pass Pydantic validation."""
    valid_output = InvestigationOutput(
        summary="Database pool saturated",
        likely_root_cause="Connection pool max capacity reached",
        confidence=0.85,
        evidence=[
            EvidenceItem(source="current", description="Active 500 errors"),
            EvidenceItem(source="historical", description="Precedent INC-104", incident_id="INC-104"),
        ],
        historical_incidents=[
            HistoricalPrecedent(
                incident_id="INC-104",
                title="PostgreSQL connection pool exhausted",
                relevance="Identical pool exhaustion signature",
                score=0.92,
            )
        ],
        recommended_actions=[
            ActionStep(step="Verify active DB sessions", verification="Check active connection count < 90%")
        ],
        runbook_id="DB-CONNECTION-01",
        risk_notes="Requires human verification prior to altering pool",
    )
    assert valid_output.confidence == 0.85
    assert len(valid_output.evidence) == 2
    assert valid_output.evidence[1].incident_id == "INC-104"


def test_investigation_output_confidence_bounds():
    """Verifies that confidence scores must be bounded between 0.0 and 1.0."""
    with pytest.raises(ValidationError):
        InvestigationOutput(
            summary="Invalid confidence",
            likely_root_cause="Testing",
            confidence=1.5,  # Exceeds maximum 1.0
            evidence=[EvidenceItem(source="current", description="error")],
            recommended_actions=[ActionStep(step="step", verification="verify")],
        )

    with pytest.raises(ValidationError):
        InvestigationOutput(
            summary="Invalid confidence",
            likely_root_cause="Testing",
            confidence=-0.1,  # Below minimum 0.0
            evidence=[EvidenceItem(source="current", description="error")],
            recommended_actions=[ActionStep(step="step", verification="verify")],
        )


@pytest.mark.asyncio
async def test_mock_investigator_with_hindsight(sample_incident_data, sample_historical_memory):
    """Verifies MockLLMProvider in WITH HINDSIGHT mode:

    - Incorporates recalled historical precedent
    - Cites the specific historical incident ID
    - Assigns higher confidence based on precedent
    - Distinguishes current vs historical evidence
    """
    provider = MockLLMProvider()
    result = await provider.investigate(
        incident_data=sample_incident_data,
        historical_memories=[sample_historical_memory],
        use_hindsight=True,
        matched_runbook=RUNBOOK_REGISTRY["DB-CONNECTION-01"],
    )

    assert result.confidence > 0.80
    assert len(result.historical_incidents) == 1
    assert result.historical_incidents[0].incident_id == "INC-104"
    assert result.runbook_id == "DB-CONNECTION-01"

    # Verify source separation in evidence
    sources = [e.source for e in result.evidence]
    assert "current" in sources
    assert "historical" in sources

    hist_evidence = [e for e in result.evidence if e.source == "historical"]
    assert any(e.incident_id == "INC-104" for e in hist_evidence)


@pytest.mark.asyncio
async def test_mock_investigator_without_hindsight(sample_incident_data):
    """Verifies MockLLMProvider in WITHOUT HINDSIGHT mode:

    - Operates in stateless baseline mode
    - Contains NO historical incident citations
    - All evidence is strictly 'current'
    - Produces conservative baseline confidence
    """
    provider = MockLLMProvider()
    result = await provider.investigate(
        incident_data=sample_incident_data,
        historical_memories=[],
        use_hindsight=False,
        matched_runbook=RUNBOOK_REGISTRY["DB-CONNECTION-01"],
    )

    assert result.confidence <= 0.50
    assert len(result.historical_incidents) == 0  # Strictly empty in baseline mode
    assert all(e.source == "current" for e in result.evidence)
    assert "baseline" in result.summary.lower()


@pytest.mark.asyncio
async def test_api_investigate_with_hindsight_mode(client: AsyncClient, sample_historical_memory):
    """Verifies end-to-end POST /api/v1/incidents/{id}/investigate with memory recall."""
    # 1. Create incident
    create_res = await client.post(
        "/api/v1/incidents",
        json={
            "title": "Database connection pool exhausted",
            "description": "Checkout service returning HTTP 500 due to connection starvation",
            "severity": "critical",
            "service": "checkout-service",
            "environment": "production",
            "logs": "FATAL: remaining connection slots are reserved for non-replication superuser connections",
            "symptoms": ["HTTP 500 spike", "Database connection pool exhausted"],
        },
    )
    assert create_res.status_code == 201
    incident_id = create_res.json()["id"]

    # 2. Mock Hindsight recall returning sample historical memory
    mock_recall_result = RecallExperienceResult(
        success=True,
        is_available=True,
        bank_id="test-incident-memory-bank",
        query="checkout-service production",
        results=[sample_historical_memory],
        total_results=1,
        details="Recalled 1 memory",
    )

    with patch(
        "backend.app.memory.hindsight_service.hindsight_service.recall_incident_experience",
        new_callable=AsyncMock,
    ) as mock_recall:
        mock_recall.return_value = mock_recall_result

        # Trigger investigation with use_hindsight=True
        inv_res = await client.post(
            f"/api/v1/incidents/{incident_id}/investigate",
            json={"use_hindsight": True},
        )
        assert inv_res.status_code == 200
        data = inv_res.json()

        assert data["incident_id"] == incident_id
        assert data["investigation_mode"] == "with_hindsight"
        assert data["hindsight_available"] is True
        assert data["recalled_incidents_count"] == 1
        assert data["matched_runbook"]["id"] == "DB-CONNECTION-01"

        inv = data["investigation"]
        assert inv["confidence"] > 0.80
        assert len(inv["historical_incidents"]) == 1
        assert inv["historical_incidents"][0]["incident_id"] == "INC-104"
        assert inv["runbook_id"] == "DB-CONNECTION-01"

        # Verify DB incident record was updated
        updated_inc_res = await client.get(f"/api/v1/incidents/{incident_id}")
        assert updated_inc_res.status_code == 200
        updated_inc = updated_inc_res.json()
        assert updated_inc["status"] == "investigating"
        assert updated_inc["suspected_root_cause"] is not None
        assert updated_inc["runbook_id"] == "DB-CONNECTION-01"


@pytest.mark.asyncio
async def test_api_investigate_without_hindsight_mode(client: AsyncClient):
    """Verifies end-to-end POST /api/v1/incidents/{id}/investigate in baseline mode."""
    # 1. Create incident
    create_res = await client.post(
        "/api/v1/incidents",
        json={
            "title": "Database connection pool exhausted",
            "description": "Checkout service connection timeout",
            "severity": "critical",
            "service": "checkout-service",
            "environment": "production",
            "logs": "connection timeout",
        },
    )
    assert create_res.status_code == 201
    incident_id = create_res.json()["id"]

    # 2. Trigger investigation with use_hindsight=False
    with patch("backend.app.memory.hindsight_service.hindsight_service.recall_incident_experience", new_callable=AsyncMock) as mock_recall:
        inv_res = await client.post(
            f"/api/v1/incidents/{incident_id}/investigate",
            json={"use_hindsight": False},
        )
        assert inv_res.status_code == 200
        data = inv_res.json()

        assert data["investigation_mode"] == "without_hindsight"
        assert data["recalled_incidents_count"] == 0
        assert len(data["investigation"]["historical_incidents"]) == 0
        assert data["investigation"]["confidence"] <= 0.50

        # Confirm Hindsight was never queried
        mock_recall.assert_not_called()


@pytest.mark.asyncio
async def test_api_investigate_hindsight_unavailable(client: AsyncClient):
    """Verifies that when Hindsight is unavailable, investigation falls back gracefully without fabricating memory."""
    create_res = await client.post(
        "/api/v1/incidents",
        json={
            "title": "PostgreSQL pool timeout",
            "description": "Database pool exhausted",
            "service": "checkout-service",
            "severity": "critical",
        },
    )
    incident_id = create_res.json()["id"]

    mock_unavailable = RecallExperienceResult(
        success=False,
        is_available=False,
        bank_id="test-incident-memory-bank",
        query="query",
        results=[],
        total_results=0,
        error="TimeoutError",
        details="Hindsight server unreachable",
    )

    with patch(
        "backend.app.memory.hindsight_service.hindsight_service.recall_incident_experience",
        new_callable=AsyncMock,
    ) as mock_recall:
        mock_recall.return_value = mock_unavailable

        inv_res = await client.post(
            f"/api/v1/incidents/{incident_id}/investigate",
            json={"use_hindsight": True},
        )
        assert inv_res.status_code == 200
        data = inv_res.json()

        assert data["hindsight_available"] is False
        assert data["recalled_incidents_count"] == 0
        assert len(data["investigation"]["historical_incidents"]) == 0


@pytest.mark.asyncio
async def test_api_investigate_nonexistent_incident_returns_404(client: AsyncClient):
    """Verifies that investigating an invalid incident ID returns HTTP 404."""
    res = await client.post(
        "/api/v1/incidents/00000000-0000-0000-0000-000000000000/investigate",
        json={"use_hindsight": True},
    )
    assert res.status_code == 404
