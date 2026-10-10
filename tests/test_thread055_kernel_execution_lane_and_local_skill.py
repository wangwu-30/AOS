from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

import bootstrap  # noqa: F401

from agentos_next.kernel.local_skill_approval import (
    FileLocalSkillApprovalStore,
    compute_local_skill_fingerprint,
)
from agentos_next.kernel.task_service import KernelTaskService, TaskSpec
from agentos_next.kernel.worker_react_runtime import (
    WorkerReActRuntime,
    WorkerReasonDecision,
    WorkerStopPolicy,
    WorkerTaskRuntimeInput,
    WorkerTokenBudget,
    WorkerToolBudget,
)


class TestThread055KernelExecutionLaneAndLocalSkill(unittest.IsolatedAsyncioTestCase):
    def test_task_service_defaults_skill_exec_without_operator_to_external_effect(self) -> None:
        with tempfile.TemporaryDirectory(prefix="agentos_next_t055_task_service_") as td:
            service = KernelTaskService.for_graph(
                data_dir=td,
                workspace_id="ws_t055",
                graph_id="g_t055",
            )
            task_id = service.submit_task(
                TaskSpec(
                    task_idempotency_key="task_t055_skill_exec",
                    workspace_id="ws_t055",
                    objective="Run a skill package",
                    submission_id="sub_t055",
                    execution_lane="skill_exec",
                )
            )
            record = service.get_task(task_id)
            assert record is not None
            self.assertEqual(record.effect_class, "external_effect")

    async def test_worker_react_runtime_holds_on_deadline(self) -> None:
        async def _reason_step(iteration, observations, call_outputs, call_states):  # noqa: ANN001
            del iteration, observations, call_outputs, call_states
            await asyncio.sleep(0.02)
            return WorkerReasonDecision(
                status="continue",
                reasoning_summary="still gathering evidence",
                token_usage={"output_tokens": 1},
            )

        async def _execute_tool_call(call, call_outputs, sequence, attempt):  # noqa: ANN001
            del call, call_outputs, sequence, attempt
            raise AssertionError("tool execution should not be reached in deadline hold test")

        runtime = WorkerReActRuntime(
            worker_input=WorkerTaskRuntimeInput(
                worker_task_id="worker_deadline",
                runtime_task_id="runtime_deadline",
                objective="Keep reasoning until the deadline is reached",
                scope_summary="deadline test",
                allowed_operator_refs=(),
                tool_budget=WorkerToolBudget(max_calls=1, max_parallel_calls=1),
                token_budget=WorkerTokenBudget(max_total_tokens=0, reserve_tokens=0),
                stop_policy=WorkerStopPolicy(
                    deadline_ms=10,
                    no_progress_window=5,
                    max_repeated_action_fingerprint_hits=2,
                ),
            ),
            reason_step=_reason_step,
            execute_tool_call=_execute_tool_call,
            record_event=lambda **kwargs: str(kwargs.get("event_kind") or "event"),
        )

        outcome = await runtime.run()

        self.assertEqual(outcome.status, "hold")
        self.assertEqual(outcome.error_code, "E_DEADLINE_EXCEEDED")
        self.assertTrue(outcome.needs_leader_review)

    async def test_worker_react_runtime_holds_on_token_budget(self) -> None:
        async def _reason_step(iteration, observations, call_outputs, call_states):  # noqa: ANN001
            del iteration, observations, call_outputs, call_states
            return WorkerReasonDecision(
                status="continue",
                reasoning_summary="token budget burn",
                token_usage={"total_tokens": 5},
            )

        async def _execute_tool_call(call, call_outputs, sequence, attempt):  # noqa: ANN001
            del call, call_outputs, sequence, attempt
            raise AssertionError("tool execution should not be reached in token hold test")

        runtime = WorkerReActRuntime(
            worker_input=WorkerTaskRuntimeInput(
                worker_task_id="worker_tokens",
                runtime_task_id="runtime_tokens",
                objective="Stop once the lane token budget is exhausted",
                scope_summary="token test",
                allowed_operator_refs=(),
                tool_budget=WorkerToolBudget(max_calls=1, max_parallel_calls=1),
                token_budget=WorkerTokenBudget(max_total_tokens=5, reserve_tokens=0),
                stop_policy=WorkerStopPolicy(
                    deadline_ms=0,
                    no_progress_window=5,
                    max_repeated_action_fingerprint_hits=2,
                ),
            ),
            reason_step=_reason_step,
            execute_tool_call=_execute_tool_call,
            record_event=lambda **kwargs: str(kwargs.get("event_kind") or "event"),
        )

        outcome = await runtime.run()

        self.assertEqual(outcome.status, "hold")
        self.assertEqual(outcome.error_code, "E_TOKEN_BUDGET_EXHAUSTED")
        self.assertTrue(outcome.needs_leader_review)

    def test_local_skill_approval_memory_is_bound_to_fingerprint(self) -> None:
        with tempfile.TemporaryDirectory(prefix="agentos_next_t055_local_skill_") as td:
            skill_dir = Path(td) / ".agentos" / "local_skills" / "workspace_summarizer"
            skill_dir.mkdir(parents=True, exist_ok=True)
            contract_path = skill_dir / "contract.skill"
            contract_path.write_text('{"name":"workspace_summarizer","version":"0.1.0"}\n', encoding="utf-8")

            store = FileLocalSkillApprovalStore(data_dir=td)
            fingerprint_v1 = compute_local_skill_fingerprint(skill_dir)
            self.assertFalse(store.is_approved(fingerprint=fingerprint_v1))

            store.remember(
                fingerprint=fingerprint_v1,
                skill_dir=skill_dir,
                mode="remember_by_fingerprint",
            )
            self.assertTrue(store.is_approved(fingerprint=fingerprint_v1))

            contract_path.write_text('{"name":"workspace_summarizer","version":"0.2.0"}\n', encoding="utf-8")
            fingerprint_v2 = compute_local_skill_fingerprint(skill_dir)
            self.assertNotEqual(fingerprint_v1, fingerprint_v2)
            self.assertFalse(store.is_approved(fingerprint=fingerprint_v2))
