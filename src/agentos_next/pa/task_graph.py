from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, Optional

TASK_GRAPH_SCHEMA_VERSION: str = "1.1.0"
TASK_GRAPH_COMPAT_SCHEMA_VERSIONS: tuple[str, ...] = ("1.0.0", TASK_GRAPH_SCHEMA_VERSION)
RUNTIME_GRAPH_TYPE = "runtime_graph_v1"

TaskState = Literal["queued", "running", "waiting_context", "awaiting_leader", "succeeded", "failed", "interrupted"]
ContextEscalationMode = Literal["auto", "leader_gate"]
WorkerTaskAdmissionMode = Literal["auto_within_scope", "leader_gate"]
FileRefType = Literal["workspace_path", "evidence_ref", "artifact_ref"]
FileRefUsage = Literal["required", "optional", "hint"]
FileRefResolver = Literal["fs.read", "fs.list", "direct_ref"]

TASK_GRAPH_ERROR_SCHEMA_INVALID = "E_PA_TG_SCHEMA_INVALID"
TASK_GRAPH_ERROR_IO_FAILED = "E_PA_TG_IO_FAILED"
TASK_GRAPH_ERROR_REPLAY_DENY = "E_PA_TG_REPLAY_DENY"

# Reuse the frozen kernel error code for "same fingerprint repeated => block".
TASK_GRAPH_ERROR_CYCLE_DETECTED = "E_CYCLE_DETECTED"


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _canonical_json(obj: object) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _safe_segment(value: str, *, fallback: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return fallback
    if re.fullmatch(r"[A-Za-z0-9._-]{1,200}", raw):
        return raw
    return "h_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def compute_task_fingerprint(*, kind: str, payload: dict[str, Any]) -> str:
    """Compute a deterministic fingerprint for a task."""
    seed = _canonical_json({"kind": str(kind), "payload": payload}).encode("utf-8")
    return "fp_" + hashlib.sha256(seed).hexdigest()


def _normalize_string_list(raw: Any) -> list[str]:
    return [str(item).strip() for item in (raw or []) if str(item).strip()]


def _normalize_file_refs(raw: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if not isinstance(raw, list):
        return out
    for item in raw:
        if not isinstance(item, dict):
            continue
        ref_type = str(item.get("ref_type") or "").strip()
        value = str(item.get("value") or "").strip()
        if ref_type not in {"workspace_path", "evidence_ref", "artifact_ref"} or not value:
            continue
        usage = str(item.get("usage") or "hint").strip()
        resolver = str(item.get("resolver") or "direct_ref").strip()
        if usage not in {"required", "optional", "hint"}:
            usage = "hint"
        if resolver not in {"fs.read", "fs.list", "direct_ref"}:
            resolver = "direct_ref"
        summary = str(item.get("summary") or "").strip() or None
        out.append(
            {
                "schema_version": "1.0.0",
                "type": "file_ref_v1",
                "ref_type": ref_type,
                "value": value,
                "usage": usage,
                "summary": summary,
                "resolver": resolver,
            }
        )
    return out


def make_file_ref_v1(
    *,
    ref_type: FileRefType,
    value: str,
    usage: FileRefUsage = "hint",
    summary: str | None = None,
    resolver: FileRefResolver | None = None,
) -> dict[str, Any]:
    resolved_resolver = str(resolver or ("fs.read" if ref_type == "workspace_path" else "direct_ref")).strip()
    if resolved_resolver not in {"fs.read", "fs.list", "direct_ref"}:
        resolved_resolver = "direct_ref"
    return {
        "schema_version": "1.0.0",
        "type": "file_ref_v1",
        "ref_type": str(ref_type),
        "value": str(value).strip(),
        "usage": str(usage),
        "summary": (str(summary).strip() if str(summary or "").strip() else None),
        "resolver": resolved_resolver,
    }


def build_task_execution_policy_v1(
    *,
    deadline_ms: int,
    llm_timeout_ms: int | None = None,
    tool_timeout_ms: int | None = None,
    max_attempts: int = 2,
    side_effect_safe_retry: bool = False,
    llm_retry_policy: dict[str, Any] | None = None,
    tool_retry_policy: dict[str, Any] | None = None,
    backoff_policy: dict[str, Any] | None = None,
    deadline_mode: str = "compat_root_cap",
) -> dict[str, Any]:
    root_deadline_ms = max(1000, int(deadline_ms))
    llm_timeout = max(1000, int(llm_timeout_ms or min(root_deadline_ms, max(5000, root_deadline_ms // 2))))
    tool_timeout = max(1000, int(tool_timeout_ms or min(root_deadline_ms, max(3000, root_deadline_ms // 3))))
    bounded_attempts = max(1, int(max_attempts))
    return {
        "schema_version": "1.0.0",
        "type": "task_execution_policy_v1",
        "root_deadline_ms": root_deadline_ms,
        "llm_timeout_ms": min(root_deadline_ms, llm_timeout),
        "tool_timeout_ms": min(root_deadline_ms, tool_timeout),
        "llm_retry_policy": dict(llm_retry_policy or {"strategy": "bounded_retry", "max_retries": max(0, bounded_attempts - 1)}),
        "tool_retry_policy": dict(
            tool_retry_policy
            or {
                "strategy": "bounded_retry",
                "max_retries": 0 if not side_effect_safe_retry else max(0, bounded_attempts - 1),
            }
        ),
        "max_attempts": bounded_attempts,
        "backoff_policy": dict(backoff_policy or {"strategy": "linear", "initial_delay_ms": 250, "max_delay_ms": 1000}),
        "side_effect_safe_retry": bool(side_effect_safe_retry),
        "deadline_mode": str(deadline_mode or "compat_root_cap").strip() or "compat_root_cap",
    }


def build_task_bundle_v1(
    *,
    objective: str,
    completion_contract_ref: str,
    task_execution_policy: dict[str, Any],
    context_snapshot_ref: str,
    workspace_root: str,
    allowed_capabilities: list[str] | tuple[str, ...],
    file_refs: list[dict[str, Any]] | None = None,
    dependency_result_refs: list[str] | None = None,
    read_only_ancestor_context_refs: list[str] | None = None,
    context_escalation_mode: ContextEscalationMode = "auto",
    worker_task_admission_mode: WorkerTaskAdmissionMode = "leader_gate",
    bundle_generation: str = "aggressive",
    sufficient_for_execution: bool | None = None,
    task_mode: str = "atomic",
    delegation_budget: int = 0,
    max_depth: int = 0,
    scope_guard: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized_files = _normalize_file_refs(file_refs or [])
    dependency_refs = _normalize_string_list(dependency_result_refs)
    ancestor_refs = _normalize_string_list(read_only_ancestor_context_refs)
    if sufficient_for_execution is None:
        sufficient_for_execution = bool(objective and completion_contract_ref and context_snapshot_ref) and (
            not normalized_files or any(str(item.get("usage") or "") == "required" for item in normalized_files)
        )
    return {
        "schema_version": "1.0.0",
        "type": "task_bundle_v1",
        "objective": str(objective).strip(),
        "completion_contract_ref": str(completion_contract_ref).strip(),
        "task_execution_policy": dict(task_execution_policy or {}),
        "context_snapshot_ref": str(context_snapshot_ref).strip(),
        "file_refs": normalized_files,
        "dependency_result_refs": dependency_refs,
        "read_only_ancestor_context_refs": ancestor_refs,
        "workspace_root": str(workspace_root).strip(),
        "allowed_capabilities": _normalize_string_list(allowed_capabilities),
        "context_escalation_mode": str(context_escalation_mode),
        "worker_task_admission_mode": str(worker_task_admission_mode),
        "bundle_generation": str(bundle_generation or "aggressive").strip() or "aggressive",
        "sufficient_for_execution": bool(sufficient_for_execution),
        "task_mode": str(task_mode or "atomic").strip() or "atomic",
        "delegation_budget": max(0, int(delegation_budget)),
        "max_depth": max(0, int(max_depth)),
        "scope_guard": dict(scope_guard or {}),
    }


@dataclass(frozen=True)
class TaskNode:
    task_id: str
    seq: int
    parent_task_id: Optional[str]
    fingerprint: str
    state: TaskState
    created_at_utc: str
    updated_at_utc: str
    attempts: int
    payload: dict[str, Any]
    error_code: Optional[str]
    plan_revision: int = 0
    context_snapshot_ref: Optional[str] = None
    completion_contract_ref: Optional[str] = None
    task_bundle: Optional[dict[str, Any]] = None
    task_execution_policy: Optional[dict[str, Any]] = None
    file_refs: list[dict[str, Any]] = field(default_factory=list)
    dependency_result_refs: list[str] = field(default_factory=list)
    read_only_ancestor_context_refs: list[str] = field(default_factory=list)
    allowed_capabilities: list[str] = field(default_factory=list)
    workspace_root: Optional[str] = None
    context_escalation_mode: ContextEscalationMode = "auto"
    worker_task_admission_mode: WorkerTaskAdmissionMode = "leader_gate"
    sufficient_for_execution: Optional[bool] = None
    result_refs: list[str] = field(default_factory=list)
    superseded_by_revision: Optional[int] = None
    interruption_reason: Optional[str] = None

    def to_json(self) -> dict[str, Any]:
        out = {
            "task_id": self.task_id,
            "seq": int(self.seq),
            "parent_task_id": self.parent_task_id,
            "fingerprint": self.fingerprint,
            "state": self.state,
            "created_at_utc": self.created_at_utc,
            "updated_at_utc": self.updated_at_utc,
            "attempts": int(self.attempts),
            "payload": dict(self.payload),
            "error_code": self.error_code,
            "plan_revision": int(self.plan_revision),
            "context_snapshot_ref": self.context_snapshot_ref,
            "completion_contract_ref": self.completion_contract_ref,
            "task_bundle": (dict(self.task_bundle) if isinstance(self.task_bundle, dict) else None),
            "task_execution_policy": (
                dict(self.task_execution_policy) if isinstance(self.task_execution_policy, dict) else None
            ),
            "file_refs": _normalize_file_refs(self.file_refs),
            "dependency_result_refs": list(self.dependency_result_refs),
            "read_only_ancestor_context_refs": list(self.read_only_ancestor_context_refs),
            "allowed_capabilities": list(self.allowed_capabilities),
            "workspace_root": self.workspace_root,
            "context_escalation_mode": str(self.context_escalation_mode),
            "worker_task_admission_mode": str(self.worker_task_admission_mode),
            "sufficient_for_execution": self.sufficient_for_execution,
            "result_refs": list(self.result_refs),
            "superseded_by_revision": self.superseded_by_revision,
            "interruption_reason": self.interruption_reason,
        }
        return out

    @classmethod
    def from_json(cls, obj: Any) -> Optional["TaskNode"]:
        if not isinstance(obj, dict):
            return None
        state = obj.get("state")
        if state not in {"queued", "running", "waiting_context", "awaiting_leader", "succeeded", "failed", "interrupted"}:
            return None
        task_id = str(obj.get("task_id") or "").strip()
        if not task_id:
            return None
        fp = str(obj.get("fingerprint") or "").strip()
        if not fp:
            return None
        payload = obj.get("payload")
        if payload is None:
            payload = {}
        if not isinstance(payload, dict):
            return None
        parent = obj.get("parent_task_id")
        parent_task_id = str(parent).strip() if parent is not None else None
        task_bundle = obj.get("task_bundle")
        if task_bundle is not None and not isinstance(task_bundle, dict):
            return None
        task_execution_policy = obj.get("task_execution_policy")
        if task_execution_policy is not None and not isinstance(task_execution_policy, dict):
            return None
        context_mode = str(obj.get("context_escalation_mode") or "auto").strip() or "auto"
        if context_mode not in {"auto", "leader_gate"}:
            return None
        admission_mode = str(obj.get("worker_task_admission_mode") or "leader_gate").strip() or "leader_gate"
        if admission_mode not in {"auto_within_scope", "leader_gate"}:
            return None
        return cls(
            task_id=task_id,
            seq=int(obj.get("seq") or 0),
            parent_task_id=parent_task_id or None,
            fingerprint=fp,
            state=state,
            created_at_utc=str(obj.get("created_at_utc") or ""),
            updated_at_utc=str(obj.get("updated_at_utc") or ""),
            attempts=int(obj.get("attempts") or 0),
            payload=dict(payload),
            error_code=str(obj.get("error_code")) if obj.get("error_code") is not None else None,
            plan_revision=max(0, int(obj.get("plan_revision") or 0)),
            context_snapshot_ref=(
                str(obj.get("context_snapshot_ref")).strip()
                if obj.get("context_snapshot_ref") is not None and str(obj.get("context_snapshot_ref")).strip()
                else None
            ),
            completion_contract_ref=(
                str(obj.get("completion_contract_ref")).strip()
                if obj.get("completion_contract_ref") is not None and str(obj.get("completion_contract_ref")).strip()
                else None
            ),
            task_bundle=dict(task_bundle) if isinstance(task_bundle, dict) else None,
            task_execution_policy=dict(task_execution_policy) if isinstance(task_execution_policy, dict) else None,
            file_refs=_normalize_file_refs(obj.get("file_refs") or []),
            dependency_result_refs=_normalize_string_list(obj.get("dependency_result_refs")),
            read_only_ancestor_context_refs=_normalize_string_list(obj.get("read_only_ancestor_context_refs")),
            allowed_capabilities=_normalize_string_list(obj.get("allowed_capabilities")),
            workspace_root=(
                str(obj.get("workspace_root")).strip()
                if obj.get("workspace_root") is not None and str(obj.get("workspace_root")).strip()
                else None
            ),
            context_escalation_mode=context_mode,  # type: ignore[arg-type]
            worker_task_admission_mode=admission_mode,  # type: ignore[arg-type]
            sufficient_for_execution=(
                bool(obj.get("sufficient_for_execution"))
                if obj.get("sufficient_for_execution") is not None
                else None
            ),
            result_refs=_normalize_string_list(obj.get("result_refs")),
            superseded_by_revision=(
                max(0, int(obj.get("superseded_by_revision") or 0))
                if obj.get("superseded_by_revision") is not None
                else None
            ),
            interruption_reason=(
                str(obj.get("interruption_reason")).strip()
                if obj.get("interruption_reason") is not None and str(obj.get("interruption_reason")).strip()
                else None
            ),
        )


@dataclass(frozen=True)
class TaskGraph:
    schema_version: str
    type: str
    workspace_id: str
    graph_id: str
    created_at_utc: str
    updated_at_utc: str
    root_task_id: str
    cycle_threshold: int
    next_task_num: int
    active_plan_revision: int
    max_parallel_workers: int
    replan_count: int
    tasks: dict[str, TaskNode]
    message_turns: list[dict[str, Any]] = field(default_factory=list)
    plan_revisions: list[dict[str, Any]] = field(default_factory=list)
    context_snapshots: list[dict[str, Any]] = field(default_factory=list)
    result_capsules: list[dict[str, Any]] = field(default_factory=list)
    leader_decisions: list[dict[str, Any]] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        tasks_sorted = sorted(self.tasks.values(), key=lambda t: (int(t.seq), str(t.task_id)))
        return {
            "schema_version": self.schema_version,
            "type": self.type,
            "workspace_id": self.workspace_id,
            "graph_id": self.graph_id,
            "created_at_utc": self.created_at_utc,
            "updated_at_utc": self.updated_at_utc,
            "root_task_id": self.root_task_id,
            "cycle_threshold": int(self.cycle_threshold),
            "next_task_num": int(self.next_task_num),
            "active_plan_revision": int(self.active_plan_revision),
            "max_parallel_workers": int(self.max_parallel_workers),
            "replan_count": int(self.replan_count),
            "tasks": [t.to_json() for t in tasks_sorted],
            "message_turns": list(self.message_turns),
            "plan_revisions": list(self.plan_revisions),
            "context_snapshots": list(self.context_snapshots),
            "result_capsules": list(self.result_capsules),
            "leader_decisions": list(self.leader_decisions),
        }

    @classmethod
    def from_json(cls, obj: Any) -> Optional["TaskGraph"]:
        if not isinstance(obj, dict):
            return None
        if str(obj.get("schema_version") or "") not in TASK_GRAPH_COMPAT_SCHEMA_VERSIONS:
            return None
        tasks_raw = obj.get("tasks")
        if not isinstance(tasks_raw, list):
            return None
        tasks: dict[str, TaskNode] = {}
        for it in tasks_raw:
            node = TaskNode.from_json(it)
            if node is None:
                return None
            tasks[node.task_id] = node
        root_task_id = str(obj.get("root_task_id") or "").strip()
        if not root_task_id or root_task_id not in tasks:
            return None
        cycle_threshold = int(obj.get("cycle_threshold") or 2)
        if cycle_threshold < 2:
            return None
        next_task_num = int(obj.get("next_task_num") or 1)
        type_value = str(obj.get("type") or RUNTIME_GRAPH_TYPE).strip() or RUNTIME_GRAPH_TYPE
        if type_value != RUNTIME_GRAPH_TYPE:
            return None
        message_turns = obj.get("message_turns") or []
        plan_revisions = obj.get("plan_revisions") or []
        context_snapshots = obj.get("context_snapshots") or []
        result_capsules = obj.get("result_capsules") or []
        leader_decisions = obj.get("leader_decisions") or []
        if not all(isinstance(value, list) for value in (message_turns, plan_revisions, context_snapshots, result_capsules, leader_decisions)):
            return None
        return cls(
            schema_version=TASK_GRAPH_SCHEMA_VERSION,
            type=type_value,
            workspace_id=str(obj.get("workspace_id") or ""),
            graph_id=str(obj.get("graph_id") or ""),
            created_at_utc=str(obj.get("created_at_utc") or ""),
            updated_at_utc=str(obj.get("updated_at_utc") or ""),
            root_task_id=root_task_id,
            cycle_threshold=cycle_threshold,
            next_task_num=next_task_num,
            active_plan_revision=max(0, int(obj.get("active_plan_revision") or 0)),
            max_parallel_workers=max(1, int(obj.get("max_parallel_workers") or 1)),
            replan_count=max(0, int(obj.get("replan_count") or 0)),
            tasks=tasks,
            message_turns=[dict(item) for item in message_turns if isinstance(item, dict)],
            plan_revisions=[dict(item) for item in plan_revisions if isinstance(item, dict)],
            context_snapshots=[dict(item) for item in context_snapshots if isinstance(item, dict)],
            result_capsules=[dict(item) for item in result_capsules if isinstance(item, dict)],
            leader_decisions=[dict(item) for item in leader_decisions if isinstance(item, dict)],
        )


@dataclass(frozen=True)
class TaskGraphError(RuntimeError):
    error_code: str
    message: str

    def to_json(self) -> dict[str, Any]:
        return {"ok": False, "error_code": self.error_code, "message": self.message}


class FileTaskGraphStore:
    """THREAD-042: file-backed task graph snapshots.

    Layout (relative to data_dir):
    - pa/task_graph/<workspace_id>/<graph_id>.json
    """

    def __init__(self, data_dir: str | os.PathLike[str] = "data") -> None:
        self._data_dir = Path(data_dir)
        self._root = (self._data_dir / "pa" / "task_graph").resolve()

    def _path(self, *, workspace_id: str, graph_id: str) -> Path:
        safe_ws = _safe_segment(workspace_id, fallback="default")
        safe_gid = _safe_segment(graph_id, fallback="missing")
        root = self._root
        p = (root / safe_ws / f"{safe_gid}.json").resolve()
        if not p.is_relative_to(root):
            raise ValueError("task graph path resolves outside task_graph root")
        return p

    def load(self, *, workspace_id: str, graph_id: str) -> TaskGraph | None:
        p = self._path(workspace_id=workspace_id, graph_id=graph_id)
        if not p.exists():
            return None
        try:
            obj = json.loads(p.read_text(encoding="utf-8"))
        except Exception as e:
            raise TaskGraphError(TASK_GRAPH_ERROR_SCHEMA_INVALID, f"cannot read task graph: {e}") from e
        g = TaskGraph.from_json(obj)
        if g is None:
            raise TaskGraphError(TASK_GRAPH_ERROR_SCHEMA_INVALID, "invalid task graph schema")
        return g

    def create_root_graph(
        self,
        *,
        workspace_id: str,
        graph_id: str,
        root_fingerprint: str,
        root_payload: dict[str, Any],
        cycle_threshold: int = 2,
        replay_mode: bool = False,
        now_utc: Optional[str] = None,
    ) -> TaskGraph:
        if replay_mode:
            raise TaskGraphError(TASK_GRAPH_ERROR_REPLAY_DENY, "replay mode forbids task graph writes")
        if cycle_threshold < 2:
            raise TaskGraphError(TASK_GRAPH_ERROR_SCHEMA_INVALID, "cycle_threshold must be >=2")
        ts = str(now_utc or _utc_iso())
        root_id = "task_0"
        root = TaskNode(
            task_id=root_id,
            seq=0,
            parent_task_id=None,
            fingerprint=str(root_fingerprint),
            state="queued",
            created_at_utc=ts,
            updated_at_utc=ts,
            attempts=0,
            payload=dict(root_payload),
            error_code=None,
        )
        g = TaskGraph(
            schema_version=TASK_GRAPH_SCHEMA_VERSION,
            type=RUNTIME_GRAPH_TYPE,
            workspace_id=str(workspace_id),
            graph_id=str(graph_id),
            created_at_utc=ts,
            updated_at_utc=ts,
            root_task_id=root_id,
            cycle_threshold=int(cycle_threshold),
            next_task_num=1,
            active_plan_revision=0,
            max_parallel_workers=1,
            replan_count=0,
            tasks={root_id: root},
        )
        self._write_once(workspace_id=workspace_id, graph_id=graph_id, obj=g.to_json())
        return g

    def save(self, *, graph: TaskGraph, replay_mode: bool = False) -> None:
        if replay_mode:
            raise TaskGraphError(TASK_GRAPH_ERROR_REPLAY_DENY, "replay mode forbids task graph writes")
        p = self._path(workspace_id=graph.workspace_id, graph_id=graph.graph_id)
        p.parent.mkdir(parents=True, exist_ok=True)
        text = _canonical_json(graph.to_json()) + "\n"
        _write_atomic(p, text)

    def load_or_create(
        self,
        *,
        workspace_id: str,
        graph_id: str,
        root_fingerprint: str,
        root_payload: dict[str, Any],
        cycle_threshold: int = 2,
        replay_mode: bool = False,
        now_utc: Optional[str] = None,
    ) -> TaskGraph:
        g = self.load(workspace_id=workspace_id, graph_id=graph_id)
        if g is not None:
            return g
        return self.create_root_graph(
            workspace_id=workspace_id,
            graph_id=graph_id,
            root_fingerprint=root_fingerprint,
            root_payload=root_payload,
            cycle_threshold=cycle_threshold,
            replay_mode=replay_mode,
            now_utc=now_utc,
        )

    def _write_once(self, *, workspace_id: str, graph_id: str, obj: dict[str, Any]) -> None:
        p = self._path(workspace_id=workspace_id, graph_id=graph_id)
        p.parent.mkdir(parents=True, exist_ok=True)
        text = _canonical_json(obj) + "\n"
        try:
            with p.open("x", encoding="utf-8") as f:
                f.write(text)
        except FileExistsError:
            # Graph already exists; caller should load instead.
            raise
        except Exception as e:
            raise TaskGraphError(TASK_GRAPH_ERROR_IO_FAILED, f"cannot write task graph: {e}") from e


def _write_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        try:
            if os.path.exists(tmp):
                os.unlink(tmp)
        except Exception:
            pass


def _fingerprint_count(graph: TaskGraph, fingerprint: str) -> int:
    fp = str(fingerprint)
    return sum(1 for t in graph.tasks.values() if t.fingerprint == fp)


def add_task(
    *,
    graph: TaskGraph,
    fingerprint: str,
    payload: dict[str, Any],
    parent_task_id: Optional[str] = None,
    now_utc: Optional[str] = None,
    plan_revision: int | None = None,
    task_bundle: dict[str, Any] | None = None,
    task_execution_policy: dict[str, Any] | None = None,
    context_snapshot_ref: str | None = None,
    completion_contract_ref: str | None = None,
    file_refs: list[dict[str, Any]] | None = None,
    dependency_result_refs: list[str] | None = None,
    read_only_ancestor_context_refs: list[str] | None = None,
    allowed_capabilities: list[str] | None = None,
    workspace_root: str | None = None,
    context_escalation_mode: ContextEscalationMode = "auto",
    worker_task_admission_mode: WorkerTaskAdmissionMode = "leader_gate",
    sufficient_for_execution: bool | None = None,
) -> TaskGraph:
    """Pure function: return an updated graph with one new queued task, or raise TaskGraphError."""
    if _fingerprint_count(graph, fingerprint) + 1 >= int(graph.cycle_threshold):
        raise TaskGraphError(TASK_GRAPH_ERROR_CYCLE_DETECTED, "cycle detected: fingerprint threshold reached")
    ts = str(now_utc or _utc_iso())
    task_id = f"task_{int(graph.next_task_num)}"
    node = TaskNode(
        task_id=task_id,
        seq=int(graph.next_task_num),
        parent_task_id=(str(parent_task_id).strip() if parent_task_id else None),
        fingerprint=str(fingerprint),
        state="queued",
        created_at_utc=ts,
        updated_at_utc=ts,
        attempts=0,
        payload=dict(payload),
        error_code=None,
        plan_revision=max(0, int(plan_revision if plan_revision is not None else graph.active_plan_revision)),
        context_snapshot_ref=(str(context_snapshot_ref).strip() if str(context_snapshot_ref or "").strip() else None),
        completion_contract_ref=(str(completion_contract_ref).strip() if str(completion_contract_ref or "").strip() else None),
        task_bundle=(dict(task_bundle) if isinstance(task_bundle, dict) else None),
        task_execution_policy=(dict(task_execution_policy) if isinstance(task_execution_policy, dict) else None),
        file_refs=_normalize_file_refs(file_refs or []),
        dependency_result_refs=_normalize_string_list(dependency_result_refs),
        read_only_ancestor_context_refs=_normalize_string_list(read_only_ancestor_context_refs),
        allowed_capabilities=_normalize_string_list(allowed_capabilities),
        workspace_root=(str(workspace_root).strip() if str(workspace_root or "").strip() else None),
        context_escalation_mode=context_escalation_mode,
        worker_task_admission_mode=worker_task_admission_mode,
        sufficient_for_execution=sufficient_for_execution,
    )
    tasks = dict(graph.tasks)
    tasks[task_id] = node
    return replace(
        graph,
        updated_at_utc=ts,
        next_task_num=int(graph.next_task_num) + 1,
        tasks=tasks,
    )


_UNSET = object()


def update_task_runtime_metadata(
    *,
    graph: TaskGraph,
    task_id: str,
    now_utc: Optional[str] = None,
    plan_revision: int | None = None,
    context_snapshot_ref: str | None = None,
    completion_contract_ref: str | None = None,
    task_bundle: dict[str, Any] | None = None,
    task_execution_policy: dict[str, Any] | None = None,
    file_refs: list[dict[str, Any]] | None = None,
    dependency_result_refs: list[str] | None = None,
    read_only_ancestor_context_refs: list[str] | None = None,
    allowed_capabilities: list[str] | None = None,
    workspace_root: str | None = None,
    context_escalation_mode: ContextEscalationMode | None = None,
    worker_task_admission_mode: WorkerTaskAdmissionMode | None = None,
    sufficient_for_execution: bool | object = _UNSET,
    result_refs: list[str] | None = None,
) -> TaskGraph:
    tid = str(task_id).strip()
    if not tid or tid not in graph.tasks:
        raise TaskGraphError(TASK_GRAPH_ERROR_SCHEMA_INVALID, "unknown task_id")
    ts = str(now_utc or _utc_iso())
    node = graph.tasks[tid]
    updated = replace(
        node,
        updated_at_utc=ts,
        plan_revision=(max(0, int(plan_revision)) if plan_revision is not None else node.plan_revision),
        context_snapshot_ref=(
            str(context_snapshot_ref).strip()
            if str(context_snapshot_ref or "").strip()
            else node.context_snapshot_ref
        ),
        completion_contract_ref=(
            str(completion_contract_ref).strip()
            if str(completion_contract_ref or "").strip()
            else node.completion_contract_ref
        ),
        task_bundle=(dict(task_bundle) if isinstance(task_bundle, dict) else node.task_bundle),
        task_execution_policy=(
            dict(task_execution_policy)
            if isinstance(task_execution_policy, dict)
            else node.task_execution_policy
        ),
        file_refs=(_normalize_file_refs(file_refs) if file_refs is not None else list(node.file_refs)),
        dependency_result_refs=(
            _normalize_string_list(dependency_result_refs)
            if dependency_result_refs is not None
            else list(node.dependency_result_refs)
        ),
        read_only_ancestor_context_refs=(
            _normalize_string_list(read_only_ancestor_context_refs)
            if read_only_ancestor_context_refs is not None
            else list(node.read_only_ancestor_context_refs)
        ),
        allowed_capabilities=(
            _normalize_string_list(allowed_capabilities)
            if allowed_capabilities is not None
            else list(node.allowed_capabilities)
        ),
        workspace_root=(
            str(workspace_root).strip()
            if str(workspace_root or "").strip()
            else node.workspace_root
        ),
        context_escalation_mode=(context_escalation_mode or node.context_escalation_mode),
        worker_task_admission_mode=(worker_task_admission_mode or node.worker_task_admission_mode),
        sufficient_for_execution=(
            bool(sufficient_for_execution)
            if sufficient_for_execution is not _UNSET
            else node.sufficient_for_execution
        ),
        result_refs=(
            _normalize_string_list(result_refs)
            if result_refs is not None
            else list(node.result_refs)
        ),
    )
    tasks = dict(graph.tasks)
    tasks[tid] = updated
    return replace(graph, updated_at_utc=ts, tasks=tasks)


def set_graph_runtime_controls(
    *,
    graph: TaskGraph,
    now_utc: Optional[str] = None,
    active_plan_revision: int | None = None,
    max_parallel_workers: int | None = None,
    replan_count: int | None = None,
) -> TaskGraph:
    ts = str(now_utc or _utc_iso())
    return replace(
        graph,
        updated_at_utc=ts,
        active_plan_revision=(
            max(0, int(active_plan_revision))
            if active_plan_revision is not None
            else graph.active_plan_revision
        ),
        max_parallel_workers=(
            max(1, int(max_parallel_workers))
            if max_parallel_workers is not None
            else graph.max_parallel_workers
        ),
        replan_count=(
            max(0, int(replan_count))
            if replan_count is not None
            else graph.replan_count
        ),
    )


def _upsert_graph_record(records: list[dict[str, Any]], record: dict[str, Any]) -> list[dict[str, Any]]:
    normalized = dict(record)
    record_id = str(normalized.get("id") or "").strip()
    if not record_id:
        return [*list(records), normalized]
    out: list[dict[str, Any]] = []
    replaced = False
    for item in records:
        if not isinstance(item, dict):
            continue
        if str(item.get("id") or "").strip() == record_id:
            out.append(normalized)
            replaced = True
        else:
            out.append(dict(item))
    if not replaced:
        out.append(normalized)
    return out


def append_message_turn(*, graph: TaskGraph, record: dict[str, Any], now_utc: Optional[str] = None) -> TaskGraph:
    ts = str(now_utc or _utc_iso())
    return replace(
        graph,
        updated_at_utc=ts,
        message_turns=_upsert_graph_record(list(graph.message_turns), record),
    )


def append_plan_revision(*, graph: TaskGraph, record: dict[str, Any], now_utc: Optional[str] = None) -> TaskGraph:
    ts = str(now_utc or _utc_iso())
    return replace(
        graph,
        updated_at_utc=ts,
        plan_revisions=_upsert_graph_record(list(graph.plan_revisions), record),
    )


def append_context_snapshot(*, graph: TaskGraph, record: dict[str, Any], now_utc: Optional[str] = None) -> TaskGraph:
    ts = str(now_utc or _utc_iso())
    return replace(
        graph,
        updated_at_utc=ts,
        context_snapshots=_upsert_graph_record(list(graph.context_snapshots), record),
    )


def append_result_capsule(*, graph: TaskGraph, record: dict[str, Any], now_utc: Optional[str] = None) -> TaskGraph:
    ts = str(now_utc or _utc_iso())
    return replace(
        graph,
        updated_at_utc=ts,
        result_capsules=_upsert_graph_record(list(graph.result_capsules), record),
    )


def append_leader_decision(*, graph: TaskGraph, record: dict[str, Any], now_utc: Optional[str] = None) -> TaskGraph:
    ts = str(now_utc or _utc_iso())
    return replace(
        graph,
        updated_at_utc=ts,
        leader_decisions=_upsert_graph_record(list(graph.leader_decisions), record),
    )


def set_task_state(
    *,
    graph: TaskGraph,
    task_id: str,
    state: TaskState,
    error_code: Optional[str] = None,
    now_utc: Optional[str] = None,
    superseded_by_revision: Optional[int] = None,
    interruption_reason: Optional[str] = None,
    result_refs: list[str] | None = None,
) -> TaskGraph:
    """Pure function: update a task state, or raise TaskGraphError."""
    tid = str(task_id).strip()
    if not tid or tid not in graph.tasks:
        raise TaskGraphError(TASK_GRAPH_ERROR_SCHEMA_INVALID, "unknown task_id")
    ts = str(now_utc or _utc_iso())
    node = graph.tasks[tid]
    updated = replace(
        node,
        state=state,
        updated_at_utc=ts,
        error_code=error_code,
        superseded_by_revision=superseded_by_revision if superseded_by_revision is not None else node.superseded_by_revision,
        interruption_reason=(
            str(interruption_reason).strip()
            if str(interruption_reason or "").strip()
            else node.interruption_reason
        ),
        result_refs=(
            _normalize_string_list(result_refs)
            if result_refs is not None
            else list(node.result_refs)
        ),
    )
    tasks = dict(graph.tasks)
    tasks[tid] = updated
    return replace(graph, updated_at_utc=ts, tasks=tasks)


def get_ready_tasks(graph: TaskGraph) -> list[TaskNode]:
    """Identify all tasks that can be executed now."""
    candidates = []
    for t in graph.tasks.values():
        if t.state != "queued":
            continue
        
        # Dependency: Child nodes only run if parent succeeded.
        parent_ok = True
        if t.parent_task_id:
            parent = graph.tasks.get(t.parent_task_id)
            if not parent or parent.state != "succeeded":
                parent_ok = False
        
        if parent_ok:
            candidates.append(t)
            
    if not candidates:
        return []

    ready = []
    for t in candidates:
        # Barrier rule: 'aggregate_reasoning' waits for sibling actions in its block.
        # This is strictly to ensure the summary has data to look at.
        is_barrier = t.payload.get("type") == "aggregate_reasoning"
        if is_barrier:
            siblings_busy = False
            for s in graph.tasks.values():
                if s.task_id == t.task_id: continue
                if s.parent_task_id == t.parent_task_id:
                    if s.payload.get("type") == "action" and s.state in ("queued", "running"):
                        siblings_busy = True
                        break
            if siblings_busy:
                continue
        
        ready.append(t)

    ready.sort(key=lambda t: (int(t.seq), str(t.task_id)))
    return ready


def next_queued_task(graph: TaskGraph) -> TaskNode | None:
    """Return the next single task to run (legacy compatibility)."""
    ready = get_ready_tasks(graph)
    return ready[0] if ready else None


def recover_incomplete(graph: TaskGraph, *, now_utc: Optional[str] = None) -> TaskGraph:
    """Pure function: reset running -> queued so execution can resume after a crash."""
    ts = str(now_utc or _utc_iso())
    changed = False
    tasks: dict[str, TaskNode] = dict(graph.tasks)
    for tid, node in list(tasks.items()):
        if node.state == "running":
            tasks[tid] = replace(node, state="queued", updated_at_utc=ts, attempts=int(node.attempts) + 1)
            changed = True
    if not changed:
        return graph
    return replace(graph, updated_at_utc=ts, tasks=tasks)
