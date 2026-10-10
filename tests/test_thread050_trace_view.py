from __future__ import annotations

import io
import json
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory

import bootstrap  # noqa: F401

from agentos_next.cli import main
from agentos_next.kernel.evidence_store import FileEvidenceStore
from agentos_next.kernel.executor import ExecuteResult, ExecuteTiming
from agentos_next.kernel.idempotency_store import FileIdempotencyStore
from agentos_next.kernel.trace_logger import FileTraceLogger
from agentos_next.kernel.types import TraceContext, TraceEvent
from agentos_next.pa.event_log import FileEventLog
from agentos_next.pa.outbox_store import FileOutboxStore, OutboxItem
from agentos_next.pa.task_graph import FileTaskGraphStore, add_task, compute_task_fingerprint
from agentos_next.runtime.package_runner import PackageRunner, PackageRunRequest
from agentos_next.tools.trace_view import build_trace_catalog, trace_serve_response
from tests.admission_helpers import make_minimal_skill_package


class TestThread050TraceView(unittest.TestCase):
    def _run_cli(self, argv: list[str]) -> tuple[int, dict[str, object]]:
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            code = main(argv)
        lines = [line for line in stdout.getvalue().splitlines() if line.strip()]
        self.assertGreaterEqual(len(lines), 1, msg="expected JSON output from CLI")
        return code, json.loads(lines[-1])

    def test_trace_view_by_trace_id_includes_prompt_and_outputs(self) -> None:
        with TemporaryDirectory(prefix="agentos_next_t050_trace_") as td:
            root = Path(td)
            data_dir = root / "data"
            pkg_dir = root / "pkg"
            make_minimal_skill_package(pkg_dir)

            trace = TraceContext(trace_id="tr_t050_pkg", turn_id="turn_t050_pkg", span_id="span_t050_pkg")
            runner = PackageRunner.for_data_dir(data_dir)
            res = runner.run(
                PackageRunRequest(
                    skill_dir=pkg_dir,
                    input_obj={"q": "hello"},
                    workspace_id="ws_t050",
                    trace=trace,
                    verify_asvp=False,
                    backend="local_mock",
                )
            )
            self.assertTrue(res.ok, msg=f"runner failed: {res.error_code}")

            code, out = self._run_cli(
                [
                    "mvp",
                    "trace-view",
                    "--data-dir",
                    str(data_dir),
                    "--trace-id",
                    trace.trace_id,
                ]
            )
            self.assertEqual(code, 0)
            self.assertTrue(out.get("ok"))
            prompts = ((out.get("evidence") or {}).get("prompts") or [])
            self.assertGreaterEqual(len(prompts), 1)
            self.assertIn("Input JSON:", str(prompts[0].get("text") or ""))
            self.assertGreaterEqual(int(((out.get("summary") or {}).get("llm_output_count") or 0)), 1)

    def test_trace_view_by_event_id_includes_pa_and_task_idempotency(self) -> None:
        with TemporaryDirectory(prefix="agentos_next_t050_pa_") as td:
            root = Path(td)
            data_dir = root / "data"
            workspace_id = "local"
            event_id = "tg_update_42"
            trace_id = f"tr_pa_{event_id}"
            turn_id = f"turn_pa_{event_id}"
            span_id = f"span_pa_{event_id}"

            evidence = FileEvidenceStore(data_dir=data_dir)
            trace_log = FileTraceLogger(data_dir=data_dir)

            input_ref = evidence.add_json(
                {"schema_version": "1.0.0", "skill": "personal_assistant_brief", "input": {"request": "hello"}},
                kind="tool_io",
            )
            root_prompt_ref = evidence.add_text("root prompt", kind="llm_io")
            root_output_ref = evidence.add_json(
                {"schema_version": "1.0.0", "output": {"reply": "root ok"}},
                kind="llm_io",
            )
            trace_log.emit(
                TraceEvent(
                    schema_version="1.0.0",
                    ctx=TraceContext(trace_id=trace_id, turn_id=turn_id, span_id=span_id),
                    event_type="TOOL_CALL_STARTED",
                    ts="2026-03-07T00:00:00Z",
                    evidence_refs=(input_ref,),
                    data={"skill": "personal_assistant_brief"},
                )
            )
            trace_log.emit(
                TraceEvent(
                    schema_version="1.0.0",
                    ctx=TraceContext(trace_id=trace_id, turn_id=turn_id, span_id=span_id),
                    event_type="TOOL_CALL_FINISHED",
                    ts="2026-03-07T00:00:01Z",
                    evidence_refs=(root_prompt_ref, root_output_ref),
                    data={"skill": "personal_assistant_brief", "ok": True},
                )
            )

            FileEventLog(data_dir=data_dir).write_once(
                workspace_id=workspace_id,
                event_id=event_id,
                envelope={
                    "schema_version": "1.0.0",
                    "event_id": event_id,
                    "workspace_id": workspace_id,
                    "conversation_id": "chat_1",
                    "message_text": "hello",
                },
            )
            FileOutboxStore(data_dir=data_dir).put_if_absent(
                item=OutboxItem(
                    schema_version="1.0.0",
                    stored_at_utc="2026-03-07T00:00:02Z",
                    workspace_id=workspace_id,
                    event_id=event_id,
                    idempotency_key="idem_42",
                    trace_id=trace_id,
                    turn_id=turn_id,
                    span_id=span_id,
                    execute_status="accepted",
                    execute_error_code=None,
                    evidence_refs=(root_prompt_ref.ref, root_output_ref.ref),
                    reply_text="root ok",
                )
            )

            tg_store = FileTaskGraphStore(data_dir=data_dir)
            graph = tg_store.create_root_graph(
                workspace_id=workspace_id,
                graph_id=event_id,
                root_fingerprint=compute_task_fingerprint(kind="ev1_root", payload={"event_id": event_id}),
                root_payload={"type": "ev1_root", "event_id": event_id},
                replay_mode=False,
                now_utc="2026-03-07T00:00:00Z",
            )
            graph = add_task(
                graph=graph,
                fingerprint=compute_task_fingerprint(kind="action", payload={"skill_ref": "builtin://shell.exec"}),
                payload={"type": "action", "skill_ref": "builtin://shell.exec"},
                parent_task_id=graph.root_task_id,
                now_utc="2026-03-07T00:00:01Z",
            )
            tg_store.save(graph=graph, replay_mode=False)

            child_prompt_ref = evidence.add_text("child prompt", kind="llm_io")
            child_output_ref = evidence.add_json(
                {"schema_version": "1.0.0", "output": {"reply": "child ok"}},
                kind="llm_io",
            )
            trace_log.emit(
                TraceEvent(
                    schema_version="1.0.0",
                    ctx=TraceContext(
                        trace_id=trace_id,
                        turn_id=turn_id,
                        span_id=f"{span_id}_task_1",
                        parent_span_id=span_id,
                    ),
                    event_type="TOOL_CALL_FINISHED",
                    ts="2026-03-07T00:00:03Z",
                    evidence_refs=(child_prompt_ref, child_output_ref),
                    data={"builtin": "shell.exec", "task_id": "task_1", "ok": True},
                )
            )
            FileIdempotencyStore(data_dir=data_dir).put_if_absent(
                workspace_id=workspace_id,
                idempotency_key=f"tg_{event_id}_task_1",
                result=ExecuteResult(
                    status="accepted",
                    evidence_refs=(child_prompt_ref, child_output_ref),
                    artifact_refs=(),
                    error_code=None,
                    timing=ExecuteTiming(started_at="2026-03-07T00:00:03Z", ended_at="2026-03-07T00:00:04Z"),
                    target="local",
                ),
            )

            code, out = self._run_cli(
                [
                    "mvp",
                    "trace-view",
                    "--data-dir",
                    str(data_dir),
                    "--workspace-id",
                    workspace_id,
                    "--event-id",
                    event_id,
                    "--html-out",
                ]
            )
            self.assertEqual(code, 0)
            self.assertTrue(out.get("ok"))
            pa = out.get("pa") or {}
            self.assertIsNotNone(pa.get("event"))
            self.assertIsNotNone(pa.get("outbox"))
            self.assertIsNotNone(pa.get("task_graph"))
            self.assertEqual(len(pa.get("task_executions") or []), 1)

            prompts = ((out.get("evidence") or {}).get("prompts") or [])
            prompt_texts = {str(item.get("text") or "") for item in prompts}
            self.assertIn("root prompt", prompt_texts)
            self.assertIn("child prompt", prompt_texts)
            html_report_path = Path(str(out.get("html_report_path") or ""))
            self.assertTrue(html_report_path.exists())
            html_text = html_report_path.read_text(encoding="utf-8")
            self.assertIn("Trace Timeline", html_text)
            self.assertIn("root prompt", html_text)
            self.assertIn("Execution DAG", html_text)
            self.assertIn("Prompt Diffs", html_text)
            self.assertIn("Output Diffs", html_text)
            self.assertIn("Context Diffs", html_text)
            self.assertIn("Trace Filters", html_text)
            self.assertIn("task-filter", html_text)
            self.assertIn("data-task-focus='task_1'", html_text)
            self.assertIn("Task Inspector", html_text)
            self.assertIn("timeline-row", html_text)
            self.assertIn("trace-line-3", html_text)
            self.assertIn("data-task-ids='task_1'", html_text)

    def test_trace_view_renders_runtime_inspector_panels(self) -> None:
        with TemporaryDirectory(prefix="agentos_next_t050_runtime_panels_") as td:
            root = Path(td)
            data_dir = root / "data"
            workspace_id = "local"
            event_id = "tg_update_runtime_panels"
            trace_id = f"tr_pa_{event_id}"
            turn_id = f"turn_pa_{event_id}"
            span_id = f"span_pa_{event_id}"

            evidence = FileEvidenceStore(data_dir=data_dir)
            query_ref = evidence.add_json(
                {
                    "schema_version": "1.0.0",
                    "type": "query_gated_query_v1",
                    "task_bundle": {
                        "schema_version": "1.0.0",
                        "type": "task_bundle_v1",
                        "objective": "inspect runtime bundle",
                        "worker_task_admission_mode": "leader_gate",
                        "delegation_budget": 2,
                        "max_depth": 1,
                        "sufficient_for_execution": True,
                        "context_snapshot_ref": "context_graph:v1",
                        "read_only_ancestor_context_refs": ["context_planes:v1"],
                        "task_mode": "decomposable",
                        "scope_guard": {"worker_split_requires_leader": True},
                        "file_refs": [
                            {
                                "schema_version": "1.0.0",
                                "type": "file_ref_v1",
                                "ref_type": "workspace_path",
                                "value": "src/app.py",
                                "usage": "required",
                                "summary": "entry source",
                                "resolver": "fs.read",
                            }
                        ],
                    },
                    "task_execution_policy": {
                        "schema_version": "1.0.0",
                        "type": "task_execution_policy_v1",
                        "llm_timeout_ms": 9000,
                        "tool_timeout_ms": 15000,
                        "max_attempts": 3,
                        "side_effect_safe_retry": False,
                        "tool_retry_policy": {"strategy": "bounded_retry", "max_retries": 1},
                    },
                    "file_refs": [
                        {
                            "schema_version": "1.0.0",
                            "type": "file_ref_v1",
                            "ref_type": "workspace_path",
                            "value": "src/app.py",
                            "usage": "required",
                            "summary": "entry source",
                            "resolver": "fs.read",
                        }
                    ],
                },
                kind="routing",
            )
            final_ref = evidence.add_json(
                {
                    "schema_version": "1.0.0",
                    "type": "assistant_loop_result",
                    "delivery_state": "hold",
                    "steps": [
                        {
                            "internal_role_phase": "intent_router",
                            "status": "accepted",
                            "deadline_ms": 9000,
                        },
                        {
                            "internal_role_phase": "planner",
                            "status": "accepted",
                            "deadline_ms": 9000,
                        },
                        {
                            "internal_role_phase": "verifier_replanner",
                            "status": "accepted",
                            "deadline_ms": 9000,
                        },
                        {
                            "internal_role_phase": "communicator",
                            "status": "missing",
                            "deadline_ms": 0,
                        },
                    ],
                },
                kind="snapshot",
            )
            FileTraceLogger(data_dir=data_dir).emit(
                TraceEvent(
                    schema_version="1.0.0",
                    ctx=TraceContext(trace_id=trace_id, turn_id=turn_id, span_id=span_id),
                    event_type="ROUTED",
                    ts="2026-03-12T00:00:00Z",
                    evidence_refs=(query_ref, final_ref),
                    data={"component": "query_gated_runtime", "ok": True},
                )
            )
            FileEventLog(data_dir=data_dir).write_once(
                workspace_id=workspace_id,
                event_id=event_id,
                envelope={
                    "schema_version": "1.0.0",
                    "event_id": event_id,
                    "workspace_id": workspace_id,
                    "conversation_id": "chat_runtime",
                    "message_text": "runtime panel message",
                },
            )
            FileOutboxStore(data_dir=data_dir).put_if_absent(
                item=OutboxItem(
                    schema_version="1.0.0",
                    stored_at_utc="2026-03-12T00:00:01Z",
                    workspace_id=workspace_id,
                    event_id=event_id,
                    idempotency_key="idem_runtime_panels",
                    trace_id=trace_id,
                    turn_id=turn_id,
                    span_id=span_id,
                    execute_status="accepted",
                    execute_error_code=None,
                    evidence_refs=(query_ref.ref, final_ref.ref),
                    reply_text="",
                )
            )
            tg_store = FileTaskGraphStore(data_dir=data_dir)
            graph = tg_store.create_root_graph(
                workspace_id=workspace_id,
                graph_id=event_id,
                root_fingerprint=compute_task_fingerprint(kind="runtime_panels", payload={"event_id": event_id}),
                root_payload={"type": "assistant_loop_root"},
                replay_mode=False,
                now_utc="2026-03-12T00:00:00Z",
            )
            graph_json = graph.to_json()
            graph_json["plan_revisions"] = [
                {
                    "id": "revision:0",
                    "plan_revision": 0,
                    "planner_status": "active",
                    "action_count": 1,
                }
            ]
            graph_json["result_capsules"] = [
                {
                    "id": "capsule:root:final",
                    "task_id": graph.root_task_id,
                    "status": "hold",
                    "delivery_state": "hold",
                    "operator_ref": "builtin://channel.send_message",
                    "evidence_refs": [query_ref.ref, final_ref.ref],
                }
            ]
            graph_json["leader_decisions"] = [
                {"id": "leader:intent:1", "phase": "intent_router", "status": "accepted", "step_index": 1, "deadline_ms": 9000},
                {"id": "leader:planner:2", "phase": "planner", "status": "accepted", "step_index": 2, "deadline_ms": 9000},
            ]
            task_graph_path = data_dir / "pa" / "task_graph" / workspace_id / f"{event_id}.json"
            task_graph_path.write_text(json.dumps(graph_json, ensure_ascii=False, sort_keys=True), encoding="utf-8")

            status, content_type, body = trace_serve_response(
                data_dir=data_dir,
                path=f"/trace?event_id={event_id}&workspace_id={workspace_id}",
            )
            self.assertEqual(status, 200)
            self.assertIn("text/html", content_type)
            html_text = body.decode("utf-8")
            self.assertIn("Leader Rail", html_text)
            self.assertIn("Task Bundle", html_text)
            self.assertIn("File Refs", html_text)
            self.assertIn("Execution Policy", html_text)
            self.assertIn("Context Chain", html_text)
            self.assertIn("Plan Revisions", html_text)
            self.assertIn("Result Capsules", html_text)
            self.assertIn("Retry & Timeout", html_text)
            self.assertIn("leader_gate", html_text)

    def test_trace_catalog_and_http_routes_render_html(self) -> None:
        with TemporaryDirectory(prefix="agentos_next_t050_catalog_") as td:
            root = Path(td)
            data_dir = root / "data"
            workspace_id = "local"
            event_id = "tg_update_99"
            trace_id = f"tr_pa_{event_id}"
            turn_id = f"turn_pa_{event_id}"
            span_id = f"span_pa_{event_id}"

            evidence = FileEvidenceStore(data_dir=data_dir)
            prompt_ref = evidence.add_text("catalog prompt", kind="llm_io")
            output_ref = evidence.add_json({"schema_version": "1.0.0", "output": {"reply": "catalog ok"}}, kind="llm_io")
            FileTraceLogger(data_dir=data_dir).emit(
                TraceEvent(
                    schema_version="1.0.0",
                    ctx=TraceContext(trace_id=trace_id, turn_id=turn_id, span_id=span_id),
                    event_type="TOOL_CALL_FINISHED",
                    ts="2026-03-07T00:00:01Z",
                    evidence_refs=(prompt_ref, output_ref),
                    data={"skill": "personal_assistant_brief", "ok": True},
                )
            )
            FileEventLog(data_dir=data_dir).write_once(
                workspace_id=workspace_id,
                event_id=event_id,
                envelope={
                    "schema_version": "1.0.0",
                    "event_id": event_id,
                    "workspace_id": workspace_id,
                    "conversation_id": "chat_99",
                    "message_text": "catalog message",
                },
            )
            FileOutboxStore(data_dir=data_dir).put_if_absent(
                item=OutboxItem(
                    schema_version="1.0.0",
                    stored_at_utc="2026-03-07T00:00:02Z",
                    workspace_id=workspace_id,
                    event_id=event_id,
                    idempotency_key="idem_99",
                    trace_id=trace_id,
                    turn_id=turn_id,
                    span_id=span_id,
                    execute_status="accepted",
                    execute_error_code=None,
                    evidence_refs=(prompt_ref.ref, output_ref.ref),
                    reply_text="catalog ok",
                )
            )
            second_event_id = "tg_update_100"
            second_trace_id = f"tr_pa_{second_event_id}"
            second_turn_id = f"turn_pa_{second_event_id}"
            second_span_id = f"span_pa_{second_event_id}"
            second_prompt_ref = evidence.add_text("catalog prompt second", kind="llm_io")
            second_output_ref = evidence.add_json(
                {"schema_version": "1.0.0", "output": {"reply": "catalog ok second"}},
                kind="llm_io",
            )
            FileTraceLogger(data_dir=data_dir).emit(
                TraceEvent(
                    schema_version="1.0.0",
                    ctx=TraceContext(trace_id=second_trace_id, turn_id=second_turn_id, span_id=second_span_id),
                    event_type="TOOL_CALL_FINISHED",
                    ts="2026-03-07T00:00:03Z",
                    evidence_refs=(second_prompt_ref, second_output_ref),
                    data={"skill": "personal_assistant_brief", "ok": True},
                )
            )
            FileEventLog(data_dir=data_dir).write_once(
                workspace_id=workspace_id,
                event_id=second_event_id,
                envelope={
                    "schema_version": "1.0.0",
                    "event_id": second_event_id,
                    "workspace_id": workspace_id,
                    "conversation_id": "chat_99",
                    "message_text": "catalog message second",
                },
            )
            FileOutboxStore(data_dir=data_dir).put_if_absent(
                item=OutboxItem(
                    schema_version="1.0.0",
                    stored_at_utc="2026-03-07T00:00:04Z",
                    workspace_id=workspace_id,
                    event_id=second_event_id,
                    idempotency_key="idem_100",
                    trace_id=second_trace_id,
                    turn_id=second_turn_id,
                    span_id=second_span_id,
                    execute_status="accepted",
                    execute_error_code=None,
                    evidence_refs=(second_prompt_ref.ref, second_output_ref.ref),
                    reply_text="catalog ok second",
                )
            )

            catalog = build_trace_catalog(data_dir=data_dir)
            self.assertTrue(catalog.get("ok"))
            items = catalog.get("items") or []
            sessions = catalog.get("sessions") or []
            self.assertGreaterEqual(len(items), 2)
            self.assertGreaterEqual(len(sessions), 1)
            self.assertEqual(sessions[0].get("entry_count"), 2)
            self.assertEqual(sessions[0].get("conversation_id"), "chat_99")

            status, content_type, body = trace_serve_response(data_dir=data_dir, path="/")
            self.assertEqual(status, 200)
            self.assertIn("text/html", content_type)
            html_index = body.decode("utf-8")
            self.assertIn("Trace Viewer", html_index)
            self.assertIn("catalog message", html_index)
            self.assertIn("2 turns", html_index)
            self.assertIn("catalog message second", html_index)

            status, content_type, body = trace_serve_response(
                data_dir=data_dir,
                path=f"/trace?event_id={second_event_id}&workspace_id={workspace_id}",
            )
            self.assertEqual(status, 200)
            self.assertIn("text/html", content_type)
            html_detail = body.decode("utf-8")
            self.assertIn("Trace Timeline", html_detail)
            self.assertIn("catalog prompt second", html_detail)
            self.assertIn("Session Turns", html_detail)
            self.assertIn(second_event_id, html_detail)
            self.assertIn(event_id, html_detail)
            self.assertIn("task-filter", html_detail)

            status, content_type, body = trace_serve_response(
                data_dir=data_dir,
                path=f"/api/trace?event_id={second_event_id}&workspace_id={workspace_id}",
            )
            self.assertEqual(status, 200)
            self.assertIn("application/json", content_type)
            api_obj = json.loads(body.decode("utf-8"))
            self.assertTrue(api_obj.get("ok"))
            self.assertEqual((api_obj.get("requested") or {}).get("event_id"), second_event_id)
            self.assertEqual((api_obj.get("session") or {}).get("entry_count"), 2)


if __name__ == "__main__":  # pragma: no cover
    unittest.main(verbosity=2)
