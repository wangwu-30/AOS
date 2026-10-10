from __future__ import annotations

import asyncio
import hashlib
import json
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from agentos_next.kernel.execution_lane import READ_ONLY_OPERATOR_PREFIXES, is_read_only_operator

READ_ONLY_TOOL_PREFIXES = READ_ONLY_OPERATOR_PREFIXES


@dataclass(frozen=True)
class WorkerToolBudget:
    max_calls: int = 4
    max_parallel_calls: int = 1
    retry_read_only_tools: bool = False


@dataclass(frozen=True)
class WorkerTokenBudget:
    max_total_tokens: int = 0
    reserve_tokens: int = 0


@dataclass(frozen=True)
class WorkerStopPolicy:
    deadline_ms: int = 0
    no_progress_window: int = 3
    max_repeated_action_fingerprint_hits: int = 2
    verification_mode: str = "final_only"
    continue_until_terminal: bool = True


@dataclass(frozen=True)
class WorkerTaskRuntimeInput:
    worker_task_id: str
    runtime_task_id: str
    objective: str
    scope_summary: str
    allowed_operator_refs: tuple[str, ...]
    tool_budget: WorkerToolBudget
    time_budget_ms: int = 0
    submission_id: str = ""
    execution_lane: str = "standard_task"
    token_budget: WorkerTokenBudget = WorkerTokenBudget()
    stop_policy: WorkerStopPolicy = WorkerStopPolicy()
    generation: int = 1
    effect_class: str = "read_only"


@dataclass(frozen=True)
class WorkerToolCall:
    call_id: str
    operator_ref: str
    arguments: dict[str, Any]
    depends_on: tuple[str, ...] = ()


@dataclass(frozen=True)
class WorkerReasonDecision:
    status: str
    tool_calls: tuple[WorkerToolCall, ...] = ()
    reasoning_summary: str = ""
    observation_capsule: str = ""
    raw_output: dict[str, Any] | None = None
    error_code: str | None = None
    token_usage: dict[str, Any] | None = None


@dataclass(frozen=True)
class WorkerToolCallResult:
    call_id: str
    operator_ref: str
    status: str
    error_code: str | None
    evidence_refs: tuple[str, ...]
    output_obj: dict[str, Any] | None = None
    output_summary: str = ""
    observation_capsule: str = ""
    extra: dict[str, Any] | None = None


@dataclass(frozen=True)
class WorkerReActOutcome:
    status: str
    error_code: str | None
    final_summary: str
    result_refs: tuple[str, ...]
    tool_call_count: int
    iteration_count: int
    needs_leader_review: bool = False
    stale: bool = False


ReasonStepFn = Callable[[int, tuple[str, ...], dict[str, Any], dict[str, str]], Awaitable[WorkerReasonDecision]]
ExecuteToolFn = Callable[[WorkerToolCall, dict[str, Any], int, int], Awaitable[WorkerToolCallResult]]
RecordEventFn = Callable[..., str]
GenerationGuardFn = Callable[[int], bool]
SideEffectBoundaryFn = Callable[[str, int], None]


def _action_fingerprint(call: WorkerToolCall) -> str:
    payload = json.dumps(
        {
            "operator_ref": str(call.operator_ref or "").strip(),
            "arguments": dict(call.arguments or {}),
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class WorkerReActRuntime:
    def __init__(
        self,
        *,
        worker_input: WorkerTaskRuntimeInput,
        reason_step: ReasonStepFn,
        execute_tool_call: ExecuteToolFn,
        record_event: RecordEventFn,
        generation_guard: GenerationGuardFn | None = None,
        mark_side_effect_boundary: SideEffectBoundaryFn | None = None,
        check_current: Callable[..., bool] | None = None,
    ) -> None:
        self._worker_input = worker_input
        self._reason_step = reason_step
        self._execute_tool_call = execute_tool_call
        self._record_event = record_event
        self._generation_guard = generation_guard
        self._mark_side_effect_boundary = mark_side_effect_boundary
        self._check_current = check_current

    async def run(self) -> WorkerReActOutcome:
        observation_capsules: list[str] = []
        call_outputs: dict[str, Any] = {}
        call_states: dict[str, str] = {}
        result_refs: list[str] = []
        calls_used = 0
        iteration = 0
        final_summary = ""
        no_progress_streak = 0
        repeated_action_hits = 0
        last_fingerprint = ""
        tool_budget = self._coerce_tool_budget(self._worker_input.tool_budget)
        token_budget = self._coerce_token_budget(self._worker_input.token_budget)
        stop_policy = self._coerce_stop_policy(self._worker_input.stop_policy)
        max_calls = max(1, int(tool_budget.max_calls or 1))
        max_parallel_calls = max(1, int(tool_budget.max_parallel_calls or 1))
        retry_read_only = bool(tool_budget.retry_read_only_tools)
        no_progress_window = max(1, int(stop_policy.no_progress_window or 1))
        repeated_action_cap = max(1, int(stop_policy.max_repeated_action_fingerprint_hits or 1))
        max_total_tokens = max(0, int(token_budget.max_total_tokens or 0))
        reserve_tokens = max(0, int(token_budget.reserve_tokens or 0))
        token_limit = max(0, max_total_tokens - reserve_tokens)
        consumed_tokens = 0
        started_monotonic = time.monotonic()

        while True:
            if self._deadline_exceeded(started_monotonic=started_monotonic, stop_policy=stop_policy):
                return WorkerReActOutcome(
                    status="hold",
                    error_code="E_DEADLINE_EXCEEDED",
                    final_summary=final_summary or "worker reached the execution deadline",
                    result_refs=tuple(dict.fromkeys(result_refs)),
                    tool_call_count=calls_used,
                    iteration_count=iteration,
                    needs_leader_review=True,
                )
            if token_limit > 0 and consumed_tokens >= token_limit:
                return WorkerReActOutcome(
                    status="hold",
                    error_code="E_TOKEN_BUDGET_EXHAUSTED",
                    final_summary=final_summary or "worker reached the lane token budget",
                    result_refs=tuple(dict.fromkeys(result_refs)),
                    tool_call_count=calls_used,
                    iteration_count=iteration,
                    needs_leader_review=True,
                )
            if not self._is_current():
                return WorkerReActOutcome(
                    status="superseded",
                    error_code="E_TASK_SUPERSEDED",
                    final_summary=final_summary or "worker superseded before next reason step",
                    result_refs=tuple(dict.fromkeys(result_refs)),
                    tool_call_count=calls_used,
                    iteration_count=iteration,
                    needs_leader_review=False,
                    stale=True,
                )
            iteration += 1
            decision = await self._reason_step(
                iteration,
                tuple(observation_capsules),
                dict(call_outputs),
                dict(call_states),
            )
            consumed_tokens += self._token_usage_total(decision.token_usage)
            if str(decision.reasoning_summary or "").strip():
                final_summary = str(decision.reasoning_summary).strip()
            iteration_capsule = self._record_event(
                event_kind="worker_iteration",
                status=str(decision.status or "").strip() or "continue",
                output_summary=str(decision.reasoning_summary or "").strip(),
                sequence=iteration,
                extra={
                    "iteration": iteration,
                    "tool_candidate_count": len(decision.tool_calls),
                    "objective": self._worker_input.objective,
                    "execution_lane": self._worker_input.execution_lane,
                    "generation": int(self._worker_input.generation),
                    "effect_class": self._worker_input.effect_class,
                },
            )
            if iteration_capsule:
                result_refs.append(iteration_capsule)
            if str(decision.observation_capsule or "").strip():
                observation_capsules.append(str(decision.observation_capsule).strip())

            status = str(decision.status or "").strip().lower() or "done"
            if status in {"blocked", "need_context", "hold", "superseded"}:
                return WorkerReActOutcome(
                    status=status,
                    error_code=(str(decision.error_code or "").strip() or None),
                    final_summary=final_summary,
                    result_refs=tuple(dict.fromkeys(result_refs)),
                    tool_call_count=calls_used,
                    iteration_count=iteration,
                    needs_leader_review=(status == "hold"),
                )
            if status == "done" and not decision.tool_calls:
                return WorkerReActOutcome(
                    status="accepted",
                    error_code=None,
                    final_summary=final_summary,
                    result_refs=tuple(dict.fromkeys(result_refs)),
                    tool_call_count=calls_used,
                    iteration_count=iteration,
                )
            if status != "continue" and decision.tool_calls:
                status = "continue"
            if not decision.tool_calls:
                no_progress_streak += 1
                if no_progress_streak >= no_progress_window:
                    return WorkerReActOutcome(
                        status="hold",
                        error_code="E_NO_PROGRESS",
                        final_summary=final_summary or "worker stopped after repeated no-progress iterations",
                        result_refs=tuple(dict.fromkeys(result_refs)),
                        tool_call_count=calls_used,
                        iteration_count=iteration,
                        needs_leader_review=True,
                    )
                continue

            no_progress_streak = 0
            batch_fingerprint = "|".join(sorted(_action_fingerprint(call) for call in decision.tool_calls))
            if batch_fingerprint and batch_fingerprint == last_fingerprint:
                repeated_action_hits += 1
            else:
                repeated_action_hits = 0
                last_fingerprint = batch_fingerprint
            if repeated_action_hits >= repeated_action_cap:
                return WorkerReActOutcome(
                    status="hold",
                    error_code="E_NO_PROGRESS",
                    final_summary=final_summary or "worker repeated the same action batch without progress",
                    result_refs=tuple(dict.fromkeys(result_refs)),
                    tool_call_count=calls_used,
                    iteration_count=iteration,
                    needs_leader_review=True,
                )

            pending = [call for call in decision.tool_calls]
            progress_made = False
            while pending:
                ready: list[WorkerToolCall] = []
                still_pending: list[WorkerToolCall] = []
                for call in pending:
                    unresolved = [dep for dep in call.depends_on if dep not in call_states]
                    if unresolved:
                        still_pending.append(call)
                        continue
                    ready.append(call)
                if not ready:
                    return WorkerReActOutcome(
                        status="blocked",
                        error_code="E_TASK_DEPENDENCY_UNRESOLVED",
                        final_summary=final_summary or "worker task dependencies could not be resolved",
                        result_refs=tuple(dict.fromkeys(result_refs)),
                        tool_call_count=calls_used,
                        iteration_count=iteration,
                    )

                batch = ready[:max_parallel_calls]
                for _ in batch:
                    calls_used += 1
                    if calls_used > max_calls:
                        return WorkerReActOutcome(
                            status="hold",
                            error_code="E_HITL_REQUIRED",
                            final_summary=final_summary or "worker tool budget exhausted",
                            result_refs=tuple(dict.fromkeys(result_refs)),
                            tool_call_count=calls_used - 1,
                            iteration_count=iteration,
                            needs_leader_review=True,
                        )

                if not self._is_current():
                    return WorkerReActOutcome(
                        status="superseded",
                        error_code="E_TASK_SUPERSEDED",
                        final_summary=final_summary or "worker superseded before tool dispatch",
                        result_refs=tuple(dict.fromkeys(result_refs)),
                        tool_call_count=calls_used - len(batch),
                        iteration_count=iteration,
                        stale=True,
                    )
                if self._deadline_exceeded(started_monotonic=started_monotonic, stop_policy=stop_policy):
                    return WorkerReActOutcome(
                        status="hold",
                        error_code="E_DEADLINE_EXCEEDED",
                        final_summary=final_summary or "worker reached the execution deadline before tool dispatch",
                        result_refs=tuple(dict.fromkeys(result_refs)),
                        tool_call_count=calls_used - len(batch),
                        iteration_count=iteration,
                        needs_leader_review=True,
                    )
                if token_limit > 0 and consumed_tokens >= token_limit:
                    return WorkerReActOutcome(
                        status="hold",
                        error_code="E_TOKEN_BUDGET_EXHAUSTED",
                        final_summary=final_summary or "worker reached the lane token budget before tool dispatch",
                        result_refs=tuple(dict.fromkeys(result_refs)),
                        tool_call_count=calls_used - len(batch),
                        iteration_count=iteration,
                        needs_leader_review=True,
                    )

                for call in batch:
                    if not is_read_only_operator(call.operator_ref) and callable(self._mark_side_effect_boundary):
                        self._mark_side_effect_boundary(call.operator_ref, self._worker_input.generation)

                results = await asyncio.gather(
                    *[
                        self._execute_with_retry(
                            call=call,
                            call_outputs=dict(call_outputs),
                            sequence=(calls_used - len(batch) + index),
                            retry_read_only=retry_read_only,
                        )
                        for index, call in enumerate(batch, start=1)
                    ]
                )
                for result in results:
                    if not self._is_current():
                        return WorkerReActOutcome(
                            status="superseded",
                            error_code="E_TASK_SUPERSEDED",
                            final_summary=final_summary or "worker superseded after tool execution",
                            result_refs=tuple(dict.fromkeys(result_refs)),
                            tool_call_count=calls_used,
                            iteration_count=iteration,
                            stale=True,
                        )
                    progress_made = True
                    call_states[result.call_id] = str(result.status or "").strip()
                    if isinstance(result.output_obj, dict):
                        call_outputs[result.call_id] = dict(result.output_obj)
                    capsule_id = self._record_event(
                        event_kind="tool_call",
                        status=str(result.status or "").strip(),
                        evidence_refs=list(result.evidence_refs),
                        output_summary=str(result.output_summary or "").strip(),
                        operator_ref=str(result.operator_ref or "").strip(),
                        error_code=result.error_code,
                        event_id=result.call_id,
                        sequence=calls_used,
                        extra=dict(result.extra or {}),
                    )
                    if capsule_id:
                        result_refs.append(capsule_id)
                    if str(result.observation_capsule or "").strip():
                        observation_capsules.append(str(result.observation_capsule).strip())
                executed_ids = {item.call_id for item in batch}
                pending = [call for call in still_pending if call.call_id not in executed_ids]

            if not progress_made:
                no_progress_streak += 1

    async def _execute_with_retry(
        self,
        *,
        call: WorkerToolCall,
        call_outputs: dict[str, Any],
        sequence: int,
        retry_read_only: bool,
    ) -> WorkerToolCallResult:
        attempts = 2 if (retry_read_only and is_read_only_operator(call.operator_ref)) else 1
        last = WorkerToolCallResult(
            call_id=call.call_id,
            operator_ref=call.operator_ref,
            status="failed",
            error_code="E_EXECUTION_FAILED",
            evidence_refs=(),
        )
        for attempt in range(1, attempts + 1):
            last = await self._execute_tool_call(call, dict(call_outputs), sequence, attempt)
            if last.status == "accepted":
                return last
            if attempt >= attempts or last.status not in {"failed", "timeout"}:
                return last
        return last

    def _is_current(self) -> bool:
        if callable(self._check_current):
            try:
                return bool(self._check_current(self._worker_input.runtime_task_id, int(self._worker_input.generation), "runtime"))
            except Exception:
                return False
        if not callable(self._generation_guard):
            return True
        try:
            return bool(self._generation_guard(int(self._worker_input.generation)))
        except Exception:
            return False

    @staticmethod
    def _coerce_tool_budget(raw: Any) -> WorkerToolBudget:
        if isinstance(raw, WorkerToolBudget):
            return raw
        obj = dict(raw or {}) if isinstance(raw, dict) else {}
        return WorkerToolBudget(
            max_calls=max(1, int(obj.get("max_calls") or 1)),
            max_parallel_calls=max(1, int(obj.get("max_parallel_calls") or 1)),
            retry_read_only_tools=bool(obj.get("retry_read_only_tools")),
        )

    @staticmethod
    def _coerce_stop_policy(raw: Any) -> WorkerStopPolicy:
        if isinstance(raw, WorkerStopPolicy):
            return raw
        obj = dict(raw or {}) if isinstance(raw, dict) else {}
        return WorkerStopPolicy(
            deadline_ms=max(0, int(obj.get("deadline_ms") or 0)),
            no_progress_window=max(1, int(obj.get("no_progress_window") or 3)),
            max_repeated_action_fingerprint_hits=max(1, int(obj.get("max_repeated_action_fingerprint_hits") or 2)),
            verification_mode=str(obj.get("verification_mode") or "final_only").strip() or "final_only",
            continue_until_terminal=bool(obj.get("continue_until_terminal", True)),
        )

    @staticmethod
    def _coerce_token_budget(raw: Any) -> WorkerTokenBudget:
        if isinstance(raw, WorkerTokenBudget):
            return raw
        obj = dict(raw or {}) if isinstance(raw, dict) else {}
        return WorkerTokenBudget(
            max_total_tokens=max(0, int(obj.get("max_total_tokens") or 0)),
            reserve_tokens=max(0, int(obj.get("reserve_tokens") or 0)),
        )

    @staticmethod
    def _token_usage_total(raw: Any) -> int:
        if not isinstance(raw, dict):
            return 0
        for key in ("total_tokens", "tokens", "total"):
            value = raw.get(key)
            try:
                parsed = int(value)
            except Exception:
                continue
            if parsed > 0:
                return parsed
        prompt_tokens = raw.get("prompt_tokens")
        completion_tokens = raw.get("completion_tokens")
        try:
            return max(0, int(prompt_tokens or 0)) + max(0, int(completion_tokens or 0))
        except Exception:
            return 0

    def _deadline_exceeded(
        self,
        *,
        started_monotonic: float,
        stop_policy: WorkerStopPolicy,
    ) -> bool:
        deadline_ms = max(
            0,
            int(
                stop_policy.deadline_ms
                or self._worker_input.time_budget_ms
                or 0
            ),
        )
        if deadline_ms <= 0:
            return False
        elapsed_ms = int((time.monotonic() - started_monotonic) * 1000)
        return elapsed_ms >= deadline_ms
