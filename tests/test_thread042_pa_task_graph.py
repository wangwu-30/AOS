from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from agentos_next.apps.telegram_connector import TelegramChannelAdapter
from agentos_next.kernel.evidence_store import FileEvidenceStore
from agentos_next.kernel.executor import ExecuteResult, ExecuteTiming
from agentos_next.kernel.hypothesis_store import FileHypothesisStore, HypothesisRecord
from agentos_next.kernel.idempotency_store import FileIdempotencyStore
from agentos_next.kernel.orchestrator import Orchestrator
from agentos_next.kernel.types import TraceContext
from agentos_next.pa.ev1_runtime import EV1Config, EV1Runtime
from agentos_next.pa.task_graph import (
    FileTaskGraphStore,
    TaskGraphError,
    TASK_GRAPH_ERROR_CYCLE_DETECTED,
    TASK_GRAPH_ERROR_REPLAY_DENY,
    add_task,
    append_context_snapshot,
    append_leader_decision,
    append_message_turn,
    append_plan_revision,
    append_result_capsule,
    build_task_bundle_v1,
    build_task_execution_policy_v1,
    compute_task_fingerprint,
    make_file_ref_v1,
    next_queued_task,
    recover_incomplete,
    set_graph_runtime_controls,
    set_task_state,
    update_task_runtime_metadata,
)

from tests.admission_helpers import make_minimal_skill_package
from tests.fixtures.telegram_webhook_fixtures import (
    generate_secret_token_fixture,
    generate_telegram_webhook_fixture,
)


def _make_envelope(*, update_id: int, workspace_id: str) -> object:
    secret = generate_secret_token_fixture()

    class _Capture:
        def __init__(self) -> None:
            self.last_envelope = None
            self.last_idem = None

        def dispatch(self, envelope, idempotency_key: str) -> None:  # noqa: ANN001
            self.last_envelope = envelope
            self.last_idem = idempotency_key

    cap = _Capture()
    adapter = TelegramChannelAdapter(expected_secret_token=secret, kernel_dispatcher=cap)
    payload = generate_telegram_webhook_fixture(update_id=update_id)
    code, body = adapter.handle_webhook(
        payload_str=payload,
        secret_token=secret,
        workspace_id=workspace_id,
        replay_mode=False,
    )
    assert code == 200, body
    assert cap.last_envelope is not None
    return cap.last_envelope


class TestThread042PATaskGraph(unittest.TestCase):
    def test_task_graph_persists_runtime_bundle_metadata(self) -> None:
        with tempfile.TemporaryDirectory(prefix="agentos_next_t042_runtime_bundle_") as td:
            data_dir = Path(td)
            store = FileTaskGraphStore(data_dir)
            graph = store.create_root_graph(
                workspace_id="ws1",
                graph_id="g_runtime",
                root_fingerprint=compute_task_fingerprint(kind="root", payload={"k": 1}),
                root_payload={"type": "root"},
                replay_mode=False,
                now_utc="2026-03-12T00:00:00Z",
            )
            policy = build_task_execution_policy_v1(deadline_ms=120000, llm_timeout_ms=9000, tool_timeout_ms=15000)
            bundle = build_task_bundle_v1(
                objective="inspect project files and summarize",
                completion_contract_ref="delivery_contract:v1",
                task_execution_policy=policy,
                context_snapshot_ref="context_graph:v1",
                workspace_root="/tmp/ws1",
                allowed_capabilities=["fs_read", "fs_list"],
                file_refs=[
                    make_file_ref_v1(
                        ref_type="workspace_path",
                        value="src/app.py",
                        usage="required",
                        summary="primary source file",
                    )
                ],
                read_only_ancestor_context_refs=["context_planes:v1"],
                worker_task_admission_mode="leader_gate",
                task_mode="decomposable",
                delegation_budget=2,
                max_depth=1,
                scope_guard={"worker_split_requires_leader": True},
            )
            graph = add_task(
                graph=graph,
                fingerprint=compute_task_fingerprint(kind="child", payload={"k": 2}),
                payload={"type": "child"},
                parent_task_id=graph.root_task_id,
                task_bundle=bundle,
                task_execution_policy=policy,
                file_refs=list(bundle.get("file_refs") or []),
                read_only_ancestor_context_refs=list(bundle.get("read_only_ancestor_context_refs") or []),
                workspace_root=str(bundle.get("workspace_root") or ""),
                worker_task_admission_mode="leader_gate",
                sufficient_for_execution=True,
                now_utc="2026-03-12T00:00:01Z",
            )
            store.save(graph=graph, replay_mode=False)

            loaded = store.load(workspace_id="ws1", graph_id="g_runtime")
            assert loaded is not None
            child = loaded.tasks["task_1"]
            self.assertEqual(loaded.type, "runtime_graph_v1")
            self.assertEqual(child.worker_task_admission_mode, "leader_gate")
            self.assertTrue(child.sufficient_for_execution)
            self.assertEqual(child.task_bundle["task_mode"], "decomposable")
            self.assertEqual(child.file_refs[0]["ref_type"], "workspace_path")

    def test_task_graph_persists_runtime_graph_records(self) -> None:
        with tempfile.TemporaryDirectory(prefix="agentos_next_t042_runtime_records_") as td:
            data_dir = Path(td)
            store = FileTaskGraphStore(data_dir)
            graph = store.create_root_graph(
                workspace_id="ws1",
                graph_id="g_runtime_records",
                root_fingerprint=compute_task_fingerprint(kind="root", payload={"k": "records"}),
                root_payload={"type": "assistant_loop_root"},
                replay_mode=False,
                now_utc="2026-03-12T00:00:00Z",
            )
            policy = build_task_execution_policy_v1(deadline_ms=120000)
            bundle = build_task_bundle_v1(
                objective="inspect runtime graph",
                completion_contract_ref="delivery_contract:v1",
                task_execution_policy=policy,
                context_snapshot_ref="context_graph:v1",
                workspace_root="/tmp/ws1",
                allowed_capabilities=["fs_read"],
                worker_task_admission_mode="leader_gate",
            )
            graph = set_graph_runtime_controls(graph=graph, active_plan_revision=1, max_parallel_workers=1, replan_count=1)
            graph = update_task_runtime_metadata(
                graph=graph,
                task_id=graph.root_task_id,
                plan_revision=1,
                context_snapshot_ref="context_graph:v1",
                completion_contract_ref="delivery_contract:v1",
                task_bundle=bundle,
                task_execution_policy=policy,
                workspace_root="/tmp/ws1",
                worker_task_admission_mode="leader_gate",
                sufficient_for_execution=True,
            )
            graph = append_message_turn(
                graph=graph,
                record={"id": "turn:1", "turn_id": "turn_1", "trace_id": "tr_1", "query": "hello"},
            )
            graph = append_plan_revision(
                graph=graph,
                record={"id": "revision:1", "plan_revision": 1, "status": "active", "action_count": 2},
            )
            graph = append_context_snapshot(
                graph=graph,
                record={"id": "context_graph:v1", "context_snapshot_ref": "context_graph:v1", "bundle_sufficient_for_execution": True},
            )
            graph = append_leader_decision(
                graph=graph,
                record={"id": "leader:intent:1", "phase": "intent_router", "status": "accepted"},
            )
            graph = append_result_capsule(
                graph=graph,
                record={"id": "capsule:root", "task_id": graph.root_task_id, "status": "done", "evidence_refs": ["ev_1"]},
            )
            store.save(graph=graph, replay_mode=False)

            loaded = store.load(workspace_id="ws1", graph_id="g_runtime_records")
            assert loaded is not None
            self.assertEqual(loaded.active_plan_revision, 1)
            self.assertEqual(loaded.replan_count, 1)
            self.assertEqual(len(loaded.message_turns), 1)
            self.assertEqual(len(loaded.plan_revisions), 1)
            self.assertEqual(len(loaded.context_snapshots), 1)
            self.assertEqual(len(loaded.leader_decisions), 1)
            self.assertEqual(len(loaded.result_capsules), 1)
            self.assertEqual(loaded.tasks[loaded.root_task_id].task_bundle["type"], "task_bundle_v1")

    def test_task_graph_persist_and_recover_states(self) -> None:
        with tempfile.TemporaryDirectory(prefix="agentos_next_t042_graph_") as td:
            data_dir = Path(td)
            store = FileTaskGraphStore(data_dir)

            g = store.create_root_graph(
                workspace_id="ws1",
                graph_id="g1",
                root_fingerprint=compute_task_fingerprint(kind="root", payload={"k": 1}),
                root_payload={"type": "root"},
                cycle_threshold=2,
                replay_mode=False,
                now_utc="2026-02-28T00:00:00Z",
            )
            g = add_task(
                graph=g,
                fingerprint=compute_task_fingerprint(kind="child", payload={"k": 2}),
                payload={"type": "child"},
                parent_task_id=g.root_task_id,
                now_utc="2026-02-28T00:00:01Z",
            )
            g = set_task_state(graph=g, task_id=g.root_task_id, state="running", now_utc="2026-02-28T00:00:02Z")
            g = set_task_state(graph=g, task_id=g.root_task_id, state="succeeded", now_utc="2026-02-28T00:00:03Z")
            store.save(graph=g, replay_mode=False)

            g2 = store.load(workspace_id="ws1", graph_id="g1")
            assert g2 is not None
            self.assertIn(g2.root_task_id, g2.tasks)
            self.assertEqual(g2.tasks[g2.root_task_id].state, "succeeded")
            t_next = next_queued_task(g2)
            self.assertIsNotNone(t_next)
            assert t_next is not None
            self.assertEqual(t_next.state, "queued")

    def test_cycle_detection_is_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory(prefix="agentos_next_t042_cycle_") as td:
            data_dir = Path(td)
            store = FileTaskGraphStore(data_dir)
            fp = compute_task_fingerprint(kind="same", payload={"k": 1})

            g = store.create_root_graph(
                workspace_id="ws1",
                graph_id="g1",
                root_fingerprint=fp,
                root_payload={"type": "root"},
                cycle_threshold=2,
                replay_mode=False,
            )

            # First add is ok (fingerprint count becomes 1).
            g = add_task(graph=g, fingerprint="fp_child", payload={"t": "child"})
            # Second attempt with same fingerprint as root would make count reach threshold (2) -> deny.
            with self.assertRaises(TaskGraphError) as ctx:
                _ = add_task(graph=g, fingerprint=fp, payload={"t": "dup"})
            self.assertEqual(ctx.exception.error_code, TASK_GRAPH_ERROR_CYCLE_DETECTED)

    def test_recover_incomplete_resets_running_to_queued(self) -> None:
        with tempfile.TemporaryDirectory(prefix="agentos_next_t042_recover_") as td:
            data_dir = Path(td)
            store = FileTaskGraphStore(data_dir)
            g = store.create_root_graph(
                workspace_id="ws1",
                graph_id="g1",
                root_fingerprint=compute_task_fingerprint(kind="root", payload={"k": 1}),
                root_payload={"type": "root"},
                replay_mode=False,
            )
            g = set_task_state(graph=g, task_id=g.root_task_id, state="running")
            store.save(graph=g, replay_mode=False)

            g2 = store.load(workspace_id="ws1", graph_id="g1")
            assert g2 is not None
            self.assertEqual(g2.tasks[g2.root_task_id].state, "running")
            g3 = recover_incomplete(g2, now_utc="2026-02-28T00:00:00Z")
            self.assertEqual(g3.tasks[g3.root_task_id].state, "queued")
            self.assertEqual(g3.tasks[g3.root_task_id].attempts, 1)

    def test_replay_mode_denies_writes_without_mkdir(self) -> None:
        with tempfile.TemporaryDirectory(prefix="agentos_next_t042_replay_") as td:
            data_dir = Path(td)
            store = FileTaskGraphStore(data_dir)
            with patch("pathlib.Path.mkdir", side_effect=RuntimeError("mkdir prohibited")):
                with self.assertRaises(TaskGraphError) as ctx:
                    _ = store.create_root_graph(
                        workspace_id="ws1",
                        graph_id="g1",
                        root_fingerprint="fp_root",
                        root_payload={"type": "root"},
                        replay_mode=True,
                    )
            self.assertEqual(ctx.exception.error_code, TASK_GRAPH_ERROR_REPLAY_DENY)
            self.assertFalse((data_dir / "pa" / "task_graph").exists())

    def test_ev1_writes_root_task_graph_state(self) -> None:
        with tempfile.TemporaryDirectory(prefix="agentos_next_t042_ev1_") as td:
            root = Path(td)
            pkg_dir = root / "pkg"
            data_dir = root / "data"
            make_minimal_skill_package(pkg_dir)

            env = _make_envelope(update_id=777, workspace_id="ws_pa")
            rt = EV1Runtime(EV1Config(data_dir=data_dir, skill_ref=str(pkg_dir), message_input_key="q"))
            out = rt.handle_envelope(env, replay_mode=False)
            self.assertTrue(out.get("ok"))

            store = FileTaskGraphStore(data_dir)
            g = store.load(workspace_id="ws_pa", graph_id="tg_update_777")
            assert g is not None
            status = (
                out.get("outbox", {})
                .get("execute", {})
                .get("status")
            )
            expected_state = "succeeded" if status == "accepted" else "failed"
            self.assertEqual(g.tasks[g.root_task_id].state, expected_state)

    def test_ev1_expands_actions_from_llm_io_with_builtin_skill_refs(self) -> None:
        with tempfile.TemporaryDirectory(prefix="agentos_next_t042_expand_") as td:
            data_dir = Path(td)
            store = FileTaskGraphStore(data_dir)
            graph = store.create_root_graph(
                workspace_id="ws_pa",
                graph_id="tg_action_expand",
                root_fingerprint=compute_task_fingerprint(kind="ev1_root", payload={"k": 1}),
                root_payload={"type": "ev1_root", "event_id": "tg_action_expand"},
                replay_mode=False,
            )
            store.save(graph=graph, replay_mode=False)

            evidence = FileEvidenceStore(data_dir=data_dir)
            llm_ref = evidence.add_json(
                {
                    "schema_version": "1.0.0",
                    "output": {
                        "reply": "ok",
                        "actions": [
                            {"operator_ref": "fs_write", "arguments": {"path": "index.html", "content": "hi"}},
                            {"operator_ref": "shell_exec", "arguments": {"command": "pwd"}},
                        ],
                    },
                },
                kind="llm_io",
            )
            result = ExecuteResult(
                status="accepted",
                evidence_refs=(llm_ref,),
                artifact_refs=(),
                error_code=None,
                timing=ExecuteTiming(started_at="2026-03-03T00:00:00Z", ended_at="2026-03-03T00:00:01Z"),
                target="local",
            )

            rt = EV1Runtime(EV1Config(data_dir=data_dir, skill_ref="skill://pa", message_input_key="q"))
            rt._maybe_expand_graph("ws_pa", "tg_action_expand", graph.root_task_id, result)

            expanded = store.load(workspace_id="ws_pa", graph_id="tg_action_expand")
            assert expanded is not None
            action_nodes = [t for t in expanded.tasks.values() if t.payload.get("type") == "action"]
            self.assertEqual(len(action_nodes), 2)
            operator_refs = {str(t.payload.get("operator_ref")) for t in action_nodes}
            self.assertEqual(operator_refs, {"builtin://fs.write", "builtin://shell.exec"})
            self.assertTrue(all("arguments" in t.payload for t in action_nodes))
            self.assertTrue(all("skill_ref" not in t.payload for t in action_nodes))
            aggregate_nodes = [t for t in expanded.tasks.values() if t.payload.get("type") == "aggregate_reasoning"]
            self.assertEqual(len(aggregate_nodes), 1)
            self.assertEqual(str(aggregate_nodes[0].payload.get("operator_ref")), "skill://pa")
            self.assertIn("arguments", aggregate_nodes[0].payload)

    def test_ev1_expand_is_idempotent_for_duplicate_actions(self) -> None:
        with tempfile.TemporaryDirectory(prefix="agentos_next_t042_expand_idem_") as td:
            data_dir = Path(td)
            store = FileTaskGraphStore(data_dir)
            graph = store.create_root_graph(
                workspace_id="ws_pa",
                graph_id="tg_expand_idem",
                root_fingerprint=compute_task_fingerprint(kind="ev1_root", payload={"k": 1}),
                root_payload={"type": "ev1_root", "event_id": "tg_expand_idem"},
                replay_mode=False,
            )
            store.save(graph=graph, replay_mode=False)

            evidence = FileEvidenceStore(data_dir=data_dir)
            llm_ref = evidence.add_json(
                {
                    "schema_version": "1.0.0",
                    "output": {
                        "reply": "ok",
                        "actions": [
                            {"operator_ref": "fs_write", "arguments": {"path": "index.html", "content": "hi"}},
                            {"operator_ref": "shell_exec", "arguments": {"command": "pwd"}},
                        ],
                    },
                },
                kind="llm_io",
            )
            result = ExecuteResult(
                status="accepted",
                evidence_refs=(llm_ref,),
                artifact_refs=(),
                error_code=None,
                timing=ExecuteTiming(started_at="2026-03-03T00:00:00Z", ended_at="2026-03-03T00:00:01Z"),
                target="local",
            )

            rt = EV1Runtime(EV1Config(data_dir=data_dir, skill_ref="skill://pa", message_input_key="q"))
            rt._maybe_expand_graph("ws_pa", "tg_expand_idem", graph.root_task_id, result)

            first = store.load(workspace_id="ws_pa", graph_id="tg_expand_idem")
            assert first is not None
            first_actions = [t for t in first.tasks.values() if t.payload.get("type") == "action"]
            first_aggregates = [t for t in first.tasks.values() if t.payload.get("type") == "aggregate_reasoning"]
            self.assertEqual(len(first_actions), 2)
            self.assertEqual(len(first_aggregates), 1)
            first_total = len(first.tasks)

            # Re-expand from reasoning parent with the same action payload.
            # This MUST be idempotent and must not keep growing the graph.
            reasoning_parent = first_aggregates[0].task_id
            rt._maybe_expand_graph("ws_pa", "tg_expand_idem", reasoning_parent, result)
            rt._maybe_expand_graph("ws_pa", "tg_expand_idem", reasoning_parent, result)

            second = store.load(workspace_id="ws_pa", graph_id="tg_expand_idem")
            assert second is not None
            self.assertEqual(len(second.tasks), first_total)
            second_actions = [t for t in second.tasks.values() if t.payload.get("type") == "action"]
            second_aggregates = [t for t in second.tasks.values() if t.payload.get("type") == "aggregate_reasoning"]
            self.assertEqual(len(second_actions), 2)
            self.assertEqual(len(second_aggregates), 1)

    def test_ev1_aggregate_reasoning_is_terminal_no_recursive_expand(self) -> None:
        with tempfile.TemporaryDirectory(prefix="agentos_next_t042_agg_terminal_") as td:
            data_dir = Path(td)
            store = FileTaskGraphStore(data_dir)
            graph = store.create_root_graph(
                workspace_id="ws_pa",
                graph_id="tg_agg_terminal",
                root_fingerprint=compute_task_fingerprint(kind="ev1_root", payload={"k": 1}),
                root_payload={"type": "ev1_root", "event_id": "tg_agg_terminal"},
                replay_mode=False,
            )
            graph = add_task(
                graph=graph,
                fingerprint=compute_task_fingerprint(kind="reasoning", payload={"r": 1}),
                payload={"type": "aggregate_reasoning", "operator_ref": "skill://pa", "arguments": {"request": "x"}},
                parent_task_id=graph.root_task_id,
            )
            store.save(graph=graph, replay_mode=False)
            aggregate_ids = [t.task_id for t in graph.tasks.values() if t.payload.get("type") == "aggregate_reasoning"]
            self.assertEqual(len(aggregate_ids), 1)
            parent_agg = aggregate_ids[0]

            evidence = FileEvidenceStore(data_dir=data_dir)
            llm_ref = evidence.add_json(
                {
                    "schema_version": "1.0.0",
                    "output": {
                        "reply": "let me search more",
                        "actions": [{"operator_ref": "web_search", "arguments": {"query": "AAPL stock"}}],
                    },
                },
                kind="llm_io",
            )
            result = ExecuteResult(
                status="accepted",
                evidence_refs=(llm_ref,),
                artifact_refs=(),
                error_code=None,
                timing=ExecuteTiming(started_at="2026-03-03T00:00:00Z", ended_at="2026-03-03T00:00:01Z"),
                target="local",
            )

            rt = EV1Runtime(EV1Config(data_dir=data_dir, skill_ref="skill://pa", message_input_key="q"))
            before = store.load(workspace_id="ws_pa", graph_id="tg_agg_terminal")
            assert before is not None
            before_total = len(before.tasks)

            rt._maybe_expand_graph("ws_pa", "tg_agg_terminal", parent_agg, result)

            after = store.load(workspace_id="ws_pa", graph_id="tg_agg_terminal")
            assert after is not None
            self.assertEqual(len(after.tasks), before_total)

    def test_aggregate_reasoning_request_includes_success_and_failure_details(self) -> None:
        with tempfile.TemporaryDirectory(prefix="agentos_next_t042_agg_audit_") as td:
            data_dir = Path(td)
            store = FileTaskGraphStore(data_dir)
            graph = store.create_root_graph(
                workspace_id="ws_pa",
                graph_id="tg_agg_audit",
                root_fingerprint=compute_task_fingerprint(kind="ev1_root", payload={"k": 1}),
                root_payload={"type": "ev1_root", "event_id": "tg_agg_audit"},
                replay_mode=False,
            )
            graph = set_task_state(graph=graph, task_id=graph.root_task_id, state="succeeded")
            graph = add_task(
                graph=graph,
                fingerprint=compute_task_fingerprint(kind="action", payload={"n": 1}),
                payload={"type": "action", "operator_ref": "builtin://fs.list", "arguments": {"path": "."}},
                parent_task_id=graph.root_task_id,
            )
            graph = add_task(
                graph=graph,
                fingerprint=compute_task_fingerprint(kind="action", payload={"n": 2}),
                payload={"type": "action", "operator_ref": "builtin://fs.read", "arguments": {"path": "~/codex/agentos-next/README.md"}},
                parent_task_id=graph.root_task_id,
            )
            graph = add_task(
                graph=graph,
                fingerprint=compute_task_fingerprint(kind="reasoning", payload={"n": 3}),
                payload={"type": "aggregate_reasoning", "operator_ref": "skill://pa", "arguments": {"request": "summarize"}},
                parent_task_id=graph.root_task_id,
            )
            graph = set_task_state(graph=graph, task_id="task_1", state="succeeded")
            graph = set_task_state(graph=graph, task_id="task_2", state="failed", error_code="E_EXECUTION_FAILED")
            store.save(graph=graph, replay_mode=False)

            action_nodes = [t for t in graph.tasks.values() if t.payload.get("type") == "action"]
            aggregate_node = [t for t in graph.tasks.values() if t.payload.get("type") == "aggregate_reasoning"][0]

            evidence = FileEvidenceStore(data_dir=data_dir)
            success_ref = evidence.add_json(
                {"schema_version": "1.0.0", "ok": True, "items": [{"name": "README.md", "is_dir": False}]},
                kind="tool_io",
            )
            failure_ref = evidence.add_json(
                {"schema_version": "1.0.0", "ok": False, "error_code": "E_EXECUTION_FAILED", "message": "file not found: ~/codex/agentos-next/README.md"},
                kind="error",
            )
            idem = FileIdempotencyStore(data_dir=data_dir)
            idem.put_if_absent(
                workspace_id="ws_pa",
                idempotency_key="tg_tg_agg_audit_task_1",
                result=ExecuteResult(
                    status="accepted",
                    evidence_refs=(success_ref,),
                    artifact_refs=(),
                    error_code=None,
                    timing=ExecuteTiming(started_at="2026-03-07T00:00:00Z", ended_at="2026-03-07T00:00:01Z"),
                    target="local",
                ),
            )
            idem.put_if_absent(
                workspace_id="ws_pa",
                idempotency_key="tg_tg_agg_audit_task_2",
                result=ExecuteResult(
                    status="failed",
                    evidence_refs=(failure_ref,),
                    artifact_refs=(),
                    error_code="E_EXECUTION_FAILED",
                    timing=ExecuteTiming(started_at="2026-03-07T00:00:00Z", ended_at="2026-03-07T00:00:01Z"),
                    target="local",
                ),
            )

            rt = EV1Runtime(EV1Config(data_dir=data_dir, skill_ref="skill://pa", message_input_key="q"))
            orch = Orchestrator(local_executor=None, remote_executor=None, idempotency_store=idem, data_dir=str(data_dir))
            summaries = rt._collect_sibling_action_summaries(
                graph=graph,
                task=aggregate_node,
                workspace_id="ws_pa",
                event_id="tg_agg_audit",
                orch=orch,
            )
            request = rt._augment_reasoning_request(
                base_request="summarize",
                sibling_summaries=summaries,
                recent_failures=[],
                aggregate=True,
            )

            self.assertEqual(len(action_nodes), 2)
            self.assertIn("Action builtin://fs.list", request)
            self.assertIn("status=success; output=", request)
            self.assertIn('"name": "README.md"', request)
            self.assertIn('"ok": true', request)
            self.assertIn("Action builtin://fs.read", request)
            self.assertIn("status=failed; detail=file not found: ~/codex/agentos-next/README.md", request)
            self.assertIn("You MUST explicitly report relevant tool successes and tool failures.", request)
            self.assertIn("Do not hide failed steps.", request)

    def test_run_pending_tasks_parallel_batch_python314_safe(self) -> None:
        with tempfile.TemporaryDirectory(prefix="agentos_next_t042_batch_") as td:
            data_dir = Path(td)
            store = FileTaskGraphStore(data_dir)
            graph = store.create_root_graph(
                workspace_id="ws_pa",
                graph_id="tg_batch",
                root_fingerprint=compute_task_fingerprint(kind="ev1_root", payload={"k": 1}),
                root_payload={"type": "ev1_root", "event_id": "tg_batch"},
                replay_mode=False,
            )
            graph = set_task_state(graph=graph, task_id=graph.root_task_id, state="succeeded")
            graph = add_task(
                graph=graph,
                fingerprint=compute_task_fingerprint(kind="action", payload={"n": 1}),
                payload={"type": "action", "operator_ref": "builtin://fs.list", "arguments": {"path": "."}},
                parent_task_id=graph.root_task_id,
            )
            store.save(graph=graph, replay_mode=False)

            rt = EV1Runtime(EV1Config(data_dir=data_dir, skill_ref="skill://pa", message_input_key="q"))

            async def _mark_succeeded(task, workspace_id, event_id, trace_context, policy_context, orch):  # noqa: ANN001
                g = store.load(workspace_id=workspace_id, graph_id=event_id)
                assert g is not None
                g = set_task_state(graph=g, task_id=task.task_id, state="succeeded")
                store.save(graph=g, replay_mode=False)

            rt._execute_task = AsyncMock(side_effect=_mark_succeeded)  # type: ignore[method-assign]
            rt.run_pending_tasks(
                workspace_id="ws_pa",
                event_id="tg_batch",
                trace_context=TraceContext(trace_id="tr", turn_id="turn", span_id="span"),
                policy_context={},
            )

            done = store.load(workspace_id="ws_pa", graph_id="tg_batch")
            assert done is not None
            action_states = [t.state for t in done.tasks.values() if t.payload.get("type") == "action"]
            self.assertEqual(action_states, ["succeeded"])

    def test_ev1_emits_capability_resolution_evidence_on_expand(self) -> None:
        with tempfile.TemporaryDirectory(prefix="agentos_next_t042_capres_") as td:
            data_dir = Path(td)
            store = FileTaskGraphStore(data_dir)
            graph = store.create_root_graph(
                workspace_id="ws_pa",
                graph_id="tg_capres",
                root_fingerprint=compute_task_fingerprint(kind="ev1_root", payload={"k": 1}),
                root_payload={"type": "ev1_root", "event_id": "tg_capres"},
                replay_mode=False,
            )
            store.save(graph=graph, replay_mode=False)

            evidence = FileEvidenceStore(data_dir=data_dir)
            llm_ref = evidence.add_json(
                {
                    "schema_version": "1.0.0",
                    "output": {
                        "reply": "ok",
                        "actions": [{"operator_ref": "fs_write", "arguments": {"path": "index.html", "content": "hi"}}],
                    },
                },
                kind="llm_io",
            )
            result = ExecuteResult(
                status="accepted",
                evidence_refs=(llm_ref,),
                artifact_refs=(),
                error_code=None,
                timing=ExecuteTiming(started_at="2026-03-03T00:00:00Z", ended_at="2026-03-03T00:00:01Z"),
                target="local",
            )

            rt = EV1Runtime(EV1Config(data_dir=data_dir, skill_ref="skill://pa", message_input_key="q"))
            rt._maybe_expand_graph("ws_pa", "tg_capres", graph.root_task_id, result)

            found = False
            for meta_path in (data_dir / "evidence" / "meta").glob("*.json"):
                obj = json.loads(meta_path.read_text(encoding="utf-8"))
                ref = str(obj.get("ref") or "")
                blob = evidence.get_blob(ref)
                if blob is None or blob.content_type != "application/json":
                    continue
                payload = json.loads(blob.content.decode("utf-8"))
                if payload.get("type") == "capability_resolution_decision_v1":
                    found = True
                    self.assertEqual(payload.get("policy"), "skill_first")
                    self.assertEqual(payload.get("selected_strategy"), "tool_composition")
                    break
            self.assertTrue(found)

    def test_run_pending_tasks_blocks_repeated_rejected_hypothesis(self) -> None:
        with tempfile.TemporaryDirectory(prefix="agentos_next_t042_hyp_block_") as td:
            data_dir = Path(td)
            store = FileTaskGraphStore(data_dir)
            graph = store.create_root_graph(
                workspace_id="ws_pa",
                graph_id="tg_hyp_block",
                root_fingerprint=compute_task_fingerprint(kind="ev1_root", payload={"k": 1}),
                root_payload={"type": "ev1_root", "event_id": "tg_hyp_block"},
                replay_mode=False,
            )
            graph = set_task_state(graph=graph, task_id=graph.root_task_id, state="succeeded")
            graph = add_task(
                graph=graph,
                fingerprint=compute_task_fingerprint(kind="action", payload={"n": 1}),
                payload={"type": "action", "skill_ref": "builtin://fs.list", "input": {"path": "."}},
                parent_task_id=graph.root_task_id,
            )
            store.save(graph=graph, replay_mode=False)

            rt = EV1Runtime(EV1Config(data_dir=data_dir, skill_ref="skill://pa", message_input_key="q"))
            ready_graph = store.load(workspace_id="ws_pa", graph_id="tg_hyp_block")
            assert ready_graph is not None
            task = [t for t in ready_graph.tasks.values() if t.payload.get("type") == "action"][0]
            hypothesis = rt._build_task_hypothesis(task=task, task_input=dict(task.payload.get("input") or {}))
            hyp_store = FileHypothesisStore(data_dir=data_dir)
            hyp_store.put_if_absent(
                workspace_id="ws_pa",
                record=HypothesisRecord(
                    schema_version="1.0.0",
                    turn_id="turn_prev",
                    iteration=1,
                    hypothesis=hypothesis,
                    verification_action="execute:builtin://fs.list",
                    verification_evidence_refs=(),
                    result="rejected",
                    revision="same task already failed",
                ),
            )

            with patch("agentos_next.pa.ev1_runtime.Orchestrator.for_data_dir") as mocked_for_dir:
                mocked_orch = AsyncMock()
                mocked_for_dir.return_value = mocked_orch
                rt.run_pending_tasks(
                    workspace_id="ws_pa",
                    event_id="tg_hyp_block",
                    trace_context=TraceContext(trace_id="tr", turn_id="turn", span_id="span"),
                    policy_context={},
                )

            done = store.load(workspace_id="ws_pa", graph_id="tg_hyp_block")
            assert done is not None
            action_state = [t for t in done.tasks.values() if t.payload.get("type") == "action"][0]
            self.assertEqual(action_state.state, "failed")
            self.assertEqual(action_state.error_code, "E_HYPOTHESIS_REPEAT_WITHOUT_NEW_EVIDENCE")

    def test_ev1_execute_task_reads_legacy_skill_ref_input_payload(self) -> None:
        with tempfile.TemporaryDirectory(prefix="agentos_next_t042_legacy_exec_") as td:
            data_dir = Path(td)
            store = FileTaskGraphStore(data_dir)
            graph = store.create_root_graph(
                workspace_id="ws_pa",
                graph_id="tg_legacy_exec",
                root_fingerprint=compute_task_fingerprint(kind="ev1_root", payload={"k": 1}),
                root_payload={"type": "ev1_root", "event_id": "tg_legacy_exec"},
                replay_mode=False,
            )
            graph = set_task_state(graph=graph, task_id=graph.root_task_id, state="succeeded")
            graph = add_task(
                graph=graph,
                fingerprint=compute_task_fingerprint(kind="action", payload={"n": 1}),
                payload={"type": "action", "skill_ref": "builtin://fs.list", "input": {"path": "."}},
                parent_task_id=graph.root_task_id,
            )
            store.save(graph=graph, replay_mode=False)

            task = store.load(workspace_id="ws_pa", graph_id="tg_legacy_exec").tasks["task_1"]  # type: ignore[union-attr]
            result = ExecuteResult(
                status="accepted",
                evidence_refs=(),
                artifact_refs=(),
                error_code=None,
                timing=ExecuteTiming(started_at="2026-03-03T00:00:00Z", ended_at="2026-03-03T00:00:01Z"),
                target="local",
            )
            orch = AsyncMock()
            orch.execute = AsyncMock(return_value=result)

            rt = EV1Runtime(EV1Config(data_dir=data_dir, skill_ref="skill://pa", message_input_key="q"))
            from agentos_next.pa.ev1_runtime import _run_async

            _run_async(
                rt._execute_task(
                    task,
                    "ws_pa",
                    "tg_legacy_exec",
                    TraceContext(trace_id="tr", turn_id="turn", span_id="span"),
                    {},
                    orch,
                )
            )

            req = orch.execute.await_args.args[0]
            self.assertEqual(req.operator_ref, "builtin://fs.list")
            self.assertEqual(req.arguments, {"path": "."})


if __name__ == "__main__":  # pragma: no cover
    unittest.main(verbosity=2)
