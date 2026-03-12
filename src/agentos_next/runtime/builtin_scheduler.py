from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from agentos_next.kernel.evidence_store import FileEvidenceStore
from agentos_next.kernel.executor import ExecuteRequest, ExecuteResult, ExecuteTiming
from agentos_next.kernel.scheduler_store import FileSchedulerStore, SchedulerError
from agentos_next.kernel.trace_logger import FileTraceLogger
from agentos_next.kernel.types import EvidenceRef, TraceEvent


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class BuiltinDispatchResult:
    handled: bool
    result: Optional[ExecuteResult] = None


def maybe_execute_builtin_scheduler(*, req: ExecuteRequest, data_dir: str) -> BuiltinDispatchResult:
    """Handle builtin://scheduler.{at,cron} skills.

    Spec: docs/specs/MVP_012_SCHEDULER.md
    """
    if not req.operator_ref.startswith("builtin://"):
        return BuiltinDispatchResult(handled=False)

    name = req.operator_ref[len("builtin://") :].strip("/")
    if not name.startswith("scheduler."):
        return BuiltinDispatchResult(handled=False)

    evidence = FileEvidenceStore(data_dir=data_dir)
    trace = FileTraceLogger(data_dir=data_dir)
    store = FileSchedulerStore(data_dir=data_dir)

    started_at = _utc_iso()
    evidence_refs: list[EvidenceRef] = []

    def _emit(event_type: str, *, ers: tuple[EvidenceRef, ...] = (), data: Optional[dict[str, Any]] = None) -> None:
        trace.emit(
            TraceEvent(
                schema_version="1.0.0",
                ctx=req.trace,
                event_type=event_type,  # type: ignore[arg-type]
                ts=_utc_iso(),
                evidence_refs=ers,
                data=data,
            )
        )

    _emit("TOOL_CALL_STARTED", data={"builtin": name})

    try:
        if name == "scheduler.at":
            task = _scheduler_at(req=req, store=store, evidence=evidence, evidence_refs=evidence_refs)
        elif name == "scheduler.cron":
            task = _scheduler_cron(req=req, store=store, evidence=evidence, evidence_refs=evidence_refs)
        else:
            out_ref = evidence.add_json(
                {"schema_version": "1.0.0", "ok": False, "error_code": "E_INPUT_SCHEMA", "message": f"unknown builtin: {name}"},
                kind="error",
            )
            evidence_refs.append(out_ref)
            _emit("ERROR", ers=(out_ref,), data={"builtin": name, "error_code": "E_INPUT_SCHEMA"})
            ended_at = _utc_iso()
            return BuiltinDispatchResult(
                handled=True,
                result=ExecuteResult(
                    status="rejected",
                    evidence_refs=tuple(evidence_refs),
                    artifact_refs=(),
                    error_code="E_INPUT_SCHEMA",
                    timing=ExecuteTiming(started_at=started_at, ended_at=ended_at),
                    target="local",
                ),
            )
    except SchedulerError as e:
        err_ref = evidence.add_json(
            {"schema_version": "1.0.0", "ok": False, "error_code": "E_INPUT_SCHEMA", "message": str(e)},
            kind="error",
        )
        evidence_refs.append(err_ref)
        _emit("ERROR", ers=(err_ref,), data={"builtin": name, "error_code": "E_INPUT_SCHEMA"})
        ended_at = _utc_iso()
        return BuiltinDispatchResult(
            handled=True,
            result=ExecuteResult(
                status="rejected",
                evidence_refs=tuple(evidence_refs),
                artifact_refs=(),
                error_code="E_INPUT_SCHEMA",
                timing=ExecuteTiming(started_at=started_at, ended_at=ended_at),
                target="local",
            ),
        )
    except Exception as e:
        err_ref = evidence.add_json(
            {"schema_version": "1.0.0", "ok": False, "error_code": "E_EXECUTION_FAILED", "message": str(e)},
            kind="error",
        )
        evidence_refs.append(err_ref)
        _emit("ERROR", ers=(err_ref,), data={"builtin": name, "error_code": "E_EXECUTION_FAILED"})
        ended_at = _utc_iso()
        return BuiltinDispatchResult(
            handled=True,
            result=ExecuteResult(
                status="failed",
                evidence_refs=tuple(evidence_refs),
                artifact_refs=(),
                error_code="E_EXECUTION_FAILED",
                timing=ExecuteTiming(started_at=started_at, ended_at=ended_at),
                target="local",
            ),
        )

    _emit("TOOL_CALL_FINISHED", data={"builtin": name, "ok": True, "task_id": task.task_id})
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


def _require_dict(obj: Any, *, name: str) -> dict[str, Any]:
    if not isinstance(obj, dict):
        raise SchedulerError(f"{name} must be a JSON object")
    return obj


def _require_str(obj: Any, *, name: str, nonempty: bool = True) -> str:
    if not isinstance(obj, str):
        raise SchedulerError(f"{name} must be a string")
    s = obj
    if nonempty and not s.strip():
        raise SchedulerError(f"{name} must be non-empty")
    return s


def _scheduler_at(
    *,
    req: ExecuteRequest,
    store: FileSchedulerStore,
    evidence: FileEvidenceStore,
    evidence_refs: list[EvidenceRef],
):
    inp = _require_dict(req.arguments, name="arguments")
    run_at = _require_str(inp.get("run_at"), name="run_at")
    draft = _require_dict(inp.get("execute_request"), name="execute_request")
    idem_root = inp.get("idempotency_root")
    if idem_root is not None:
        idem_root = _require_str(idem_root, name="idempotency_root")

    task = store.create_at(
        workspace_id=req.workspace_id,
        run_at=run_at,
        execute_request_draft=draft,
        idempotency_root=idem_root,
    )

    snap_ref = evidence.add_json(
        {"schema_version": "1.0.0", "type": "scheduled_task", **task.to_dict()},
        kind="snapshot",
    )
    evidence_refs.append(snap_ref)

    out_ref = evidence.add_json(
        {
            "schema_version": "1.0.0",
            "ok": True,
            "error_code": None,
            "task_id": task.task_id,
            "next_run_at": task.next_run_at,
            "evidence_refs": [snap_ref.ref],
        },
        kind="tool_io",
    )
    evidence_refs.append(out_ref)
    return task


def _scheduler_cron(
    *,
    req: ExecuteRequest,
    store: FileSchedulerStore,
    evidence: FileEvidenceStore,
    evidence_refs: list[EvidenceRef],
):
    inp = _require_dict(req.arguments, name="arguments")
    cron = _require_str(inp.get("cron"), name="cron")
    tz = str(inp.get("timezone") or "UTC")
    if tz != "UTC":
        raise SchedulerError("MVP only supports timezone=UTC")
    draft = _require_dict(inp.get("execute_request"), name="execute_request")
    idem_root = inp.get("idempotency_root")
    if idem_root is not None:
        idem_root = _require_str(idem_root, name="idempotency_root")

    task = store.create_cron(
        workspace_id=req.workspace_id,
        cron=cron,
        now=datetime.now(timezone.utc),
        execute_request_draft=draft,
        idempotency_root=idem_root,
    )

    snap_ref = evidence.add_json(
        {"schema_version": "1.0.0", "type": "scheduled_task", **task.to_dict()},
        kind="snapshot",
    )
    evidence_refs.append(snap_ref)

    out_ref = evidence.add_json(
        {
            "schema_version": "1.0.0",
            "ok": True,
            "error_code": None,
            "task_id": task.task_id,
            "next_run_at": task.next_run_at,
            "evidence_refs": [snap_ref.ref],
        },
        kind="tool_io",
    )
    evidence_refs.append(out_ref)
    return task
