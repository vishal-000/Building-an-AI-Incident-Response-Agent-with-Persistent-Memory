"""Live end-to-end integration smoke test verifying Phase 8 frontend-backend integration.

Executes real HTTP requests against the FastAPI backend, verifying:
- Health reporting (truthful Hindsight unavailable status)
- Incident creation
- Dual-mode investigation (Without vs With Hindsight)
- Human resolution confirmation
- Retention attempt under real offline Hindsight condition (verifying no fabricated data)
- Runbook catalog
"""

import asyncio
import sys
from pathlib import Path

# Ensure root directory is on PYTHONPATH
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from httpx import AsyncClient, ASGITransport
from backend.app.main import app


async def run_smoke_test():
    print("=" * 70)
    print("STARTING REAL SMOKE TEST FOR PHASE 8 FRONTEND-BACKEND INTEGRATION")
    print("=" * 70)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        # 1. Health check
        print("\n1. Testing GET /api/v1/health...")
        health_res = await client.get("/api/v1/health")
        assert health_res.status_code == 200, f"Health check failed: {health_res.text}"
        health = health_res.json()
        services = health.get("services") or health.get("components") or {}
        print(f"   Overall status: {health['status']}")
        print(f"   Database: {services['database']['status']}")
        print(f"   Hindsight: {services['hindsight']['status']} (Truthful offline status)")
        print(f"   LLM: {services['llm']['status']}")

        assert services["database"]["status"] in ("healthy", "connected")
        assert services["database"]["connected"] is True
        assert services["hindsight"]["status"] == "unavailable"

        # 2. Create Incident
        print("\n2. Testing POST /api/v1/incidents (Primary Checkout Scenario)...")
        create_payload = {
            "title": "Database connection pool starvation during checkout traffic",
            "description": "Elevated latency and database timeouts in checkout service causing 500 error spike for consumers.",
            "severity": "critical",
            "service": "checkout-service",
            "environment": "production",
            "logs": "FATAL: remaining connection slots are reserved for non-replication superuser connections\nHikariPool-1 - Connection is not available, request timed out after 30000ms",
            "symptoms": ["HTTP 500 spike", "database connection timeout", "high database latency"],
        }
        create_res = await client.post("/api/v1/incidents", json=create_payload)
        assert create_res.status_code == 201, f"Create incident failed: {create_res.text}"
        inc = create_res.json()
        incident_id = inc["id"]
        print(f"   Incident created: {incident_id}")
        print(f"   Title: {inc['title']}")
        print(f"   Status: {inc['status']}")
        print(f"   Retained: {inc['is_retained']}")
        assert inc["status"] == "open"
        assert inc["is_retained"] is False

        # 3. List Incidents
        print("\n3. Testing GET /api/v1/incidents...")
        list_res = await client.get("/api/v1/incidents")
        assert list_res.status_code == 200, f"List incidents failed: {list_res.text}"
        list_data = list_res.json()
        assert "items" in list_data, "Response missing 'items' key"
        assert "total" in list_data, "Response missing 'total' key"
        print(f"   Total incidents in DB: {list_data['total']}")
        assert any(i["id"] == incident_id for i in list_data["items"])

        # 4. Investigate WITHOUT Hindsight (Stateless Baseline)
        print("\n4. Testing POST /api/v1/incidents/{id}/investigate (WITHOUT Hindsight)...")
        inv_baseline_res = await client.post(
            f"/api/v1/incidents/{incident_id}/investigate",
            json={"use_hindsight": False},
        )
        assert inv_baseline_res.status_code == 200, f"Baseline investigation failed: {inv_baseline_res.text}"
        baseline = inv_baseline_res.json()
        print(f"   Mode: {baseline['investigation_mode']}")
        print(f"   Hindsight Available: {baseline['hindsight_available']}")
        print(f"   Historical precedents: {len(baseline['investigation']['historical_incidents'])}")
        print(f"   Confidence: {baseline['investigation']['confidence'] * 100:.0f}%")
        print(f"   Likely root cause: {baseline['investigation']['likely_root_cause']}")

        assert baseline["investigation_mode"] == "without_hindsight"
        assert len(baseline["investigation"]["historical_incidents"]) == 0
        assert baseline["investigation"]["confidence"] <= 0.50

        # 5. Investigate WITH Hindsight (Live Offline Verification)
        print("\n5. Testing POST /api/v1/incidents/{id}/investigate (WITH Hindsight)...")
        inv_with_res = await client.post(
            f"/api/v1/incidents/{incident_id}/investigate",
            json={"use_hindsight": True},
        )
        assert inv_with_res.status_code == 200, f"With Hindsight investigation failed: {inv_with_res.text}"
        with_res = inv_with_res.json()
        print(f"   Mode: {with_res['investigation_mode']}")
        print(f"   Hindsight Available: {with_res['hindsight_available']} (Truthfully False)")
        print(f"   Recalled count: {with_res['recalled_incidents_count']}")
        print(f"   Matched runbook: {with_res.get('matched_runbook', {}).get('id') if with_res.get('matched_runbook') else 'None'}")
        print(f"   Confidence: {with_res['investigation']['confidence'] * 100:.0f}%")

        assert with_res["investigation_mode"] == "with_hindsight"
        assert with_res["hindsight_available"] is False
        assert with_res["recalled_incidents_count"] == 0

        # 6. Human Resolution
        print("\n6. Testing POST /api/v1/incidents/{id}/resolve (Human Confirmation)...")
        resolve_payload = {
            "confirmed_root_cause": "connection pool exhaustion caused by long-running queries / saturated pool limit",
            "resolution": "increase pool capacity appropriately, gracefully restart affected service pods, and verify connection metrics normalize",
            "runbook_id": "DB-CONNECTION-01",
            "outcome": "successful",
        }
        resolve_res = await client.post(f"/api/v1/incidents/{incident_id}/resolve", json=resolve_payload)
        assert resolve_res.status_code == 200, f"Resolve failed: {resolve_res.text}"
        resolved = resolve_res.json()
        print(f"   Status: {resolved['status']}")
        print(f"   Confirmed root cause: {resolved['confirmed_root_cause']}")
        print(f"   Resolution: {resolved['resolution']}")
        print(f"   Resolved at: {resolved['resolved_at']}")
        print(f"   Is Retained: {resolved['is_retained']}")

        assert resolved["status"] == "resolved"
        assert resolved["confirmed_root_cause"] == resolve_payload["confirmed_root_cause"]
        assert resolved["is_retained"] is False

        # 7. Attempt Retention with Offline Hindsight
        print("\n7. Testing POST /api/v1/incidents/{id}/retain (Truthful Offline Handling)...")
        retain_res = await client.post(f"/api/v1/incidents/{incident_id}/retain")
        assert retain_res.status_code == 200, f"Retain request failed: {retain_res.text}"
        retain_data = retain_res.json()
        print(f"   Success: {retain_data['success']}")
        print(f"   Operation ID: {retain_data['operation_id']} (None fabricated)")
        print(f"   Details: {retain_data['details']}")
        print(f"   Error: {retain_data['error']}")

        # Ensure no fabrication when offline
        assert retain_data["success"] is False
        assert retain_data["operation_id"] is None
        assert "unavailable" in retain_data["details"].lower() or "connection" in retain_data["details"].lower()

        # Verify incident in DB remained resolved and not retained
        final_inc_res = await client.get(f"/api/v1/incidents/{incident_id}")
        assert final_inc_res.status_code == 200
        final_inc = final_inc_res.json()
        assert final_inc["status"] == "resolved"
        assert final_inc["is_retained"] is False
        print(f"   Verified DB state: status='{final_inc['status']}', is_retained={final_inc['is_retained']}")

        # 8. Runbook Catalog
        print("\n8. Testing GET /api/v1/runbooks...")
        rb_res = await client.get("/api/v1/runbooks")
        assert rb_res.status_code == 200
        runbooks = rb_res.json()
        print(f"   Catalog count: {len(runbooks)}")
        assert len(runbooks) >= 4
        assert any(r["id"] == "DB-CONNECTION-01" for r in runbooks)

    print("\n" + "=" * 70)
    print("ALL SMOKE TEST SCENARIOS PASSED WITH 100% TRUTHFUL DATA VERIFICATION")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(run_smoke_test())
