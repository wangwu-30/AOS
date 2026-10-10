from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Awaitable, Callable

from agentos_next.kernel.execution_lane import (
    default_stop_policy_for_lane,
    default_token_budget_for_lane,
    infer_effect_class,
    normalize_execution_lane,
)
from agentos_next.kernel.task_execution_graph import (
    TASK_EXECUTION_GRAPH_TYPE,
    TASK_EXECUTION_TERMINAL_STATES,
    FileTaskExecutionGraphStore,
    TaskExecutionAttempt,
    TaskExecutionEvent,
    TaskExecutionGraph,
    TaskExecutionNode,
)


@dataclass(frozen=True)
class TaskSpec:
    task_idempotency_key: str
    workspace_id: str
    objective: str
    depends_on: tuple[str, ...] = ()
    allowed_operator_refs: tuple[str, ...] = ()
    input_refs: tuple[str, ...] = ()
    completion_contract_ref: str = ""
    submission_id: str = ""
    execution_lane: str = "standard_task"
    tool_budget: dict[str, Any] | None = None
    token_budget: dict[str, Any] | None = None
    stop_policy: dict[str, Any] | None = None
    time_budget_ms: int = 0
    task_execution_policy: dict[str, Any] | None = None
    trace: dict[str, Any] | None = None
    submitter: str = ""
    worker_task_id: str = ""
    scope_summary: str = ""
    source_phase: str = ""
    effect_class: str | None = None


@dataclass(frozen=True)
class TaskRecord:
    task_id: str
    worker_task_id: str
    status: str
    attempt: int
    generation: int
    submission_id: str
    execution_lane: str
    result_ref: str | None
    evidence_refs: tuple[str, ...]
    error_code: str | None
    created_at: str
    started_at: str | None
    ended_at: str | None
    objective: str
    scope_summary: str
    depends_on: tuple[str, ...]
    allowed_operator_refs: tuple[str, ...]
    input_refs: tuple[str, ...]
    completion_contract_ref: str
    tool_budget: dict[str, Any]
    token_budget: dict[str, Any]
    stop_policy: dict[str, Any]
    time_budget_ms: int
    task_execution_policy: dict[str, Any]
    submitter: str
    source_phase: str
    effect_class: str
    side_effect_boundary_reached: bool
    superseded_by_submission_id: str | None


@dataclass(frozen=True)
class TaskRunResult:
    task_id: str
    status: str
    error_code: str | None
    evidence_refs: tuple[str, ...]
    output_summary: str
    result_ref: str | None = None
    tool_call_count: int = 0
    iteration_count: int = 0
    needs_controller_review: bool = False
    stale: bool = False


@dataclass(frozen=True)
class SubmissionSupersedeResult:
    old_submission_id: str
    new_submission_id: str | None
    superseded_task_ids: tuple[str, ...]
    held_task_ids: tuple[str, ...]


TaskEventRecorder = Callable[..., str]
TaskRunner = Callable[[TaskRecord, TaskEventRecorder], Awaitable[TaskRunResult]]


def _utc_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _node_to_record(node: TaskExecutionNode) -> TaskRecord:
    return TaskRecord(
        task_id=node.task_id,
        worker_task_id=node.worker_task_id or node.task_id,
        status=node.status,
        attempt=int(node.attempt),
        generation=int(node.generation),
        submission_id=node.submission_id,
        execution_lane=node.execution_lane,
        result_ref=node.result_ref,
        evidence_refs=tuple(node.evidence_refs),
        error_code=node.error_code,
        created_at=node.created_at_utc,
        started_at=node.started_at_utc,
        ended_at=node.ended_at_utc,
        objective=node.objective,
        scope_summary=node.scope_summary,
        depends_on=tuple(node.depends_on),
        allowed_operator_refs=tuple(node.allowed_operator_refs),
        input_refs=tuple(node.input_refs),
        completion_contract_ref=node.completion_contract_ref,
        tool_budget=dict(node.tool_budget),
        token_budget=dict(node.token_budget),
        stop_policy=dict(node.stop_policy),
        time_budget_ms=int(node.time_budget_ms),
        task_execution_policy=dict(node.task_execution_policy),
        submitter=node.submitter,
        source_phase=node.source_phase,
        effect_class=node.effect_class,
        side_effect_boundary_reached=bool(node.side_effect_boundary_reached),
        superseded_by_submission_id=node.superseded_by_submission_id,
    )


class KernelTaskService:
    def __init__(self, *, store: FileTaskExecutionGraphStore, graph: TaskExecutionGraph) -> None:
        self._store = store
        self._graph = graph

    @classmethod
    def for_graph(
        cls,
        *,
        data_dir: str,
        workspace_id: str,
        graph_id: str,
        max_parallel_workers: int = 1,
    ) -> "KernelTaskService":
        store = FileTaskExecutionGraphStore(data_dir=data_dir)
        graph = store.load_or_create(
            workspace_id=workspace_id,
            graph_id=graph_id,
            max_parallel_workers=max_parallel_workers,
        )
        graph = store.recover_incomplete(graph)
        return cls(store=store, graph=graph)

    @property
    def graph_id(self) -> str:
        return str(self._graph.graph_id)

    @property
    def graph_type(self) -> str:
        return TASK_EXECUTION_GRAPH_TYPE

    def submit_task(self, task_spec: TaskSpec) -> str:
        task_id = str(task_spec.task_idempotency_key or "").strip()
        if not task_id:
            raise ValueError("task_idempotency_key is required")
        existing = self._graph.tasks.get(task_id)
        if existing is not None:
            return str(existing.task_id)
        now_utc = _utc_iso()
        execution_lane = normalize_execution_lane(task_spec.execution_lane)
        inferred_effect_class = infer_effect_class(allowed_operator_refs=task_spec.allowed_operator_refs)
        if execution_lane == "skill_exec" and not tuple(task_spec.allowed_operator_refs):
            inferred_effect_class = "external_effect"
        effect_class = (
            str(task_spec.effect_class or "").strip()
            or inferred_effect_class
        )
        node = TaskExecutionNode(
            task_id=task_id,
            seq=int(self._graph.next_task_num),
            task_idempotency_key=task_id,
            status="queued",
            objective=str(task_spec.objective or "").strip(),
            worker_task_id=str(task_spec.worker_task_id or task_id).strip() or task_id,
            scope_summary=str(task_spec.scope_summary or "").strip(),
            depends_on=tuple(str(item).strip() for item in task_spec.depends_on if str(item).strip()),
            allowed_operator_refs=tuple(
                str(item).strip() for item in task_spec.allowed_operator_refs if str(item).strip()
            ),
            input_refs=tuple(str(item).strip() for item in task_spec.input_refs if str(item).strip()),
            completion_contract_ref=str(task_spec.completion_contract_ref or "").strip(),
            submission_id=str(task_spec.submission_id or "").strip(),
            execution_lane=execution_lane,
            tool_budget=dict(task_spec.tool_budget or {}),
            token_budget=dict(task_spec.token_budget or default_token_budget_for_lane(execution_lane)),
            stop_policy=dict(
                task_spec.stop_policy
                or default_stop_policy_for_lane(execution_lane, deadline_ms=int(task_spec.time_budget_ms or 0))
            ),
            time_budget_ms=max(0, int(task_spec.time_budget_ms or 0)),
            task_execution_policy=dict(task_spec.task_execution_policy or {}),
            submitter=str(task_spec.submitter or "").strip(),
            source_phase=str(task_spec.source_phase or "").strip(),
            trace=dict(task_spec.trace or {}),
            attempt=0,
            generation=1,
            superseded_by_submission_id=None,
            effect_class=effect_class,  # type: ignore[arg-type]
            side_effect_boundary_reached=False,
            result_ref=None,
            evidence_refs=(),
            error_code=None,
            created_at_utc=now_utc,
            started_at_utc=None,
            ended_at_utc=None,
        )
        tasks = dict(self._graph.tasks)
        tasks[node.task_id] = node
        self._replace_graph(
            replace(
                self._graph,
                tasks=tasks,
                next_task_num=int(self._graph.next_task_num) + 1,
                updated_at_utc=now_utc,
            )
        )
        return node.task_id

    def get_task(self, task_id: str) -> TaskRecord | None:
        node = self._graph.tasks.get(str(task_id or "").strip())
        return _node_to_record(node) if node is not None else None

    def list_tasks(
        self,
        states: tuple[str, ...] | None = None,
        *,
        submission_id: str | None = None,
    ) -> list[TaskRecord]:
        allowed = {str(item).strip() for item in (states or ()) if str(item).strip()}
        expected_submission = str(submission_id or "").strip()
        out: list[TaskRecord] = []
        for node in sorted(self._graph.tasks.values(), key=lambda item: (item.seq, item.task_id)):
            if allowed and str(node.status) not in allowed:
                continue
            if expected_submission and str(node.submission_id or "").strip() != expected_submission:
                continue
            out.append(_node_to_record(node))
        return out

    def list_submission_tasks(
        self,
        *,
        submission_id: str,
        states: tuple[str, ...] | None = None,
    ) -> list[TaskRecord]:
        return self.list_tasks(states=states, submission_id=submission_id)

    def active_submission_ids(
        self,
        *,
        states: tuple[str, ...] = ("queued", "running", "hold", "need_context"),
    ) -> tuple[str, ...]:
        seen: list[str] = []
        for record in self.list_tasks(states=states):
            submission_id = str(record.submission_id or "").strip()
            if submission_id and submission_id not in seen:
                seen.append(submission_id)
        return tuple(seen)

    def cancel_task(self, task_id: str) -> TaskRecord | None:
        node = self._graph.tasks.get(str(task_id or "").strip())
        if node is None:
            return None
        if node.status in TASK_EXECUTION_TERMINAL_STATES or node.status == "hold":
            return _node_to_record(node)
        updated = replace(node, status="canceled", ended_at_utc=_utc_iso())
        tasks = dict(self._graph.tasks)
        tasks[updated.task_id] = updated
        self._replace_graph(replace(self._graph, tasks=tasks, updated_at_utc=_utc_iso()))
        return _node_to_record(updated)

    def retry_task(self, task_id: str) -> str | None:
        existing = self._graph.tasks.get(str(task_id or "").strip())
        if existing is None:
            return None
        retry_index = 1
        retry_task_id = f"{existing.task_id}:retry:{retry_index}"
        while retry_task_id in self._graph.tasks:
            retry_index += 1
            retry_task_id = f"{existing.task_id}:retry:{retry_index}"
        return self.submit_task(
            TaskSpec(
                task_idempotency_key=retry_task_id,
                workspace_id=self._graph.workspace_id,
                objective=existing.objective,
                depends_on=tuple(existing.depends_on),
                allowed_operator_refs=tuple(existing.allowed_operator_refs),
                input_refs=tuple(existing.input_refs),
                completion_contract_ref=existing.completion_contract_ref,
                submission_id=existing.submission_id,
                execution_lane=existing.execution_lane,
                tool_budget=dict(existing.tool_budget),
                token_budget=dict(existing.token_budget),
                stop_policy=dict(existing.stop_policy),
                time_budget_ms=int(existing.time_budget_ms),
                task_execution_policy=dict(existing.task_execution_policy),
                trace=dict(existing.trace),
                submitter=existing.submitter,
                worker_task_id=existing.worker_task_id,
                scope_summary=existing.scope_summary,
                source_phase=existing.source_phase,
                effect_class=existing.effect_class,
            )
        )

    def current_generation(self, task_id: str) -> int:
        node = self._graph.tasks.get(str(task_id or "").strip())
        if node is None:
            return 0
        return int(node.generation)

    def is_task_generation_current(self, task_id: str, generation: int) -> bool:
        node = self._graph.tasks.get(str(task_id or "").strip())
        if node is None:
            return False
        if node.status == "superseded":
            return False
        return int(node.generation) == int(generation)

    def is_generation_current(self, *, task_id: str, generation: int) -> bool:
        return self.is_task_generation_current(task_id, generation)

    def is_task_current(self, *, task_id: str, generation: int) -> bool:
        return self.is_task_generation_current(task_id, generation)

    def mark_side_effect_boundary(
        self,
        *,
        task_id: str,
        generation: int,
        operator_ref: str = "",
    ) -> bool:
        node = self._graph.tasks.get(str(task_id or "").strip())
        if node is None or int(node.generation) != int(generation):
            return False
        if node.side_effect_boundary_reached:
            return True
        updated = replace(node, side_effect_boundary_reached=True)
        tasks = dict(self._graph.tasks)
        tasks[task_id] = updated
        self._replace_graph(replace(self._graph, tasks=tasks, updated_at_utc=_utc_iso()))
        attempt_id = self._current_attempt_id(task_id=task_id, generation=generation)
        if attempt_id:
            self._append_event(
                task_id=task_id,
                attempt_id=attempt_id,
                generation=generation,
                event_kind="side_effect_boundary",
                status="accepted",
                operator_ref=str(operator_ref or "").strip(),
                extra={"side_effect_boundary_reached": True},
            )
        return True

    def supersede_submission(
        self,
        *,
        old_submission_id: str,
        new_submission_id: str | None,
        reason: str = "amendment",
    ) -> SubmissionSupersedeResult:
        old_id = str(old_submission_id or "").strip()
        next_id = str(new_submission_id or "").strip() or None
        if not old_id:
            return SubmissionSupersedeResult(old_submission_id="", new_submission_id=next_id, superseded_task_ids=(), held_task_ids=())
        ts = _utc_iso()
        tasks = dict(self._graph.tasks)
        attempts = list(self._graph.attempts)
        superseded_ids: list[str] = []
        held_ids: list[str] = []
        for task_id, node in list(tasks.items()):
            if str(node.submission_id or "").strip() != old_id:
                continue
            if node.status in TASK_EXECUTION_TERMINAL_STATES or node.status == "canceled":
                continue
            next_generation = int(node.generation) + 1
            can_auto_supersede = node.effect_class == "read_only" and not bool(node.side_effect_boundary_reached)
            next_status = "superseded" if can_auto_supersede else "hold"
            next_error = None if can_auto_supersede else "E_HITL_REQUIRED"
            updated_node = replace(
                node,
                status=next_status,  # type: ignore[arg-type]
                generation=next_generation,
                superseded_by_submission_id=next_id,
                error_code=next_error,
                ended_at_utc=ts,
            )
            tasks[task_id] = updated_node
            if can_auto_supersede:
                superseded_ids.append(task_id)
            else:
                held_ids.append(task_id)
            updated_attempts: list[TaskExecutionAttempt] = []
            for attempt in attempts:
                if (
                    attempt.task_id == task_id
                    and attempt.status == "running"
                    and int(attempt.generation) == int(node.generation)
                ):
                    updated_attempts.append(
                        replace(
                            attempt,
                            status=next_status,
                            ended_at_utc=ts,
                            error_code=next_error,
                            stale=True,
                        )
                    )
                else:
                    updated_attempts.append(attempt)
            attempts = updated_attempts
            self._replace_graph(replace(self._graph, tasks=tasks, attempts=attempts, updated_at_utc=ts))
            self._append_event(
                task_id=task_id,
                attempt_id=f"{task_id}:supersede",
                generation=next_generation,
                event_kind="submission_superseded",
                status=next_status,
                error_code=next_error,
                output_summary=f"{reason}:{old_id}->{next_id or '-'}",
                extra={
                    "old_submission_id": old_id,
                    "new_submission_id": next_id,
                    "reason": reason,
                },
                stale=(next_status == "superseded"),
            )
        self._replace_graph(replace(self._graph, tasks=tasks, attempts=attempts, updated_at_utc=ts))
        return SubmissionSupersedeResult(
            old_submission_id=old_id,
            new_submission_id=next_id,
            superseded_task_ids=tuple(superseded_ids),
            held_task_ids=tuple(held_ids),
        )

    async def execute_ready_batch(
        self,
        *,
        run_task: TaskRunner,
        max_tasks: int | None = None,
    ) -> list[TaskRunResult]:
        ready = self._ready_tasks()
        if not ready:
            return []
        limit = max(1, int(max_tasks or self._graph.max_parallel_workers or 1))
        results: list[TaskRunResult] = []
        for node in ready[:limit]:
            attempt = self._start_attempt(task_id=node.task_id)
            current_node = self._graph.tasks[node.task_id]
            current_record = _node_to_record(current_node)

            def _record_event(**kwargs: Any) -> str:
                return self._append_event(
                    task_id=current_record.task_id,
                    attempt_id=attempt.attempt_id,
                    generation=attempt.generation,
                    **kwargs,
                )

            run_result = await run_task(current_record, _record_event)
            final_result = self._finish_attempt(task_id=current_record.task_id, attempt=attempt, run_result=run_result)
            results.append(final_result)
        return results

    def _ready_tasks(self) -> list[TaskExecutionNode]:
        ready: list[TaskExecutionNode] = []
        for node in sorted(self._graph.tasks.values(), key=lambda item: (item.seq, item.task_id)):
            if node.status != "queued":
                continue
            deps_satisfied = True
            for dep in node.depends_on:
                dep_node = self._graph.tasks.get(dep)
                if dep_node is None or dep_node.status != "succeeded":
                    deps_satisfied = False
                    break
            if deps_satisfied:
                ready.append(node)
        return ready

    def _start_attempt(self, *, task_id: str) -> TaskExecutionAttempt:
        now_utc = _utc_iso()
        node = self._graph.tasks[task_id]
        attempt_num = int(node.attempt) + 1
        attempt = TaskExecutionAttempt(
            attempt_id=f"{task_id}:attempt:{attempt_num}",
            task_id=task_id,
            attempt=attempt_num,
            generation=int(node.generation),
            status="running",
            started_at_utc=now_utc,
        )
        updated_node = replace(
            node,
            status="running",
            attempt=attempt_num,
            started_at_utc=now_utc,
            ended_at_utc=None,
            error_code=None,
            evidence_refs=(),
            result_ref=None,
        )
        tasks = dict(self._graph.tasks)
        tasks[task_id] = updated_node
        attempts = list(self._graph.attempts)
        attempts.append(attempt)
        self._replace_graph(replace(self._graph, tasks=tasks, attempts=attempts, updated_at_utc=now_utc))
        return attempt

    def _current_attempt_id(self, *, task_id: str, generation: int) -> str:
        for attempt in reversed(self._graph.attempts):
            if attempt.task_id == task_id and int(attempt.generation) == int(generation):
                return attempt.attempt_id
        return ""

    def _append_event(
        self,
        *,
        task_id: str,
        attempt_id: str,
        generation: int,
        event_kind: str,
        status: str,
        evidence_refs: list[str] | None = None,
        output_summary: str = "",
        operator_ref: str = "",
        error_code: str | None = None,
        event_id: str = "",
        sequence: int = 0,
        extra: dict[str, Any] | None = None,
        stale: bool = False,
    ) -> str:
        event = TaskExecutionEvent(
            event_id=str(event_id or f"{task_id}:{event_kind}:{len(self._graph.events) + 1}").strip(),
            task_id=task_id,
            attempt_id=attempt_id,
            generation=max(1, int(generation or 1)),
            event_kind=str(event_kind or "").strip(),
            status=str(status or "").strip(),
            operator_ref=str(operator_ref or "").strip(),
            sequence=max(0, int(sequence or 0)),
            evidence_refs=tuple(str(item).strip() for item in (evidence_refs or []) if str(item).strip()),
            output_summary=str(output_summary or "").strip(),
            error_code=(str(error_code).strip() if str(error_code or "").strip() else None),
            created_at_utc=_utc_iso(),
            extra=dict(extra or {}),
            stale=bool(stale),
        )
        events = list(self._graph.events)
        events.append(event)
        self._replace_graph(replace(self._graph, events=events, updated_at_utc=_utc_iso()))
        return event.event_id

    def _finish_attempt(
        self,
        *,
        task_id: str,
        attempt: TaskExecutionAttempt,
        run_result: TaskRunResult,
    ) -> TaskRunResult:
        current_node = self._graph.tasks[task_id]
        ended_at_utc = _utc_iso()
        if current_node.status == "superseded" or int(current_node.generation) != int(attempt.generation):
            stale_event_id = self._append_event(
                task_id=task_id,
                attempt_id=attempt.attempt_id,
                generation=attempt.generation,
                event_kind="worker_final",
                status="superseded",
                evidence_refs=list(run_result.evidence_refs),
                output_summary=str(run_result.output_summary or "").strip(),
                error_code="E_TASK_SUPERSEDED",
                event_id=str(run_result.result_ref or f"{task_id}:worker_final:stale:{attempt.attempt}").strip(),
                sequence=max(0, int(run_result.iteration_count or 0)),
                extra={
                    "tool_call_count": int(run_result.tool_call_count or 0),
                    "iteration_count": int(run_result.iteration_count or 0),
                    "needs_controller_review": bool(run_result.needs_controller_review),
                    "stale_result": True,
                },
                stale=True,
            )
            attempts: list[TaskExecutionAttempt] = []
            for item in self._graph.attempts:
                if item.attempt_id == attempt.attempt_id:
                    attempts.append(
                        replace(
                            item,
                            status="superseded",
                            ended_at_utc=ended_at_utc,
                            error_code="E_TASK_SUPERSEDED",
                            result_ref=stale_event_id,
                            evidence_refs=tuple(str(ref).strip() for ref in run_result.evidence_refs if str(ref).strip()),
                            stale=True,
                        )
                    )
                else:
                    attempts.append(item)
            self._replace_graph(replace(self._graph, attempts=attempts, updated_at_utc=ended_at_utc))
            return replace(
                run_result,
                status="superseded",
                error_code="E_TASK_SUPERSEDED",
                result_ref=stale_event_id,
            )

        final_status = str(run_result.status or "").strip() or "failed"
        task_status = {
            "accepted": "succeeded",
            "blocked": "failed",
            "failed": "failed",
            "canceled": "canceled",
            "hold": "hold",
            "need_context": "need_context",
            "superseded": "superseded",
        }.get(final_status, "failed")
        final_event_id = self._append_event(
            task_id=task_id,
            attempt_id=attempt.attempt_id,
            generation=attempt.generation,
            event_kind="worker_final",
            status=final_status,
            evidence_refs=list(run_result.evidence_refs),
            output_summary=str(run_result.output_summary or "").strip(),
            error_code=run_result.error_code,
            event_id=str(run_result.result_ref or f"{task_id}:worker_final:{attempt.attempt}").strip(),
            sequence=max(0, int(run_result.iteration_count or 0)),
            extra={
                "tool_call_count": int(run_result.tool_call_count or 0),
                "iteration_count": int(run_result.iteration_count or 0),
                "needs_controller_review": bool(run_result.needs_controller_review),
            },
        )
        attempts: list[TaskExecutionAttempt] = []
        for item in self._graph.attempts:
            if item.attempt_id == attempt.attempt_id:
                attempts.append(
                    replace(
                        item,
                        status=final_status,
                        ended_at_utc=ended_at_utc,
                        error_code=run_result.error_code,
                        result_ref=final_event_id,
                        evidence_refs=tuple(str(ref).strip() for ref in run_result.evidence_refs if str(ref).strip()),
                    )
                )
            else:
                attempts.append(item)
        updated_node = replace(
            current_node,
            status=task_status,  # type: ignore[arg-type]
            result_ref=final_event_id,
            evidence_refs=tuple(str(ref).strip() for ref in run_result.evidence_refs if str(ref).strip()),
            error_code=run_result.error_code,
            ended_at_utc=ended_at_utc,
        )
        tasks = dict(self._graph.tasks)
        tasks[task_id] = updated_node
        self._replace_graph(replace(self._graph, tasks=tasks, attempts=attempts, updated_at_utc=ended_at_utc))
        return replace(run_result, result_ref=final_event_id)

    def _replace_graph(self, graph: TaskExecutionGraph) -> None:
        self._graph = graph
        self._store.save(self._graph)
