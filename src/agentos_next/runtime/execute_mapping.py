from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable, Optional

from agentos_next.kernel.executor import ExecuteResult, ExecuteTiming
from agentos_next.kernel.types import EvidenceRef
from agentos_next.runtime.package_runner import PackageRunResult


def _utc_iso() -> str:
    # Keep format consistent with EvidenceStore / TraceLogger: RFC 3339-ish with trailing "Z".
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_utc_iso(ts: str) -> Optional[datetime]:
    # EvidenceRef.ts is written as ISO with "Z". Be tolerant of other ISO forms.
    try:
        if ts.endswith("Z"):
            return datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return datetime.fromisoformat(ts)
    except Exception:
        return None


def _timing_from_evidence_refs(evidence_refs: Iterable[EvidenceRef]) -> ExecuteTiming:
    dts: list[datetime] = []
    for ev in evidence_refs:
        dt = _parse_utc_iso(str(ev.ts))
        if dt is not None:
            dts.append(dt)

    if dts:
        started = min(dts).astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        ended = max(dts).astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        return ExecuteTiming(started_at=started, ended_at=ended)

    # Fallback: if timestamps are missing/unparseable, keep shape stable with "now".
    now = _utc_iso()
    return ExecuteTiming(started_at=now, ended_at=now)


def _status_from_package_result(res: PackageRunResult) -> str:
    if res.ok:
        return "accepted"
    if res.error_code in {"E_HITL_REQUIRED", "E_PRECHECK_FAIL", "E_POSTCHECK_FAIL", "E_BUDGET_EXHAUSTED", "E_BUDGET_SCHEMA_INVALID"}:
        return "rejected"
    if res.error_code == "E_TIMEOUT":
        return "timeout"
    if res.error_code == "E_CANCELED":
        return "canceled"
    return "failed"


def package_run_result_to_execute_result(res: PackageRunResult) -> ExecuteResult:
    """Bounded spike mapping layer: PackageRunResult -> ExecuteResult.

    Notes:
    - `target` is fixed to "local" for this spike.
    - `timing` is derived from EvidenceRef timestamps when available; otherwise uses mapping-time UTC ISO.
    """

    status = _status_from_package_result(res)
    timing = _timing_from_evidence_refs(res.evidence_refs)

    # ExecuteResult includes artifact_refs, but PackageRunResult does not surface artifacts yet.
    return ExecuteResult(
        status=status,  # type: ignore[arg-type]  # Literal in kernel/executor.py
        target="local",  # type: ignore[arg-type]  # ExecutionTarget Literal
        timing=timing,
        error_code=res.error_code,
        evidence_refs=tuple(res.evidence_refs),
        artifact_refs=(),
    )
