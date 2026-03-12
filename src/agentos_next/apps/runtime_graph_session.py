from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from agentos_next.pa.runtime_graph_scheduler import (
    DurableRuntimeGraphScheduler,
    RuntimeGraphSchedulerBootstrap,
)


@dataclass(frozen=True)
class WorkerTaskSpec:
    worker_task_id: str
    objective: str
    depends_on: tuple[str, ...] = ()
    allowed_operator_refs: tuple[str, ...] = ()
    scope_summary: str = ""
    completion_contract_ref: str = ""
    tool_budget: dict[str, Any] | None = None
    time_budget_ms: int = 0
    source_phase: str = "planner"


class RuntimeGraphSession(Protocol):
    @property
    def graph_id(self) -> str: ...

    @property
    def root_task_id(self) -> str: ...

    @property
    def active_plan_revision(self) -> int: ...

    @property
    def replan_count(self) -> int: ...

    def record_compile_failure(self, *, error_code: str, query_ref: str, verification_ref: str) -> None: ...

    def set_task_state(
        self,
        *,
        task_id: str,
        state: str,
        error_code: str | None = None,
        result_refs: list[str] | None = None,
        interruption_reason: str | None = None,
    ) -> None: ...

    def record_reasoning_step(
        self,
        *,
        task_id: str,
        step_summary: dict[str, Any],
        output_summary: str = "",
        leader_phase: str | None = None,
        phase_status: str | None = None,
    ) -> None: ...

    def append_plan_revision(self, *, record: dict[str, Any]) -> None: ...

    def advance_plan_revision(self, *, record: dict[str, Any]) -> int: ...

    def ensure_worker_task(self, *, spec: WorkerTaskSpec) -> str | None: ...

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
    ) -> str: ...

    def finalize_worker_task(
        self,
        *,
        task_id: str,
        worker_task_id: str,
        state: str,
        error_code: str | None,
        result_refs: list[str],
        output_summary: str = "",
        extra: dict[str, Any] | None = None,
    ) -> str: ...

    def list_worker_tasks(self, *, states: tuple[str, ...] = ("queued", "running", "awaiting_leader")) -> list[dict[str, Any]]: ...

    def finalize_root(
        self,
        *,
        final_delivery_state: str,
        error_code: str | None,
        result_refs: list[str],
        output_summary: str = "",
    ) -> None: ...


class NullRuntimeGraphSession:
    graph_id = ""
    root_task_id = ""
    active_plan_revision = 0
    replan_count = 0

    def record_compile_failure(self, *, error_code: str, query_ref: str, verification_ref: str) -> None:
        del error_code, query_ref, verification_ref

    def set_task_state(
        self,
        *,
        task_id: str,
        state: str,
        error_code: str | None = None,
        result_refs: list[str] | None = None,
        interruption_reason: str | None = None,
    ) -> None:
        del task_id, state, error_code, result_refs, interruption_reason

    def record_reasoning_step(
        self,
        *,
        task_id: str,
        step_summary: dict[str, Any],
        output_summary: str = "",
        leader_phase: str | None = None,
        phase_status: str | None = None,
    ) -> None:
        del task_id, step_summary, output_summary, leader_phase, phase_status

    def append_plan_revision(self, *, record: dict[str, Any]) -> None:
        del record

    def advance_plan_revision(self, *, record: dict[str, Any]) -> int:
        del record
        return 0

    def ensure_worker_task(self, *, spec: WorkerTaskSpec) -> str | None:
        del spec
        return None

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
        del (
            task_id,
            worker_task_id,
            event_kind,
            status,
            evidence_refs,
            output_summary,
            operator_ref,
            error_code,
            event_id,
            sequence,
            extra,
        )
        return ""

    def finalize_worker_task(
        self,
        *,
        task_id: str,
        worker_task_id: str,
        state: str,
        error_code: str | None,
        result_refs: list[str],
        output_summary: str = "",
        extra: dict[str, Any] | None = None,
    ) -> str:
        del task_id, worker_task_id, state, error_code, result_refs, output_summary, extra
        return ""

    def list_worker_tasks(self, *, states: tuple[str, ...] = ("queued", "running", "awaiting_leader")) -> list[dict[str, Any]]:
        del states
        return []

    def finalize_root(
        self,
        *,
        final_delivery_state: str,
        error_code: str | None,
        result_refs: list[str],
        output_summary: str = "",
    ) -> None:
        del final_delivery_state, error_code, result_refs, output_summary


class TaskGraphRuntimeGraphSession:
    def __init__(self, scheduler: DurableRuntimeGraphScheduler) -> None:
        self._scheduler = scheduler

    @classmethod
    def bootstrap_for_assistant_loop(cls, bootstrap: RuntimeGraphSchedulerBootstrap) -> "TaskGraphRuntimeGraphSession":
        return cls(DurableRuntimeGraphScheduler.bootstrap_for_assistant_loop(bootstrap))

    @property
    def graph_id(self) -> str:
        return str(self._scheduler.graph_id)

    @property
    def root_task_id(self) -> str:
        return str(self._scheduler.root_task_id)

    @property
    def active_plan_revision(self) -> int:
        return int(self._scheduler.active_plan_revision)

    @property
    def replan_count(self) -> int:
        return int(self._scheduler.replan_count)

    def record_compile_failure(self, *, error_code: str, query_ref: str, verification_ref: str) -> None:
        self._scheduler.record_compile_failure(
            error_code=error_code,
            query_ref=query_ref,
            verification_ref=verification_ref,
        )

    def set_task_state(
        self,
        *,
        task_id: str,
        state: str,
        error_code: str | None = None,
        result_refs: list[str] | None = None,
        interruption_reason: str | None = None,
    ) -> None:
        self._scheduler.set_task_state(
            task_id=task_id,
            state=state,
            error_code=error_code,
            result_refs=result_refs,
            interruption_reason=interruption_reason,
        )

    def record_reasoning_step(
        self,
        *,
        task_id: str,
        step_summary: dict[str, Any],
        output_summary: str = "",
        leader_phase: str | None = None,
        phase_status: str | None = None,
    ) -> None:
        self._scheduler.record_step(
            task_id=task_id,
            step_summary=step_summary,
            output_summary=output_summary,
            leader_phase=leader_phase,
            phase_status=phase_status,
        )

    def append_plan_revision(self, *, record: dict[str, Any]) -> None:
        self._scheduler.append_plan_revision(record=record)

    def advance_plan_revision(self, *, record: dict[str, Any]) -> int:
        return self._scheduler.advance_plan_revision(record=record)

    def ensure_worker_task(self, *, spec: WorkerTaskSpec) -> str | None:
        return self._scheduler.ensure_worker_task(
            worker_task_id=spec.worker_task_id,
            objective=spec.objective,
            depends_on=list(spec.depends_on),
            allowed_operator_refs=list(spec.allowed_operator_refs),
            scope_summary=spec.scope_summary,
            completion_contract_ref=spec.completion_contract_ref,
            tool_budget=dict(spec.tool_budget or {}),
            time_budget_ms=int(spec.time_budget_ms or 0),
            source_phase=spec.source_phase,
        )

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
        return self._scheduler.record_worker_event(
            task_id=task_id,
            worker_task_id=worker_task_id,
            event_kind=event_kind,
            status=status,
            evidence_refs=evidence_refs,
            output_summary=output_summary,
            operator_ref=operator_ref,
            error_code=error_code,
            event_id=event_id,
            sequence=sequence,
            extra=extra,
        )

    def finalize_worker_task(
        self,
        *,
        task_id: str,
        worker_task_id: str,
        state: str,
        error_code: str | None,
        result_refs: list[str],
        output_summary: str = "",
        extra: dict[str, Any] | None = None,
    ) -> str:
        capsule_id = self._scheduler.record_worker_event(
            task_id=task_id,
            worker_task_id=worker_task_id,
            event_kind="worker_final",
            status=("accepted" if state == "succeeded" else state),
            evidence_refs=result_refs,
            output_summary=output_summary,
            error_code=error_code,
            extra=extra,
        )
        self._scheduler.remember_worker_result(worker_task_id=worker_task_id, capsule_id=capsule_id)
        self._scheduler.set_task_state(
            task_id=task_id,
            state=state,
            error_code=error_code,
            result_refs=result_refs,
            interruption_reason=("waiting for leader review" if state == "awaiting_leader" else None),
        )
        return capsule_id

    def list_worker_tasks(self, *, states: tuple[str, ...] = ("queued", "running", "awaiting_leader")) -> list[dict[str, Any]]:
        return self._scheduler.list_worker_tasks(states=states)

    def finalize_root(
        self,
        *,
        final_delivery_state: str,
        error_code: str | None,
        result_refs: list[str],
        output_summary: str = "",
    ) -> None:
        self._scheduler.finalize_root(
            final_delivery_state=final_delivery_state,
            error_code=error_code,
            result_refs=result_refs,
            output_summary=output_summary,
        )
