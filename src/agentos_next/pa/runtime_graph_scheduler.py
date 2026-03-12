from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agentos_next.pa.task_graph import (
    FileTaskGraphStore,
    TaskGraph,
    add_task,
    append_context_snapshot,
    append_leader_decision,
    append_message_turn,
    append_plan_revision,
    append_result_capsule,
    compute_task_fingerprint,
    recover_incomplete,
    set_graph_runtime_controls,
    set_task_state,
    update_task_runtime_metadata,
)


def _string_list(raw: Any) -> list[str]:
    return [str(item).strip() for item in (raw or []) if str(item).strip()]


def _dict_list(raw: Any) -> list[dict[str, Any]]:
    return [dict(item) for item in (raw or []) if isinstance(item, dict)]


def _context_escalation_mode(task_bundle: dict[str, Any]) -> str:
    return str(task_bundle.get("context_escalation_mode") or "auto").strip() or "auto"


def _worker_task_admission_mode(task_bundle: dict[str, Any]) -> str:
    return str(task_bundle.get("worker_task_admission_mode") or "leader_gate").strip() or "leader_gate"


@dataclass(frozen=True)
class RuntimeGraphSchedulerBootstrap:
    data_dir: str
    workspace_id: str
    graph_id: str
    logical_task_id: str
    query: str
    objective: str
    trace_id: str
    turn_id: str
    conversation_id: str = ""
    interaction_mode: str = "task"
    query_ref: str = ""
    active_plan_revision: int = 0
    task_bundle: dict[str, Any] | None = None
    task_execution_policy: dict[str, Any] | None = None
    file_refs: tuple[dict[str, Any], ...] = ()
    now_utc: str | None = None


class DurableRuntimeGraphScheduler:
    """Single-writer durable scheduler backed by RuntimeGraph snapshots."""

    def __init__(
        self,
        *,
        store: FileTaskGraphStore,
        graph: TaskGraph,
        task_bundle: dict[str, Any] | None = None,
        task_execution_policy: dict[str, Any] | None = None,
        file_refs: list[dict[str, Any]] | None = None,
    ) -> None:
        self._store = store
        self._graph = graph
        self._task_bundle = dict(task_bundle or {})
        self._task_execution_policy = dict(task_execution_policy or {})
        self._file_refs = _dict_list(file_refs or [])
        self._worker_task_ids: dict[str, str] = {}
        self._worker_result_refs: dict[str, str] = {}
        self._action_task_ids: dict[str, str] = {}
        self._action_result_refs: dict[str, str] = {}
        self._rebuild_indexes()

    @classmethod
    def bootstrap_for_assistant_loop(
        cls,
        bootstrap: RuntimeGraphSchedulerBootstrap,
    ) -> "DurableRuntimeGraphScheduler":
        store = FileTaskGraphStore(bootstrap.data_dir)
        task_bundle = dict(bootstrap.task_bundle or {})
        task_execution_policy = dict(bootstrap.task_execution_policy or {})
        file_refs = _dict_list(bootstrap.file_refs)
        graph = store.load_or_create(
            workspace_id=str(bootstrap.workspace_id),
            graph_id=str(bootstrap.graph_id),
            root_fingerprint=compute_task_fingerprint(
                kind="assistant_loop_root",
                payload={
                    "graph_id": str(bootstrap.graph_id),
                    "trace_id": str(bootstrap.trace_id),
                    "turn_id": str(bootstrap.turn_id),
                },
            ),
            root_payload={
                "type": "assistant_loop_root",
                "logical_task_id": str(bootstrap.logical_task_id),
                "query": str(bootstrap.query),
                "objective": str(bootstrap.objective),
                "trace_id": str(bootstrap.trace_id),
                "turn_id": str(bootstrap.turn_id),
                "conversation_id": str(bootstrap.conversation_id or ""),
                "interaction_mode": str(bootstrap.interaction_mode or "task"),
            },
            replay_mode=False,
            now_utc=bootstrap.now_utc,
        )
        recovered = recover_incomplete(graph, now_utc=bootstrap.now_utc)
        if recovered is not graph:
            store.save(graph=recovered, replay_mode=False)
            graph = recovered
        scheduler = cls(
            store=store,
            graph=graph,
            task_bundle=task_bundle,
            task_execution_policy=task_execution_policy,
            file_refs=file_refs,
        )
        scheduler._bootstrap_root(bootstrap=bootstrap)
        return scheduler

    @staticmethod
    def build_record_id(prefix: str, *parts: Any) -> str:
        suffix = ":".join(str(part).strip() for part in parts if str(part).strip())
        return f"{prefix}:{suffix}" if suffix else prefix

    @property
    def graph_id(self) -> str:
        return str(self._graph.graph_id)

    @property
    def root_task_id(self) -> str:
        return str(self._graph.root_task_id)

    @property
    def active_plan_revision(self) -> int:
        return int(self._graph.active_plan_revision)

    @property
    def replan_count(self) -> int:
        return int(self._graph.replan_count)

    def record_compile_failure(
        self,
        *,
        error_code: str,
        query_ref: str,
        verification_ref: str,
    ) -> None:
        self._graph = append_leader_decision(
            graph=self._graph,
            record={
                "id": "leader:compile",
                "phase": "query_compile",
                "status": "failed",
                "error_code": str(error_code),
                "query_ref": str(query_ref),
                "verification_ref": str(verification_ref),
            },
        )
        self._graph = set_task_state(
            graph=self._graph,
            task_id=self.root_task_id,
            state="failed",
            error_code=str(error_code),
            result_refs=[str(query_ref), str(verification_ref)],
        )
        self._save()

    def set_task_state(
        self,
        *,
        task_id: str,
        state: str,
        error_code: str | None = None,
        result_refs: list[str] | None = None,
        interruption_reason: str | None = None,
    ) -> None:
        self._graph = set_task_state(
            graph=self._graph,
            task_id=str(task_id),
            state=state,  # type: ignore[arg-type]
            error_code=(str(error_code) if error_code else None),
            result_refs=result_refs,
            interruption_reason=interruption_reason,
        )
        self._save()

    def append_plan_revision(self, *, record: dict[str, Any]) -> None:
        self._graph = append_plan_revision(graph=self._graph, record=dict(record))
        self._save()

    def advance_plan_revision(self, *, record: dict[str, Any]) -> int:
        next_revision = int(self._graph.active_plan_revision) + 1
        self._graph = set_graph_runtime_controls(
            graph=self._graph,
            active_plan_revision=next_revision,
            replan_count=int(self._graph.replan_count) + 1,
        )
        payload = dict(record)
        payload["id"] = str(payload.get("id") or f"revision:{next_revision}")
        payload["plan_revision"] = next_revision
        self._graph = append_plan_revision(graph=self._graph, record=payload)
        self._save()
        return next_revision

    def record_step(
        self,
        *,
        task_id: str,
        step_summary: dict[str, Any],
        output_summary: str = "",
        leader_phase: str | None = None,
        phase_status: str | None = None,
    ) -> None:
        runtime_task_id = str(task_id).strip()
        if not runtime_task_id:
            return
        runtime_role = str(step_summary.get("runtime_role") or "").strip()
        capsule_id = self.build_record_id("capsule", runtime_task_id, int(step_summary.get("i") or 0))
        result_refs = _string_list(step_summary.get("evidence_refs") or [])
        status = str(step_summary.get("status") or "").strip()
        error_code = str(step_summary.get("error_code") or "").strip() or None
        runtime_state = "running"
        if runtime_task_id != self.root_task_id:
            runtime_state = (
                "succeeded"
                if status == "accepted"
                else ("awaiting_leader" if error_code == "E_HITL_REQUIRED" else "failed")
            )
        elif status != "accepted":
            runtime_state = "awaiting_leader" if error_code == "E_HITL_REQUIRED" else "failed"
        self._graph = set_task_state(
            graph=self._graph,
            task_id=runtime_task_id,
            state=runtime_state,  # type: ignore[arg-type]
            error_code=error_code,
            result_refs=result_refs,
        )
        self._graph = append_result_capsule(
            graph=self._graph,
            record={
                "id": capsule_id,
                "task_id": runtime_task_id,
                "operator_ref": str(step_summary.get("operator_ref") or ""),
                "runtime_role": runtime_role,
                "status": status,
                "error_code": str(step_summary.get("error_code") or ""),
                "deadline_ms": int(step_summary.get("deadline_ms") or 0),
                "evidence_refs": result_refs,
                "output_summary": str(output_summary or "").strip(),
            },
        )
        if runtime_role == "leader" and str(leader_phase or "").strip():
            self._graph = append_leader_decision(
                graph=self._graph,
                record={
                    "id": self.build_record_id("leader", leader_phase, int(step_summary.get("i") or 0)),
                    "phase": str(leader_phase),
                    "step_index": int(step_summary.get("i") or 0),
                    "runtime_role": "leader",
                    "status": status,
                    "error_code": str(step_summary.get("error_code") or ""),
                    "deadline_ms": int(step_summary.get("deadline_ms") or 0),
                    "evidence_refs": result_refs,
                    "phase_status": str(phase_status or "").strip(),
                },
            )
        self._save()

    def ensure_worker_task(
        self,
        *,
        worker_task_id: str,
        objective: str,
        depends_on: list[str],
        allowed_operator_refs: list[str],
        scope_summary: str,
        completion_contract_ref: str,
        tool_budget: dict[str, Any] | None,
        time_budget_ms: int,
        source_phase: str = "planner",
    ) -> str:
        worker_key = self.build_record_id("worker", source_phase, worker_task_id)
        existing = self._worker_task_ids.get(worker_key)
        if existing:
            return existing
        dependency_result_refs = [
            str(self._worker_result_refs.get(dep) or "").strip()
            for dep in depends_on
            if str(self._worker_result_refs.get(dep) or "").strip()
        ]
        child_bundle = dict(self._task_bundle or {})
        child_bundle["objective"] = str(objective).strip()
        child_bundle["allowed_operator_refs"] = _string_list(allowed_operator_refs)
        child_bundle["scope_summary"] = str(scope_summary or "").strip()
        child_bundle["tool_budget"] = dict(tool_budget or {})
        child_bundle["time_budget_ms"] = int(time_budget_ms or 0)
        child_bundle["parent_runtime_role"] = "worker"
        self._graph = add_task(
            graph=self._graph,
            fingerprint=compute_task_fingerprint(
                kind="worker_task",
                payload={
                    "source_phase": str(source_phase),
                    "worker_task_id": str(worker_task_id),
                    "objective": str(objective),
                },
            ),
            payload={
                "type": "worker_task",
                "worker_task_id": str(worker_task_id),
                "source_phase": str(source_phase),
                "objective": str(objective).strip(),
                "depends_on": list(depends_on),
                "allowed_operator_refs": _string_list(allowed_operator_refs),
                "scope_summary": str(scope_summary or "").strip(),
                "tool_budget": dict(tool_budget or {}),
                "time_budget_ms": int(time_budget_ms or 0),
            },
            parent_task_id=self.root_task_id,
            plan_revision=int(self._graph.active_plan_revision),
            task_bundle=child_bundle,
            task_execution_policy=(self._task_execution_policy if self._task_execution_policy else None),
            context_snapshot_ref=str(self._task_bundle.get("context_snapshot_ref") or ""),
            completion_contract_ref=str(completion_contract_ref or ""),
            file_refs=_dict_list(self._file_refs),
            dependency_result_refs=dependency_result_refs,
            read_only_ancestor_context_refs=_string_list(self._task_bundle.get("read_only_ancestor_context_refs") or []),
            allowed_capabilities=_string_list(self._task_bundle.get("allowed_capabilities") or []),
            workspace_root=str(self._task_bundle.get("workspace_root") or ""),
            context_escalation_mode=_context_escalation_mode(self._task_bundle),  # type: ignore[arg-type]
            worker_task_admission_mode=_worker_task_admission_mode(self._task_bundle),  # type: ignore[arg-type]
            sufficient_for_execution=bool(self._task_bundle.get("sufficient_for_execution")),
        )
        child_task_id = f"task_{int(self._graph.next_task_num) - 1}"
        self._worker_task_ids[worker_key] = child_task_id
        self._save()
        return child_task_id

    def record_worker_event(
        self,
        *,
        task_id: str,
        worker_task_id: str,
        event_kind: str,
        status: str,
        evidence_refs: list[str] | None = None,
        output_summary: str = "",
        operator_ref: str = "",
        error_code: str | None = None,
        event_id: str = "",
        sequence: int = 0,
        extra: dict[str, Any] | None = None,
    ) -> str:
        runtime_task_id = str(task_id).strip()
        worker_id = str(worker_task_id).strip()
        if not runtime_task_id or not worker_id:
            return ""
        capsule_id = self.build_record_id(
            "capsule",
            runtime_task_id,
            str(event_kind or "worker_event").strip() or "worker_event",
            str(event_id or sequence or len(self._graph.result_capsules) + 1),
        )
        record = {
            "id": capsule_id,
            "task_id": runtime_task_id,
            "worker_task_id": worker_id,
            "event_kind": str(event_kind or "worker_event").strip() or "worker_event",
            "status": str(status or "").strip(),
            "operator_ref": str(operator_ref or "").strip(),
            "error_code": str(error_code or ""),
            "evidence_refs": _string_list(evidence_refs or []),
            "output_summary": str(output_summary or "").strip(),
        }
        if extra:
            record.update(dict(extra))
        self._graph = append_result_capsule(graph=self._graph, record=record)
        if record["event_kind"] == "worker_final":
            self._worker_result_refs[worker_id] = capsule_id
        self._save()
        return capsule_id

    def remember_worker_result(self, *, worker_task_id: str, capsule_id: str) -> None:
        worker_id = str(worker_task_id).strip()
        capsule = str(capsule_id).strip()
        if not worker_id or not capsule:
            return
        self._worker_result_refs[worker_id] = capsule

    def list_worker_tasks(
        self,
        *,
        states: tuple[str, ...] = ("queued", "running", "awaiting_leader"),
    ) -> list[dict[str, Any]]:
        allowed_states = {str(item).strip() for item in states if str(item).strip()}
        items: list[dict[str, Any]] = []
        for task in self._graph.tasks.values():
            payload = dict(task.payload or {})
            if str(payload.get("type") or "").strip() != "worker_task":
                continue
            if allowed_states and str(task.state).strip() not in allowed_states:
                continue
            items.append(
                {
                    "task_id": str(task.task_id),
                    "state": str(task.state),
                    "worker_task_id": str(payload.get("worker_task_id") or ""),
                    "objective": str(payload.get("objective") or ""),
                    "depends_on": [str(x).strip() for x in (payload.get("depends_on") or []) if str(x).strip()],
                    "allowed_operator_refs": _string_list(payload.get("allowed_operator_refs") or []),
                    "scope_summary": str(payload.get("scope_summary") or ""),
                    "completion_contract_ref": str(task.completion_contract_ref or ""),
                    "tool_budget": dict(payload.get("tool_budget") or {}),
                    "time_budget_ms": int(payload.get("time_budget_ms") or 0),
                }
            )
        items.sort(key=lambda item: str(item.get("task_id") or ""))
        return items

    def ensure_action_task(
        self,
        *,
        source_phase: str,
        action_id: str,
        operator_ref: str,
        prepared_arguments: dict[str, Any],
        depends_on: list[str],
    ) -> str:
        key = self.build_record_id("action", source_phase, action_id, operator_ref)
        existing = self._action_task_ids.get(key)
        if existing:
            return existing
        dependency_result_refs = [
            str(self._action_result_refs.get(dep) or "").strip()
            for dep in depends_on
            if str(self._action_result_refs.get(dep) or "").strip()
        ]
        child_bundle = dict(self._task_bundle or {})
        child_bundle["objective"] = f"execute {operator_ref} for {action_id}"
        child_bundle["dependency_result_refs"] = dependency_result_refs
        self._graph = add_task(
            graph=self._graph,
            fingerprint=compute_task_fingerprint(
                kind="assistant_loop_action",
                payload={
                    "source_phase": str(source_phase),
                    "action_id": str(action_id),
                    "operator_ref": str(operator_ref),
                    "arguments": dict(prepared_arguments or {}),
                },
            ),
            payload={
                "type": "action",
                "action_id": str(action_id),
                "operator_ref": str(operator_ref),
                "source_phase": str(source_phase),
                "depends_on": list(depends_on),
            },
            parent_task_id=self.root_task_id,
            plan_revision=int(self._graph.active_plan_revision),
            task_bundle=child_bundle,
            task_execution_policy=(self._task_execution_policy if self._task_execution_policy else None),
            context_snapshot_ref=str(self._task_bundle.get("context_snapshot_ref") or ""),
            completion_contract_ref="action_result:v1",
            file_refs=_dict_list(self._file_refs),
            dependency_result_refs=dependency_result_refs,
            read_only_ancestor_context_refs=_string_list(self._task_bundle.get("read_only_ancestor_context_refs") or []),
            allowed_capabilities=_string_list(self._task_bundle.get("allowed_capabilities") or []),
            workspace_root=str(self._task_bundle.get("workspace_root") or ""),
            context_escalation_mode=_context_escalation_mode(self._task_bundle),  # type: ignore[arg-type]
            worker_task_admission_mode=_worker_task_admission_mode(self._task_bundle),  # type: ignore[arg-type]
            sufficient_for_execution=bool(self._task_bundle.get("sufficient_for_execution")),
        )
        child_task_id = f"task_{int(self._graph.next_task_num) - 1}"
        self._action_task_ids[key] = child_task_id
        self._save()
        return child_task_id

    def remember_action_result(
        self,
        *,
        action_id: str,
        task_id: str,
        step_index: int,
    ) -> None:
        if not str(action_id).strip() or not str(task_id).strip():
            return
        self._action_result_refs[str(action_id).strip()] = self.build_record_id(
            "capsule",
            str(task_id).strip(),
            int(step_index),
        )

    def finalize_root(
        self,
        *,
        final_delivery_state: str,
        error_code: str | None,
        result_refs: list[str],
        output_summary: str = "",
    ) -> None:
        self._graph = append_result_capsule(
            graph=self._graph,
            record={
                "id": "capsule:root:final",
                "task_id": self.root_task_id,
                "runtime_role": "leader",
                "status": str(final_delivery_state),
                "error_code": str(error_code or ""),
                "evidence_refs": _string_list(result_refs),
                "output_summary": str(output_summary or "").strip(),
                "delivery_state": str(final_delivery_state),
            },
        )
        final_state = (
            "succeeded"
            if final_delivery_state == "done"
            else (
                "waiting_context"
                if final_delivery_state == "need_context"
                else ("awaiting_leader" if final_delivery_state == "hold" else "failed")
            )
        )
        self._graph = set_task_state(
            graph=self._graph,
            task_id=self.root_task_id,
            state=final_state,  # type: ignore[arg-type]
            error_code=(str(error_code) if error_code else None),
            result_refs=_string_list(result_refs),
            interruption_reason=("waiting for HITL after budget hold" if final_delivery_state == "hold" else None),
        )
        self._save()

    def _bootstrap_root(self, *, bootstrap: RuntimeGraphSchedulerBootstrap) -> None:
        self._graph = set_graph_runtime_controls(
            graph=self._graph,
            active_plan_revision=int(bootstrap.active_plan_revision or 0),
            max_parallel_workers=1,
        )
        self._graph = append_message_turn(
            graph=self._graph,
            record={
                "id": f"turn:{bootstrap.turn_id}",
                "trace_id": str(bootstrap.trace_id),
                "turn_id": str(bootstrap.turn_id),
                "graph_id": str(bootstrap.graph_id),
                "workspace_id": str(bootstrap.workspace_id),
                "conversation_id": str(bootstrap.conversation_id or ""),
                "query": str(bootstrap.query),
                "objective": str(bootstrap.objective),
                "task_id": str(bootstrap.logical_task_id),
            },
        )
        self._graph = update_task_runtime_metadata(
            graph=self._graph,
            task_id=self.root_task_id,
            plan_revision=int(bootstrap.active_plan_revision or 0),
            context_snapshot_ref=str(self._task_bundle.get("context_snapshot_ref") or ""),
            completion_contract_ref=str(self._task_bundle.get("completion_contract_ref") or ""),
            task_bundle=(self._task_bundle if self._task_bundle else None),
            task_execution_policy=(self._task_execution_policy if self._task_execution_policy else None),
            file_refs=_dict_list(self._file_refs),
            dependency_result_refs=_string_list(self._task_bundle.get("dependency_result_refs") or []),
            read_only_ancestor_context_refs=_string_list(self._task_bundle.get("read_only_ancestor_context_refs") or []),
            allowed_capabilities=_string_list(self._task_bundle.get("allowed_capabilities") or []),
            workspace_root=str(self._task_bundle.get("workspace_root") or ""),
            context_escalation_mode=_context_escalation_mode(self._task_bundle),  # type: ignore[arg-type]
            worker_task_admission_mode=_worker_task_admission_mode(self._task_bundle),  # type: ignore[arg-type]
            sufficient_for_execution=(
                bool(self._task_bundle.get("sufficient_for_execution"))
                if self._task_bundle.get("sufficient_for_execution") is not None
                else True
            ),
        )
        if self._task_bundle:
            self._graph = append_context_snapshot(
                graph=self._graph,
                record={
                    "id": str(self._task_bundle.get("context_snapshot_ref") or f"context:{bootstrap.turn_id}"),
                    "context_snapshot_ref": str(self._task_bundle.get("context_snapshot_ref") or ""),
                    "query_ref": str(bootstrap.query_ref or ""),
                    "workspace_id": str(bootstrap.workspace_id),
                    "conversation_id": str(bootstrap.conversation_id or ""),
                    "task_id": str(bootstrap.logical_task_id),
                    "bundle_sufficient_for_execution": bool(self._task_bundle.get("sufficient_for_execution")),
                    "file_ref_count": len(self._file_refs),
                },
            )
            self._graph = append_plan_revision(
                graph=self._graph,
                record={
                    "id": f"revision:{int(bootstrap.active_plan_revision or 0)}",
                    "plan_revision": int(bootstrap.active_plan_revision or 0),
                    "task_id": str(bootstrap.logical_task_id),
                    "objective": str(self._task_bundle.get("objective") or bootstrap.query),
                    "task_mode": str(self._task_bundle.get("task_mode") or ""),
                    "delegation_budget": int(self._task_bundle.get("delegation_budget") or 0),
                    "max_depth": int(self._task_bundle.get("max_depth") or 0),
                    "status": "active",
                },
            )
        self._graph = set_task_state(graph=self._graph, task_id=self.root_task_id, state="running")
        self._save()

    def _rebuild_indexes(self) -> None:
        self._worker_task_ids = {}
        self._worker_result_refs = {}
        self._action_task_ids = {}
        self._action_result_refs = {}
        for task in self._graph.tasks.values():
            payload = dict(task.payload or {})
            if str(payload.get("type") or "").strip() == "worker_task":
                worker_key = self.build_record_id(
                    "worker",
                    str(payload.get("source_phase") or ""),
                    str(payload.get("worker_task_id") or ""),
                )
                if worker_key:
                    self._worker_task_ids[worker_key] = str(task.task_id)
            if str(payload.get("type") or "").strip() != "action":
                if str(payload.get("type") or "").strip() != "action":
                    continue
            key = self.build_record_id(
                "action",
                str(payload.get("source_phase") or ""),
                str(payload.get("action_id") or ""),
                str(payload.get("operator_ref") or ""),
            )
            if key:
                self._action_task_ids[key] = str(task.task_id)
        for capsule in self._graph.result_capsules:
            if not isinstance(capsule, dict):
                continue
            task_id = str(capsule.get("task_id") or "").strip()
            if not task_id:
                continue
            task = self._graph.tasks.get(task_id)
            if task is None:
                continue
            payload = dict(task.payload or {})
            action_id = str(payload.get("action_id") or "").strip()
            worker_task_id = str(payload.get("worker_task_id") or "").strip()
            record_id = str(capsule.get("id") or "").strip()
            event_kind = str(capsule.get("event_kind") or "").strip()
            if str(payload.get("type") or "").strip() == "worker_task" and worker_task_id and record_id and event_kind == "worker_final":
                self._worker_result_refs[worker_task_id] = record_id
            if str(payload.get("type") or "").strip() == "action" and action_id and record_id:
                self._action_result_refs[action_id] = record_id

    def _save(self) -> None:
        self._store.save(graph=self._graph, replay_mode=False)
