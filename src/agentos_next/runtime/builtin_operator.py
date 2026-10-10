from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from agentos_next.kernel.capabilities import parse_capabilities
from agentos_next.kernel.evidence_store import FileEvidenceStore
from agentos_next.kernel.executor import ExecuteRequest, ExecuteResult, ExecuteTiming
from agentos_next.kernel.operator_catalog import search_operator_catalog
from agentos_next.kernel.trace_logger import FileTraceLogger
from agentos_next.kernel.types import EvidenceRef, TraceEvent


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class BuiltinDispatchResult:
    handled: bool
    result: Optional[ExecuteResult] = None


def maybe_execute_builtin_operator(*, req: ExecuteRequest, data_dir: str) -> BuiltinDispatchResult:
    if req.operator_ref != "builtin://operator.search":
        return BuiltinDispatchResult(handled=False)

    evidence = FileEvidenceStore(data_dir=data_dir)
    trace = FileTraceLogger(data_dir=data_dir)
    started_at = _utc_iso()
    evidence_refs: list[EvidenceRef] = []

    def _emit(event_type: str, *, ers: tuple[EvidenceRef, ...] = (), data: Optional[dict[str, object]] = None) -> None:
        trace.emit(
            TraceEvent(
                schema_version="1.0.0",
                ctx=req.trace,
                event_type=event_type,
                ts=_utc_iso(),
                evidence_refs=ers,
                data=data,
            )
        )

    _emit("TOOL_CALL_STARTED", data={"builtin": "operator.search"})
    parsed = parse_capabilities(dict(req.policy_context or {}))
    query = str((req.arguments or {}).get("query") or "").strip()
    limit = int((req.arguments or {}).get("limit") or 6)
    results = search_operator_catalog(
        query_text=query,
        available_capabilities=sorted(parsed.names),
        limit=limit,
    )
    io_ref = evidence.add_json(
        {
            "schema_version": "1.0.0",
            "ok": True,
            "operator_ref": req.operator_ref,
            "output": {"results": results},
        },
        kind="tool_io",
    )
    evidence_refs.append(io_ref)
    _emit("TOOL_CALL_FINISHED", ers=(io_ref,), data={"builtin": "operator.search", "ok": True})
    ended_at = _utc_iso()
    return BuiltinDispatchResult(
        handled=True,
        result=ExecuteResult(
            status="accepted",
            evidence_refs=tuple(evidence_refs),
            artifact_refs=(),
            error_code=None,
            timing=ExecuteTiming(started_at=started_at, ended_at=ended_at),
            target="local",
        ),
    )
