# Incident Memory Agent - Architecture Documentation

## Executive Overview
The **Incident Memory Agent** is a memory-driven AI Incident Response system designed for DevOps, SRE, and software engineering teams. 

Unlike generic chatbots or stateless assistants, this system leverages **Hindsight** agent memory to build an organizational repository of operational experience. It retains structured incident outcomes (symptoms, logs, confirmed root causes, applied runbooks, and resolution efficacy) and recalls relevant historical experience when new production incidents arise.

---

## Architectural Principles

1. **Memory as Evidence, Not Absolute Truth**:
   Historical memories retrieved from Hindsight provide empirical evidence and operational precedent. The system never blindly assumes a past incident is 100% identical; instead, it synthesizes current telemetry against historical memories to form reasoned hypotheses.

2. **Strict Separation of Telemetry vs. Memory vs. Hypothesis**:
   The agent's structured reasoning clearly isolates:
   - **Current Incident Observations**: Fresh error logs, stack traces, affected service, environment.
   - **Historical Precedents (Hindsight RECALL)**: Previous incidents with similar symptoms, previous root causes, and previous outcomes.
   - **AI Root-Cause Hypothesis**: Probabilistic assessment with confidence score and supporting evidence.
   - **Recommended Actions & Runbooks**: Step-by-step remediation guide.
   - **Human Sign-Off & Verification**: Human engineer confirms diagnosis before any action is executed.
   - **Organizational Learning (Hindsight RETAIN)**: The resolved incident outcome is committed back to the Hindsight memory bank.

3. **Human-in-the-Loop Remediation**:
   The agent does **not** execute destructive or production-altering operations automatically. Every remediation requires human confirmation.

4. **Zero-Friction Local Development with Production Scalability**:
   - Local: SQLite (`sqlite+aiosqlite:///./incident_memory.db`) allows instantaneous execution without local Docker/Postgres daemon requirements.
   - Production: Full PostgreSQL support (`DATABASE_URL=postgresql+asyncpg://...`) configured via environment variables.

---

## High-Level Architecture Diagram

```
+-----------------------------------------------------------------------------------+
|                                  USER / SRE                                       |
+-----------------------------------------+-----------------------------------------+
                                          | Browser (React + TypeScript + Tailwind)
                                          v
+-----------------------------------------------------------------------------------+
|                               Frontend Dashboard                                  |
|   - Real-time Incident Feed & Timeline     - Side-by-side With/Without Memory     |
|   - Hindsight Memory Bank Visualizer       - Safe Realistic Incident Simulator    |
+-----------------------------------------+-----------------------------------------+
                                          | REST API (HTTP / JSON)
                                          v
+-----------------------------------------------------------------------------------+
|                               FastAPI Backend Engine                              |
|   +-------------------+  +---------------------+  +---------------------------+   |
|   | Incident Service  |  | Runbook Registry    |  | AI Investigator Engine    |   |
|   +---------+---------+  +----------+----------+  +-------------+-------------+   |
|             |                       |                           |                 |
|             v                       v                           v                 |
|   +-------------------+  +---------------------+  +---------------------------+   |
|   | SQLite / Postgres |  | Standard Runbooks   |  | Multi-Provider LLM Client |   |
|   | (Async SQLAlchemy)|  | (DB-01, MEM-01, etc)|  | (OpenAI / Claude / Gemini)|   |
|   +-------------------+  +---------------------+  +-------------+-------------+   |
+-----------------------------------------------------------------|-----------------+
                                                                  |
                                      +---------------------------+
                                      | Hindsight Client SDK
                                      v
+-----------------------------------------------------------------------------------+
|                        Hindsight Agent Memory Service                             |
|                                                                                   |
|  - RETAIN: Ingests normalized post-mortem operational lessons into memory bank    |
|  - RECALL: Multi-strategy retrieval (semantic, keyword, graph, temporal)          |
|  - REFLECT: Synthesizes patterns and updates organizational knowledge             |
+-----------------------------------------------------------------------------------+
```

---

## The Incident Lifecycle & Memory Flow

```
1. INCIDENT INGESTION
   An incident is triggered (via API, Simulator, or Engineer).
   Data: Title, Service, Environment, Severity, Logs, Symptoms.
          │
          ▼
2. HINDSIGHT RECALL
   Backend queries Hindsight memory bank with incident symptoms and error signatures.
   Query: "Database connection timeout, pool exhausted, service=checkout"
   Result: Historical incident records with relevance scores, prior causes, and resolutions.
          │
          ▼
3. STRUCTURED AI INVESTIGATION
   AI Investigator synthesizes current observations + recalled Hindsight memories.
   Produces validated structured output:
   {
     "summary": "...",
     "likely_root_cause": "...",
     "confidence": 0.92,
     "evidence": ["Current logs show connection pool limit", "Recall matches incident #104"],
     "historical_incidents": ["INC-104: Pool starvation solved by pool resizing"],
     "recommended_actions": ["Verify active connections", "Apply DB-CONNECTION-01"],
     "runbook_id": "DB-CONNECTION-01",
     "risk_notes": "Do not restart without checking ongoing queries"
   }
          │
          ▼
4. HUMAN REVIEW & APPROVAL
   Engineer reviews evidence, verifies root cause, and executes recommended runbook steps.
          │
          ▼
5. RESOLUTION & OUTCOME CAPTURE
   Engineer records actual resolution, confirmation status, and outcome (Success/Failure).
          │
          ▼
6. HINDSIGHT RETAIN
   Operational lesson is formatted into structured knowledge and stored into Hindsight:
   client.retain(bank_id="incident-memory-bank", content="Incident INC-202...")
   Memory bank is now enriched; subsequent similar incidents benefit from this experience.
```

---

## Hindsight Integration Details
- **Official SDK**: `hindsight-client`
- **Memory Bank Namespace**: Configurable via `HINDSIGHT_BANK_ID` (default: `incident-memory-bank`).
- **Endpoints Utilized**:
  - `client.recall(bank_id, query)`: Multi-strategy recall across experiences.
  - `client.retain(bank_id, content)`: Storing validated operational experience.
- **Graceful Fallback**: If Hindsight is temporarily unreachable, the system exposes an explicit health warning and allows incident analysis in "Without Memory" baseline mode, maintaining full transparent observability.

---

## Dual Investigation Modes: With Memory vs. Without Memory

The investigation engine explicitly supports two distinct operational modes via `POST /api/v1/incidents/{id}/investigate`:

### Mode A: With Hindsight Memory (`use_hindsight: true`)
1. Generates a dense retrieval query from current symptoms and error logs (`build_recall_query`).
2. Queries Hindsight's multi-strategy TEMPR engine to pull past operational experiences.
3. Distinguishes `current` observations from `historical` precedent evidence.
4. AI reasons over both:
   - Assigns high confidence (e.g. 0.85 - 0.95) when symptoms corroborate a past resolved outage.
   - Cites specific historical incident IDs (`historical_incidents`).
   - Selects proven runbook (`DB-CONNECTION-01`).
   - Recommends tailored remediation steps with pre/post verification checks.

### Mode B: Without Hindsight Memory (`use_hindsight: false`)
1. Bypasses Hindsight memory entirely (zero memory queries).
2. Evaluates only raw current telemetry (stateless baseline).
3. Produces textbook general troubleshooting steps (ping host, check credentials, inspect network).
4. Assigns conservative confidence (e.g. 0.40 - 0.50).
5. Sets `historical_incidents = []` and labels all evidence strictly as `current`.

This contrast demonstrates the tangible value of long-term agent memory: transforming repetitive fire-fighting into progressive organizational learning.

---

## Deterministic Runbook Matching
Rather than relying on non-deterministic LLM hallucinations for runbook selection, the system incorporates a rule-based runbook matcher:
- **`DB-CONNECTION-01`**: Database Connection Pool Exhaustion & Connection Timeout
- **`MEMORY-HIGH-01`**: Container Memory Pressure & OOM Mitigation
- **`SERVICE-UNAVAILABLE-01`**: HTTP 502/503 Service Unavailable & Ingress Routing Failure
- **`DEPLOYMENT-FAILURE-01`**: Failed Release Deployment & CrashLoopBackOff Recovery

Remediation steps are presented as human-in-the-loop recommendations with verification checks. No production-altering actions are executed without engineer approval.

---

## End-to-End Incident Lifecycle & Operational Resolution

The complete incident lifecycle follows a strict sequence:

```
CREATE ──► INVESTIGATE ──► HUMAN REVIEW ──► RESOLVE ──► RETAIN ──► FUTURE RECALL
```

### Core Product Principle
> **"AI proposes. Human confirms. Hindsight remembers."**

This principle dictates that:
1. **AI Proposes**: The AI investigator generates root cause hypotheses, confidence estimates, and recommended runbooks based on telemetry and historical memory. The AI's `suspected_root_cause` is explicitly tentative.
2. **Human Confirms**: A human operator/engineer must actively inspect the system, review the AI's proposal, and provide explicit confirmation via `POST /api/v1/incidents/{id}/resolve`. The endpoint validates non-empty `confirmed_root_cause`, non-empty `resolution`, a valid `outcome` (`successful`, `partially_successful`, `unsuccessful`), and an optional valid `runbook_id`. The AI's hypothesis is never automatically copied into `confirmed_root_cause` without human confirmation.
3. **Hindsight Remembers**: Once resolved, the operational experience is retained into Hindsight agent memory via `POST /api/v1/incidents/{id}/retain`. Subsequent similar incidents recall this confirmed experience.

### Lifecycle State Machine
- **`OPEN`**: Incident created with symptoms, logs, severity, and affected service.
- **`INVESTIGATING`**: AI investigator processes current observations and recalls any relevant past incidents.
- **`RESOLVED`**: Human engineer submits confirmed root cause, actual resolution steps, runbook used, and operational outcome. `resolved_at` is stamped.
- **`RETAINED`**: Hindsight has successfully ingested the normalized post-mortem operational lesson into the configured memory bank (`incident-memory-bank`). `is_retained` is set to `true`.

### Truthful Retention & Idempotency Rules
- **Prerequisite Validation**: Only incidents in `RESOLVED` status with valid resolution fields can be retained. Retaining an unresolved incident returns HTTP 400.
- **Truthful Status**: `is_retained` is updated to `true` **only** after Hindsight confirms successful retention.
- **Failure Resilience**: If Hindsight is unavailable or returns an error, the incident status remains `RESOLVED`, `is_retained` remains `false`, and no memory ID or operation ID is fabricated.
- **Idempotency**: Repeated retention requests on an already-retained incident (`is_retained == true`) safely return a structured response with `already_retained: true` without creating duplicate memory records in Hindsight.

### Safety Guarantee
The Incident Memory Agent strictly adheres to a non-autonomous remediation policy. The agent recommends verification steps, diagnostics, and runbooks (e.g. connection pool adjustments, graceful restarts), but **never executes destructive or production-altering operations autonomously**. All changes require human confirmation and execution.

