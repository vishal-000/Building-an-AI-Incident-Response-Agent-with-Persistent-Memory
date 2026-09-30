"""Runbook registry and deterministic matching service."""

from typing import Dict, List, Optional
from backend.app.schemas.runbook import Runbook

# Standard operational runbook registry
RUNBOOK_REGISTRY: Dict[str, Runbook] = {
    "DB-CONNECTION-01": Runbook(
        id="DB-CONNECTION-01",
        title="Database Connection Pool Exhaustion & Connection Timeout",
        category="database",
        symptoms=[
            "connection pool exhausted",
            "connection timeout",
            "FATAL: remaining connection slots are reserved",
            "too many clients",
            "database connection pool timeout",
            "HikariPool",
            "connection checkout timeout",
        ],
        diagnostic_checks=[
            "Query active and idle connections in PostgreSQL: SELECT state, count(*) FROM pg_stat_activity GROUP BY state;",
            "Check current server max_connections limit: SHOW max_connections;",
            "Inspect client connection pool saturation metrics in application APM dashboard.",
            "Identify long-running unindexed queries blocking connection returns: SELECT pid, query, now() - query_start AS duration FROM pg_stat_activity WHERE state != 'idle' ORDER BY duration DESC LIMIT 5;",
        ],
        remediation_steps=[
            "Verify database host CPU and RAM headroom before increasing client pool capacity.",
            "Terminate orphaned 'idle in transaction' sessions exceeding 5 minutes: SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE state = 'idle in transaction' AND state_change < now() - INTERVAL '5 minutes';",
            "Increase application connection pool maximum size (max_overflow) in deployment config after capacity verification.",
            "Perform rolling restart of saturated service pods to clear stale connection thread handles.",
        ],
        verification_checks=[
            "Confirm HTTP 500 error rate drops below 0.1% on affected endpoints.",
            "Verify active database connections stabilize below 70% of maximum pool capacity.",
            "Confirm database query response latency returns to baseline (< 100ms).",
        ],
        risk_notes=(
            "Do NOT increase database max_connections globally without checking database RAM limits. "
            "Terminating active sessions will abort in-flight client transactions; verify connection state prior to killing PIDs. "
            "Requires human verification before executing remediation."
        ),
    ),
    "MEMORY-HIGH-01": Runbook(
        id="MEMORY-HIGH-01",
        title="Container Memory Pressure & OOM Mitigation",
        category="memory",
        symptoms=[
            "OOMKilled",
            "memory usage > 90%",
            "high swap usage",
            "java.lang.OutOfMemoryError",
            "GC overhead limit exceeded",
            "memory leak",
        ],
        diagnostic_checks=[
            "Inspect container cgroup memory metrics using 'kubectl top pod' or node telemetry.",
            "Check recent deployments for unbounded in-memory caches or unindexed bulk data queries.",
            "Analyze JVM / Python GC pause intervals and heap allocation profiles.",
        ],
        remediation_steps=[
            "Temporarily increase pod memory limits to provide operational buffer during traffic surge.",
            "Perform rolling restart of leaking worker pod replicas.",
            "Purge non-essential in-memory local caches and restart background queue workers.",
        ],
        verification_checks=[
            "Confirm container resident set size (RSS) stabilizes below 75% of assigned memory limit.",
            "Ensure zero OOM termination events occur during subsequent traffic cycles.",
        ],
        risk_notes=(
            "Terminating workers during active batch consumption may result in duplicate processing if jobs are not idempotent. "
            "Requires human verification before restarting worker pools."
        ),
    ),
    "SERVICE-UNAVAILABLE-01":
        Runbook(
            id="SERVICE-UNAVAILABLE-01",
            title="HTTP 502/503 Service Unavailable & Ingress Routing Failure",
            category="network",
            symptoms=[
                "502 Bad Gateway",
                "503 Service Unavailable",
                "upstream connect error",
                "connection refused by upstream",
                "readiness probe failed",
            ],
            diagnostic_checks=[
                "Inspect backend container readiness probe status: 'kubectl describe pod <pod-name>'.",
                "Check ingress controller upstream endpoints: 'kubectl get endpoints'.",
                "Inspect network policies and internal Kubernetes CoreDNS resolution.",
            ],
            remediation_steps=[
                "Remove unhealthy pod replicas from active load balancer pool.",
                "Restart failing upstream pods and inspect container startup logs.",
                "Verify internal service discovery DNS resolution and network security groups.",
            ],
            verification_checks=[
                "Confirm ingress HTTP status returns 200 OK across synthetic health monitors.",
                "Verify all registered upstream pod replicas report Ready status.",
            ],
            risk_notes=(
                "Avoid mass restarts that would drop remaining healthy capacity below required throughput. "
                "Maintain minimum ready replicas."
            ),
        ),
    "DEPLOYMENT-FAILURE-01": Runbook(
        id="DEPLOYMENT-FAILURE-01",
        title="Failed Release Deployment & CrashLoopBackOff Recovery",
        category="deployment",
        symptoms=[
            "CrashLoopBackOff",
            "ImagePullBackOff",
            "migration failure",
            "pod startup exit code 1",
            "unhealthy release",
        ],
        diagnostic_checks=[
            "Review container termination logs: 'kubectl logs --previous <pod-name>'.",
            "Verify database migration status and identify failed schema migrations.",
            "Check deployment manifest for missing environment variables or invalid secret mounts.",
        ],
        remediation_steps=[
            "Execute immediate rollback to previous known stable release: 'kubectl rollout undo deployment/<service>'.",
            "Verify rollback revision pods enter Running status and pass readiness probes.",
            "Lock CI/CD pipeline deployments until root-cause post-mortem is completed.",
        ],
        verification_checks=[
            "Confirm previous stable container image revision is running.",
            "Verify application synthetic health checks pass consistently.",
        ],
        risk_notes=(
            "If the failed deployment executed irreversible database schema changes, rolling back code may cause serialization faults. "
            "Check database backward compatibility before rolling back."
        ),
    ),
}


class RunbookService:
    """Service managing runbook lookups and deterministic incident matching."""

    @staticmethod
    def get_runbook(runbook_id: str) -> Optional[Runbook]:
        """Retrieves a runbook by exact identifier."""
        return RUNBOOK_REGISTRY.get(runbook_id.strip().upper())

    @staticmethod
    def list_runbooks() -> List[Runbook]:
        """Lists all registered standard runbooks."""
        return list(RUNBOOK_REGISTRY.values())

    @staticmethod
    def match_runbook(
        service: str,
        title: str,
        symptoms: List[str],
        logs: Optional[str] = None,
    ) -> Optional[Runbook]:
        """Deterministically matches an incident against the runbook registry.

        Uses explicit keyword and symptom signatures. Does not require an LLM for deterministic matching.
        """
        combined_text = (
            f"{service} {title} {' '.join(symptoms)} {logs or ''}"
        ).lower()

        # 1. Database connection failure signatures (Primary scenario)
        db_keywords = [
            "connection pool",
            "pool exhausted",
            "remaining connection slots",
            "connection timeout",
            "too many clients",
            "hikaripool",
            "database latency",
            "database connection",
            "postgres",
            "active connections",
        ]
        if any(kw in combined_text for kw in db_keywords):
            return RUNBOOK_REGISTRY["DB-CONNECTION-01"]

        # 2. Memory exhaustion signatures
        memory_keywords = [
            "oomkilled",
            "out of memory",
            "outofmemoryerror",
            "memory leak",
            "high memory",
            "gc overhead",
            "heap space",
        ]
        if any(kw in combined_text for kw in memory_keywords):
            return RUNBOOK_REGISTRY["MEMORY-HIGH-01"]

        # 3. Service unavailable / Ingress signatures
        ingress_keywords = [
            "502 bad gateway",
            "503 service unavailable",
            "bad gateway",
            "service unavailable",
            "upstream connect error",
            "connection refused by upstream",
            "readiness probe",
        ]
        if any(kw in combined_text for kw in ingress_keywords):
            return RUNBOOK_REGISTRY["SERVICE-UNAVAILABLE-01"]

        # 4. Deployment failure signatures
        deploy_keywords = [
            "crashloopbackoff",
            "imagepullbackoff",
            "migration failure",
            "rollout undo",
            "failed deployment",
            "startup exit code",
        ]
        if any(kw in combined_text for kw in deploy_keywords):
            return RUNBOOK_REGISTRY["DEPLOYMENT-FAILURE-01"]

        return None


runbook_service = RunbookService()
