from __future__ import annotations

import contextlib
import json
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from agentos_next.kernel.dialog_state_machine import build_user_message_digest
from agentos_next.kernel.evidence_store import FileEvidenceStore
from agentos_next.kernel.executor import ExecuteRequest
from agentos_next.kernel.orchestrator import Orchestrator
from agentos_next.kernel.scheduler_store import (
    FileSchedulerStore,
    ScheduledTask,
    SchedulerError,
    next_cron_time,
)
from agentos_next.kernel.trace_logger import FileTraceLogger
from agentos_next.kernel.types import EvidenceRef, TraceContext, TraceEvent


def _utc_iso(dt: Optional[datetime] = None) -> str:
    d = dt or datetime.now(timezone.utc)
    return d.isoformat().replace("+00:00", "Z")


def _parse_utc_iso(s: str) -> datetime:
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s)


@contextlib.contextmanager
def _acquire_tick_lock(*, data_dir: Path, timeout_sec: float = 2.0, stale_sec: float = 60.0):
    lock_path = data_dir / "scheduler" / "tick.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)

    deadline = time.time() + float(timeout_sec)
    while True:
        now = time.time()
        try:
            with lock_path.open("x", encoding="utf-8") as f:
                f.write(json.dumps({"pid": os.getpid(), "ts": now}) + "\n")
            break
        except FileExistsError:
            stale = False
            try:
                obj = json.loads(lock_path.read_text(encoding="utf-8"))
                ts = float(obj.get("ts"))
                stale = (now - ts) > float(stale_sec)
            except Exception:
                try:
                    stale = (now - lock_path.stat().st_mtime) > float(stale_sec)
                except Exception:
                    stale = False
            if stale:
                with contextlib.suppress(Exception):
                    lock_path.unlink()
                continue
            if now >= deadline:
                raise SchedulerError("scheduler tick is locked (concurrent runner)")
            time.sleep(0.05)

    try:
        yield
    finally:
        with contextlib.suppress(Exception):
            lock_path.unlink()


@dataclass(frozen=True)
class SchedulerTickRequest:
    data_dir: str
    now: Optional[str] = None  # UTC ISO; if None uses current time
    # Governance keys are passed explicitly; tasks cannot override these at trigger time.
    replay_mode: bool = False
    remote_calls_armed: bool = False
    allow_network_egress: bool = False
    approved_by_human: bool = False
    max_fires: int = 50
    trace: Optional[TraceContext] = None


@dataclass(frozen=True)
class FiredTask:
    task_id: str
    kind: str
    fired_at: str
    trace_id: str
    execute_status: str
    error_code: Optional[str]
    target: str
    evidence_refs: tuple[str, ...]
    next_run_at: Optional[str]


@dataclass(frozen=True)
class SchedulerTickResult:
    ok: bool
    error_code: Optional[str]
    fired: tuple[FiredTask, ...]
    evidence_refs: tuple[str, ...]


async def run_scheduler_tick_async(req: SchedulerTickRequest, *, orchestrator: Orchestrator) -> SchedulerTickResult:
    """Fire due tasks and execute them via Orchestrator.

    MVP constraints:
    - no daemon; caller drives tick
    - UTC only
    - fail-closed on parsing / invalid task data
    """
    evidence = FileEvidenceStore(data_dir=req.data_dir)
    trace = FileTraceLogger(data_dir=req.data_dir)
    store = FileSchedulerStore(data_dir=req.data_dir)
    ctx = req.trace or TraceContext(trace_id="tr_sched_tick", turn_id="turn_tick", span_id="span_tick")

    try:
        now_dt = datetime.now(timezone.utc) if req.now is None else _parse_utc_iso(str(req.now))
    except Exception:
        err_ref = evidence.add_json(
            {
                "schema_version": "1.0.0",
                "type": "scheduler_tick_error",
                "error_code": "E_INPUT_SCHEMA",
                "message": "now must be UTC ISO timestamp",
                "now": req.now,
            },
            kind="error",
        )
        trace.emit(
            TraceEvent(
                schema_version="1.0.0",
                ctx=ctx,
                event_type="ERROR",
                ts=_utc_iso(),
                evidence_refs=(err_ref,),
                data={"builtin": "scheduler.tick", "error_code": "E_INPUT_SCHEMA"},
            )
        )
        return SchedulerTickResult(ok=False, error_code="E_INPUT_SCHEMA", fired=(), evidence_refs=(err_ref.ref,))

    now_dt = now_dt.astimezone(timezone.utc)
    now_iso = _utc_iso(now_dt)
    fired: list[FiredTask] = []
    tick_evidence: list[EvidenceRef] = []

    tick_ref = evidence.add_json(
        {"schema_version": "1.0.0", "type": "scheduler_tick", "now": now_iso, "max_fires": int(req.max_fires)},
        kind="snapshot",
    )
    tick_evidence.append(tick_ref)
    trace.emit(
        TraceEvent(
            schema_version="1.0.0",
            ctx=ctx,
            event_type="TOOL_CALL_STARTED",
            ts=_utc_iso(),
            evidence_refs=(tick_ref,),
            data={"builtin": "scheduler.tick", "now": now_iso},
        )
    )

    try:
        with _acquire_tick_lock(data_dir=Path(req.data_dir)):
            tasks = store.list_tasks()
            due: list[ScheduledTask] = []
            for task in tasks:
                if task.status != "scheduled":
                    continue
                try:
                    if _parse_utc_iso(task.next_run_at).astimezone(timezone.utc) <= now_dt:
                        due.append(task)
                except Exception:
                    err = evidence.add_json(
                        {"schema_version": "1.0.0", "type": "scheduler_task_invalid", "task_id": task.task_id, "next_run_at": task.next_run_at},
                        kind="error",
                    )
                    tick_evidence.append(err)
                    store.put(ScheduledTask.from_dict({**task.to_dict(), "status": "failed"}))

            for task in due[: max(0, int(req.max_fires))]:
                store.put(ScheduledTask.from_dict({**task.to_dict(), "status": "running"}))

                draft = dict(task.execute_request or {})
                policy = dict(draft.get("policy_context") or {})
                dialog_trace_id = None
                dtid = policy.get("dialog_trace_id")
                if isinstance(dtid, str) and dtid.strip():
                    dialog_trace_id = dtid.strip()

                policy["replay_mode"] = bool(req.replay_mode)
                policy["remote_calls_armed"] = bool(req.remote_calls_armed)
                policy["allow_network_egress"] = bool(req.allow_network_egress)
                policy["approved_by_human"] = bool(req.approved_by_human)

                deadline_ms = int(draft.get("deadline_ms") or 0)
                if deadline_ms <= 0:
                    fire_ref = evidence.add_json(
                        {
                            "schema_version": "1.0.0",
                            "type": "scheduler_fire",
                            "task_id": task.task_id,
                            "fired_at": now_iso,
                            "error_code": "E_TIMEOUT",
                            "message": "invalid deadline_ms<=0",
                        },
                        kind="error",
                    )
                    tick_evidence.append(fire_ref)
                    store.put(ScheduledTask.from_dict({**task.to_dict(), "status": "failed", "attempts": int(task.attempts) + 1}))
                    continue

                attempt = int(task.attempts) + 1
                trace_id = f"tr_{task.task_id}"
                exec_trace = TraceContext(trace_id=trace_id, turn_id=f"turn_{attempt}", span_id=f"span_{attempt}")

                fire_started_ref = evidence.add_json(
                    {
                        "schema_version": "1.0.0",
                        "type": "scheduler_fire_started",
                        "task_id": task.task_id,
                        "kind": task.kind,
                        "attempt": attempt,
                        "fired_at": now_iso,
                        "dialog_trace_id": dialog_trace_id,
                    },
                    kind="routing",
                )
                tick_evidence.append(fire_started_ref)

                dialog_turn_index: int | None = None
                if dialog_trace_id is not None:
                    dialog_turn_index = _next_dialog_turn_index(data_dir=Path(req.data_dir), dialog_trace_id=dialog_trace_id)
                    dlg_ctx = TraceContext(
                        trace_id=dialog_trace_id,
                        turn_id=f"turn_sched_{task.task_id}_{attempt}",
                        span_id=f"span_sched_{task.task_id}_{attempt}",
                        parent_span_id=None,
                    )
                    trace.emit(
                        TraceEvent(
                            schema_version="1.0.0",
                            ctx=dlg_ctx,
                            event_type="DIALOG_EVENT",  # type: ignore[arg-type]
                            ts=_utc_iso(),
                            evidence_refs=(fire_started_ref,),
                            data={
                                "dialog_event_type": "USER_MESSAGE_RECEIVED",
                                "dialog_id": dialog_trace_id,
                                "turn_index": dialog_turn_index,
                                "input_digest": build_user_message_digest(message=f"[scheduler]{task.task_id}:{attempt}"),
                                "source": "scheduler",
                                "task_id": task.task_id,
                                "attempt": attempt,
                            },
                        )
                    )
                    trace.emit(
                        TraceEvent(
                            schema_version="1.0.0",
                            ctx=dlg_ctx,
                            event_type="DIALOG_EVENT",  # type: ignore[arg-type]
                            ts=_utc_iso(),
                            evidence_refs=(fire_started_ref,),
                            data={
                                "dialog_event_type": "TURN_STARTED",
                                "dialog_id": dialog_trace_id,
                                "turn_index": dialog_turn_index,
                                "source": "scheduler",
                                "task_id": task.task_id,
                                "attempt": attempt,
                            },
                        )
                    )

                policy["trigger"] = {
                    "type": "scheduler",
                    "task_id": task.task_id,
                    "kind": task.kind,
                    "attempt": attempt,
                    "fired_at": now_iso,
                    "dialog_trace_id": dialog_trace_id,
                }

                exec_req = ExecuteRequest(
                    workspace_id=str(draft.get("workspace_id") or ""),
                    operator_ref=str(draft.get("operator_ref") or draft.get("skill_ref") or ""),
                    arguments=dict(draft.get("arguments") or draft.get("input") or {}),
                    idempotency_key=f"{task.idempotency_root}:{attempt}",
                    deadline_ms=deadline_ms,
                    trace=exec_trace,
                    policy_context=policy,
                    preferred_target=(draft.get("preferred_target") if draft.get("preferred_target") else None),
                )
                res = await orchestrator.execute(exec_req)

                fire_ref = evidence.add_json(
                    {
                        "schema_version": "1.0.0",
                        "type": "scheduler_fire",
                        "task_id": task.task_id,
                        "kind": task.kind,
                        "fired_at": now_iso,
                        "dialog_trace_id": dialog_trace_id,
                        "execute_request": {
                            "workspace_id": exec_req.workspace_id,
                            "operator_ref": exec_req.operator_ref,
                            "idempotency_key": exec_req.idempotency_key,
                            "deadline_ms": exec_req.deadline_ms,
                            "preferred_target": exec_req.preferred_target,
                        },
                        "execute_result": {
                            "status": res.status,
                            "error_code": res.error_code,
                            "target": res.target,
                            "evidence_refs": [er.ref for er in res.evidence_refs],
                        },
                        "next_run_at_before": task.next_run_at,
                    },
                    kind="routing",
                )
                tick_evidence.append(fire_ref)

                if dialog_trace_id is not None:
                    if dialog_turn_index is None:
                        dialog_turn_index = _next_dialog_turn_index(data_dir=Path(req.data_dir), dialog_trace_id=dialog_trace_id)
                    dlg_ctx = TraceContext(
                        trace_id=dialog_trace_id,
                        turn_id=f"turn_sched_{task.task_id}_{attempt}",
                        span_id=f"span_sched_{task.task_id}_{attempt}",
                        parent_span_id=None,
                    )
                    trace.emit(
                        TraceEvent(
                            schema_version="1.0.0",
                            ctx=dlg_ctx,
                            event_type="DIALOG_EVENT",  # type: ignore[arg-type]
                            ts=_utc_iso(),
                            evidence_refs=(fire_ref,),
                            data={
                                "dialog_event_type": "TURN_FINISHED",
                                "dialog_id": dialog_trace_id,
                                "turn_index": dialog_turn_index,
                                "ok": bool(res.status == "accepted"),
                                "error_code": res.error_code,
                                "final_snapshot_ref": fire_ref.ref,
                                "source": "scheduler",
                                "task_id": task.task_id,
                                "attempt": attempt,
                                "execute_trace_id": exec_trace.trace_id,
                            },
                        )
                    )

                next_run_at = None
                status = "failed"
                if task.kind == "at":
                    status = "done" if res.status == "accepted" else "failed"
                elif task.kind == "cron":
                    try:
                        if not task.cron:
                            raise SchedulerError("missing cron on cron task")
                        next_dt = next_cron_time(str(task.cron), now=now_dt)
                        next_run_at = _utc_iso(next_dt)
                        status = "scheduled"
                    except Exception:
                        status = "failed"

                updated = {**task.to_dict(), "status": status, "attempts": attempt}
                if next_run_at is not None:
                    updated["next_run_at"] = next_run_at
                store.put(ScheduledTask.from_dict(updated))

                fired.append(
                    FiredTask(
                        task_id=task.task_id,
                        kind=task.kind,
                        fired_at=now_iso,
                        trace_id=trace_id,
                        execute_status=res.status,
                        error_code=res.error_code,
                        target=res.target,
                        evidence_refs=tuple(er.ref for er in res.evidence_refs),
                        next_run_at=next_run_at,
                    )
                )
    except SchedulerError:
        err_ref = evidence.add_json(
            {
                "schema_version": "1.0.0",
                "type": "scheduler_tick_error",
                "error_code": "E_EXECUTION_FAILED",
                "message": "scheduler tick is locked (concurrent runner)",
            },
            kind="error",
        )
        trace.emit(
            TraceEvent(
                schema_version="1.0.0",
                ctx=ctx,
                event_type="ERROR",
                ts=_utc_iso(),
                evidence_refs=(err_ref,),
                data={"builtin": "scheduler.tick", "error_code": "E_EXECUTION_FAILED"},
            )
        )
        return SchedulerTickResult(ok=False, error_code="E_EXECUTION_FAILED", fired=(), evidence_refs=(err_ref.ref,))

    out_ref = evidence.add_json(
        {
            "schema_version": "1.0.0",
            "type": "scheduler_tick_result",
            "now": now_iso,
            "fired_task_ids": [ft.task_id for ft in fired],
            "fired_count": len(fired),
            "evidence_refs": [er.ref for er in tick_evidence],
        },
        kind="tool_io",
    )
    tick_evidence.append(out_ref)
    trace.emit(
        TraceEvent(
            schema_version="1.0.0",
            ctx=ctx,
            event_type="TOOL_CALL_FINISHED",
            ts=_utc_iso(),
            evidence_refs=(out_ref,),
            data={"builtin": "scheduler.tick", "ok": True, "fired_count": len(fired)},
        )
    )

    return SchedulerTickResult(
        ok=True,
        error_code=None,
        fired=tuple(fired),
        evidence_refs=tuple(er.ref for er in tick_evidence),
    )


def _next_dialog_turn_index(*, data_dir: Path, dialog_trace_id: str) -> int:
    """Best-effort monotonic index assignment for dialog-linked scheduler events.

    MVP assumes a single runner; this is used for trace readability and rehydration tests.
    """
    p = data_dir / "traces" / f"{dialog_trace_id}.jsonl"
    if not p.exists():
        return 1
    mx = 0
    for ln in p.read_text(encoding="utf-8").splitlines():
        ln = ln.strip()
        if not ln:
            continue
        try:
            ev = json.loads(ln)
        except Exception:
            continue
        if not isinstance(ev, dict) or ev.get("event_type") != "DIALOG_EVENT":
            continue
        data = ev.get("data")
        if not isinstance(data, dict):
            continue
        idx = data.get("turn_index")
        if isinstance(idx, int) and idx > mx:
            mx = idx
    return mx + 1
