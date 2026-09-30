"""Script verifying end-to-end Incident Create -> Retrieve -> Update -> Health flow."""

import asyncio
import json
import os
import sys

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath("."))

import httpx
from backend.app.database.session import init_db
from backend.app.main import app


async def run_verification():
    # Ensure database schema is ready
    await init_db()

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Health check verification
        print("=== 1. Health Endpoint Check ===")
        h_res = await client.get("/api/v1/health")
        h_json = h_res.json()
        print(f"Status Code: {h_res.status_code} | System Status: {h_json['status']}")
        print(f"Database: {h_json['services']['database']['status']} ({h_json['services']['database']['engine']})")
        print(f"Hindsight: {h_json['services']['hindsight']['status']}")

        # 2. Create Incident Flow
        print("\n=== 2. Create Incident Flow (POST /api/v1/incidents) ===")
        create_payload = {
            "title": "Database connection pool exhausted",
            "description": "PostgreSQL pool exhausted under high traffic surge in checkout service.",
            "severity": "critical",
            "service": "checkout-service",
            "environment": "production",
            "logs": "FATAL: remaining connection slots are reserved for non-replication superuser connections",
            "symptoms": ["HTTP 500 surge", "Database connection timeout", "Latency > 8000ms"],
            "suspected_root_cause": "Connection pool max capacity reached",
            "runbook_id": "DB-CONNECTION-01",
        }
        c_res = await client.post("/api/v1/incidents", json=create_payload)
        assert c_res.status_code == 201, f"Expected 201, got {c_res.status_code}: {c_res.text}"
        created = c_res.json()
        incident_id = created["id"]
        print(f"Created Incident ID: {incident_id}")
        print(f"Initial Status: {created['status']}, Outcome: {created['outcome']}")
        print(json.dumps(created, indent=2))

        # 3. Retrieve Incident Flow
        print(f"\n=== 3. Retrieve Incident Flow (GET /api/v1/incidents/{incident_id}) ===")
        r_res = await client.get(f"/api/v1/incidents/{incident_id}")
        assert r_res.status_code == 200, f"Expected 200, got {r_res.status_code}"
        retrieved = r_res.json()
        assert retrieved["id"] == incident_id
        print(f"Retrieved Title: {retrieved['title']}")
        print(f"Service: {retrieved['service']} | Severity: {retrieved['severity']}")

        # 4. Update Incident Flow
        print(f"\n=== 4. Update Incident Flow (PATCH /api/v1/incidents/{incident_id}) ===")
        patch_payload = {
            "status": "resolved",
            "confirmed_root_cause": "Max pool limit of 20 connections was saturated by unclosed checkout queries.",
            "resolution": "Increased pool max_overflow to 40, verified connection drains, and updated DB-CONNECTION-01 runbook.",
            "outcome": "successful",
        }
        p_res = await client.patch(f"/api/v1/incidents/{incident_id}", json=patch_payload)
        assert p_res.status_code == 200, f"Expected 200, got {p_res.status_code}"
        updated = p_res.json()
        print(f"Updated Status: {updated['status']}")
        print(f"Resolved At: {updated['resolved_at']}")
        print(f"Outcome: {updated['outcome']}")
        print(json.dumps(updated, indent=2))

        print("\nAll API verification steps completed successfully!")


if __name__ == "__main__":
    asyncio.run(run_verification())
