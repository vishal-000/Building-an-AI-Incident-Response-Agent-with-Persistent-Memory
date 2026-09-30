# Incident Memory Agent — Live Demo Walkthrough

This document outlines the step-by-step demonstration scenario for the **Incident Memory Agent**, showcasing how long-term agent memory powered by [Hindsight](https://github.com/vectorize-io/hindsight) fundamentally transforms SRE and DevOps incident troubleshooting.

---

## 🎯 Primary Demo Scenario: Database Connection Pool Exhaustion

- **Service:** `checkout-service`
- **Environment:** `production`
- **Severity:** `critical` (Sev-1)
- **Observed Symptoms:**
  - `HTTP 500 spike`
  - `database connection timeout`
  - `high database latency`
- **Captured Error Telemetry:**
  ```log
  FATAL: remaining connection slots are reserved for non-replication superuser connections
  org.postgresql.util.PSQLException: FATAL: 53300: remaining connection slots are reserved
  HikariPool-1 - Connection is not available, request timed out after 30000ms
  ```

---

## 🔄 Complete 10-Step Workflow

### Step 1: Create Historical Incident
1. Open the Incident Memory Agent Dashboard (`http://localhost:5173`).
2. Click **New Incident** (or navigate to `/create`).
3. Click the preset button: **"Checkout DB Exhaustion (Primary)"**.
   - This automatically populates the form with the `checkout-service` outage parameters and PostgreSQL pool error logs.
4. Click **Create Incident**. The system redirects to the new Incident Details page.

---

### Step 2: Investigate (Baseline Diagnosis)
1. On the Incident Details page, locate the **Investigation Comparison: Memory Difference** section.
2. Click **Run Stateless Baseline** (or run investigation without memory).
3. **Observe the result:**
   - **Mode:** Without Hindsight (Stateless Baseline).
   - **Hypothesis:** Generic connectivity failure or downstream service unreachability.
   - **Historical Precedents:** 0 (Troubleshooting starts from scratch).
   - **Confidence:** Conservative ~45%.
   - **Recommended Actions:** Generic ping, telnet, DNS check, and manual log inspection.

---

### Step 3: Human SRE Confirms Root Cause
1. Scroll down to the **Human Operational Resolution** section.
2. The AI proposed hypotheses, but an engineer performs manual verification:
   - SRE checks database active connection counts via `pg_stat_activity` and discovers connection starvation.
3. In **Confirmed Root Cause**, enter:
   ```text
   PostgreSQL connection pool exhausted by unindexed customer cart query holding pool slots during traffic surge.
   ```

---

### Step 4: Resolve the Incident
1. In **Operational Resolution & Actions Executed**, enter:
   ```text
   Applied runbook DB-CONNECTION-01: Increased HikariPool max-lifetime and pool ceiling from 50 to 120. Rolling restart of checkout-service pods executed; connection pool latency normalized under 15ms.
   ```
2. In **Matched Runbook SOP**, select `DB-CONNECTION-01`.
3. In **Outcome**, select `Successful (Fully Restored)`.
4. Click **Confirm & Resolve Incident**.
   - Status changes to `RESOLVED`.
   - Resolution timestamp is recorded in the operational lifecycle timeline.

---

### Step 5: Retain Incident Experience in Hindsight
1. Click **Retain Experience in Hindsight**.
2. A confirmation dialog appears explaining what operational data will be committed:
   - Incident ID, title, affected service, severity, symptoms, error signatures, confirmed root cause, verified resolution, and applied runbook.
3. Click **Confirm & Retain**.
   - If Hindsight is connected: The backend formats the post-mortem into a structured operational experience and commits it to the `incident-memory-bank`. The incident is marked `RETAINED IN HINDSIGHT`.
   - If Hindsight is offline: The UI truthfully indicates that Hindsight is unavailable, preserving data integrity without fabricating confirmation hashes.

---

### Step 6: Create a Similar Incident (Future Outage Simulation)
1. Several days later, a new alert fires during a flash sale.
2. Navigate to `/create` and click **"Checkout DB Exhaustion (Primary)"** (or enter similar symptoms for `checkout-service`).
3. Click **Create Incident**.

---

### Step 7: Investigate with Hindsight Agent Memory
1. On the new Incident Details page, click **Investigate with Hindsight**.
2. The agent executes a semantic and contextual recall query against the `incident-memory-bank` using the current telemetry, service name, and symptom tokens.

---

### Step 8: Observe Historical Precedent Recall
1. Under **With Hindsight Agent Memory**, observe the retrieved context:
   - The previously retained historical incident appears in the **Recalled Historical Incidents** list.
   - The historical confirmed root cause and previous resolution are cited directly.
   - Relevance score and operational similarity are displayed.

---

### Step 9: Compare WITHOUT vs WITH Hindsight
Side-by-side comparison in the UI demonstrates the stark contrast:

| Attribute | Without Hindsight (Stateless) | With Hindsight (Memory-Augmented) |
| :--- | :--- | :--- |
| **Analysis Basis** | Isolated telemetry from current incident only | Current telemetry + institutional memory bank |
| **Root Cause** | Generic database connectivity failure | Corroborated connection pool exhaustion with past cause |
| **Confidence** | ~45% (Uncertain, exploratory) | ~88% (High confidence backed by historical precedent) |
| **Historical Precedent** | None (Engineer starts from zero) | Recalled previous post-mortem with exact previous resolution |
| **Remediation** | Generic triage (ping, check DNS) | Targeted execution of runbook `DB-CONNECTION-01` |
| **Time to Triage** | High (Trial-and-error debugging) | Rapid (Immediate alignment with proven resolution) |

---

### Step 10: Resolve and Retain New Experience
1. Confirm the resolution for the second incident.
2. Commit the new post-mortem back to Hindsight.
3. The organizational memory bank continually compounds knowledge, enabling the team to handle recurring failure patterns faster and more reliably.

---

## 🛡️ Fallback Behavior When Hindsight is Unavailable

If the local Docker daemon is not running or the Hindsight server is offline:

1. **Dashboard & Health Indicator:**
   - Displays a truthful warning banner: `"Hindsight Memory Service Unavailable (OFFLINE)"`.
   - Explains that the agent is running in stateless baseline mode.
2. **Investigation Endpoint:**
   - When `use_hindsight=true` is requested, the backend catches the network exception, records `hindsight_available=false`, logs the event, and safely returns the baseline investigation.
   - The UI displays an amber alert: *"Hindsight unavailable — historical memory cannot currently be recalled. Investigation completed using current telemetry only."*
3. **Retention Endpoint:**
   - Returns `{ "success": false, "details": "Hindsight unavailable" }`.
   - The database status remains truthfully un-retained (`is_retained=false`).
   - **Zero fabricated operation IDs, hashes, scores, or memory IDs are ever generated.**
