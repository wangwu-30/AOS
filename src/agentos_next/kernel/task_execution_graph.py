from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, Optional

TASK_EXECUTION_GRAPH_SCHEMA_VERSION = "1.0.0"
TASK_EXECUTION_GRAPH_TYPE = "task_execution_graph_v1"

TaskExecutionStatus = Literal[
    "queued",
    "running",
    "succeeded",
    "failed",
    "canceled",
    "hold",
    "need_context",
    "interrupted",
    "superseded",
]

TaskEffectClass = Literal[
    "read_only",
    "workspace_write",
    "external_effect",
    "user_visible_delivery",
]

TASK_EXECUTION_TERMINAL_STATES = frozenset(
    {
        "succeeded",
        "failed",
        "canceled",
        "need_context",
        "interrupted",
        "superseded",
    }
)

TASK_EXECUTION_GRAPH_ERROR_SCHEMA_INVALID = "E_TASK_EXECUTION_GRAPH_INVALID"
TASK_EXECUTION_GRAPH_ERROR_IO_FAILED = "E_PA_TG_IO_FAILED"


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _safe_segment(value: str, *, fallback: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return fallback
    if re.fullmatch(r"[A-Za-z0-9._:-]{1,200}", raw):
        return raw
    return fallback


def _string_list(raw: Any) -> list[str]:
    return [str(item).strip() for item in (raw or []) if str(item).strip()]


def _normalize_effect_class(raw: Any) -> TaskEffectClass:
    value = str(raw or "read_only").strip() or "read_only"
    if value in {"read_only", "workspace_write", "external_effect", "user_visible_delivery"}:
        return value  # type: ignore[return-value]
    return "read_only"


@dataclass(frozen=True)
class TaskExecutionNode:
    task_id: str
    seq: int
    task_idempotency_key: str
    status: TaskExecutionStatus
    objective: str
    worker_task_id: str = ""
    scope_summary: str = ""
    depends_on: tuple[str, ...] = ()
    allowed_operator_refs: tuple[str, ...] = ()
    input_refs: tuple[str, ...] = ()
    completion_contract_ref: str = ""
    submission_id: str = ""
    execution_lane: str = "standard_task"
    tool_budget: dict[str, Any] = field(default_factory=dict)
    token_budget: dict[str, Any] = field(default_factory=dict)
    stop_policy: dict[str, Any] = field(default_factory=dict)
    time_budget_ms: int = 0
    task_execution_policy: dict[str, Any] = field(default_factory=dict)
    submitter: str = ""
    source_phase: str = ""
    trace: dict[str, Any] = field(default_factory=dict)
    attempt: int = 0
    generation: int = 1
    superseded_by_submission_id: str | None = None
    effect_class: TaskEffectClass = "read_only"
    side_effect_boundary_reached: bool = False
    result_ref: str | None = None
    evidence_refs: tuple[str, ...] = ()
    error_code: str | None = None
    created_at_utc: str = ""
    started_at_utc: str | None = None
    ended_at_utc: str | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "seq": int(self.seq),
            "task_idempotency_key": self.task_idempotency_key,
            "status": self.status,
            "objective": self.objective,
            "worker_task_id": self.worker_task_id,
            "scope_summary": self.scope_summary,
            "depends_on": list(self.depends_on),
            "allowed_operator_refs": list(self.allowed_operator_refs),
            "input_refs": list(self.input_refs),
            "completion_contract_ref": self.completion_contract_ref,
            "submission_id": self.submission_id,
            "execution_lane": self.execution_lane,
            "tool_budget": dict(self.tool_budget),
            "token_budget": dict(self.token_budget),
            "stop_policy": dict(self.stop_policy),
            "time_budget_ms": int(self.time_budget_ms),
            "task_execution_policy": dict(self.task_execution_policy),
            "submitter": self.submitter,
            "source_phase": self.source_phase,
            "trace": dict(self.trace),
            "attempt": int(self.attempt),
            "generation": int(self.generation),
            "superseded_by_submission_id": self.superseded_by_submission_id,
            "effect_class": self.effect_class,
            "side_effect_boundary_reached": bool(self.side_effect_boundary_reached),
            "result_ref": self.result_ref,
            "evidence_refs": list(self.evidence_refs),
            "error_code": self.error_code,
            "created_at_utc": self.created_at_utc,
            "started_at_utc": self.started_at_utc,
            "ended_at_utc": self.ended_at_utc,
        }

    @classmethod
    def from_json(cls, obj: Any) -> Optional["TaskExecutionNode"]:
        if not isinstance(obj, dict):
            return None
        task_id = str(obj.get("task_id") or "").strip()
        status = str(obj.get("status") or "").strip()
        if not task_id or status not in {
            "queued",
            "running",
            "succeeded",
            "failed",
            "canceled",
            "hold",
            "need_context",
            "interrupted",
            "superseded",
        }:
            return None
        return cls(
            task_id=task_id,
            seq=max(0, int(obj.get("seq") or 0)),
            task_idempotency_key=str(obj.get("task_idempotency_key") or task_id).strip() or task_id,
            status=status,  # type: ignore[arg-type]
            objective=str(obj.get("objective") or "").strip(),
            worker_task_id=str(obj.get("worker_task_id") or "").strip(),
            scope_summary=str(obj.get("scope_summary") or "").strip(),
            depends_on=tuple(_string_list(obj.get("depends_on"))),
            allowed_operator_refs=tuple(_string_list(obj.get("allowed_operator_refs"))),
            input_refs=tuple(_string_list(obj.get("input_refs"))),
            completion_contract_ref=str(obj.get("completion_contract_ref") or "").strip(),
            submission_id=str(obj.get("submission_id") or "").strip(),
            execution_lane=str(obj.get("execution_lane") or "standard_task").strip() or "standard_task",
            tool_budget=dict(obj.get("tool_budget") or {}),
            token_budget=dict(obj.get("token_budget") or {}),
            stop_policy=dict(obj.get("stop_policy") or {}),
            time_budget_ms=max(0, int(obj.get("time_budget_ms") or 0)),
            task_execution_policy=dict(obj.get("task_execution_policy") or {}),
            submitter=str(obj.get("submitter") or "").strip(),
            source_phase=str(obj.get("source_phase") or "").strip(),
            trace=dict(obj.get("trace") or {}),
            attempt=max(0, int(obj.get("attempt") or 0)),
            generation=max(1, int(obj.get("generation") or 1)),
            superseded_by_submission_id=(
                str(obj.get("superseded_by_submission_id")).strip()
                if obj.get("superseded_by_submission_id") is not None
                else None
            ),
            effect_class=_normalize_effect_class(obj.get("effect_class")),
            side_effect_boundary_reached=bool(obj.get("side_effect_boundary_reached")),
            result_ref=(str(obj.get("result_ref")).strip() if obj.get("result_ref") is not None else None),
            evidence_refs=tuple(_string_list(obj.get("evidence_refs"))),
            error_code=(str(obj.get("error_code")).strip() if obj.get("error_code") is not None else None),
            created_at_utc=str(obj.get("created_at_utc") or "").strip(),
            started_at_utc=(str(obj.get("started_at_utc")).strip() if obj.get("started_at_utc") is not None else None),
            ended_at_utc=(str(obj.get("ended_at_utc")).strip() if obj.get("ended_at_utc") is not None else None),
        )


@dataclass(frozen=True)
class TaskExecutionAttempt:
    attempt_id: str
    task_id: str
    attempt: int
    generation: int
    status: str
    started_at_utc: str
    ended_at_utc: str | None = None
    error_code: str | None = None
    result_ref: str | None = None
    evidence_refs: tuple[str, ...] = ()
    stale: bool = False

    def to_json(self) -> dict[str, Any]:
        return {
            "attempt_id": self.attempt_id,
            "task_id": self.task_id,
            "attempt": int(self.attempt),
            "generation": int(self.generation),
            "status": self.status,
            "started_at_utc": self.started_at_utc,
            "ended_at_utc": self.ended_at_utc,
            "error_code": self.error_code,
            "result_ref": self.result_ref,
            "evidence_refs": list(self.evidence_refs),
            "stale": bool(self.stale),
        }

    @classmethod
    def from_json(cls, obj: Any) -> Optional["TaskExecutionAttempt"]:
        if not isinstance(obj, dict):
            return None
        attempt_id = str(obj.get("attempt_id") or "").strip()
        task_id = str(obj.get("task_id") or "").strip()
        if not attempt_id or not task_id:
            return None
        return cls(
            attempt_id=attempt_id,
            task_id=task_id,
            attempt=max(0, int(obj.get("attempt") or 0)),
            generation=max(1, int(obj.get("generation") or 1)),
            status=str(obj.get("status") or "").strip() or "unknown",
            started_at_utc=str(obj.get("started_at_utc") or "").strip(),
            ended_at_utc=(str(obj.get("ended_at_utc")).strip() if obj.get("ended_at_utc") is not None else None),
            error_code=(str(obj.get("error_code")).strip() if obj.get("error_code") is not None else None),
            result_ref=(str(obj.get("result_ref")).strip() if obj.get("result_ref") is not None else None),
            evidence_refs=tuple(_string_list(obj.get("evidence_refs"))),
            stale=bool(obj.get("stale")),
        )


@dataclass(frozen=True)
class TaskExecutionEvent:
    event_id: str
    task_id: str
    attempt_id: str
    generation: int
    event_kind: str
    status: str
    operator_ref: str = ""
    sequence: int = 0
    evidence_refs: tuple[str, ...] = ()
    output_summary: str = ""
    error_code: str | None = None
    created_at_utc: str = ""
    extra: dict[str, Any] = field(default_factory=dict)
    stale: bool = False

    def to_json(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "task_id": self.task_id,
            "attempt_id": self.attempt_id,
            "generation": int(self.generation),
            "event_kind": self.event_kind,
            "status": self.status,
            "operator_ref": self.operator_ref,
            "sequence": int(self.sequence),
            "evidence_refs": list(self.evidence_refs),
            "output_summary": self.output_summary,
            "error_code": self.error_code,
            "created_at_utc": self.created_at_utc,
            "extra": dict(self.extra),
            "stale": bool(self.stale),
        }

    @classmethod
    def from_json(cls, obj: Any) -> Optional["TaskExecutionEvent"]:
        if not isinstance(obj, dict):
            return None
        event_id = str(obj.get("event_id") or "").strip()
        task_id = str(obj.get("task_id") or "").strip()
        attempt_id = str(obj.get("attempt_id") or "").strip()
        if not event_id or not task_id or not attempt_id:
            return None
        return cls(
            event_id=event_id,
            task_id=task_id,
            attempt_id=attempt_id,
            generation=max(1, int(obj.get("generation") or 1)),
            event_kind=str(obj.get("event_kind") or "").strip(),
            status=str(obj.get("status") or "").strip(),
            operator_ref=str(obj.get("operator_ref") or "").strip(),
            sequence=max(0, int(obj.get("sequence") or 0)),
            evidence_refs=tuple(_string_list(obj.get("evidence_refs"))),
            output_summary=str(obj.get("output_summary") or "").strip(),
            error_code=(str(obj.get("error_code")).strip() if obj.get("error_code") is not None else None),
            created_at_utc=str(obj.get("created_at_utc") or "").strip(),
            extra=dict(obj.get("extra") or {}),
            stale=bool(obj.get("stale")),
        )


@dataclass(frozen=True)
class TaskExecutionGraph:
    schema_version: str
    type: str
    workspace_id: str
    graph_id: str
    created_at_utc: str
    updated_at_utc: str
    next_task_num: int
    max_parallel_workers: int
    tasks: dict[str, TaskExecutionNode]
    attempts: list[TaskExecutionAttempt] = field(default_factory=list)
    events: list[TaskExecutionEvent] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "type": self.type,
            "workspace_id": self.workspace_id,
            "graph_id": self.graph_id,
            "created_at_utc": self.created_at_utc,
            "updated_at_utc": self.updated_at_utc,
            "next_task_num": int(self.next_task_num),
            "max_parallel_workers": int(self.max_parallel_workers),
            "tasks": [item.to_json() for item in sorted(self.tasks.values(), key=lambda value: (value.seq, value.task_id))],
            "attempts": [item.to_json() for item in self.attempts],
            "events": [item.to_json() for item in self.events],
        }

    @classmethod
    def from_json(cls, obj: Any) -> Optional["TaskExecutionGraph"]:
        if not isinstance(obj, dict):
            return None
        if str(obj.get("schema_version") or "") != TASK_EXECUTION_GRAPH_SCHEMA_VERSION:
            return None
        if str(obj.get("type") or "") != TASK_EXECUTION_GRAPH_TYPE:
            return None
        tasks_raw = obj.get("tasks")
        attempts_raw = obj.get("attempts")
        events_raw = obj.get("events")
        if not isinstance(tasks_raw, list) or not isinstance(attempts_raw, list) or not isinstance(events_raw, list):
            return None
        tasks: dict[str, TaskExecutionNode] = {}
        for item in tasks_raw:
            node = TaskExecutionNode.from_json(item)
            if node is None:
                return None
            tasks[node.task_id] = node
        attempts: list[TaskExecutionAttempt] = []
        for item in attempts_raw:
            attempt = TaskExecutionAttempt.from_json(item)
            if attempt is None:
                return None
            attempts.append(attempt)
        events: list[TaskExecutionEvent] = []
        for item in events_raw:
            event = TaskExecutionEvent.from_json(item)
            if event is None:
                return None
            events.append(event)
        return cls(
            schema_version=TASK_EXECUTION_GRAPH_SCHEMA_VERSION,
            type=TASK_EXECUTION_GRAPH_TYPE,
            workspace_id=str(obj.get("workspace_id") or "").strip(),
            graph_id=str(obj.get("graph_id") or "").strip(),
            created_at_utc=str(obj.get("created_at_utc") or "").strip(),
            updated_at_utc=str(obj.get("updated_at_utc") or "").strip(),
            next_task_num=max(0, int(obj.get("next_task_num") or 0)),
            max_parallel_workers=max(1, int(obj.get("max_parallel_workers") or 1)),
            tasks=tasks,
            attempts=attempts,
            events=events,
        )


@dataclass(frozen=True)
class TaskExecutionGraphError(RuntimeError):
    error_code: str
    message: str


class FileTaskExecutionGraphStore:
    def __init__(self, data_dir: str | os.PathLike[str] = "data") -> None:
        self._data_dir = Path(data_dir)
        self._root = (self._data_dir / "kernel" / "task_execution_graph").resolve()

    def _path(self, *, workspace_id: str, graph_id: str) -> Path:
        safe_ws = _safe_segment(workspace_id, fallback="default")
        safe_graph_id = _safe_segment(graph_id, fallback="graph")
        root = self._root
        path = (root / safe_ws / f"{safe_graph_id}.json").resolve()
        if not path.is_relative_to(root):
            raise ValueError("task execution graph path resolves outside root")
        return path

    def load(self, *, workspace_id: str, graph_id: str) -> TaskExecutionGraph | None:
        path = self._path(workspace_id=workspace_id, graph_id=graph_id)
        if not path.exists():
            return None
        try:
            obj = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise TaskExecutionGraphError(
                TASK_EXECUTION_GRAPH_ERROR_SCHEMA_INVALID,
                f"cannot read task execution graph: {exc}",
            ) from exc
        graph = TaskExecutionGraph.from_json(obj)
        if graph is None:
            raise TaskExecutionGraphError(
                TASK_EXECUTION_GRAPH_ERROR_SCHEMA_INVALID,
                "invalid task execution graph schema",
            )
        return graph

    def create_graph(
        self,
        *,
        workspace_id: str,
        graph_id: str,
        max_parallel_workers: int = 1,
        now_utc: str | None = None,
    ) -> TaskExecutionGraph:
        ts = str(now_utc or _utc_iso())
        graph = TaskExecutionGraph(
            schema_version=TASK_EXECUTION_GRAPH_SCHEMA_VERSION,
            type=TASK_EXECUTION_GRAPH_TYPE,
            workspace_id=str(workspace_id),
            graph_id=str(graph_id),
            created_at_utc=ts,
            updated_at_utc=ts,
            next_task_num=1,
            max_parallel_workers=max(1, int(max_parallel_workers)),
            tasks={},
            attempts=[],
            events=[],
        )
        self.save(graph)
        return graph

    def save(self, graph: TaskExecutionGraph) -> None:
        path = self._path(workspace_id=graph.workspace_id, graph_id=graph.graph_id)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                "w",
                encoding="utf-8",
                dir=str(path.parent),
                prefix=f"{path.stem}.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                json.dump(graph.to_json(), handle, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                handle.write("\n")
                tmp_path = Path(handle.name)
            tmp_path.replace(path)
        except Exception as exc:
            raise TaskExecutionGraphError(
                TASK_EXECUTION_GRAPH_ERROR_IO_FAILED,
                f"cannot write task execution graph: {exc}",
            ) from exc

    def load_or_create(
        self,
        *,
        workspace_id: str,
        graph_id: str,
        max_parallel_workers: int = 1,
        now_utc: str | None = None,
    ) -> TaskExecutionGraph:
        existing = self.load(workspace_id=workspace_id, graph_id=graph_id)
        if existing is not None:
            return existing
        return self.create_graph(
            workspace_id=workspace_id,
            graph_id=graph_id,
            max_parallel_workers=max_parallel_workers,
            now_utc=now_utc,
        )

    def recover_incomplete(self, graph: TaskExecutionGraph, *, now_utc: str | None = None) -> TaskExecutionGraph:
        ts = str(now_utc or _utc_iso())
        changed = False
        tasks = dict(graph.tasks)
        attempts = list(graph.attempts)
        for task_id, task in list(tasks.items()):
            if task.status != "running":
                continue
            recovered_status: TaskExecutionStatus = "queued"
            if str(task.superseded_by_submission_id or "").strip():
                recovered_status = "superseded"
            tasks[task_id] = replace(task, status=recovered_status, started_at_utc=None, error_code=None)
            changed = True
        updated_attempts: list[TaskExecutionAttempt] = []
        for attempt in attempts:
            if attempt.status == "running":
                updated_attempts.append(replace(attempt, status="interrupted", ended_at_utc=ts))
                changed = True
            else:
                updated_attempts.append(attempt)
        if not changed:
            return graph
        recovered = replace(graph, tasks=tasks, attempts=updated_attempts, updated_at_utc=ts)
        self.save(recovered)
        return recovered
