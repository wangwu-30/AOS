from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import bootstrap  # noqa: F401

from agentos_next.apps.runtime_graph_session import (
    NullRuntimeGraphSession,
    TaskGraphRuntimeGraphSession,
    WorkerTaskSpec,
)
from agentos_next.pa.runtime_graph_scheduler import (
    DurableRuntimeGraphScheduler,
    RuntimeGraphSchedulerBootstrap,
)
from agentos_next.pa.task_graph import FileTaskGraphStore


class TestThread053RuntimeGraphScheduler(unittest.TestCase):
    def test_scheduler_bootstrap_and_worker_task_records_are_durable(self) -> None:
        with tempfile.TemporaryDirectory(prefix="agentos_next_t053_sched_") as td:
            data_dir = Path(td)
            session = TaskGraphRuntimeGraphSession.bootstrap_for_assistant_loop(
                RuntimeGraphSchedulerBootstrap(
                    data_dir=str(data_dir),
                    workspace_id="ws53",
                    graph_id="g_runtime_sched",
                    logical_task_id="task_runtime_sched",
                    query="分析 README",
                    objective="阅读 README 并总结",
                    trace_id="tr_53",
                    turn_id="turn_53",
                    conversation_id="conv_53",
                    interaction_mode="task",
                    query_ref="ev_query_53",
                    active_plan_revision=0,
                    task_bundle={
                        "schema_version": "1.0.0",
                        "type": "task_bundle_v1",
                        "objective": "阅读 README 并总结",
                        "completion_contract_ref": "delivery_contract:v1",
                        "context_snapshot_ref": "context_graph:v1",
                        "workspace_root": "/tmp/ws53",
                        "allowed_capabilities": ["fs_read"],
                        "read_only_ancestor_context_refs": ["context_planes:v1"],
                        "dependency_result_refs": [],
                        "context_escalation_mode": "auto",
                        "worker_task_admission_mode": "leader_gate",
                        "bundle_generation": "aggressive",
                        "sufficient_for_execution": True,
                        "task_mode": "decomposable",
                        "delegation_budget": 1,
                        "max_depth": 1,
                        "scope_guard": {"worker_split_requires_leader": True},
                    },
                    task_execution_policy={
                        "schema_version": "1.0.0",
                        "type": "task_execution_policy_v1",
                        "root_deadline_ms": 120000,
                        "llm_timeout_ms": 9000,
                        "tool_timeout_ms": 15000,
                        "llm_retry_policy": {"strategy": "bounded_retry", "max_retries": 0},
                        "tool_retry_policy": {"strategy": "bounded_retry", "max_retries": 0},
                        "max_attempts": 1,
                        "backoff_policy": {"strategy": "linear", "initial_delay_ms": 250, "max_delay_ms": 1000},
                        "side_effect_safe_retry": False,
                        "deadline_mode": "compat_root_cap",
                    },
                    file_refs=(
                        {
                            "schema_version": "1.0.0",
                            "type": "file_ref_v1",
                            "ref_type": "workspace_path",
                            "value": "README.md",
                            "usage": "required",
                            "summary": "primary file",
                            "resolver": "fs.read",
                        },
                    ),
                    now_utc="2026-03-12T00:00:00Z",
                )
            )

            worker_spec = WorkerTaskSpec(
                worker_task_id="worker_readme",
                objective="读取 README 并整理关键事实",
                depends_on=(),
                allowed_operator_refs=("builtin://fs.read",),
                scope_summary="仅允许读取 README.md",
                completion_contract_ref="worker_result:v1",
                tool_budget={"max_calls": 1, "max_parallel_calls": 1, "retry_read_only_tools": False},
                time_budget_ms=15000,
                source_phase="planner",
            )
            worker_task_id = session.ensure_worker_task(spec=worker_spec)
            self.assertIsNotNone(worker_task_id)
            self.assertEqual(
                worker_task_id,
                session.ensure_worker_task(spec=worker_spec),
            )
            assert worker_task_id is not None
            session.set_task_state(task_id=worker_task_id, state="running")
            session.record_reasoning_step(
                task_id=session.root_task_id,
                step_summary={
                    "i": 1,
                    "operator_ref": "skill://assistant",
                    "runtime_role": "leader",
                    "status": "accepted",
                    "error_code": None,
                    "deadline_ms": 2500,
                    "evidence_refs": ["ev_plan_1"],
                },
                output_summary="planner accepted worker task graph",
                leader_phase="planner",
                phase_status="continue",
            )
            tool_capsule = session.record_worker_event(
                task_id=worker_task_id,
                worker_task_id="worker_readme",
                event_kind="tool_call",
                status="accepted",
                evidence_refs=["ev_fs_1"],
                output_summary="README snapshot",
                operator_ref="builtin://fs.read",
                event_id="readme_call",
                sequence=1,
            )
            self.assertTrue(tool_capsule)
            session.append_plan_revision(
                record={
                    "id": "revision:0",
                    "plan_revision": 0,
                    "task_id": "task_runtime_sched",
                    "objective": "阅读 README 并总结",
                    "planner_status": "continue",
                    "worker_task_count": 1,
                    "worker_tasks": [
                        {
                            "worker_task_id": "worker_readme",
                            "objective": "读取 README 并整理关键事实",
                            "depends_on": [],
                            "allowed_operator_refs": ["builtin://fs.read"],
                            "scope_summary": "仅允许读取 README.md",
                            "completion_contract_ref": "worker_result:v1",
                            "tool_budget": {"max_calls": 1, "max_parallel_calls": 1, "retry_read_only_tools": False},
                            "time_budget_ms": 15000,
                        }
                    ],
                    "status": "active",
                }
            )
            final_capsule = session.finalize_worker_task(
                task_id=worker_task_id,
                worker_task_id="worker_readme",
                state="succeeded",
                error_code=None,
                result_refs=[tool_capsule],
                output_summary="worker completed README inspection",
                extra={"tool_call_count": 1, "iteration_count": 1, "worker_status": "accepted"},
            )
            self.assertTrue(final_capsule)
            next_revision = session.advance_plan_revision(
                record={
                    "task_id": "task_runtime_sched",
                    "objective": "阅读 README 并总结",
                    "planner_status": "continue",
                    "worker_task_count": 1,
                    "worker_tasks": [
                        {
                            "worker_task_id": "worker_readme",
                            "objective": "读取 README 并整理关键事实",
                            "depends_on": [],
                            "allowed_operator_refs": ["builtin://fs.read"],
                            "scope_summary": "仅允许读取 README.md",
                            "completion_contract_ref": "worker_result:v1",
                            "tool_budget": {"max_calls": 1, "max_parallel_calls": 1, "retry_read_only_tools": False},
                            "time_budget_ms": 15000,
                        }
                    ],
                    "source_phase": "verifier_replanner",
                    "status": "active",
                }
            )
            self.assertEqual(next_revision, 1)
            session.finalize_root(
                final_delivery_state="done",
                error_code=None,
                result_refs=["ev_plan_1", "ev_verify_1", "ev_final_1"],
                output_summary="总结已生成",
            )

            graph = FileTaskGraphStore(data_dir).load(workspace_id="ws53", graph_id="g_runtime_sched")
            assert graph is not None
            self.assertEqual(graph.tasks[graph.root_task_id].state, "succeeded")
            self.assertEqual(graph.tasks[worker_task_id].state, "succeeded")
            self.assertEqual(graph.active_plan_revision, 1)
            self.assertEqual(graph.replan_count, 1)
            self.assertEqual(len(graph.message_turns), 1)
            self.assertGreaterEqual(len(graph.plan_revisions), 2)
            self.assertGreaterEqual(len(graph.result_capsules), 3)
            self.assertTrue(any(str(item.get("phase") or "") == "planner" for item in graph.leader_decisions))
            self.assertEqual(
                [task.task_id for task in graph.tasks.values() if (task.payload or {}).get("type") == "worker_task"],
                [worker_task_id],
            )
            self.assertTrue(any(str(item.get("event_kind") or "") == "tool_call" for item in graph.result_capsules))
            self.assertTrue(any(str(item.get("event_kind") or "") == "worker_final" for item in graph.result_capsules))

    def test_scheduler_compile_failure_marks_root_failed(self) -> None:
        with tempfile.TemporaryDirectory(prefix="agentos_next_t053_compile_") as td:
            data_dir = Path(td)
            scheduler = DurableRuntimeGraphScheduler.bootstrap_for_assistant_loop(
                RuntimeGraphSchedulerBootstrap(
                    data_dir=str(data_dir),
                    workspace_id="ws53",
                    graph_id="g_compile_failure",
                    logical_task_id="task_compile_failure",
                    query="坏输入",
                    objective="坏输入",
                    trace_id="tr_compile",
                    turn_id="turn_compile",
                    query_ref="ev_query_compile",
                    now_utc="2026-03-12T00:00:00Z",
                )
            )
            scheduler.record_compile_failure(
                error_code="E_QUERY_SCHEMA_INVALID",
                query_ref="ev_query_compile",
                verification_ref="ev_query_verify",
            )

            graph = FileTaskGraphStore(data_dir).load(workspace_id="ws53", graph_id="g_compile_failure")
            assert graph is not None
            self.assertEqual(graph.tasks[graph.root_task_id].state, "failed")
            self.assertEqual(graph.tasks[graph.root_task_id].error_code, "E_QUERY_SCHEMA_INVALID")
            self.assertTrue(any(str(item.get("id") or "") == "leader:compile" for item in graph.leader_decisions))

    def test_null_runtime_graph_session_is_noop(self) -> None:
        session = NullRuntimeGraphSession()
        self.assertEqual(session.ensure_worker_task(spec=WorkerTaskSpec(worker_task_id="w1", objective="noop")), None)
        self.assertEqual(
            session.record_worker_event(
                task_id="task_1",
                worker_task_id="w1",
                event_kind="tool_call",
                status="accepted",
            ),
            "",
        )
        self.assertEqual(
            session.finalize_worker_task(
                task_id="task_1",
                worker_task_id="w1",
                state="succeeded",
                error_code=None,
                result_refs=[],
            ),
            "",
        )
        self.assertEqual(session.list_worker_tasks(), [])
        session.finalize_root(final_delivery_state="done", error_code=None, result_refs=[])


if __name__ == "__main__":  # pragma: no cover
    unittest.main(verbosity=2)
