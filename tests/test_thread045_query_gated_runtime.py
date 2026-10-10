from __future__ import annotations

import json
import re
import tempfile
import time
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

import bootstrap  # noqa: F401

from agentos_next.apps.assistant_loop import (
    AssistantLoopRequest,
    _build_pending_contract,
    _build_terminal_communicator_request,
    _is_infra_only_hypothesis_record,
    _map_hypothesis_result,
    _phase_output_violation,
    run_assistant_loop_async,
)
from agentos_next.apps.assistant_runtime import run_assistant_runtime_async
from agentos_next.apps.canonical_task_ingress import build_canonical_task_ingress_request
from agentos_next.apps.query_gated_runtime import (
    build_context_plane_pack_v1,
    build_query_hypothesis,
    build_user_facing_failure_summary_v1,
    compile_query_for_assistant_loop,
    verify_assistant_execution,
)
from agentos_next.kernel.agent_profile import FileAgentProfileStore, build_default_agent_profile_v1
from agentos_next.kernel.conversation_state_store import FileConversationStateStore
from agentos_next.kernel.evidence_store import FileEvidenceStore
from agentos_next.kernel.executor import ExecuteResult, ExecuteTiming
from agentos_next.kernel.hypothesis_store import FileHypothesisStore, HypothesisRecord
from agentos_next.kernel.research_doctrine import build_research_evidence_pack_v1
from agentos_next.kernel.runtime_snapshot_store import FileRuntimeSnapshotStore
from agentos_next.kernel.scheduler_store import FileSchedulerStore
from agentos_next.kernel.types import TraceContext
from agentos_next.llm.backend import LocalMockLLMBackend
from agentos_next.pa.task_graph import FileTaskGraphStore
from agentos_next.runtime.local_executor import LocalExecutor
from agentos_next.runtime.package_runner import PackageRunner


def _caps(*names: str) -> dict[str, Any]:
    effective = [str(name).strip() for name in names if str(name).strip()]
    return {
        "schema_version": "1.0.0",
        "type": "effective_runtime_capabilities_v1",
        "requested_capabilities": effective,
        "effective_capabilities": effective,
        "disabled_capabilities": [],
        "web": {
            "schema_version": "1.0.0",
            "type": "web_runtime_capability_probe_v1",
            "web_search_enabled": "web_search" in effective,
            "web_browse_enabled": "web_browse" in effective,
            "browse_unavailable_reason": None,
            "backends": {
                "available": ["playwright"] if ("web_search" in effective or "web_browse" in effective) else [],
                "unavailable": {},
                "default": "playwright" if ("web_search" in effective or "web_browse" in effective) else None,
            },
        },
        "delivery": {
            "channel_message_enabled": "channel_send" in effective,
            "adapter_mode": "channel_adapter_available",
        },
        "summary_lines": [],
    }


def _prompt_profile(prompt: str) -> str:
    normalized = str(prompt or "")
    for phase in ("intent_router", "planner", "executor", "verifier_replanner", "communicator"):
        if f"PROMPT_PROFILE={phase}" in normalized:
            return phase
    if "Execute the approved worker task using bounded ReAct" in normalized or "WORKER_TASK_ID=" in normalized:
        return "executor"
    if "Bind the current user input to the active intent" in normalized:
        return "intent_router"
    if "Generate WorkerTaskGraphV1" in normalized:
        return "planner"
    if "Review the latest verified execution state" in normalized:
        return "verifier_replanner"
    if (
        "Final delivery MUST be send_message" in normalized
        or "Prepare a concise progress update" in normalized
        or "Ask the user for the missing context" in normalized
    ):
        return "communicator"
    if "Using the current action graph and verified state" in normalized:
        return "executor"
    return ""


def _worker_tasks_from_legacy_actions(actions: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    normalized_actions = [dict(item) for item in (actions or []) if isinstance(item, dict)]
    worker_ids = {
        str(item.get("action_id") or "").strip(): (
            str(item.get("worker_task_id") or "").strip()
            or f"worker_{str(item.get('action_id') or '').strip() or index}"
        )
        for index, item in enumerate(normalized_actions, start=1)
    }
    worker_tasks: list[dict[str, Any]] = []
    for index, item in enumerate(normalized_actions, start=1):
        action_id = str(item.get("action_id") or "").strip()
        operator_ref = str(item.get("operator_ref") or "").strip()
        worker_task_id = worker_ids.get(action_id) or f"worker_{action_id or index}"
        depends_on = [
            worker_ids.get(str(dep).strip(), f"worker_{str(dep).strip()}")
            for dep in (item.get("depends_on") or [])
            if str(dep).strip()
        ]
        worker_tasks.append(
            {
                "worker_task_id": worker_task_id,
                "objective": str(item.get("objective") or f"execute {operator_ref}").strip() or f"execute {operator_ref}",
                "depends_on": depends_on,
                "allowed_operator_refs": [operator_ref] if operator_ref else [],
                "scope_summary": str(item.get("scope_summary") or f"Approved tool scope for {operator_ref}").strip(),
                "completion_contract_ref": str(item.get("completion_contract_ref") or "worker_result:v1").strip(),
                "tool_budget": dict(
                    item.get("tool_budget")
                    or {"max_calls": 1, "max_parallel_calls": 1, "retry_read_only_tools": False}
                ),
                "time_budget_ms": int(item.get("time_budget_ms") or 0),
            }
        )
    return worker_tasks


def _normalize_mock_phase_output(phase: str, output: dict[str, Any]) -> dict[str, Any]:
    normalized = json.loads(json.dumps(output, ensure_ascii=False))
    if (
        phase in {"planner", "verifier_replanner"}
        and isinstance(normalized, dict)
        and "worker_tasks" not in normalized
        and isinstance(normalized.get("actions"), list)
    ):
        normalized["worker_tasks"] = _worker_tasks_from_legacy_actions(normalized.get("actions"))
        normalized.pop("actions", None)
    return normalized


def _phase_backend_picker(phase_outputs: dict[str, Any]):
    executor_calls: dict[str, int] = {}

    def _legacy_executor_output(prompt_text: str) -> dict[str, Any] | None:
        match = re.search(r"WORKER_TASK_ID=([^\s\\\\]+)", str(prompt_text or ""))
        worker_task_id = str(match.group(1) if match else "").strip()
        if not worker_task_id:
            return None
        phase_order = ("verifier_replanner", "planner")
        for phase_name in phase_order:
            raw_phase_output = phase_outputs.get(phase_name)
            if not isinstance(raw_phase_output, dict):
                continue
            legacy_actions = [dict(item) for item in (raw_phase_output.get("actions") or []) if isinstance(item, dict)]
            if not legacy_actions:
                continue
            worker_tasks = _worker_tasks_from_legacy_actions(legacy_actions)
            for action, worker_task in zip(legacy_actions, worker_tasks):
                if str(worker_task.get("worker_task_id") or "").strip() != worker_task_id:
                    continue
                call_index = executor_calls.get(worker_task_id, 0)
                executor_calls[worker_task_id] = call_index + 1
                if call_index == 0:
                    return {"status": "continue", "actions": [action]}
                return {"status": "done", "actions": []}
        return None

    class _PhaseBackend:
        def complete_json(self, *, prompt, json_schema, safety, model_id=None, stream_callback=None):  # noqa: ANN001
            prompt_text = str(prompt or "")
            phase = _prompt_profile(prompt_text)
            if not phase and callable(phase_outputs.get("executor")):
                raw = phase_outputs["executor"](
                    prompt=prompt,
                    json_schema=json_schema,
                    safety=safety,
                    model_id=model_id,
                    stream_callback=stream_callback,
                )
                return _normalize_mock_phase_output("executor", raw) if isinstance(raw, dict) else raw
            output = phase_outputs.get(phase, {"status": "done"})
            if callable(output):
                raw = output(
                    prompt=prompt,
                    json_schema=json_schema,
                    safety=safety,
                    model_id=model_id,
                    stream_callback=stream_callback,
                )
                return _normalize_mock_phase_output(phase, raw) if isinstance(raw, dict) else raw
            normalized = _normalize_mock_phase_output(
                phase,
                json.loads(json.dumps(output, ensure_ascii=False)),
            )
            if phase == "executor" and isinstance(normalized, dict):
                has_actions = isinstance(normalized.get("actions"), list) and bool(normalized.get("actions"))
                if not has_actions:
                    synthesized = _legacy_executor_output(prompt_text)
                    if synthesized is not None:
                        return synthesized
            return normalized

    def _pick_backend(self, req):  # noqa: ANN001
        return _PhaseBackend()

    return _pick_backend


def _worker_task(
    *,
    worker_task_id: str,
    objective: str,
    allowed_operator_refs: list[str],
    depends_on: list[str] | None = None,
    scope_summary: str = "",
    completion_contract_ref: str = "delivery_contract:v1",
    tool_budget: dict[str, Any] | None = None,
    time_budget_ms: int = 4000,
) -> dict[str, Any]:
    return {
        "worker_task_id": worker_task_id,
        "objective": objective,
        "depends_on": list(depends_on or []),
        "allowed_operator_refs": [str(item).strip() for item in allowed_operator_refs if str(item).strip()],
        "scope_summary": scope_summary or objective,
        "completion_contract_ref": completion_contract_ref,
        "tool_budget": {
            "max_calls": int((tool_budget or {}).get("max_calls") or 4),
            "max_parallel_calls": int((tool_budget or {}).get("max_parallel_calls") or 1),
            "retry_read_only_tools": bool((tool_budget or {}).get("retry_read_only_tools")),
        },
        "time_budget_ms": int(time_budget_ms),
    }


def _worker_task_for_actions(
    *,
    worker_task_id: str,
    objective: str,
    actions: list[dict[str, Any]],
    depends_on: list[str] | None = None,
    scope_summary: str = "",
    completion_contract_ref: str = "delivery_contract:v1",
    tool_budget: dict[str, Any] | None = None,
    time_budget_ms: int = 4000,
) -> dict[str, Any]:
    allowed_operator_refs: list[str] = []
    for action in actions:
        if not isinstance(action, dict):
            continue
        operator_ref = str(action.get("operator_ref") or "").strip()
        if operator_ref and operator_ref not in allowed_operator_refs:
            allowed_operator_refs.append(operator_ref)
    return _worker_task(
        worker_task_id=worker_task_id,
        objective=objective,
        allowed_operator_refs=allowed_operator_refs,
        depends_on=depends_on,
        scope_summary=scope_summary or objective,
        completion_contract_ref=completion_contract_ref,
        tool_budget=tool_budget,
        time_budget_ms=time_budget_ms,
    )


def _worker_executor_from_batches(
    batches_by_worker_task: dict[str, list[list[dict[str, Any]]]],
    *,
    terminal_status_by_worker_task: dict[str, str] | None = None,
) -> Any:
    calls: dict[str, int] = {}

    def _complete_json(self=None, *, prompt, json_schema, safety, model_id=None, stream_callback=None):  # noqa: ANN001
        del self, json_schema, safety, model_id, stream_callback
        prompt_text = str(prompt or "")
        match = re.search(r"WORKER_TASK_ID=([^\s\\\\]+)", prompt_text)
        worker_task_id = str(match.group(1) if match else "").strip()
        if not worker_task_id:
            return {"status": "done", "actions": []}
        call_index = calls.get(worker_task_id, 0)
        calls[worker_task_id] = call_index + 1
        planned_batches = batches_by_worker_task.get(worker_task_id, [])
        if call_index < len(planned_batches):
            return {"status": "continue", "actions": planned_batches[call_index]}
        terminal_status = str((terminal_status_by_worker_task or {}).get(worker_task_id) or "done").strip() or "done"
        return {"status": terminal_status, "actions": []}

    return _complete_json


def _complete_json_from_phase_outputs(phase_outputs: dict[str, Any]) -> Any:
    backend = _phase_backend_picker(phase_outputs)(None, None)

    def _complete_json(self=None, *, prompt, json_schema, safety, model_id=None, stream_callback=None):  # noqa: ANN001
        return backend.complete_json(
            prompt=prompt,
            json_schema=json_schema,
            safety=safety,
            model_id=model_id,
            stream_callback=stream_callback,
        )

    return _complete_json


class TestThread045QueryGatedRuntime(unittest.IsolatedAsyncioTestCase):
    def test_compile_query_contains_required_fields_and_triage_decision(self) -> None:
        trace = TraceContext(trace_id="tr_qg_1", turn_id="turn_qg_1", span_id="span_qg_1")
        out = compile_query_for_assistant_loop(
            query_text="请帮我总结一下今天的工作安排",
            req_trace=trace,
            workspace_id="ws_qg",
            effective_runtime_capabilities=_caps("memory_write", "llm_remote"),
            deadline_ms=60000,
            response_language="zh-CN",
        )
        self.assertTrue(out.ok)
        q = out.query
        for key in (
            "task_envelope",
            "delivery_contract",
            "solution_query",
            "prompt_compilation",
            "context_graph",
            "task_context_views",
            "prompt_profiles",
            "active_style_pack",
            "response_language",
            "active_doctrine_pack",
            "global_soul",
            "domain_policy_pack",
            "intent_recovery",
            "interaction_mode",
            "model_routing_policy",
            "objective",
            "context_pack",
            "capabilities",
            "workspace_snapshot",
            "constraints",
            "acceptance_criteria",
            "budget",
            "termination_policy",
        ):
            self.assertIn(key, q)
        evidence = q.get("context_pack", {}).get("evidence", [])
        self.assertGreaterEqual(len(evidence), 5)
        self.assertLessEqual(len(evidence), 10)
        triage = [x for x in evidence if isinstance(x, dict) and x.get("kind") == "decision" and x.get("ref") == "triage:v1"]
        policy_ev = [x for x in evidence if isinstance(x, dict) and x.get("kind") == "policy" and x.get("ref") == "agent_profile:v1"]
        self.assertEqual(len(triage), 1)
        self.assertEqual(len(policy_ev), 1)
        self.assertEqual(policy_ev[0]["data"]["operator_resolution_policy"], "skill_first")
        self.assertEqual(q["objective"], q["task_envelope"]["objective"])
        self.assertEqual(q["delivery_contract"]["task_id"], q["task_envelope"]["task_id"])
        self.assertEqual(q["acceptance_criteria"][0], q["task_envelope"]["acceptance_criteria"][0])
        self.assertEqual(q["intent_recovery"]["intent_option"], "DIRECT_TASK")
        self.assertEqual(q["solution_query"]["continuity_binding"], "raw_input")
        self.assertEqual(q["interaction_mode"], "task")
        self.assertTrue(q["model_routing_policy"]["user_override_allowed"])
        self.assertEqual(q["model_routing_policy"]["planner_strategy"], "model_owned")
        self.assertEqual(q["model_routing_policy"]["routing_strategy"], "planner_first")
        self.assertEqual(q["context_graph"]["type"], "context_graph_v1")
        self.assertEqual(q["task_context_views"]["type"], "task_context_views_v1")
        self.assertIn("executor", q["prompt_profiles"])
        self.assertIn("communicator", q["prompt_profiles"])
        self.assertEqual(q["active_style_pack"]["pack_id"], "concise")
        self.assertIn(q["active_doctrine_pack"]["pack_id"], {"fast_path_mode", "scientific_hypothesis_mode"})
        self.assertEqual(q["prompt_compilation"]["type"], "prompt_compilation_v1")
        self.assertEqual(q["prompt_compilation"]["compiler_mode"], "deterministic_with_rewrite_slots")
        self.assertEqual(q["response_language"], "zh-CN")
        self.assertEqual(q["prompt_compilation"]["active_response_language"], "zh-CN")
        self.assertIn("research_required", q)
        self.assertIn("research_depth", q)
        self.assertIn("selected_doctrine_pack", q)
        self.assertIn("evidence_expectation", q)
        self.assertIn("citation_required", q)
        executor_prompt = q["prompt_profiles"]["executor"]["reasoning_prompt"]
        communicator_prompt = q["prompt_profiles"]["communicator"]["reasoning_prompt"]
        self.assertIn("PROMPT_PROFILE=executor", executor_prompt)
        self.assertIn("SEND_MESSAGE_POLICY=", executor_prompt)
        self.assertIn("PROMPT_PROFILE=communicator", communicator_prompt)
        self.assertIn("RESPONSE_LANGUAGE=zh-CN", communicator_prompt)
        projection = [
            x
            for x in evidence
            if isinstance(x, dict) and x.get("kind") == "prompt_compiler" and x.get("ref") == "context_projection:v1"
        ]
        self.assertEqual(len(projection), 1)
        self.assertEqual(sorted(projection[0]["data"]["prompt_profiles"]), sorted(q["prompt_profiles"].keys()))

    def test_compile_query_emits_task_bundle_execution_policy_and_file_refs(self) -> None:
        trace = TraceContext(trace_id="tr_qg_bundle", turn_id="turn_qg_bundle", span_id="span_qg_bundle")
        out = compile_query_for_assistant_loop(
            query_text="请看下我给你的文件并总结重点",
            req_trace=trace,
            workspace_id="ws_qg_bundle",
            effective_runtime_capabilities=_caps("fs_read", "fs_list"),
            deadline_ms=120000,
            attachments=[
                {
                    "media_kind": "document",
                    "workspace_path": "docs/specs/MVP_045_QUERY_GATED_RUNTIME.md",
                    "caption": "runtime spec",
                    "evidence_ref": "ev_doc_1",
                    "artifact_ref": "artifact_doc_1",
                }
            ],
            new_evidence_refs=["ev_new_1"],
        )
        self.assertTrue(out.ok)
        q = out.query
        task_bundle = q.get("task_bundle") or {}
        task_execution_policy = q.get("task_execution_policy") or {}
        file_refs = q.get("file_refs") or []
        self.assertEqual(task_bundle.get("type"), "task_bundle_v1")
        self.assertEqual(task_execution_policy.get("type"), "task_execution_policy_v1")
        self.assertEqual(task_bundle.get("worker_task_admission_mode"), "leader_gate")
        self.assertTrue(bool((task_bundle.get("scope_guard") or {}).get("worker_split_requires_leader")))
        self.assertGreaterEqual(len(file_refs), 3)
        ref_types = {str(item.get("ref_type") or "") for item in file_refs if isinstance(item, dict)}
        self.assertTrue({"workspace_path", "evidence_ref", "artifact_ref"}.issubset(ref_types))
        self.assertGreater(int(task_execution_policy.get("llm_timeout_ms") or 0), 0)
        self.assertGreater(int(task_execution_policy.get("tool_timeout_ms") or 0), 0)

    def test_verify_assistant_execution_enters_hold_on_budget_exhaustion(self) -> None:
        trace = TraceContext(trace_id="tr_qg_hold", turn_id="turn_qg_hold", span_id="span_qg_hold")
        compiled = compile_query_for_assistant_loop(
            query_text="请调研并比较今天北京和上海的天气来源",
            req_trace=trace,
            workspace_id="ws_qg_hold",
            effective_runtime_capabilities=_caps("web_search", "web_browse"),
            deadline_ms=5000,
        )
        self.assertTrue(compiled.ok)
        compiled.query["budget"]["tool_calls_max"] = 1
        verify = verify_assistant_execution(
            compiled_query=compiled.query,
            mode=compiled.mode,
            exec_summaries=[
                {"operator_ref": "builtin://web.search", "status": "accepted"},
                {"operator_ref": "builtin://web.browse", "status": "accepted"},
            ],
            error_code="E_HITL_REQUIRED",
            final_output=None,
        )
        self.assertEqual(verify.get("delivery_state"), "hold")
        self.assertTrue(bool(verify.get("hitl_required")))
        self.assertEqual(verify.get("primary_failure_code"), "E_HITL_REQUIRED")

    def test_compile_query_grants_extra_replan_budget_for_external_evidence_tasks(self) -> None:
        trace = TraceContext(trace_id="tr_qg_budget_ext", turn_id="turn_qg_budget_ext", span_id="span_qg_budget_ext")
        out = compile_query_for_assistant_loop(
            query_text="告诉我今天上海天气",
            req_trace=trace,
            workspace_id="ws_qg",
            effective_runtime_capabilities=_caps("web_search", "web_browse"),
            deadline_ms=5000,
        )
        self.assertTrue(out.ok)
        self.assertEqual(int(out.query["budget"]["loops_max"]), 3)
        self.assertEqual(int(out.query["budget"]["tool_calls_max"]), 8)
        self.assertFalse(out.query["research_required"])
        self.assertEqual(out.query["selected_doctrine_pack"], "scientific_hypothesis_mode")
        self.assertEqual(out.query["task_requirements"]["external_evidence_policy_v1"]["search_rounds_max"], 2)
        self.assertEqual(out.query["task_requirements"]["external_evidence_policy_v1"]["browse_candidates_per_search_max"], 3)
        self.assertEqual(out.query["task_requirements"]["external_evidence_policy_v1"]["total_browse_steps_max"], 4)

    def test_compile_query_distinguishes_lookup_from_research_doctrine(self) -> None:
        trace_lookup = TraceContext(trace_id="tr_qg_lookup", turn_id="turn_qg_lookup", span_id="span_qg_lookup")
        lookup = compile_query_for_assistant_loop(
            query_text="告诉我今天上海天气",
            req_trace=trace_lookup,
            workspace_id="ws_qg",
            effective_runtime_capabilities=_caps("web_search", "web_browse"),
            deadline_ms=5000,
        )
        self.assertTrue(lookup.ok)
        self.assertFalse(lookup.query["research_required"])
        self.assertEqual(lookup.query["research_depth"], "lookup")
        self.assertEqual(lookup.query["selected_doctrine_pack"], "scientific_hypothesis_mode")
        self.assertFalse(lookup.query["citation_required"])

        trace_research = TraceContext(trace_id="tr_qg_research", turn_id="turn_qg_research", span_id="span_qg_research")
        research = compile_query_for_assistant_loop(
            query_text="调研并比较今天北京空气质量与天气来源，给我一个带引用的结论",
            req_trace=trace_research,
            workspace_id="ws_qg",
            effective_runtime_capabilities=_caps("web_search", "web_browse"),
            deadline_ms=5000,
        )
        self.assertTrue(research.ok)
        self.assertTrue(research.query["research_required"])
        self.assertIn(research.query["research_depth"], {"standard", "deep"})
        self.assertEqual(research.query["selected_doctrine_pack"], "browser_research_mode")
        self.assertTrue(research.query["citation_required"])
        self.assertEqual(research.query["evidence_expectation"], "research_citation_set")
        self.assertEqual(research.query["active_doctrine_pack"]["pack_id"], "browser_research_mode")

    def test_compile_query_does_not_escalate_ordinary_external_lookup_into_research(self) -> None:
        trace = TraceContext(trace_id="tr_qg_explicit_gate", turn_id="turn_qg_explicit_gate", span_id="span_qg_explicit_gate")
        out = compile_query_for_assistant_loop(
            query_text="为什么今天北京这么冷",
            req_trace=trace,
            workspace_id="ws_qg",
            effective_runtime_capabilities=_caps("web_search", "web_browse"),
            deadline_ms=5000,
        )
        self.assertTrue(out.ok)
        self.assertTrue(out.query["task_requirements"]["requires_external_evidence"])
        self.assertFalse(out.query["research_required"])
        self.assertEqual(out.query["research_depth"], "lookup")

    def test_mode_select_is_deterministic(self) -> None:
        trace = TraceContext(trace_id="tr_qg_2", turn_id="turn_qg_2", span_id="span_qg_2")
        r1 = compile_query_for_assistant_loop(
            query_text="hello",
            req_trace=trace,
            workspace_id="ws_qg",
            effective_runtime_capabilities=_caps(),
            deadline_ms=5000,
        )
        r2 = compile_query_for_assistant_loop(
            query_text="hello",
            req_trace=trace,
            workspace_id="ws_qg",
            effective_runtime_capabilities=_caps(),
            deadline_ms=5000,
        )
        self.assertEqual(r1.mode, r2.mode)
        self.assertEqual(json.dumps(r1.query, ensure_ascii=False, sort_keys=True), json.dumps(r2.query, ensure_ascii=False, sort_keys=True))

    def test_compile_query_reads_agent_profile_context_planes_and_message_time(self) -> None:
        trace = TraceContext(trace_id="tr_qg_3", turn_id="turn_qg_3", span_id="span_qg_3")
        profile = build_default_agent_profile_v1(agent_id="assistant_loop")
        planes = build_context_plane_pack_v1(
            query_text="现在几点发的这条消息",
            workspace_id="ws_qg",
            trace=trace,
            active_axiom_ids=[x["id"] for x in profile["axioms"]],
            active_constraint_ids=[x["id"] for x in profile["reality_constraints"]],
            recent_failures=["mode=simple; objective=old failure"],
            recent_success_patterns=["prefer skill-first for simple asks"],
            message_received_at_utc="2026-03-07T12:34:56Z",
        )
        out = compile_query_for_assistant_loop(
            query_text="现在几点发的这条消息",
            req_trace=trace,
            workspace_id="ws_qg",
            effective_runtime_capabilities=_caps("memory_search"),
            deadline_ms=5000,
            agent_profile=profile,
            context_planes=planes,
            message_received_at_utc="2026-03-07T12:34:56Z",
        )
        self.assertTrue(out.ok)
        self.assertEqual(out.query["workspace_snapshot"]["message_received_at_utc"], "2026-03-07T12:34:56Z")
        self.assertEqual(out.query["workspace_snapshot"]["temporal_anchor"]["anchor_time_utc"], "2026-03-07T12:34:56Z")
        today_local = out.query["workspace_snapshot"]["temporal_anchor"]["relative_dates"]["today"]
        self.assertEqual(today_local, out.query["workspace_snapshot"]["temporal_anchor"]["date_local"])
        self.assertEqual(out.query["workspace_snapshot"]["agent_profile"]["agent_id"], "assistant_loop")
        self.assertIn("message_received_at_utc=2026-03-07T12:34:56Z", out.query["context_pack"]["state_summary"])
        self.assertIn(f"date_local={today_local}", out.query["context_pack"]["state_summary"])
        planner_facts = out.query["task_context_views"]["views"]["planner"]["relevant_facts"]
        self.assertIn(f"relative_date_today_local={today_local}", planner_facts)
        self.assertIn("execution_axiom:AX_QUERY_GATED", out.query["constraints"])

    def test_compile_query_debounces_identical_user_input_within_short_window(self) -> None:
        trace = TraceContext(trace_id="tr_qg_4", turn_id="turn_qg_4", span_id="span_qg_4")
        profile = build_default_agent_profile_v1(agent_id="assistant_loop")
        repeated = build_query_hypothesis(query_text="hello", mode="simple")
        planes = build_context_plane_pack_v1(
            query_text="hello",
            workspace_id="ws_qg",
            trace=trace,
            active_axiom_ids=[x["id"] for x in profile["axioms"]],
            active_constraint_ids=[x["id"] for x in profile["reality_constraints"]],
            recent_failures=[repeated],
            last_user_query="hello",
            last_user_query_at_utc="2026-03-07T12:34:56Z",
        )
        blocked = compile_query_for_assistant_loop(
            query_text="hello",
            req_trace=trace,
            workspace_id="ws_qg",
            effective_runtime_capabilities=_caps(),
            deadline_ms=5000,
            agent_profile=profile,
            context_planes=planes,
            message_received_at_utc="2026-03-07T12:34:56.500000Z",
        )
        self.assertFalse(blocked.ok)
        self.assertEqual(blocked.error_code, "E_INPUT_DEBOUNCED")

        allowed = compile_query_for_assistant_loop(
            query_text="hello",
            req_trace=trace,
            workspace_id="ws_qg",
            effective_runtime_capabilities=_caps(),
            deadline_ms=5000,
            agent_profile=profile,
            context_planes=planes,
            message_received_at_utc="2026-03-07T12:34:58Z",
        )
        self.assertTrue(allowed.ok)
        self.assertFalse(allowed.query["ingress_control"]["input_debounced"])

    def test_compile_query_allows_repeated_input_outside_debounce_window_even_with_recent_failures(self) -> None:
        trace = TraceContext(trace_id="tr_qg_4b", turn_id="turn_qg_4b", span_id="span_qg_4b")
        profile = build_default_agent_profile_v1(agent_id="assistant_loop")
        repeated = build_query_hypothesis(query_text="分析~/codex/agentos-next项目，给出你的评价和建议", mode="standard")
        planes = build_context_plane_pack_v1(
            query_text="分析~/codex/agentos-next项目，给出你的评价和建议",
            workspace_id="ws_qg",
            trace=trace,
            active_axiom_ids=[x["id"] for x in profile["axioms"]],
            active_constraint_ids=[x["id"] for x in profile["reality_constraints"]],
            recent_failures=[repeated],
            expected_next_user_act="followup_or_new_task",
            last_delivery_state="done",
            last_delivery_summary="delivery verified successfully",
            pending_contract={
                "schema_version": "1.0.0",
                "type": "continuation_contract_v1",
                "objective": "？",
                "intent_option": "DIRECT_TASK",
                "interaction_mode": "task",
                "delivery_kind": "user_visible_answer",
                "requires_workspace_observation": False,
                "requires_external_evidence": False,
            },
            last_user_query="分析~/codex/agentos-next项目，给出你的评价和建议",
            last_user_query_at_utc="2026-03-07T12:34:56Z",
        )
        allowed = compile_query_for_assistant_loop(
            query_text="分析~/codex/agentos-next项目，给出你的评价和建议",
            req_trace=trace,
            workspace_id="ws_qg",
            effective_runtime_capabilities=_caps("fs_read", "shell_exec"),
            deadline_ms=5000,
            agent_profile=profile,
            context_planes=planes,
            message_received_at_utc="2026-03-07T12:35:05Z",
        )
        self.assertTrue(allowed.ok)
        self.assertFalse(allowed.query["hypothesis"]["repeated_without_new_evidence"])
        self.assertFalse(allowed.query["ingress_control"]["input_debounced"])

    def test_compile_query_ignores_recent_failures_for_normal_repeat_user_input(self) -> None:
        trace = TraceContext(trace_id="tr_qg_cap_retry", turn_id="turn_qg_cap_retry", span_id="span_qg_cap_retry")
        profile = build_default_agent_profile_v1(agent_id="assistant_loop")
        repeated = build_query_hypothesis(query_text="告诉我今天上海天气", mode="standard")
        planes = build_context_plane_pack_v1(
            query_text="告诉我今天上海天气",
            workspace_id="ws_qg",
            trace=trace,
            active_axiom_ids=[x["id"] for x in profile["axioms"]],
            active_constraint_ids=[x["id"] for x in profile["reality_constraints"]],
            recent_failures=[repeated],
        )
        allowed = compile_query_for_assistant_loop(
            query_text="告诉我今天上海天气",
            req_trace=trace,
            workspace_id="ws_qg",
            effective_runtime_capabilities=_caps("web_search", "web_browse"),
            deadline_ms=5000,
            agent_profile=profile,
            context_planes=planes,
        )
        self.assertTrue(allowed.ok)
        self.assertFalse(allowed.query["hypothesis"]["repeated_without_new_evidence"])
        self.assertIn(
            "capabilities=web_browse|web_search",
            build_query_hypothesis(
                query_text="告诉我今天上海天气",
                mode="standard",
                capability_names=["web_search", "web_browse"],
            ),
        )

    def test_compile_query_recovers_context_dependent_ack_with_fixed_option_and_note(self) -> None:
        trace = TraceContext(trace_id="tr_qg_intent", turn_id="turn_qg_intent", span_id="span_qg_intent")
        profile = build_default_agent_profile_v1(agent_id="assistant_loop")
        planes = build_context_plane_pack_v1(
            query_text="开始 按刚才那个延期邮件",
            workspace_id="ws_qg",
            trace=trace,
            active_axiom_ids=[x["id"] for x in profile["axioms"]],
            active_constraint_ids=[x["id"] for x in profile["reality_constraints"]],
            last_pending_task="请帮我写一封延期邮件",
            expected_next_user_act="ack_execute",
            last_delivery_state="done",
            last_delivery_summary="draft prepared",
        )
        out = compile_query_for_assistant_loop(
            query_text="开始 按刚才那个延期邮件",
            req_trace=trace,
            workspace_id="ws_qg",
            effective_runtime_capabilities=_caps(),
            deadline_ms=5000,
            agent_profile=profile,
            context_planes=planes,
        )
        self.assertTrue(out.ok)
        self.assertEqual(out.query["intent_recovery"]["intent_option"], "ACK_EXECUTE")
        self.assertEqual(out.query["intent_recovery"]["intent_note"], "按刚才那个延期邮件")
        self.assertIn("请帮我写一封延期邮件", out.query["objective"])
        self.assertEqual(out.query["interaction_mode"], "confirm")
        self.assertEqual(out.query["model_routing_policy"]["routing_strategy"], "planner_first")

    def test_compile_query_derives_workspace_analysis_requirements(self) -> None:
        trace = TraceContext(trace_id="tr_qg_analysis", turn_id="turn_qg_analysis", span_id="span_qg_analysis")
        out = compile_query_for_assistant_loop(
            query_text="分析~/codex/agentos-next项目，给出你的评价和建议",
            req_trace=trace,
            workspace_id="ws_qg",
            effective_runtime_capabilities=_caps("fs_read", "shell_exec"),
            deadline_ms=5000,
        )
        self.assertTrue(out.ok)
        self.assertNotEqual(out.mode, "simple")
        reqs = out.query["task_requirements"]
        self.assertTrue(reqs["requires_workspace_observation"])
        self.assertTrue(reqs["requires_multi_step_plan"])
        self.assertTrue(reqs["forbid_speculation_without_evidence"])
        self.assertEqual(out.query["task_envelope"]["deliverable"], "workspace_analysis")
        self.assertIn("project_work", out.query["context_graph"]["domain_tags"])
        self.assertEqual(out.query["active_doctrine_pack"]["pack_id"], "scientific_hypothesis_mode")

    def test_compile_query_rebinds_low_specificity_followup_to_pending_contract(self) -> None:
        trace = TraceContext(trace_id="tr_qg_followup_bind", turn_id="turn_qg_followup_bind", span_id="span_qg_followup_bind")
        profile = build_default_agent_profile_v1(agent_id="assistant_loop")
        planes = build_context_plane_pack_v1(
            query_text="你现在想起来了吗",
            workspace_id="ws_qg",
            trace=trace,
            active_axiom_ids=[x["id"] for x in profile["axioms"]],
            active_constraint_ids=[x["id"] for x in profile["reality_constraints"]],
            last_pending_task="把你前面对agentos项目的建议落到文件吧",
            expected_next_user_act="followup_or_new_task",
            last_delivery_state="done",
            last_delivery_summary="delivery verified successfully",
            pending_contract={
                "schema_version": "1.0.0",
                "type": "continuation_contract_v1",
                "objective": "把你前面对agentos项目的建议落到文件吧",
                "intent_option": "DIRECT_TASK",
                "interaction_mode": "task",
                "delivery_kind": "workspace_analysis",
                "requires_workspace_observation": True,
                "requires_external_evidence": False,
            },
        )
        out = compile_query_for_assistant_loop(
            query_text="你现在想起来了吗",
            req_trace=trace,
            workspace_id="ws_qg",
            effective_runtime_capabilities=_caps("fs_read", "shell_exec"),
            deadline_ms=5000,
            agent_profile=profile,
            context_planes=planes,
        )
        self.assertTrue(out.ok)
        self.assertEqual(out.query["intent_recovery"]["intent_option"], "FOLLOWUP_PENDING")
        self.assertEqual(out.query["solution_query"]["continuity_binding"], "pending_contract")
        self.assertTrue(out.query["solution_query"]["preserve_pending_contract"])
        self.assertEqual(out.query["objective"], "把你前面对agentos项目的建议落到文件吧")
        self.assertTrue(out.query["task_requirements"]["requires_workspace_observation"])
        self.assertNotEqual(out.mode, "simple")

    def test_compile_query_separates_communicator_and_executor_prompt_layers(self) -> None:
        trace = TraceContext(trace_id="tr_qg_prompt", turn_id="turn_qg_prompt", span_id="span_qg_prompt")
        out = compile_query_for_assistant_loop(
            query_text="请先总结一下当前状态，再告诉我接下来要做什么",
            req_trace=trace,
            workspace_id="ws_qg",
            effective_runtime_capabilities=_caps("memory_search"),
            deadline_ms=5000,
        )
        self.assertTrue(out.ok)
        profiles = out.query["prompt_profiles"]
        executor = profiles["executor"]
        communicator = profiles["communicator"]
        self.assertNotEqual(executor["role_axioms"]["statements"], communicator["role_axioms"]["statements"])
        self.assertEqual(executor["style_pack"]["pack_id"], communicator["style_pack"]["pack_id"])
        self.assertIn("do not emit direct user-visible delivery", executor["output_contract"]["requirements"][1])
        self.assertIn("send_message task", communicator["output_contract"]["requirements"][1])

    def test_verify_assistant_execution_binds_delivery_contract(self) -> None:
        trace = TraceContext(trace_id="tr_qg_verify", turn_id="turn_qg_verify", span_id="span_qg_verify")
        compiled = compile_query_for_assistant_loop(
            query_text="请帮我总结一下今天的工作安排",
            req_trace=trace,
            workspace_id="ws_qg",
            effective_runtime_capabilities=_caps(),
            deadline_ms=5000,
        )
        self.assertTrue(compiled.ok)

        verify = verify_assistant_execution(
            compiled_query=compiled.query,
            mode=compiled.mode,
            exec_summaries=[{"i": 1, "operator_ref": "example", "status": "accepted"}],
            error_code=None,
            final_output={},
        )
        self.assertFalse(verify["acceptance_pass"])
        self.assertEqual(verify["delivery_state"], "blocker")
        self.assertEqual(verify["primary_failure_code"], "E_DELIVERY_VERIFICATION_FAILED")

    def test_verify_assistant_execution_requires_workspace_observation_when_derived(self) -> None:
        trace = TraceContext(trace_id="tr_qg_verify_obs", turn_id="turn_qg_verify_obs", span_id="span_qg_verify_obs")
        compiled = compile_query_for_assistant_loop(
            query_text="分析这个项目并给出建议",
            req_trace=trace,
            workspace_id="ws_qg",
            effective_runtime_capabilities=_caps("fs_read", "shell_exec"),
            deadline_ms=5000,
        )
        self.assertTrue(compiled.ok)

        verify = verify_assistant_execution(
            compiled_query=compiled.query,
            mode=compiled.mode,
            exec_summaries=[{"i": 1, "operator_ref": "example", "status": "accepted"}],
            error_code=None,
            final_output={"reply": "我觉得这个项目不错"},
        )
        self.assertFalse(verify["acceptance_pass"])
        self.assertEqual(verify["primary_failure_code"], "E_REQUIRED_WORKSPACE_OBSERVATION_MISSING")

    def test_verify_assistant_execution_requires_send_message_task_for_user_visible_delivery(self) -> None:
        trace = TraceContext(trace_id="tr_qg_verify_msg", turn_id="turn_qg_verify_msg", span_id="span_qg_verify_msg")
        compiled = compile_query_for_assistant_loop(
            query_text="请帮我总结一下今天的工作安排",
            req_trace=trace,
            workspace_id="ws_qg",
            effective_runtime_capabilities=_caps(),
            deadline_ms=5000,
        )
        self.assertTrue(compiled.ok)

        verify = verify_assistant_execution(
            compiled_query=compiled.query,
            mode=compiled.mode,
            exec_summaries=[{"i": 1, "operator_ref": "example", "status": "accepted"}],
            error_code=None,
            final_output={"reply": "今天主要有两个安排"},
        )
        self.assertFalse(verify["acceptance_pass"])
        self.assertEqual(verify["primary_failure_code"], "E_MESSAGE_TASK_MISSING")

    def test_verify_assistant_execution_rejects_non_terminal_success_delivery_stage(self) -> None:
        trace = TraceContext(trace_id="tr_qg_verify_stage", turn_id="turn_qg_verify_stage", span_id="span_qg_verify_stage")
        compiled = compile_query_for_assistant_loop(
            query_text="告诉我今天上海天气",
            req_trace=trace,
            workspace_id="ws_qg",
            effective_runtime_capabilities=_caps("web_search", "web_browse"),
            deadline_ms=5000,
        )
        self.assertTrue(compiled.ok)

        verify = verify_assistant_execution(
            compiled_query=compiled.query,
            mode=compiled.mode,
            exec_summaries=[
                {"i": 1, "operator_ref": "builtin://channel.send_message", "status": "accepted", "source_phase": "communicator"}
            ],
            error_code=None,
            final_output={
                "operator_ref": "builtin://channel.send_message",
                "text": "上海今天多云。",
                "delivery_stage": "progress",
            },
        )
        self.assertFalse(verify["acceptance_pass"])
        self.assertEqual(verify["primary_failure_code"], "E_DELIVERY_VERIFICATION_FAILED")

    def test_build_pending_contract_skips_punctuation_only_objective(self) -> None:
        contract = _build_pending_contract(
            compiled_query={
                "task_envelope": {"objective": "？"},
                "task_requirements": {"delivery_kind": "user_visible_answer"},
            },
            effective_query="？",
            interaction_mode="task",
        )
        self.assertIsNone(contract)

    def test_map_hypothesis_result_treats_timeout_as_partial(self) -> None:
        result = _map_hypothesis_result(
            verify_report={"acceptance_pass": False, "failures": []},
            error_code="E_TIMEOUT",
        )
        self.assertEqual(result, "partial")

    async def test_assistant_loop_emits_query_gated_evidence_and_simple_plan(self) -> None:
        root = Path(__file__).resolve().parents[1]
        skill_dir = root / "examples" / "skills" / "personal_assistant_brief"
        self.assertTrue(skill_dir.exists(), msg=f"missing example skill: {skill_dir}")

        with tempfile.TemporaryDirectory(prefix="agentos_next_t045_") as td:
            data_dir = Path(td) / "data"
            trace = TraceContext(trace_id="tr_qg_loop", turn_id="turn_qg_loop", span_id="span_qg_loop")
            req = AssistantLoopRequest(
                query="hello",
                assistant_skill_dir=skill_dir,
                workspace_id="ws_qg",
                data_dir=data_dir,
                trace=trace,
                idempotency_key="idem_qg",
                deadline_ms=8000,
                verify_asvp=False,
                public_keys_dir=None,
                backend="local_mock",
                planner="model_owned",
                model=None,
                remote_calls_armed=False,
                allow_network_egress=False,
                approved_by_human=False,
                replay_mode=True,
            )
            res = await run_assistant_loop_async(req)

            evidence = FileEvidenceStore(data_dir=data_dir)
            self.assertGreaterEqual(len(res.evidence_refs), 1)
            found_query = False
            found_verify = False
            controller_routing = None
            worker_task_graph_status = None
            worker_task_count = None
            prompt_profile_ids = None
            style_pack_id = None
            for ref in res.evidence_refs:
                blob = evidence.get_blob(ref)
                if blob is None or blob.content_type != "application/json":
                    continue
                try:
                    obj = json.loads(blob.content.decode("utf-8"))
                except Exception:
                    continue
                if isinstance(obj, dict) and obj.get("type") == "query_gated_query_v1":
                    found_query = True
                    prompt_profile_ids = sorted(list((obj.get("prompt_profiles") or {}).keys()))
                    style_pack_id = str((obj.get("active_style_pack") or {}).get("pack_id") or "")
                if isinstance(obj, dict) and obj.get("type") == "worker_task_graph_v1":
                    if obj.get("query_mode") == "simple":
                        steps = obj.get("worker_tasks")
                        if isinstance(steps, list):
                            worker_task_count = len(steps)
                        worker_task_graph_status = str(obj.get("planner_status") or "")
                        compiled_ids = sorted(
                            list((((obj.get("policy") or {}).get("prompt_compilation") or {}).get("profile_ids") or []))
                        )
                        self.assertEqual(
                            compiled_ids,
                            ["communicator", "executor", "intent_router", "planner", "verifier_replanner"],
                        )
                if isinstance(obj, dict) and obj.get("type") == "controller_routing_decision_v1":
                    controller_routing = obj
                if isinstance(obj, dict) and "schema_valid" in obj and "acceptance_pass" in obj and "failures" in obj:
                    found_verify = True

            self.assertTrue(found_query, msg=f"missing query-gated query evidence; refs={res.evidence_refs}")
            self.assertTrue(found_verify, msg=f"missing verification report evidence; refs={res.evidence_refs}")
            self.assertTrue(res.ok)
            self.assertEqual(
                worker_task_count,
                0,
                msg="simple mode should allow an empty worker task graph when no tool execution is required",
            )
            self.assertEqual(worker_task_graph_status, "done")
            self.assertEqual(prompt_profile_ids, ["communicator", "executor", "intent_router", "planner", "verifier_replanner"])
            self.assertEqual(style_pack_id, "concise")
            self.assertIsNotNone(controller_routing)
            self.assertEqual(controller_routing["controller_execution_mode"], "token_time_progress")
            self.assertIn(controller_routing["execution_lane"], {"fast_chat", "standard_task"})
            self.assertTrue(
                {
                    "model_pool_ref",
                    "on_lane_insufficient",
                    "reasoning_profile_ref",
                    "tool_parallelism_cap",
                    "verification_mode",
                }.issubset(set((controller_routing["execution_lane_policy"] or {}).keys()))
            )
            self.assertTrue(any(str(step.get("operator_ref") or "") == "builtin://channel.send_message" for step in res.steps))
            self.assertEqual(str((res.final_output or {}).get("channel") or ""), "assistant_runtime")

    async def test_assistant_loop_executes_emitted_actions_then_aggregate_reasoning(self) -> None:
        root = Path(__file__).resolve().parents[1]
        skill_dir = root / "examples" / "skills" / "personal_assistant_brief"
        worker_actions = [
            {
                "action_id": "readme_call",
                "operator_ref": "builtin://fs.read",
                "arguments": {"path": "README.md"},
            }
        ]
        executor_calls = {"count": 0}

        def _fake_complete_json(self, *, prompt, json_schema, safety, model_id=None, stream_callback=None):  # noqa: ANN001
            del self, json_schema, safety, model_id, stream_callback
            prompt_text = str(prompt or "")
            if "PROMPT_PROFILE=intent_router" in prompt_text:
                return {"status": "done"}
            if "PROMPT_PROFILE=planner" in prompt_text:
                return {
                    "status": "continue",
                    "worker_tasks": [
                        _worker_task_for_actions(
                            worker_task_id="worker_readme",
                            objective="Read README.md and collect key project details",
                            actions=worker_actions,
                            scope_summary="Inspect README.md only",
                            tool_budget={"max_calls": 1, "max_parallel_calls": 1, "retry_read_only_tools": False},
                            time_budget_ms=1000,
                        )
                    ],
                }
            if "PROMPT_PROFILE=executor" in prompt_text:
                executor_calls["count"] += 1
                if executor_calls["count"] == 1:
                    return {"status": "continue", "actions": worker_actions}
                return {"status": "done", "actions": []}
            if "PROMPT_PROFILE=verifier_replanner" in prompt_text:
                return {"status": "done"}
            if "PROMPT_PROFILE=communicator" in prompt_text:
                return {
                    "status": "done",
                    "actions": [
                        {
                            "action_id": "final_message",
                            "operator_ref": "builtin://channel.send_message",
                            "arguments": {
                                "text": "已查看 README，建议先聚焦 runtime、验证和显式消息任务。",
                                "channel": "assistant_runtime",
                            },
                        }
                    ],
                }
            return {"status": "done"}

        with tempfile.TemporaryDirectory(prefix="agentos_next_t045_actions_") as td:
            data_dir = Path(td) / "data"
            trace = TraceContext(trace_id="tr_qg_actions", turn_id="turn_qg_actions", span_id="span_qg_actions")
            req = AssistantLoopRequest(
                query="分析这个项目并给出建议",
                assistant_skill_dir=skill_dir,
                workspace_id="ws_qg",
                data_dir=data_dir,
                trace=trace,
                idempotency_key="idem_qg_actions",
                deadline_ms=8000,
                verify_asvp=False,
                public_keys_dir=None,
                backend="local_mock",
                planner="model_owned",
                model=None,
                remote_calls_armed=False,
                allow_network_egress=False,
                approved_by_human=False,
                replay_mode=False,
                capabilities="fs_read,shell_exec",
            )
            with patch("agentos_next.llm.backend.LocalMockLLMBackend.complete_json", new=_fake_complete_json):
                res = await run_assistant_loop_async(req)

            self.assertTrue(res.ok, msg=f"error_code={res.error_code}")
            operator_refs = [str(step.get("operator_ref") or "") for step in res.steps]
            builtin_actions = [ref for ref in operator_refs if ref.startswith("builtin://") and ref != "builtin://channel.send_message"]
            self.assertGreaterEqual(len(builtin_actions), 1)
            self.assertGreaterEqual(operator_refs.count(str(skill_dir)), 3)
            self.assertIn("builtin://channel.send_message", operator_refs)
            self.assertEqual(str((res.final_output or {}).get("channel") or ""), "assistant_runtime")
            self.assertIn("已查看 README", str((res.final_output or {}).get("text") or ""))

    async def test_assistant_loop_persists_runtime_graph_records(self) -> None:
        root = Path(__file__).resolve().parents[1]
        skill_dir = root / "examples" / "skills" / "personal_assistant_brief"
        worker_actions = [
            {
                "action_id": "readme",
                "operator_ref": "builtin://fs.read",
                "arguments": {"path": "README.md"},
            }
        ]
        executor_calls = {"count": 0}

        def _fake_complete_json(self, *, prompt, json_schema, safety, model_id=None, stream_callback=None):  # noqa: ANN001
            del self, json_schema, safety, model_id, stream_callback
            prompt_text = str(prompt or "")
            if "PROMPT_PROFILE=intent_router" in prompt_text:
                return {"status": "done"}
            if "PROMPT_PROFILE=planner" in prompt_text:
                return {
                    "status": "continue",
                    "worker_tasks": [
                        _worker_task_for_actions(
                            worker_task_id="worker_readme",
                            objective="Read README.md and collect key project details",
                            actions=worker_actions,
                            scope_summary="Inspect README.md only",
                        )
                    ],
                }
            if "PROMPT_PROFILE=executor" in prompt_text:
                executor_calls["count"] += 1
                if executor_calls["count"] == 1:
                    return {"status": "continue", "actions": worker_actions}
                return {"status": "done", "actions": []}
            if "PROMPT_PROFILE=verifier_replanner" in prompt_text:
                return {"status": "done"}
            if "PROMPT_PROFILE=communicator" in prompt_text:
                return {
                    "status": "done",
                    "actions": [
                        {
                            "action_id": "final_message",
                            "operator_ref": "builtin://channel.send_message",
                            "arguments": {"text": "runtime graph ok", "channel": "assistant_runtime"},
                        }
                    ],
                }
            return {"status": "done"}

        with tempfile.TemporaryDirectory(prefix="agentos_next_t045_runtime_graph_") as td:
            data_dir = Path(td) / "data"
            trace = TraceContext(trace_id="tr_qg_runtime_graph", turn_id="turn_qg_runtime_graph", span_id="span_qg_runtime_graph")
            req = AssistantLoopRequest(
                query="分析这个项目并给出建议",
                assistant_skill_dir=skill_dir,
                workspace_id="ws_qg",
                data_dir=data_dir,
                trace=trace,
                idempotency_key="idem_qg_runtime_graph",
                deadline_ms=8000,
                verify_asvp=False,
                public_keys_dir=None,
                backend="local_mock",
                planner="model_owned",
                model=None,
                remote_calls_armed=False,
                allow_network_egress=False,
                approved_by_human=False,
                replay_mode=False,
                capabilities="fs_read,shell_exec",
                graph_id="evt_runtime_graph",
            )
            with patch("agentos_next.llm.backend.LocalMockLLMBackend.complete_json", new=_fake_complete_json):
                res = await run_assistant_loop_async(req)

            self.assertTrue(res.ok, msg=f"error_code={res.error_code}")
            self.assertEqual(res.delivery_state, "done")
            self.assertEqual(res.graph_id, "evt_runtime_graph")

            graph = FileTaskGraphStore(data_dir).load(workspace_id="ws_qg", graph_id="evt_runtime_graph")
            assert graph is not None
            root_task = graph.tasks[graph.root_task_id]
            worker_tasks = [task for task in graph.tasks.values() if (task.payload or {}).get("type") == "worker_task"]
            leader_phases = {str(item.get("phase") or "") for item in graph.leader_decisions}
            tool_call_capsules = [item for item in graph.result_capsules if str(item.get("event_kind") or "") == "tool_call"]
            worker_final_capsules = [item for item in graph.result_capsules if str(item.get("event_kind") or "") == "worker_final"]

            self.assertEqual(graph.type, "runtime_graph_v1")
            self.assertEqual(root_task.state, "succeeded")
            self.assertEqual(str((root_task.task_bundle or {}).get("worker_task_admission_mode") or ""), "leader_gate")
            self.assertGreaterEqual(len(graph.message_turns), 1)
            self.assertGreaterEqual(len(graph.plan_revisions), 1)
            self.assertGreaterEqual(len(graph.result_capsules), 2)
            self.assertTrue(worker_tasks)
            self.assertTrue(any(task.state == "succeeded" for task in worker_tasks))
            self.assertTrue(tool_call_capsules)
            self.assertTrue(worker_final_capsules)
            self.assertTrue({"binder", "planner", "verifier_replanner", "communicator"}.issubset(leader_phases))

    async def test_assistant_loop_continues_until_deadline_without_replan_budget_cutoff(self) -> None:
        root = Path(__file__).resolve().parents[1]
        skill_dir = root / "examples" / "skills" / "personal_assistant_brief"
        verifier_calls = {"count": 0}
        worker_executor_calls: dict[str, int] = {}
        communicator_calls: list[str] = []

        def _fake_complete_json(self, *, prompt, json_schema, safety, model_id=None, stream_callback=None):  # noqa: ANN001
            if "PROMPT_PROFILE=intent_router" in prompt:
                return {"status": "done"}
            if "PROMPT_PROFILE=planner" in prompt:
                return _normalize_mock_phase_output("planner", {
                    "status": "continue",
                    "worker_tasks": [
                        _worker_task(
                            worker_task_id="worker_readme_1",
                            objective="Read README.md to establish verified facts",
                            allowed_operator_refs=["builtin://fs.read"],
                            scope_summary="Inspect README.md only",
                        )
                    ],
                })
            if "PROMPT_PROFILE=executor" in prompt:
                match = re.search(r"WORKER_TASK_ID=([^\s\\\\]+)", str(prompt or ""))
                worker_task_id = str(match.group(1) if match else "").strip()
                call_index = worker_executor_calls.get(worker_task_id or "worker", 0)
                worker_executor_calls[worker_task_id or "worker"] = call_index + 1
                if call_index > 0:
                    return {"status": "done", "actions": []}
                return {
                    "status": "continue",
                    "actions": [
                        {
                            "action_id": f"{worker_task_id or 'worker'}_readme_exec",
                            "operator_ref": "builtin://fs.read",
                            "arguments": {"path": "README.md"},
                        }
                    ],
                }
            if "PROMPT_PROFILE=verifier_replanner" in prompt:
                verifier_calls["count"] += 1
                return _normalize_mock_phase_output("verifier_replanner", {
                    "status": "continue",
                    "worker_tasks": [
                        _worker_task(
                            worker_task_id=f"worker_replan_{verifier_calls['count']}",
                            objective="Continue verifying README details",
                            allowed_operator_refs=["builtin://fs.read"],
                            scope_summary="Inspect README.md only",
                        )
                    ],
                })
            if "PROMPT_PROFILE=communicator" in prompt:
                communicator_calls.append(str(prompt))
                return {"status": "done"}
            return {"status": "done"}

        with tempfile.TemporaryDirectory(prefix="agentos_next_t045_hold_deadline_") as td:
            data_dir = Path(td) / "data"
            trace = TraceContext(trace_id="tr_qg_hold_deadline", turn_id="turn_qg_hold_deadline", span_id="span_qg_hold_deadline")
            req = AssistantLoopRequest(
                query="分析这个项目并给出建议",
                assistant_skill_dir=skill_dir,
                workspace_id="ws_qg",
                data_dir=data_dir,
                trace=trace,
                idempotency_key="idem_qg_hold_deadline",
                deadline_ms=1200,
                verify_asvp=False,
                public_keys_dir=None,
                backend="local_mock",
                planner="model_owned",
                model=None,
                remote_calls_armed=False,
                allow_network_egress=False,
                approved_by_human=False,
                replay_mode=False,
                capabilities="fs_read",
                graph_id="evt_hold_deadline",
            )
            with patch("agentos_next.llm.backend.LocalMockLLMBackend.complete_json", new=_fake_complete_json):
                res = await run_assistant_loop_async(req)

            self.assertFalse(res.ok)
            self.assertEqual(res.error_code, "E_DEADLINE_EXCEEDED")
            self.assertEqual(res.delivery_state, "hold")
            self.assertIsNone(res.final_output)
            self.assertGreaterEqual(verifier_calls["count"], 2)

            graph = FileTaskGraphStore(data_dir).load(workspace_id="ws_qg", graph_id="evt_hold_deadline")
            assert graph is not None
            self.assertEqual(graph.tasks[graph.root_task_id].state, "awaiting_leader")
            self.assertGreaterEqual(graph.replan_count, 1)
            self.assertGreaterEqual(graph.active_plan_revision, 1)

    async def test_assistant_loop_rejects_non_communicator_send_message_actions(self) -> None:
        root = Path(__file__).resolve().parents[1]
        skill_dir = root / "examples" / "skills" / "personal_assistant_brief"

        def _fake_complete_json(self, *, prompt, json_schema, safety, model_id=None, stream_callback=None):  # noqa: ANN001
            if "PROMPT_PROFILE=intent_router" in prompt:
                return {"status": "done"}
            if "PROMPT_PROFILE=planner" in prompt:
                return {
                    "status": "continue",
                    "actions": [
                        {
                            "action_id": "readme",
                            "operator_ref": "builtin://fs.read",
                            "arguments": {"path": "README.md"},
                        },
                        {
                            "action_id": "notify",
                            "operator_ref": "builtin://channel.send_message",
                            "arguments": {"text": "已读取 README，继续分析中。", "channel": "assistant_runtime"},
                            "depends_on": ["readme"],
                        },
                    ],
                }
            return {"status": "done"}

        with tempfile.TemporaryDirectory(prefix="agentos_next_t045_action_dep_") as td:
            data_dir = Path(td) / "data"
            trace = TraceContext(trace_id="tr_qg_action_dep", turn_id="turn_qg_action_dep", span_id="span_qg_action_dep")
            req = AssistantLoopRequest(
                query="分析这个项目并给出建议",
                assistant_skill_dir=skill_dir,
                workspace_id="ws_qg",
                data_dir=data_dir,
                trace=trace,
                idempotency_key="idem_qg_action_dep",
                deadline_ms=8000,
                verify_asvp=False,
                public_keys_dir=None,
                backend="local_mock",
                planner="model_owned",
                model=None,
                remote_calls_armed=False,
                allow_network_egress=False,
                approved_by_human=False,
                replay_mode=False,
                capabilities="fs_read,shell_exec",
            )
            with patch("agentos_next.llm.backend.LocalMockLLMBackend.complete_json", new=_fake_complete_json):
                res = await run_assistant_loop_async(req)

            self.assertFalse(res.ok)
            self.assertEqual(res.error_code, "E_MESSAGE_TASK_PHASE_VIOLATION")

    async def test_assistant_loop_routes_controller_phases_and_communicator_to_doubao_backend(self) -> None:
        root = Path(__file__).resolve().parents[1]
        skill_dir = root / "examples" / "skills" / "personal_assistant_brief"
        records: list[dict[str, str]] = []
        executor_calls: dict[str, int] = {}

        def _wrapped_pick_backend(self, req):  # noqa: ANN001
            policy = dict(req.policy_context or {})
            records.append(
                {
                    "profile": str(policy.get("active_prompt_profile") or ""),
                    "backend": str(req.backend or ""),
                    "model": str(req.model_id_override or ""),
                }
            )
            class _RoutedBackend:
                def complete_json(self, *, prompt, json_schema, safety, model_id=None, stream_callback=None):  # noqa: ANN001
                    del json_schema, safety, model_id, stream_callback
                    prompt_text = str(prompt or "")
                    if "PROMPT_PROFILE=intent_router" in prompt_text:
                        return {"status": "done"}
                    if "PROMPT_PROFILE=planner" in prompt_text:
                        return {
                            "status": "continue",
                            "worker_tasks": [
                                _worker_task(
                                    worker_task_id="worker_route_readme",
                                    objective="Read README before answering",
                                    allowed_operator_refs=["builtin://fs.read"],
                                    scope_summary="Inspect README.md only",
                                )
                            ],
                        }
                    if "PROMPT_PROFILE=executor" in prompt_text:
                        match = re.search(r"WORKER_TASK_ID=([^\s\\\\]+)", prompt_text)
                        worker_task_id = str(match.group(1) if match else "worker").strip() or "worker"
                        call_index = executor_calls.get(worker_task_id, 0)
                        executor_calls[worker_task_id] = call_index + 1
                        if call_index == 0:
                            return {
                                "status": "continue",
                                "actions": [
                                    {
                                        "action_id": "readme_call",
                                        "operator_ref": "builtin://fs.read",
                                        "arguments": {"path": "README.md"},
                                    }
                                ],
                            }
                        return {"status": "done", "actions": []}
                    if "PROMPT_PROFILE=verifier_replanner" in prompt_text:
                        return {"status": "done"}
                    if "PROMPT_PROFILE=communicator" in prompt_text:
                        return {
                            "status": "done",
                            "actions": [
                                {
                                    "action_id": "final_message",
                                    "operator_ref": "builtin://channel.send_message",
                                    "arguments": {
                                        "text": "README 已读取并汇总。",
                                        "channel": "assistant_runtime",
                                    },
                                }
                            ],
                        }
                    return {"status": "done"}

            return _RoutedBackend()

        with tempfile.TemporaryDirectory(prefix="agentos_next_t045_phase_route_") as td:
            data_dir = Path(td) / "data"
            trace = TraceContext(trace_id="tr_qg_phase_route", turn_id="turn_qg_phase_route", span_id="span_qg_phase_route")
            req = AssistantLoopRequest(
                query="分析这个项目并给出建议",
                assistant_skill_dir=skill_dir,
                workspace_id="ws_qg",
                data_dir=data_dir,
                trace=trace,
                idempotency_key="idem_qg_phase_route",
                deadline_ms=8000,
                verify_asvp=False,
                public_keys_dir=None,
                backend="codex_oauth",
                planner="model_owned",
                model="gpt-5-codex",
                intent_backend="doubao_ark",
                intent_model="ep-intent-20260309",
                communicator_backend="doubao_ark",
                communicator_model="ep-comm-20260309",
                remote_calls_armed=False,
                allow_network_egress=False,
                approved_by_human=False,
                replay_mode=False,
                capabilities="fs_read",
            )
            with patch.object(PackageRunner, "_pick_backend", new=_wrapped_pick_backend):
                res = await run_assistant_loop_async(req)

        self.assertTrue(res.ok, msg=f"error_code={res.error_code}")
        phase_map = {item["profile"]: item for item in records if item.get("profile")}
        self.assertNotIn("intent_router", phase_map)
        self.assertEqual(phase_map["planner"]["backend"], "codex_oauth")
        self.assertEqual(phase_map["planner"]["model"], "gpt-5-codex")
        self.assertEqual(phase_map["executor"]["backend"], "codex_oauth")
        self.assertEqual(phase_map["verifier_replanner"]["backend"], "codex_oauth")
        self.assertEqual(phase_map["communicator"]["backend"], "doubao_ark")
        self.assertEqual(phase_map["communicator"]["model"], "ep-comm-20260309")

    async def test_assistant_loop_gives_remote_role_phases_larger_deadline_slice(self) -> None:
        root = Path(__file__).resolve().parents[1]
        skill_dir = root / "examples" / "skills" / "personal_assistant_brief"

        class _DelayedLocalMockLLMBackend(LocalMockLLMBackend):
            def complete_json(self, *, prompt, json_schema, safety, model_id=None, stream_callback=None):  # noqa: ANN001
                time.sleep(3.0)
                return super().complete_json(
                    prompt=prompt,
                    json_schema=json_schema,
                    safety=safety,
                    model_id=model_id,
                    stream_callback=stream_callback,
                )

        def _wrapped_pick_backend(self, req):  # noqa: ANN001
            if str(req.backend or "") == "doubao_ark":
                return _DelayedLocalMockLLMBackend()
            return LocalMockLLMBackend()

        with tempfile.TemporaryDirectory(prefix="agentos_next_t045_phase_deadline_") as td:
            data_dir = Path(td) / "data"
            trace = TraceContext(trace_id="tr_qg_phase_deadline", turn_id="turn_qg_phase_deadline", span_id="span_qg_phase_deadline")
            req = AssistantLoopRequest(
                query="先理解我的意图，再给我一个正式回复",
                assistant_skill_dir=skill_dir,
                workspace_id="ws_qg",
                data_dir=data_dir,
                trace=trace,
                idempotency_key="idem_qg_phase_deadline",
                deadline_ms=12000,
                verify_asvp=False,
                public_keys_dir=None,
                backend="local_mock",
                planner="model_owned",
                model="local_mock",
                intent_backend="doubao_ark",
                intent_model="doubao-seed-2-0-pro-260215",
                communicator_backend="doubao_ark",
                communicator_model="doubao-seed-2-0-pro-260215",
                remote_calls_armed=False,
                allow_network_egress=False,
                approved_by_human=False,
                replay_mode=False,
            )
            with patch.object(PackageRunner, "_pick_backend", new=_wrapped_pick_backend):
                res = await run_assistant_loop_async(req)

        self.assertTrue(res.ok, msg=f"error_code={res.error_code}")
        phase_deadlines = {
            str(item.get("internal_role_phase") or ""): int(item.get("deadline_ms") or 0)
            for item in res.steps
            if isinstance(item, dict) and str(item.get("internal_role_phase") or "").strip()
        }
        self.assertNotIn("intent_router", phase_deadlines)
        self.assertGreaterEqual(phase_deadlines["communicator"], 3000)

    async def test_assistant_loop_timeout_blocker_is_phase_specific_and_delivered(self) -> None:
        root = Path(__file__).resolve().parents[1]
        skill_dir = root / "examples" / "skills" / "personal_assistant_brief"
        original_execute = LocalExecutor.execute
        communicator_requests: list[str] = []

        with tempfile.TemporaryDirectory(prefix="agentos_next_t045_timeout_blocker_") as td:
            data_dir = Path(td) / "data"
            trace = TraceContext(trace_id="tr_qg_timeout_blocker", turn_id="turn_qg_timeout_blocker", span_id="span_qg_timeout_blocker")

            async def _fake_execute(self, req):  # noqa: ANN001
                profile = str((req.policy_context or {}).get("active_prompt_profile") or "").strip()
                if profile == "planner":
                    return ExecuteResult(
                        status="timeout",
                        evidence_refs=(),
                        artifact_refs=(),
                        error_code="E_TIMEOUT",
                        timing=ExecuteTiming(
                            started_at="2026-03-09T00:00:00Z",
                            ended_at="2026-03-09T00:00:01Z",
                        ),
                        target="local",
                    )
                if profile == "communicator":
                    communicator_requests.append(str((req.arguments or {}).get("request") or ""))
                    evidence = FileEvidenceStore(data_dir=data_dir)
                    out_ref = evidence.add_json(
                        {
                            "schema_version": "1.0.0",
                            "output": {
                                "status": "blocked",
                                "actions": [
                                    {
                                        "action_id": "timeout_blocker_message",
                                        "operator_ref": "builtin://channel.send_message",
                                        "arguments": {
                                            "text": "意图识别阶段超时，请重试；如仍失败，可提高 deadline_ms 或切换更快的模型。",
                                            "channel": "assistant_runtime",
                                        },
                                    }
                                ],
                            },
                        },
                        kind="llm_io",
                    )
                    return ExecuteResult(
                        status="accepted",
                        evidence_refs=(out_ref,),
                        artifact_refs=(),
                        error_code=None,
                        timing=ExecuteTiming(
                            started_at="2026-03-09T00:00:01Z",
                            ended_at="2026-03-09T00:00:02Z",
                        ),
                        target="local",
                    )
                return await original_execute(self, req)

            req = AssistantLoopRequest(
                query="先理解我的意图，然后告诉我今天上海天气，并正式回复",
                assistant_skill_dir=skill_dir,
                workspace_id="ws_qg",
                data_dir=data_dir,
                trace=trace,
                idempotency_key="idem_qg_timeout_blocker",
                deadline_ms=8000,
                verify_asvp=False,
                public_keys_dir=None,
                backend="local_mock",
                planner="model_owned",
                model=None,
                remote_calls_armed=False,
                allow_network_egress=False,
                approved_by_human=False,
                replay_mode=False,
            )
            with patch.object(LocalExecutor, "execute", new=_fake_execute):
                res = await run_assistant_loop_async(req)

        self.assertFalse(res.ok)
        self.assertEqual(res.error_code, "E_TIMEOUT")
        self.assertEqual(str((res.final_output or {}).get("operator_ref") or ""), "builtin://channel.send_message")
        self.assertEqual(str((res.final_output or {}).get("delivery_stage") or ""), "blocker")
        self.assertIn("意图识别阶段超时", str((res.final_output or {}).get("text") or ""))
        self.assertEqual(
            [str(step.get("internal_role_phase") or step.get("operator_ref") or "") for step in res.steps],
            ["planner", "communicator", "builtin://channel.send_message"],
        )
        self.assertEqual(str((res.steps[-1].get("delivery") or {}).get("delivery_stage") or ""), "blocker")
        self.assertTrue(communicator_requests)
        self.assertIn("phase=planner", communicator_requests[0])
        self.assertIn("error_code=E_TIMEOUT", communicator_requests[0])
        self.assertNotIn("blocked task", communicator_requests[0].lower())

    async def test_assistant_loop_strips_non_communicator_reply_from_phase_output(self) -> None:
        root = Path(__file__).resolve().parents[1]
        skill_dir = root / "examples" / "skills" / "personal_assistant_brief"

        def _fake_complete_json(self, *, prompt, json_schema, safety, model_id=None, stream_callback=None):  # noqa: ANN001
            if "PROMPT_PROFILE=intent_router" in prompt:
                return {"status": "done"}
            if "PROMPT_PROFILE=planner" in prompt:
                return {
                    "status": "done",
                    "reply": "This should be ignored outside communicator.",
                    "reasoning": "Planner can finish without emitting any direct user text.",
                }
            if "PROMPT_PROFILE=executor" in prompt:
                return {"status": "done"}
            if "PROMPT_PROFILE=verifier_replanner" in prompt:
                return {"status": "done"}
            if "PROMPT_PROFILE=communicator" in prompt:
                return {
                    "status": "done",
                    "actions": [
                        {
                            "action_id": "final_message",
                            "operator_ref": "builtin://channel.send_message",
                            "arguments": {
                                "text": "已完成阶段处理。",
                                "channel": "assistant_runtime",
                            },
                        }
                    ],
                }
            return {"status": "done"}

        with tempfile.TemporaryDirectory(prefix="agentos_next_t045_strip_phase_reply_") as td:
            data_dir = Path(td) / "data"
            trace = TraceContext(trace_id="tr_qg_strip_phase_reply", turn_id="turn_qg_strip_phase_reply", span_id="span_qg_strip_phase_reply")
            req = AssistantLoopRequest(
                query="告诉我今天上海天气",
                assistant_skill_dir=skill_dir,
                workspace_id="ws_qg",
                data_dir=data_dir,
                trace=trace,
                idempotency_key="idem_qg_strip_phase_reply",
                deadline_ms=8000,
                verify_asvp=False,
                public_keys_dir=None,
                backend="local_mock",
                planner="model_owned",
                model=None,
                remote_calls_armed=False,
                allow_network_egress=False,
                approved_by_human=False,
                replay_mode=False,
            )
            with patch("agentos_next.llm.backend.LocalMockLLMBackend.complete_json", new=_fake_complete_json):
                res = await run_assistant_loop_async(req)

        self.assertTrue(res.ok, msg=f"error_code={res.error_code}")
        self.assertEqual(str((res.final_output or {}).get("operator_ref") or ""), "builtin://channel.send_message")
        self.assertEqual(str((res.final_output or {}).get("text") or ""), "已完成阶段处理。")

    async def test_assistant_loop_projects_web_search_results_into_verifier_observation_capsule(self) -> None:
        root = Path(__file__).resolve().parents[1]
        skill_dir = root / "examples" / "skills" / "personal_assistant_brief"
        original_execute = LocalExecutor.execute
        verifier_prompts: list[str] = []
        phase_outputs = {
            "intent_router": {"status": "done"},
            "planner": {
                "status": "continue",
                "actions": [
                    {
                        "action_id": "lookup_web",
                        "operator_ref": "builtin://web.search",
                        "arguments": {"query": "上海 今天天气 预报 实时"},
                    }
                ],
            },
            "verifier_replanner": lambda **kwargs: (  # noqa: ARG005
                verifier_prompts.append(str(kwargs.get("prompt") or "")) or {"status": "done"}
            ),
            "communicator": {
                "status": "done",
                "actions": [
                    {
                        "action_id": "final_message",
                        "operator_ref": "builtin://channel.send_message",
                        "arguments": {
                            "text": "上海今日天气已整理。",
                            "channel": "assistant_runtime",
                        },
                    }
                ],
            },
        }

        with tempfile.TemporaryDirectory(prefix="agentos_next_t045_web_capsule_") as td:
            data_dir = Path(td) / "data"
            trace = TraceContext(trace_id="tr_qg_web_capsule", turn_id="turn_qg_web_capsule", span_id="span_qg_web_capsule")

            async def _fake_execute(self, req):  # noqa: ANN001
                if str(req.operator_ref or "") == "builtin://web.search":
                    evidence = FileEvidenceStore(data_dir=data_dir)
                    out_ref = evidence.add_json(
                        {
                            "schema_version": "1.0.0",
                            "ok": True,
                            "provider_used": "playwright",
                            "degraded": False,
                            "expectation_mismatch": False,
                            "results": [
                                {
                                    "title": "上海天气预报,上海7天天气预报",
                                    "url": "https://www.weather.com.cn/weather/101020100.shtml",
                                    "snippet": "上海天气预报，及时准确发布中央气象台天气信息，便捷查询上海今日天气。",
                                }
                            ],
                        },
                        kind="tool_io",
                    )
                    return ExecuteResult(
                        status="accepted",
                        evidence_refs=(out_ref,),
                        artifact_refs=(),
                        error_code=None,
                        timing=ExecuteTiming(
                            started_at="2026-03-09T00:00:00Z",
                            ended_at="2026-03-09T00:00:01Z",
                        ),
                        target="local",
                    )
                return await original_execute(self, req)

            req = AssistantLoopRequest(
                query="告诉我今天上海天气",
                assistant_skill_dir=skill_dir,
                workspace_id="ws_qg",
                data_dir=data_dir,
                trace=trace,
                idempotency_key="idem_qg_web_capsule",
                deadline_ms=8000,
                verify_asvp=False,
                public_keys_dir=None,
                backend="local_mock",
                planner="model_owned",
                model=None,
                remote_calls_armed=False,
                allow_network_egress=False,
                approved_by_human=False,
                replay_mode=False,
                capabilities="web_search,web_browse",
                effective_runtime_capabilities=_caps("web_search", "web_browse"),
            )
            with patch.object(LocalExecutor, "execute", new=_fake_execute):
                with patch(
                    "agentos_next.llm.backend.LocalMockLLMBackend.complete_json",
                    new=_complete_json_from_phase_outputs(phase_outputs),
                ):
                    res = await run_assistant_loop_async(req)

        self.assertTrue(res.ok, msg=f"error_code={res.error_code}")
        self.assertTrue(verifier_prompts)
        self.assertIn("WEB SEARCH RESULTS", verifier_prompts[0])
        self.assertIn("GOAL=告诉我今天上海天气", verifier_prompts[0])
        self.assertIn("上海天气预报,上海7天天气预报", verifier_prompts[0])
        self.assertIn("weather.com.cn/weather/101020100.shtml", verifier_prompts[0])
        self.assertIn("continue with a bounded browse step", verifier_prompts[0])

    async def test_assistant_loop_projects_web_search_failure_into_communicator_observation_capsule(self) -> None:
        root = Path(__file__).resolve().parents[1]
        skill_dir = root / "examples" / "skills" / "personal_assistant_brief"
        original_execute = LocalExecutor.execute
        communicator_prompts: list[str] = []

        phase_outputs = {
            "intent_router": {"status": "done"},
            "planner": {
                "status": "continue",
                "actions": [
                    {
                        "action_id": "lookup_web",
                        "operator_ref": "builtin://web.search",
                        "arguments": {"query": "北京 今日 天气"},
                    }
                ],
            },
            "verifier_replanner": {"status": "blocked", "error_code": "E_WEB_SEARCH_NO_RESULTS"},
            "communicator": lambda **kwargs: (  # noqa: ARG005
                communicator_prompts.append(str(kwargs.get("prompt") or ""))
                or {
                    "status": "blocked",
                    "actions": [
                        {
                            "action_id": "final_message",
                            "operator_ref": "builtin://channel.send_message",
                            "arguments": {
                                "text": "抱歉，当前无法为你查询北京今日天气。",
                                "channel": "assistant_runtime",
                            },
                        }
                    ],
                }
            ),
        }

        with tempfile.TemporaryDirectory(prefix="agentos_next_t045_web_failure_capsule_") as td:
            data_dir = Path(td) / "data"
            trace = TraceContext(
                trace_id="tr_qg_web_failure_capsule",
                turn_id="turn_qg_web_failure_capsule",
                span_id="span_qg_web_failure_capsule",
            )

            async def _fake_execute(self, req):  # noqa: ANN001
                if str(req.operator_ref or "") == "builtin://web.search":
                    evidence = FileEvidenceStore(data_dir=data_dir)
                    err_ref = evidence.add_json(
                        {
                            "schema_version": "1.0.0",
                            "ok": False,
                            "operator_ref": "builtin://web.search",
                            "error_code": "E_WEB_SEARCH_NO_RESULTS",
                            "message": "web search failed for '北京 今日 天气'; attempts=brave:failed:BRAVE_SEARCH_API_KEY is not configured | duckduckgo_html:failed:E_WEB_SEARCH_NO_RESULTS:DuckDuckGo HTML search only returned the DuckDuckGo homepage/search portal without usable results for query='北京 今日 天气'",
                            "query": "北京 今日 天气",
                            "limit": 5,
                            "degraded": False,
                            "expectation_mismatch": True,
                            "provider_attempts": [
                                {
                                    "provider": "brave",
                                    "status": "failed",
                                    "detail": "BRAVE_SEARCH_API_KEY is not configured",
                                },
                                {
                                    "provider": "duckduckgo_html",
                                    "status": "failed",
                                    "error_code": "E_WEB_SEARCH_NO_RESULTS",
                                    "detail": "DuckDuckGo HTML search only returned the DuckDuckGo homepage/search portal without usable results for query='北京 今日 天气'",
                                },
                            ],
                            "results": [],
                            "notices": [
                                "brave unavailable: BRAVE_SEARCH_API_KEY is not configured",
                                "duckduckgo_html unavailable: DuckDuckGo HTML search only returned the DuckDuckGo homepage/search portal without usable results for query='北京 今日 天气'",
                            ],
                        },
                        kind="error",
                    )
                    return ExecuteResult(
                        status="failed",
                        evidence_refs=(err_ref,),
                        artifact_refs=(),
                        error_code="E_WEB_SEARCH_NO_RESULTS",
                        timing=ExecuteTiming(
                            started_at="2026-03-10T00:00:00Z",
                            ended_at="2026-03-10T00:00:01Z",
                        ),
                        target="local",
                    )
                return await original_execute(self, req)

            req = AssistantLoopRequest(
                query="告诉我北京今日天气",
                assistant_skill_dir=skill_dir,
                workspace_id="ws_qg",
                data_dir=data_dir,
                trace=trace,
                idempotency_key="idem_qg_web_failure_capsule",
                deadline_ms=8000,
                verify_asvp=False,
                public_keys_dir=None,
                backend="local_mock",
                planner="model_owned",
                model=None,
                remote_calls_armed=False,
                allow_network_egress=False,
                approved_by_human=False,
                replay_mode=False,
                capabilities="web_search,web_browse",
                effective_runtime_capabilities=_caps("web_search", "web_browse"),
            )
            with patch.object(LocalExecutor, "execute", new=_fake_execute):
                with patch(
                    "agentos_next.llm.backend.LocalMockLLMBackend.complete_json",
                    new=_complete_json_from_phase_outputs(phase_outputs),
                ):
                    res = await run_assistant_loop_async(req)

        self.assertFalse(res.ok)
        self.assertEqual(res.error_code, "E_VERIFICATION_BLOCKED")
        self.assertTrue(communicator_prompts)
        self.assertIn("WEB SEARCH FAILED [E_WEB_SEARCH_NO_RESULTS]", communicator_prompts[0])
        self.assertIn("Verified Failure Summary:", communicator_prompts[0])
        self.assertIn("ALLOWED_USER_VISIBLE_FACTS:", communicator_prompts[0])
        self.assertIn("DISALLOWED_INFERENCES:", communicator_prompts[0])
        self.assertIn("query=北京 今日 天气", communicator_prompts[0])
        self.assertIn("BRAVE_SEARCH_API_KEY is not configured", communicator_prompts[0])
        self.assertIn("DuckDuckGo homepage/search portal", communicator_prompts[0])

    async def test_assistant_loop_hides_internal_browser_search_provider_from_prompt(self) -> None:
        root = Path(__file__).resolve().parents[1]
        skill_dir = root / "examples" / "skills" / "personal_assistant_brief"
        original_execute = LocalExecutor.execute
        communicator_prompts: list[str] = []

        phase_outputs = {
            "intent_router": {"status": "done"},
            "planner": {
                "status": "continue",
                "actions": [
                    {
                        "action_id": "lookup_web",
                        "operator_ref": "builtin://web.search",
                        "arguments": {"query": "北京 今日 天气"},
                    }
                ],
            },
            "verifier_replanner": {"status": "blocked", "error_code": "E_WEB_SEARCH_NO_RESULTS"},
            "communicator": lambda **kwargs: (  # noqa: ARG005
                communicator_prompts.append(str(kwargs.get("prompt") or ""))
                or {
                    "status": "blocked",
                    "actions": [
                        {
                            "action_id": "final_message",
                            "operator_ref": "builtin://channel.send_message",
                            "arguments": {
                                "text": "抱歉，当前无法为你查询北京今日天气。",
                                "channel": "assistant_runtime",
                            },
                        }
                    ],
                }
            ),
        }

        with tempfile.TemporaryDirectory(prefix="agentos_next_t045_web_hidden_provider_") as td:
            data_dir = Path(td) / "data"
            trace = TraceContext(
                trace_id="tr_qg_web_hidden_provider",
                turn_id="turn_qg_web_hidden_provider",
                span_id="span_qg_web_hidden_provider",
            )

            async def _fake_execute(self, req):  # noqa: ANN001
                if str(req.operator_ref or "") == "builtin://web.search":
                    evidence = FileEvidenceStore(data_dir=data_dir)
                    err_ref = evidence.add_json(
                        {
                            "schema_version": "1.0.0",
                            "ok": False,
                            "operator_ref": "builtin://web.search",
                            "error_code": "E_WEB_SEARCH_NO_RESULTS",
                            "message": "web search failed for '北京 今日 天气'; attempts=brave:failed:BRAVE_SEARCH_API_KEY is not configured | playwright_search:failed:E_WEB_SEARCH_NO_RESULTS:Browser-assisted search returned no usable results for query='北京 今日 天气'",
                            "query": "北京 今日 天气",
                            "limit": 5,
                            "degraded": False,
                            "expectation_mismatch": True,
                            "provider_attempts": [
                                {
                                    "provider": "brave",
                                    "status": "failed",
                                    "detail": "BRAVE_SEARCH_API_KEY is not configured",
                                },
                                {
                                    "provider": "playwright_search",
                                    "status": "failed",
                                    "error_code": "E_WEB_SEARCH_NO_RESULTS",
                                    "detail": "Browser-assisted search returned no usable results for query='北京 今日 天气'",
                                },
                            ],
                            "results": [],
                            "notices": [
                                "brave unavailable: BRAVE_SEARCH_API_KEY is not configured",
                                "playwright_search unavailable: Browser-assisted search returned no usable results for query='北京 今日 天气'",
                            ],
                        },
                        kind="error",
                    )
                    return ExecuteResult(
                        status="failed",
                        evidence_refs=(err_ref,),
                        artifact_refs=(),
                        error_code="E_WEB_SEARCH_NO_RESULTS",
                        timing=ExecuteTiming(
                            started_at="2026-03-10T00:00:00Z",
                            ended_at="2026-03-10T00:00:01Z",
                        ),
                        target="local",
                    )
                return await original_execute(self, req)

            req = AssistantLoopRequest(
                query="告诉我北京今日天气",
                assistant_skill_dir=skill_dir,
                workspace_id="ws_qg",
                data_dir=data_dir,
                trace=trace,
                idempotency_key="idem_qg_web_hidden_provider",
                deadline_ms=8000,
                verify_asvp=False,
                public_keys_dir=None,
                backend="local_mock",
                planner="model_owned",
                model=None,
                remote_calls_armed=False,
                allow_network_egress=False,
                approved_by_human=False,
                replay_mode=False,
                capabilities="web_search,web_browse",
                effective_runtime_capabilities=_caps("web_search", "web_browse"),
            )
            with patch.object(LocalExecutor, "execute", new=_fake_execute):
                with patch(
                    "agentos_next.llm.backend.LocalMockLLMBackend.complete_json",
                    new=_complete_json_from_phase_outputs(phase_outputs),
                ):
                    res = await run_assistant_loop_async(req)

        self.assertFalse(res.ok)
        self.assertTrue(communicator_prompts)
        self.assertNotIn("playwright_search", communicator_prompts[0])
        self.assertIn("fallback_search", communicator_prompts[0])

    def test_build_user_facing_failure_summary_constrains_fallback_failure_claims(self) -> None:
        summary = build_user_facing_failure_summary_v1(
            query_text="今天北京天气怎么样？",
            exec_summaries=[
                {
                    "operator_ref": "builtin://web.search",
                    "status": "failed",
                    "error_code": "E_WEB_RUNTIME_UNAVAILABLE",
                    "source_phase": "executor",
                    "arguments": {"query": "北京天气 2026年3月11日"},
                }
            ],
            step_outputs=[
                {
                    "schema_version": "1.0.0",
                    "ok": False,
                    "operator_ref": "builtin://web.search",
                    "error_code": "E_WEB_RUNTIME_UNAVAILABLE",
                    "query": "北京天气 2026年3月11日",
                    "provider_attempts": [
                        {
                            "provider": "brave",
                            "status": "failed",
                            "detail": "BRAVE_SEARCH_API_KEY is not configured",
                        },
                        {
                            "provider": "duckduckgo_html",
                            "status": "failed",
                            "detail": "name '_strip_tags' is not defined",
                        },
                    ],
                }
            ],
            error_code="E_WEB_RUNTIME_UNAVAILABLE",
        )

        assert summary is not None
        self.assertEqual(summary["reason_class"], "external_evidence_unavailable")
        self.assertIn(
            "DuckDuckGo HTTP search failed before returning usable results.",
            summary["allowed_user_visible_facts"],
        )
        self.assertTrue(
            any("code bug" in item for item in summary["disallowed_inferences"]),
        )

    def test_build_user_facing_failure_summary_constrains_web_browse_claims(self) -> None:
        summary = build_user_facing_failure_summary_v1(
            query_text="帮我核实这个网页的内容",
            exec_summaries=[
                {
                    "operator_ref": "builtin://web.browse",
                    "status": "failed",
                    "error_code": "E_WEB_RUNTIME_UNAVAILABLE",
                    "source_phase": "executor",
                    "arguments": {"url": "https://example.com/report"},
                }
            ],
            step_outputs=[
                {
                    "schema_version": "1.0.0",
                    "ok": False,
                    "operator_ref": "builtin://web.browse",
                    "error_code": "E_WEB_RUNTIME_UNAVAILABLE",
                    "message": "Playwright runtime is unavailable; install the Python package and browser binaries.",
                }
            ],
            error_code="E_WEB_RUNTIME_UNAVAILABLE",
        )

        assert summary is not None
        self.assertEqual(summary["reason_class"], "web_browse_unavailable")
        self.assertIn(
            "The runtime could not access the required web browsing backend.",
            summary["allowed_user_visible_facts"],
        )
        self.assertTrue(
            any("verified evidence explicitly says so" in item for item in summary["disallowed_inferences"]),
        )

    def test_build_user_facing_failure_summary_classifies_worker_task_graph_invalid_as_internal_plan(self) -> None:
        summary = build_user_facing_failure_summary_v1(
            query_text="告诉我今天北京天气",
            exec_summaries=[
                {
                    "status": "blocked",
                    "error_code": "E_WORKER_TASK_GRAPH_INVALID",
                    "source_phase": "planner",
                }
            ],
            step_outputs=[
                {
                    "schema_version": "1.0.0",
                    "status": "blocked",
                    "error_code": "E_WORKER_TASK_GRAPH_INVALID",
                    "summary": "planner emitted invalid worker task graph",
                }
            ],
            error_code="E_WORKER_TASK_GRAPH_INVALID",
            phase_outcome="blocked",
        )

        assert summary is not None
        self.assertEqual(summary["reason_class"], "invalid_internal_plan")
        self.assertEqual(summary["template_key"], "blocker.invalid_internal_plan")
        self.assertEqual(summary["failure_scope"], "planning")
        self.assertIn(
            "The assistant produced an invalid or unfinished internal action plan before completing the request.",
            summary["allowed_user_visible_facts"],
        )

    def test_terminal_communicator_request_treats_worker_task_graph_invalid_as_structural(self) -> None:
        prompt = _build_terminal_communicator_request(
            terminal_stage="blocker",
            error_code="E_WORKER_TASK_GRAPH_INVALID",
            exec_summaries=[
                {
                    "source_phase": "planner",
                    "status": "failed",
                    "error_code": "E_WORKER_TASK_GRAPH_INVALID",
                }
            ],
            query_text="告诉我今天北京天气",
        )

        self.assertIn("invalid or unfinished internal action plan", prompt)
        self.assertNotIn("infrastructure failure", prompt)

    def test_phase_output_violation_tolerates_legacy_action_echo_when_worker_tasks_exist(self) -> None:
        violation = _phase_output_violation(
            profile_id="planner",
            output_obj={
                "status": "continue",
                "worker_tasks": [
                    {
                        "worker_task_id": "worker_weather",
                        "objective": "先搜索再浏览北京天气来源",
                        "depends_on": [],
                        "allowed_operator_refs": ["builtin://web.search", "builtin://web.browse"],
                        "scope_summary": "Read-only weather lookup.",
                        "completion_contract_ref": "worker_contract:weather",
                        "tool_budget": {
                            "max_calls": 2,
                            "max_parallel_calls": 1,
                            "retry_read_only_tools": True,
                        },
                        "time_budget_ms": 8000,
                    }
                ],
                "actions": [
                    {
                        "action_id": "legacy_search_echo",
                        "operator_ref": "builtin://web.search",
                        "arguments": {"query": "北京 今天天气"},
                    }
                ],
            },
        )

        self.assertIsNone(violation)

    def test_build_user_facing_failure_summary_classifies_candidate_exhaustion(self) -> None:
        summary = build_user_facing_failure_summary_v1(
            compiled_query={
                "task_requirements": {
                    "requires_external_evidence": True,
                    "external_evidence_policy_v1": {
                        "search_rounds_max": 2,
                        "browse_candidates_per_search_max": 3,
                        "total_browse_steps_max": 4,
                    },
                }
            },
            query_text="告诉我今天北京天气",
            exec_summaries=[
                {
                    "operator_ref": "builtin://web.search",
                    "status": "accepted",
                    "source_phase": "planner",
                    "arguments": {"query": "北京 今天天气"},
                },
                {
                    "operator_ref": "builtin://web.browse",
                    "status": "failed",
                    "error_code": "E_WEB_NAVIGATION_FAILED",
                    "source_phase": "runtime_browse_bridge",
                    "arguments": {"url": "https://ip.cn/tianqi/beijing/beijing/202603.html"},
                },
            ],
            step_outputs=[
                {
                    "schema_version": "1.0.0",
                    "ok": True,
                    "results": [
                        {
                            "title": "北京月天气",
                            "url": "https://ip.cn/tianqi/beijing/beijing/202603.html",
                            "snippet": "月天气归档。",
                        }
                    ],
                },
                {
                    "schema_version": "1.0.0",
                    "ok": False,
                    "operator_ref": "builtin://web.browse",
                    "error_code": "E_WEB_NAVIGATION_FAILED",
                    "message": "Playwright browse produced no readable page text.",
                    "url": "https://ip.cn/tianqi/beijing/beijing/202603.html",
                },
            ],
            error_code="E_WEB_NAVIGATION_FAILED",
        )

        assert summary is not None
        self.assertEqual(summary["reason_class"], "external_evidence_candidate_exhausted")
        self.assertEqual(summary["template_key"], "blocker.external_evidence_candidate_exhausted")
        self.assertTrue(
            any("ordinary search and browse budget" in item for item in summary["allowed_user_visible_facts"]),
        )

    def test_build_research_evidence_pack_accepts_explicit_research_run_output(self) -> None:
        pack = build_research_evidence_pack_v1(
            task_id="task_explicit_research",
            objective="给我一份带引用的调研报告",
            task_requirements={
                "requires_external_evidence": True,
                "research_required": True,
                "research_depth": "standard",
                "selected_doctrine_pack": "browser_research_mode",
                "evidence_expectation": "research_citation_set",
                "citation_required": True,
                "research_max_rounds": 2,
            },
            exec_summaries=[
                {
                    "operator_ref": "builtin://research.run",
                    "status": "accepted",
                    "error_code": None,
                    "arguments": {"objective": "给我一份带引用的调研报告", "min_sources": 2},
                }
            ],
            step_outputs=[
                {
                    "summary": "已收集两个来源。",
                    "report": "# 调研报告\n\n## 引用",
                    "search_queries": [
                        {
                            "query": "北京天气 多来源",
                            "provider_used": "duckduckgo_html",
                            "result_count": 4,
                            "degraded": True,
                        }
                    ],
                    "visited_sources": [
                        {
                            "url": "https://example.com/weather-1",
                            "title": "来源一",
                            "status": "accepted",
                        },
                        {
                            "url": "https://example.com/weather-2",
                            "title": "来源二",
                            "status": "accepted",
                        },
                    ],
                    "citations": [
                        {"id": "[1]", "title": "来源一", "url": "https://example.com/weather-1"},
                        {"id": "[2]", "title": "来源二", "url": "https://example.com/weather-2"},
                    ],
                    "sources": [
                        {
                            "title": "来源一",
                            "url": "https://example.com/weather-1",
                            "excerpt": "天气摘要一",
                            "search_query": "北京天气 多来源",
                            "search_rank": 1,
                        },
                        {
                            "title": "来源二",
                            "url": "https://example.com/weather-2",
                            "excerpt": "天气摘要二",
                            "search_query": "北京天气 多来源",
                            "search_rank": 2,
                        },
                    ],
                }
            ],
            error_code=None,
        )

        self.assertIsNotNone(pack)
        self.assertEqual(pack["research_depth"], "standard")
        self.assertEqual(len(pack["query_history"]), 1)
        self.assertEqual(len(pack["final_citation_set"]), 2)
        self.assertEqual(len(pack["accepted_evidence"]), 2)
        self.assertEqual(pack["accepted_evidence"][0]["kind"], "research_source")

    def test_build_user_facing_failure_summary_constrains_shell_exec_claims(self) -> None:
        summary = build_user_facing_failure_summary_v1(
            query_text="检查仓库当前状态",
            exec_summaries=[
                {
                    "operator_ref": "builtin://shell.exec",
                    "status": "failed",
                    "error_code": "E_TIMEOUT",
                    "source_phase": "executor",
                    "arguments": {"command": "rg TODO .", "cwd": "."},
                }
            ],
            step_outputs=[
                {
                    "schema_version": "1.0.0",
                    "ok": False,
                    "operator_ref": "builtin://shell.exec",
                    "error_code": "E_TIMEOUT",
                    "message": "command timed out",
                    "command": "rg TODO .",
                    "cwd": ".",
                }
            ],
            error_code="E_TIMEOUT",
        )

        assert summary is not None
        self.assertEqual(summary["reason_class"], "workspace_command_timeout")
        self.assertIn(
            "The command timed out before returning a result.",
            summary["allowed_user_visible_facts"],
        )
        self.assertTrue(
            any("changed files" in item for item in summary["disallowed_inferences"]),
        )

    def test_build_user_facing_failure_summary_constrains_memory_search_claims(self) -> None:
        summary = build_user_facing_failure_summary_v1(
            query_text="你记得我昨天的要求吗",
            exec_summaries=[
                {
                    "operator_ref": "builtin://memory.search",
                    "status": "rejected",
                    "error_code": "E_INPUT_SCHEMA",
                    "source_phase": "executor",
                    "arguments": {"query": "昨天 要求", "limit": 0},
                }
            ],
            step_outputs=[
                {
                    "schema_version": "1.0.0",
                    "ok": False,
                    "operator_ref": "builtin://memory.search",
                    "error_code": "E_INPUT_SCHEMA",
                    "message": "limit must be in [1, 200]",
                }
            ],
            error_code="E_INPUT_SCHEMA",
        )

        assert summary is not None
        self.assertEqual(summary["reason_class"], "memory_lookup_invalid_request")
        self.assertIn(
            "The memory lookup request was invalid for the current runtime contract.",
            summary["allowed_user_visible_facts"],
        )
        self.assertTrue(
            any("memory contained or lacked" in item for item in summary["disallowed_inferences"]),
        )

    async def test_assistant_loop_resolves_structured_action_refs_for_browse_followup(self) -> None:
        root = Path(__file__).resolve().parents[1]
        skill_dir = root / "examples" / "skills" / "personal_assistant_brief"
        original_execute = LocalExecutor.execute
        browse_urls: list[str] = []
        phase_outputs = {
            "intent_router": {"status": "done"},
            "planner": {
                "status": "continue",
                "worker_tasks": [
                    _worker_task(
                        worker_task_id="worker_weather_followup",
                        objective="先搜索再浏览上海天气来源",
                        allowed_operator_refs=["builtin://web.search", "builtin://web.browse"],
                    )
                ],
            },
            "executor": _worker_executor_from_batches(
                {
                    "worker_weather_followup": [
                        [
                            {
                                "action_id": "t1",
                                "operator_ref": "builtin://web.search",
                                "arguments": {"query": "上海 今天天气"},
                            }
                        ],
                        [
                            {
                                "action_id": "browse_page",
                                "operator_ref": "builtin://web.browse",
                                "arguments": {"url": {"$from_action": "t1", "path": ["results", 0, "url"]}},
                                "depends_on": ["t1"],
                            }
                        ],
                    ]
                }
            ),
            "verifier_replanner": {"status": "done"},
            "communicator": {
                "status": "done",
                "actions": [
                    {
                        "action_id": "final_message",
                        "operator_ref": "builtin://channel.send_message",
                        "arguments": {
                            "text": "上海天气信息已提取。",
                            "channel": "assistant_runtime",
                        },
                    }
                ],
            },
        }

        with tempfile.TemporaryDirectory(prefix="agentos_next_t045_action_alias_") as td:
            data_dir = Path(td) / "data"
            trace = TraceContext(trace_id="tr_qg_action_alias", turn_id="turn_qg_action_alias", span_id="span_qg_action_alias")

            async def _fake_execute(self, req):  # noqa: ANN001
                operator_ref = str(req.operator_ref or "")
                if operator_ref == "builtin://web.search":
                    evidence = FileEvidenceStore(data_dir=data_dir)
                    out_ref = evidence.add_json(
                        {
                            "schema_version": "1.0.0",
                            "ok": True,
                            "provider_used": "playwright",
                            "degraded": False,
                            "expectation_mismatch": False,
                            "results": [
                                {
                                    "title": "上海天气预报",
                                    "url": "https://www.weather.com.cn/weather/101020100.shtml",
                                    "snippet": "上海今日天气信息。",
                                }
                            ],
                        },
                        kind="tool_io",
                    )
                    return ExecuteResult(
                        status="accepted",
                        evidence_refs=(out_ref,),
                        artifact_refs=(),
                        error_code=None,
                        timing=ExecuteTiming(
                            started_at="2026-03-09T00:00:00Z",
                            ended_at="2026-03-09T00:00:01Z",
                        ),
                        target="local",
                    )
                if operator_ref == "builtin://web.browse":
                    browse_urls.append(str((req.arguments or {}).get("url") or ""))
                    evidence = FileEvidenceStore(data_dir=data_dir)
                    out_ref = evidence.add_json(
                        {
                            "schema_version": "1.0.0",
                            "ok": True,
                            "output": {
                                "reply": "上海今日多云，气温 8 到 13 摄氏度。",
                            },
                        },
                        kind="tool_io",
                    )
                    return ExecuteResult(
                        status="accepted",
                        evidence_refs=(out_ref,),
                        artifact_refs=(),
                        error_code=None,
                        timing=ExecuteTiming(
                            started_at="2026-03-09T00:00:01Z",
                            ended_at="2026-03-09T00:00:02Z",
                        ),
                        target="local",
                    )
                return await original_execute(self, req)

            req = AssistantLoopRequest(
                query="告诉我今天上海天气",
                assistant_skill_dir=skill_dir,
                workspace_id="ws_qg",
                data_dir=data_dir,
                trace=trace,
                idempotency_key="idem_qg_action_alias",
                deadline_ms=8000,
                verify_asvp=False,
                public_keys_dir=None,
                backend="local_mock",
                planner="model_owned",
                model=None,
                remote_calls_armed=False,
                allow_network_egress=False,
                approved_by_human=False,
                replay_mode=False,
                capabilities="web_search,web_browse",
                effective_runtime_capabilities=_caps("web_search", "web_browse"),
            )
            with patch.object(LocalExecutor, "execute", new=_fake_execute):
                with patch(
                    "agentos_next.llm.backend.LocalMockLLMBackend.complete_json",
                    new=_complete_json_from_phase_outputs(phase_outputs),
                ):
                    res = await run_assistant_loop_async(req)

        self.assertTrue(res.ok, msg=f"error_code={res.error_code}")
        operator_refs = [str(step.get("operator_ref") or "") for step in res.steps]
        self.assertIn("builtin://web.search", operator_refs)
        self.assertIn("builtin://web.browse", operator_refs)
        self.assertEqual(browse_urls, ["https://www.weather.com.cn/weather/101020100.shtml"])
        self.assertEqual(str((res.final_output or {}).get("text") or ""), "上海天气信息已提取。")

    async def test_assistant_loop_runtime_browse_bridge_tries_later_candidates_within_budget(self) -> None:
        root = Path(__file__).resolve().parents[1]
        skill_dir = root / "examples" / "skills" / "personal_assistant_brief"
        original_execute = LocalExecutor.execute
        browse_urls: list[str] = []
        phase_outputs = {
            "intent_router": {"status": "done"},
            "planner": {
                "status": "continue",
                "worker_tasks": [
                    _worker_task(
                        worker_task_id="worker_lookup_weather",
                        objective="查找北京今天天气来源",
                        allowed_operator_refs=["builtin://web.search"],
                    )
                ],
            },
            "executor": _worker_executor_from_batches(
                {
                    "worker_lookup_weather": [
                        [
                            {
                                "action_id": "lookup_web",
                                "operator_ref": "builtin://web.search",
                                "arguments": {"query": "北京 今天天气"},
                            }
                        ]
                    ]
                }
            ),
            "verifier_replanner": {"status": "done"},
            "communicator": {
                "status": "done",
                "actions": [
                    {
                        "action_id": "final_message",
                        "operator_ref": "builtin://channel.send_message",
                        "arguments": {"text": "北京天气信息已整理。"},
                    }
                ],
            },
        }

        with tempfile.TemporaryDirectory(prefix="agentos_next_t045_bridge_budget_") as td:
            data_dir = Path(td) / "data"
            trace = TraceContext(
                trace_id="tr_qg_bridge_budget",
                turn_id="turn_qg_bridge_budget",
                span_id="span_qg_bridge_budget",
            )

            async def _fake_execute(self, req):  # noqa: ANN001
                operator_ref = str(req.operator_ref or "")
                if operator_ref == "builtin://web.search":
                    evidence = FileEvidenceStore(data_dir=data_dir)
                    out_ref = evidence.add_json(
                        {
                            "schema_version": "1.0.0",
                            "ok": True,
                            "provider_used": "duckduckgo_html",
                            "degraded": False,
                            "expectation_mismatch": False,
                            "results": [
                                {
                                    "title": "北京月天气",
                                    "url": "https://ip.cn/tianqi/beijing/beijing/202603.html",
                                    "snippet": "北京 2026 年 03 月天气信息。",
                                },
                                {
                                    "title": "北京天气预报",
                                    "url": "https://www.weather.com.cn/weather/101010100.shtml",
                                    "snippet": "北京今日天气，实时更新。",
                                },
                            ],
                        },
                        kind="tool_io",
                    )
                    return ExecuteResult(
                        status="accepted",
                        evidence_refs=(out_ref,),
                        artifact_refs=(),
                        error_code=None,
                        timing=ExecuteTiming(
                            started_at="2026-03-09T00:00:00Z",
                            ended_at="2026-03-09T00:00:01Z",
                        ),
                        target="local",
                    )
                if operator_ref == "builtin://web.browse":
                    url = str((req.arguments or {}).get("url") or "")
                    browse_urls.append(url)
                    evidence = FileEvidenceStore(data_dir=data_dir)
                    if url.endswith("202603.html"):
                        out_ref = evidence.add_json(
                            {
                                "schema_version": "1.0.0",
                                "ok": False,
                                "operator_ref": "builtin://web.browse",
                                "error_code": "E_WEB_NAVIGATION_FAILED",
                                "message": "Playwright browse produced no readable page text.",
                                "url": url,
                            },
                            kind="error",
                        )
                        return ExecuteResult(
                            status="failed",
                            evidence_refs=(out_ref,),
                            artifact_refs=(),
                            error_code="E_WEB_NAVIGATION_FAILED",
                            timing=ExecuteTiming(
                                started_at="2026-03-09T00:00:01Z",
                                ended_at="2026-03-09T00:00:02Z",
                            ),
                            target="local",
                        )
                    out_ref = evidence.add_json(
                        {
                            "schema_version": "1.0.0",
                            "ok": True,
                            "url": url,
                            "output": {
                                "reply": "北京今天多云，5 到 13 摄氏度。",
                                "url": url,
                            },
                        },
                        kind="tool_io",
                    )
                    return ExecuteResult(
                        status="accepted",
                        evidence_refs=(out_ref,),
                        artifact_refs=(),
                        error_code=None,
                        timing=ExecuteTiming(
                            started_at="2026-03-09T00:00:02Z",
                            ended_at="2026-03-09T00:00:03Z",
                        ),
                        target="local",
                    )
                return await original_execute(self, req)

            req = AssistantLoopRequest(
                query="告诉我今天北京天气",
                assistant_skill_dir=skill_dir,
                workspace_id="ws_qg",
                data_dir=data_dir,
                trace=trace,
                idempotency_key="idem_qg_bridge_budget",
                deadline_ms=8000,
                verify_asvp=False,
                public_keys_dir=None,
                backend="local_mock",
                planner="model_owned",
                model=None,
                remote_calls_armed=False,
                allow_network_egress=False,
                approved_by_human=False,
                replay_mode=False,
                capabilities="web_search,web_browse",
                effective_runtime_capabilities=_caps("web_search", "web_browse"),
            )
            with patch.object(LocalExecutor, "execute", new=_fake_execute):
                with patch.object(PackageRunner, "_pick_backend", new=_phase_backend_picker(phase_outputs)):
                    res = await run_assistant_loop_async(req)

        self.assertTrue(res.ok, msg=f"error_code={res.error_code}")
        self.assertEqual(
            browse_urls,
            [
                "https://ip.cn/tianqi/beijing/beijing/202603.html",
                "https://www.weather.com.cn/weather/101010100.shtml",
            ],
        )
        self.assertEqual(str((res.final_output or {}).get("text") or ""), "北京天气信息已整理。")

    async def test_assistant_loop_overrides_terminal_delivery_stage_and_avoids_send_message_idem_collision(self) -> None:
        root = Path(__file__).resolve().parents[1]
        skill_dir = root / "examples" / "skills" / "personal_assistant_brief"
        original_execute = LocalExecutor.execute
        verifier_calls = {"count": 0}
        phase_outputs = {
            "intent_router": {"status": "done"},
            "planner": {
                "status": "continue",
                "actions": [
                    {
                        "action_id": "lookup_web",
                        "operator_ref": "builtin://web.search",
                        "arguments": {"query": "上海 今天天气"},
                    }
                ],
            },
            "verifier_replanner": lambda **kwargs: (  # noqa: ARG005
                {"status": "done"}
                if (verifier_calls.__setitem__("count", verifier_calls["count"] + 1) or verifier_calls["count"]) > 1
                else {
                    "status": "continue",
                    "actions": [
                        {
                            "action_id": "browse_page",
                            "operator_ref": "builtin://web.browse",
                            "arguments": {"url": "https://www.weather.com.cn/weather/101020100.shtml"},
                        }
                    ],
                }
            ),
            "communicator": {
                "status": "done",
                "actions": [
                    {
                        "action_id": "final_message",
                        "operator_ref": "builtin://channel.send_message",
                        "arguments": {
                            "text": "上海今天多云，4 到 12 摄氏度。",
                            "delivery_stage": "progress",
                        },
                    }
                ],
            },
        }

        with tempfile.TemporaryDirectory(prefix="agentos_next_t045_final_stage_override_") as td:
            data_dir = Path(td) / "data"
            trace = TraceContext(
                trace_id="tr_qg_final_stage_override",
                turn_id="turn_qg_final_stage_override",
                span_id="span_qg_final_stage_override",
            )

            async def _fake_execute(self, req):  # noqa: ANN001
                operator_ref = str(req.operator_ref or "")
                if operator_ref == "builtin://web.search":
                    evidence = FileEvidenceStore(data_dir=data_dir)
                    out_ref = evidence.add_json(
                        {
                            "schema_version": "1.0.0",
                            "ok": True,
                            "provider_used": "playwright",
                            "degraded": False,
                            "expectation_mismatch": False,
                            "results": [
                                {
                                    "title": "上海天气预报",
                                    "url": "https://www.weather.com.cn/weather/101020100.shtml",
                                    "snippet": "上海今日天气信息。",
                                }
                            ],
                        },
                        kind="tool_io",
                    )
                    return ExecuteResult(
                        status="accepted",
                        evidence_refs=(out_ref,),
                        artifact_refs=(),
                        error_code=None,
                        timing=ExecuteTiming(
                            started_at="2026-03-09T00:00:00Z",
                            ended_at="2026-03-09T00:00:01Z",
                        ),
                        target="local",
                    )
                if operator_ref == "builtin://web.browse":
                    evidence = FileEvidenceStore(data_dir=data_dir)
                    out_ref = evidence.add_json(
                        {
                            "schema_version": "1.0.0",
                            "ok": True,
                            "output": {
                                "reply": "上海今天多云，4 到 12 摄氏度。",
                            },
                        },
                        kind="tool_io",
                    )
                    return ExecuteResult(
                        status="accepted",
                        evidence_refs=(out_ref,),
                        artifact_refs=(),
                        error_code=None,
                        timing=ExecuteTiming(
                            started_at="2026-03-09T00:00:01Z",
                            ended_at="2026-03-09T00:00:02Z",
                        ),
                        target="local",
                    )
                return await original_execute(self, req)

            req = AssistantLoopRequest(
                query="告诉我今天上海天气",
                assistant_skill_dir=skill_dir,
                workspace_id="ws_qg",
                data_dir=data_dir,
                trace=trace,
                idempotency_key="idem_qg_final_stage_override",
                deadline_ms=8000,
                verify_asvp=False,
                public_keys_dir=None,
                backend="local_mock",
                planner="model_owned",
                model=None,
                remote_calls_armed=False,
                allow_network_egress=False,
                approved_by_human=False,
                replay_mode=False,
                capabilities="web_search,web_browse",
            )
            with patch.object(LocalExecutor, "execute", new=_fake_execute):
                with patch(
                    "agentos_next.llm.backend.LocalMockLLMBackend.complete_json",
                    new=_complete_json_from_phase_outputs(phase_outputs),
                ):
                    res = await run_assistant_loop_async(req)

        self.assertTrue(res.ok, msg=f"error_code={res.error_code}")
        self.assertEqual(str((res.final_output or {}).get("delivery_stage") or ""), "final")
        deliveries = [
            dict(step.get("delivery") or {})
            for step in res.steps
            if str(step.get("operator_ref") or "") == "builtin://channel.send_message"
        ]
        self.assertEqual([str(item.get("delivery_stage") or "") for item in deliveries], ["progress", "final"])
        self.assertEqual(
            [str(item.get("text") or "") for item in deliveries],
            ["上海今天多云，4 到 12 摄氏度。", "上海今天多云，4 到 12 摄氏度。"],
        )

    async def test_assistant_loop_executor_batch_can_reference_planner_actions_without_cycle(self) -> None:
        root = Path(__file__).resolve().parents[1]
        skill_dir = root / "examples" / "skills" / "personal_assistant_brief"
        original_execute = LocalExecutor.execute
        search_calls: list[str] = []
        browse_calls: list[str] = []
        phase_outputs = {
            "intent_router": {"status": "done"},
            "planner": {
                "status": "continue",
                "worker_tasks": [
                    _worker_task(
                        worker_task_id="worker_weather_chain",
                        objective="搜索并浏览上海天气来源",
                        allowed_operator_refs=["builtin://web.search", "builtin://web.browse"],
                    )
                ],
            },
            "executor": _worker_executor_from_batches(
                {
                    "worker_weather_chain": [
                        [
                            {
                                "action_id": "lookup_web",
                                "operator_ref": "builtin://web.search",
                                "arguments": {"query": "上海 今天天气"},
                            }
                        ],
                        [
                            {
                                "action_id": "browse_page",
                                "operator_ref": "builtin://web.browse",
                                "arguments": {"url": {"$from_action": "lookup_web", "path": ["results", 0, "url"]}},
                                "depends_on": ["lookup_web"],
                            }
                        ],
                    ]
                }
            ),
            "verifier_replanner": {"status": "done"},
            "communicator": {
                "status": "done",
                "actions": [
                    {
                        "action_id": "final_message",
                        "operator_ref": "builtin://channel.send_message",
                        "arguments": {"text": "上海天气已获取。"},
                    }
                ],
            },
        }

        with tempfile.TemporaryDirectory(prefix="agentos_next_t045_batch_dep_inject_") as td:
            data_dir = Path(td) / "data"
            trace = TraceContext(
                trace_id="tr_qg_batch_dep_inject",
                turn_id="turn_qg_batch_dep_inject",
                span_id="span_qg_batch_dep_inject",
            )

            async def _fake_execute(self, req):  # noqa: ANN001
                operator_ref = str(req.operator_ref or "")
                if operator_ref == "builtin://web.search":
                    search_calls.append(str((req.arguments or {}).get("query") or ""))
                    evidence = FileEvidenceStore(data_dir=data_dir)
                    out_ref = evidence.add_json(
                        {
                            "schema_version": "1.0.0",
                            "ok": True,
                            "provider_used": "playwright",
                            "degraded": False,
                            "expectation_mismatch": False,
                            "results": [
                                {
                                    "title": "上海天气预报",
                                    "url": "https://www.weather.com.cn/weather/101020100.shtml",
                                    "snippet": "上海今日天气信息。",
                                }
                            ],
                        },
                        kind="tool_io",
                    )
                    return ExecuteResult(
                        status="accepted",
                        evidence_refs=(out_ref,),
                        artifact_refs=(),
                        error_code=None,
                        timing=ExecuteTiming(
                            started_at="2026-03-09T00:00:00Z",
                            ended_at="2026-03-09T00:00:01Z",
                        ),
                        target="local",
                    )
                if operator_ref == "builtin://web.browse":
                    browse_calls.append(str((req.arguments or {}).get("url") or ""))
                    evidence = FileEvidenceStore(data_dir=data_dir)
                    out_ref = evidence.add_json(
                        {
                            "schema_version": "1.0.0",
                            "ok": True,
                            "url": str((req.arguments or {}).get("url") or ""),
                            "output": {
                                "reply": "上海今天多云，4 到 12 摄氏度。",
                                "url": str((req.arguments or {}).get("url") or ""),
                            },
                        },
                        kind="tool_io",
                    )
                    return ExecuteResult(
                        status="accepted",
                        evidence_refs=(out_ref,),
                        artifact_refs=(),
                        error_code=None,
                        timing=ExecuteTiming(
                            started_at="2026-03-09T00:00:01Z",
                            ended_at="2026-03-09T00:00:02Z",
                        ),
                        target="local",
                    )
                return await original_execute(self, req)

            req = AssistantLoopRequest(
                query="告诉我今天上海天气",
                assistant_skill_dir=skill_dir,
                workspace_id="ws_qg",
                data_dir=data_dir,
                trace=trace,
                idempotency_key="idem_qg_batch_dep_inject",
                deadline_ms=8000,
                verify_asvp=False,
                public_keys_dir=None,
                backend="local_mock",
                planner="model_owned",
                model=None,
                remote_calls_armed=False,
                allow_network_egress=False,
                approved_by_human=False,
                replay_mode=False,
                capabilities="web_search,web_browse",
            )
            with patch.object(LocalExecutor, "execute", new=_fake_execute):
                with patch(
                    "agentos_next.llm.backend.LocalMockLLMBackend.complete_json",
                    new=_complete_json_from_phase_outputs(phase_outputs),
                ):
                    res = await run_assistant_loop_async(req)

        self.assertTrue(res.ok, msg=f"error_code={res.error_code}")
        self.assertNotEqual(res.error_code, "E_TASK_DEPENDENCY_CYCLE")
        self.assertEqual(search_calls, ["上海 今天天气"])
        self.assertEqual(browse_calls, ["https://www.weather.com.cn/weather/101020100.shtml"])
        self.assertEqual(str((res.final_output or {}).get("text") or ""), "上海天气已获取。")

    async def test_assistant_loop_rejects_unapproved_worker_split_actions(self) -> None:
        root = Path(__file__).resolve().parents[1]
        skill_dir = root / "examples" / "skills" / "personal_assistant_brief"
        phase_outputs = {
            "intent_router": {"status": "done"},
            "planner": {
                "status": "continue",
                "actions": [
                    {
                        "action_id": "readme",
                        "operator_ref": "builtin://fs.read",
                        "arguments": {"path": "README.md"},
                    }
                ],
            },
            "executor": {
                "status": "continue",
                "actions": [
                    {
                        "action_id": "novel_split",
                        "operator_ref": "builtin://fs.list",
                        "arguments": {"path": "."},
                    }
                ],
            },
            "communicator": {
                "status": "done",
                "actions": [
                    {
                        "action_id": "final_message",
                        "operator_ref": "builtin://channel.send_message",
                        "arguments": {"text": "planner approval required", "channel": "assistant_runtime"},
                    }
                ],
            },
        }

        with tempfile.TemporaryDirectory(prefix="agentos_next_t045_worker_split_gate_") as td:
            data_dir = Path(td) / "data"
            trace = TraceContext(trace_id="tr_qg_worker_split_gate", turn_id="turn_qg_worker_split_gate", span_id="span_qg_worker_split_gate")
            req = AssistantLoopRequest(
                query="分析这个项目并给出建议",
                assistant_skill_dir=skill_dir,
                workspace_id="ws_qg",
                data_dir=data_dir,
                trace=trace,
                idempotency_key="idem_qg_worker_split_gate",
                deadline_ms=8000,
                verify_asvp=False,
                public_keys_dir=None,
                backend="local_mock",
                planner="model_owned",
                model=None,
                remote_calls_armed=False,
                allow_network_egress=False,
                approved_by_human=False,
                replay_mode=False,
                capabilities="fs_read,fs_list",
            )
            with patch(
                "agentos_next.llm.backend.LocalMockLLMBackend.complete_json",
                new=_complete_json_from_phase_outputs(phase_outputs),
            ):
                res = await run_assistant_loop_async(req)

        self.assertFalse(res.ok)
        self.assertEqual(res.error_code, "E_WORKER_SPLIT_REQUIRES_LEADER")
        self.assertEqual(str((res.final_output or {}).get("delivery_stage") or ""), "blocker")

    async def test_assistant_loop_marks_unknown_dependency_as_unresolved_not_cycle(self) -> None:
        root = Path(__file__).resolve().parents[1]
        skill_dir = root / "examples" / "skills" / "personal_assistant_brief"
        phase_outputs = {
            "intent_router": {"status": "done"},
            "planner": {
                "status": "continue",
                "actions": [
                    {
                        "action_id": "t2",
                        "operator_ref": "builtin://web.browse",
                        "arguments": {"url": {"$from_action": "unknown_dep", "path": ["results", 0, "url"]}},
                        "depends_on": ["unknown_dep"],
                    }
                ],
            },
            "communicator": {
                "status": "blocked",
                "actions": [
                    {
                        "action_id": "final_message",
                        "operator_ref": "builtin://channel.send_message",
                        "arguments": {"text": "blocked"},
                    }
                ],
            },
        }

        with tempfile.TemporaryDirectory(prefix="agentos_next_t045_dep_unresolved_") as td:
            data_dir = Path(td) / "data"
            trace = TraceContext(
                trace_id="tr_qg_dep_unresolved",
                turn_id="turn_qg_dep_unresolved",
                span_id="span_qg_dep_unresolved",
            )
            req = AssistantLoopRequest(
                query="告诉我今天上海天气",
                assistant_skill_dir=skill_dir,
                workspace_id="ws_qg",
                data_dir=data_dir,
                trace=trace,
                idempotency_key="idem_qg_dep_unresolved",
                deadline_ms=8000,
                verify_asvp=False,
                public_keys_dir=None,
                backend="local_mock",
                planner="model_owned",
                model=None,
                remote_calls_armed=False,
                allow_network_egress=False,
                approved_by_human=False,
                replay_mode=False,
                capabilities="web_search,web_browse",
            )
            with patch(
                "agentos_next.llm.backend.LocalMockLLMBackend.complete_json",
                new=_complete_json_from_phase_outputs(phase_outputs),
            ):
                res = await run_assistant_loop_async(req)

        self.assertFalse(res.ok)
        self.assertEqual(res.error_code, "E_TASK_DEPENDENCY_UNRESOLVED")

    async def test_assistant_loop_ignores_infra_failures_for_repeat_hypothesis_gate(self) -> None:
        root = Path(__file__).resolve().parents[1]
        skill_dir = root / "examples" / "skills" / "personal_assistant_brief"

        with tempfile.TemporaryDirectory(prefix="agentos_next_t045_repeat_infra_") as td:
            data_dir = Path(td) / "data"
            store = FileHypothesisStore(data_dir=data_dir)
            store.put_if_absent(
                workspace_id="ws_qg",
                record=HypothesisRecord(
                    schema_version="1.0.0",
                    turn_id="turn_prev",
                    iteration=1,
                    hypothesis="mode=simple; objective=先理解我的意图，再给我一个正式回复",
                    verification_action="verify_assistant_execution",
                    verification_evidence_refs=(),
                    result="rejected",
                    revision="error_code=E_EXECUTION_FAILED",
                ),
            )
            trace = TraceContext(
                trace_id="tr_qg_repeat_infra",
                turn_id="turn_qg_repeat_infra",
                span_id="span_qg_repeat_infra",
            )
            req = AssistantLoopRequest(
                query="先理解我的意图，再给我一个正式回复",
                assistant_skill_dir=skill_dir,
                workspace_id="ws_qg",
                data_dir=data_dir,
                trace=trace,
                idempotency_key="idem_qg_repeat_infra",
                deadline_ms=8000,
                verify_asvp=False,
                public_keys_dir=None,
                backend="local_mock",
                planner="model_owned",
                model=None,
                remote_calls_armed=False,
                allow_network_egress=False,
                approved_by_human=False,
                replay_mode=False,
            )
            res = await run_assistant_loop_async(req)

        self.assertTrue(res.ok, msg=f"error_code={res.error_code}")

    def test_infra_only_hypothesis_record_detects_failed_snapshot_without_accepted_steps(self) -> None:
        with tempfile.TemporaryDirectory(prefix="agentos_next_t045_hypo_snapshot_") as td:
            data_dir = Path(td) / "data"
            evidence = FileEvidenceStore(data_dir=data_dir)
            final_ref = evidence.add_json(
                {
                    "schema_version": "1.0.0",
                    "type": "assistant_loop_result",
                    "error_code": "E_EXECUTION_FAILED",
                    "steps": [
                        {
                            "i": 1,
                            "status": "failed",
                            "internal_role_phase": "intent_router",
                        }
                    ],
                },
                kind="snapshot",
            )
            rec = HypothesisRecord(
                schema_version="1.0.0",
                turn_id="turn_prev",
                iteration=1,
                hypothesis="mode=simple; objective=先理解我的意图，再给我一个正式回复",
                verification_action="verify_assistant_execution",
                verification_evidence_refs=(final_ref.ref,),
                result="rejected",
                revision="return non-empty user-visible output or explicit blocked explanation",
            )
            self.assertTrue(_is_infra_only_hypothesis_record(record=rec, evidence=evidence))

    def test_infra_only_hypothesis_record_ignores_retryable_replan_budget_snapshot(self) -> None:
        with tempfile.TemporaryDirectory(prefix="agentos_next_t045_hypo_replan_") as td:
            data_dir = Path(td) / "data"
            evidence = FileEvidenceStore(data_dir=data_dir)
            final_ref = evidence.add_json(
                {
                    "schema_version": "1.0.0",
                    "type": "assistant_loop_result",
                    "error_code": "E_REPLAN_BUDGET_EXHAUSTED",
                    "steps": [
                        {
                            "i": 1,
                            "status": "accepted",
                            "internal_role_phase": "verifier_replanner",
                        }
                    ],
                },
                kind="snapshot",
            )
            rec = HypothesisRecord(
                schema_version="1.0.0",
                turn_id="turn_prev_retryable",
                iteration=1,
                hypothesis="mode=standard; objective=告诉我今天上海天气; capabilities=web_browse|web_search",
                verification_action="verify_assistant_execution",
                verification_evidence_refs=(final_ref.ref,),
                result="rejected",
                revision="error_code=E_REPLAN_BUDGET_EXHAUSTED",
            )
            self.assertTrue(_is_infra_only_hypothesis_record(record=rec, evidence=evidence))

    def test_map_hypothesis_result_treats_replan_budget_exhausted_as_partial(self) -> None:
        result = _map_hypothesis_result(
            verify_report={"acceptance_pass": False, "failures": []},
            error_code="E_REPLAN_BUDGET_EXHAUSTED",
        )
        self.assertEqual(result, "partial")

    async def test_assistant_loop_emits_delivery_state_lifecycle_events(self) -> None:
        root = Path(__file__).resolve().parents[1]
        skill_dir = root / "examples" / "skills" / "personal_assistant_brief"

        with tempfile.TemporaryDirectory(prefix="agentos_next_t045_delivery_") as td:
            data_dir = Path(td) / "data"
            trace = TraceContext(trace_id="tr_qg_delivery", turn_id="turn_qg_delivery", span_id="span_qg_delivery")
            req = AssistantLoopRequest(
                query="hello",
                assistant_skill_dir=skill_dir,
                workspace_id="ws_qg",
                data_dir=data_dir,
                trace=trace,
                idempotency_key="idem_qg_delivery",
                deadline_ms=8000,
                verify_asvp=False,
                public_keys_dir=None,
                backend="local_mock",
                planner="model_owned",
                model=None,
                remote_calls_armed=False,
                allow_network_egress=False,
                approved_by_human=False,
                replay_mode=False,
            )
            res = await run_assistant_loop_async(req)
            self.assertTrue(res.ok)

    async def test_assistant_loop_recovers_conversation_state_for_start_ack(self) -> None:
        root = Path(__file__).resolve().parents[1]
        skill_dir = root / "examples" / "skills" / "personal_assistant_brief"

        with tempfile.TemporaryDirectory(prefix="agentos_next_t045_conv_") as td:
            data_dir = Path(td) / "data"
            first_trace = TraceContext(trace_id="tr_conv_1", turn_id="turn_conv_1", span_id="span_conv_1")
            second_trace = TraceContext(trace_id="tr_conv_2", turn_id="turn_conv_2", span_id="span_conv_2")

            first_req = AssistantLoopRequest(
                query="请帮我写一封延期邮件",
                assistant_skill_dir=skill_dir,
                workspace_id="ws_qg",
                data_dir=data_dir,
                trace=first_trace,
                idempotency_key="idem_conv_1",
                deadline_ms=8000,
                verify_asvp=False,
                public_keys_dir=None,
                backend="local_mock",
                planner="model_owned",
                model=None,
                remote_calls_armed=False,
                allow_network_egress=False,
                approved_by_human=False,
                replay_mode=False,
                conversation_id="chat_123",
            )
            first_res = await run_assistant_loop_async(first_req)
            self.assertTrue(first_res.ok)

            second_req = AssistantLoopRequest(
                query="开始",
                assistant_skill_dir=skill_dir,
                workspace_id="ws_qg",
                data_dir=data_dir,
                trace=second_trace,
                idempotency_key="idem_conv_2",
                deadline_ms=8000,
                verify_asvp=False,
                public_keys_dir=None,
                backend="local_mock",
                planner="model_owned",
                model=None,
                remote_calls_armed=False,
                allow_network_egress=False,
                approved_by_human=False,
                replay_mode=False,
                conversation_id="chat_123",
            )
            second_res = await run_assistant_loop_async(second_req)
            self.assertTrue(second_res.ok)

            evidence = FileEvidenceStore(data_dir=data_dir)
            recovered_objective = ""
            recovered_option = ""
            for ref in second_res.evidence_refs:
                blob = evidence.get_blob(ref)
                if blob is None or blob.content_type != "application/json":
                    continue
                try:
                    obj = json.loads(blob.content.decode("utf-8"))
                except Exception:
                    continue
                if isinstance(obj, dict) and obj.get("type") == "query_gated_query_v1":
                    recovered_objective = str(obj.get("objective") or "")
                    recovered_option = str((obj.get("intent_recovery") or {}).get("intent_option") or "")
                    break
            self.assertEqual(recovered_option, "ACK_EXECUTE")
            self.assertIn("请帮我写一封延期邮件", recovered_objective)

            trace_path = data_dir / "traces" / f"{second_trace.trace_id}.jsonl"
            events = [json.loads(ln) for ln in trace_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
            delivery_events = [
                ev for ev in events
                if ev.get("event_type") == "DIALOG_EVENT"
                and isinstance(ev.get("data"), dict)
                and ev["data"].get("dialog_event_type") == "DELIVERY_STATE"
            ]
            states = [str(ev["data"].get("state")) for ev in delivery_events]
            self.assertIn("ack", states)
            self.assertIn("progress", states)
            self.assertEqual(states[-1], "done")

    async def test_assistant_loop_plans_inspect_first_for_workspace_analysis(self) -> None:
        root = Path(__file__).resolve().parents[1]
        skill_dir = root / "examples" / "skills" / "personal_assistant_brief"
        phase_outputs = {
            "intent_router": {"status": "done"},
            "planner": {
                "status": "continue",
                "worker_tasks": [
                    _worker_task(
                        worker_task_id="worker_workspace_scan",
                        objective="先列目录再确认当前工作目录",
                        allowed_operator_refs=["builtin://fs.list", "builtin://shell.exec"],
                        scope_summary="Inspect the current workspace root only",
                    )
                ],
            },
            "executor": _worker_executor_from_batches(
                {
                    "worker_workspace_scan": [
                        [
                            {
                                "action_id": "inspect_root",
                                "operator_ref": "builtin://fs.list",
                                "arguments": {"path": "."},
                            }
                        ],
                        [
                            {
                                "action_id": "inspect_pwd",
                                "operator_ref": "builtin://shell.exec",
                                "arguments": {"command": "pwd", "cwd": "."},
                                "depends_on": ["inspect_root"],
                            }
                        ],
                    ]
                }
            ),
            "verifier_replanner": {"status": "done"},
            "communicator": {
                "status": "done",
                "actions": [
                    {
                        "action_id": "final_message",
                        "operator_ref": "builtin://channel.send_message",
                        "arguments": {"text": "已完成 workspace 初步勘察。"},
                    }
                ],
            },
        }

        with tempfile.TemporaryDirectory(prefix="agentos_next_t045_inspect_") as td:
            data_dir = Path(td) / "data"
            trace = TraceContext(trace_id="tr_qg_inspect", turn_id="turn_qg_inspect", span_id="span_qg_inspect")
            req = AssistantLoopRequest(
                query="分析这个项目并给出架构建议",
                assistant_skill_dir=skill_dir,
                workspace_id="ws_qg",
                data_dir=data_dir,
                trace=trace,
                idempotency_key="idem_qg_inspect",
                deadline_ms=12000,
                verify_asvp=False,
                public_keys_dir=None,
                backend="local_mock",
                planner="model_owned",
                model=None,
                remote_calls_armed=False,
                allow_network_egress=False,
                approved_by_human=False,
                replay_mode=False,
                capabilities="fs_read,shell_exec",
            )
            with patch.object(PackageRunner, "_pick_backend", new=_phase_backend_picker(phase_outputs)):
                res = await run_assistant_loop_async(req)
            self.assertTrue(res.ok, msg=f"error_code={res.error_code}")

            evidence = FileEvidenceStore(data_dir=data_dir)
            planned_steps: list[str] = []
            query_mode = ""
            for ref in res.evidence_refs:
                blob = evidence.get_blob(ref)
                if blob is None or blob.content_type != "application/json":
                    continue
                try:
                    obj = json.loads(blob.content.decode("utf-8"))
                except Exception:
                    continue
                if isinstance(obj, dict) and obj.get("type") == "worker_task_graph_v1":
                    query_mode = str(obj.get("query_mode") or "")
                    planned_steps = [
                        str(operator_ref or "")
                        for step in (obj.get("worker_tasks") or [])
                        if isinstance(step, dict)
                        for operator_ref in (step.get("allowed_operator_refs") or [])
                    ]
                    break

            self.assertNotEqual(query_mode, "simple")
            self.assertGreaterEqual(len(planned_steps), 2)
            self.assertEqual(planned_steps[0], "builtin://fs.list")
            self.assertIn("builtin://shell.exec", planned_steps)

    async def test_assistant_loop_preserves_pending_contract_for_low_specificity_followup(self) -> None:
        root = Path(__file__).resolve().parents[1]
        skill_dir = root / "examples" / "skills" / "personal_assistant_brief"
        phase_outputs = {
            "intent_router": {"status": "done"},
            "planner": {
                "status": "continue",
                "worker_tasks": [
                    _worker_task(
                        worker_task_id="worker_workspace_scan",
                        objective="恢复上下文后重新检查当前 workspace",
                        allowed_operator_refs=["builtin://fs.list", "builtin://shell.exec"],
                        scope_summary="Inspect the current workspace root only",
                    )
                ],
            },
            "executor": _worker_executor_from_batches(
                {
                    "worker_workspace_scan": [
                        [
                            {
                                "action_id": "inspect_root",
                                "operator_ref": "builtin://fs.list",
                                "arguments": {"path": "."},
                            }
                        ],
                        [
                            {
                                "action_id": "inspect_pwd",
                                "operator_ref": "builtin://shell.exec",
                                "arguments": {"command": "pwd", "cwd": "."},
                                "depends_on": ["inspect_root"],
                            }
                        ],
                    ]
                }
            ),
            "verifier_replanner": {"status": "done"},
            "communicator": {
                "status": "done",
                "actions": [
                    {
                        "action_id": "final_message",
                        "operator_ref": "builtin://channel.send_message",
                        "arguments": {"text": "已恢复上下文并继续执行。"},
                    }
                ],
            },
        }

        with tempfile.TemporaryDirectory(prefix="agentos_next_t045_followup_bind_") as td:
            data_dir = Path(td) / "data"
            conversation_store = FileConversationStateStore(data_dir=data_dir)
            conversation_store.put(
                workspace_id="ws_qg",
                conversation_id="chat_followup",
                last_pending_task="把你前面对agentos项目的建议落到文件吧",
                expected_next_user_act="followup_or_new_task",
                last_delivery_state="done",
                last_delivery_summary="delivery verified successfully",
                pending_contract={
                    "schema_version": "1.0.0",
                    "type": "continuation_contract_v1",
                    "objective": "把你前面对agentos项目的建议落到文件吧",
                    "intent_option": "DIRECT_TASK",
                    "interaction_mode": "task",
                    "delivery_kind": "workspace_analysis",
                    "requires_workspace_observation": True,
                    "requires_external_evidence": False,
                },
            )
            trace = TraceContext(
                trace_id="tr_qg_followup_bind_loop",
                turn_id="turn_qg_followup_bind_loop",
                span_id="span_qg_followup_bind_loop",
            )
            req = AssistantLoopRequest(
                query="你现在想起来了吗",
                assistant_skill_dir=skill_dir,
                workspace_id="ws_qg",
                data_dir=data_dir,
                trace=trace,
                idempotency_key="idem_qg_followup_bind_loop",
                deadline_ms=12000,
                verify_asvp=False,
                public_keys_dir=None,
                backend="local_mock",
                planner="model_owned",
                model=None,
                remote_calls_armed=False,
                allow_network_egress=False,
                approved_by_human=False,
                replay_mode=False,
                capabilities="fs_read,shell_exec",
                conversation_id="chat_followup",
            )
            with patch.object(PackageRunner, "_pick_backend", new=_phase_backend_picker(phase_outputs)):
                res = await run_assistant_loop_async(req)
            self.assertTrue(res.ok, msg=f"error_code={res.error_code}")

            evidence = FileEvidenceStore(data_dir=data_dir)
            planned_steps: list[str] = []
            resolved_objective = ""
            for ref in res.evidence_refs:
                blob = evidence.get_blob(ref)
                if blob is None or blob.content_type != "application/json":
                    continue
                obj = json.loads(blob.content.decode("utf-8"))
                if isinstance(obj, dict) and obj.get("type") == "query_gated_query_v1":
                    resolved_objective = str(obj.get("objective") or "")
                if isinstance(obj, dict) and obj.get("type") == "worker_task_graph_v1":
                    planned_steps = [
                        str(operator_ref or "")
                        for step in (obj.get("worker_tasks") or [])
                        if isinstance(step, dict)
                        for operator_ref in (step.get("allowed_operator_refs") or [])
                    ]
            self.assertEqual(resolved_objective, "把你前面对agentos项目的建议落到文件吧")
            self.assertGreaterEqual(len(planned_steps), 2)
            self.assertEqual(planned_steps[0], "builtin://fs.list")

            state = conversation_store.get(workspace_id="ws_qg", conversation_id="chat_followup")
            self.assertIsNotNone(state)
            self.assertEqual(state.last_pending_task, "把你前面对agentos项目的建议落到文件吧")  # type: ignore[union-attr]

    async def test_assistant_loop_input_debounce_updates_snapshot_for_retry(self) -> None:
        root = Path(__file__).resolve().parents[1]
        skill_dir = root / "examples" / "skills" / "personal_assistant_brief"

        with tempfile.TemporaryDirectory(prefix="agentos_next_t045_compile_block_") as td:
            data_dir = Path(td) / "data"
            FileRuntimeSnapshotStore(data_dir=data_dir).put(
                workspace_id="ws_qg",
                conversation_id="chat_compile_block",
                last_user_query="hello",
                last_user_query_at_utc="2026-03-07T12:34:56Z",
            )
            trace = TraceContext(trace_id="tr_qg_compile_block", turn_id="turn_qg_compile_block", span_id="span_qg_compile_block")
            req = AssistantLoopRequest(
                query="hello",
                assistant_skill_dir=skill_dir,
                workspace_id="ws_qg",
                data_dir=data_dir,
                trace=trace,
                idempotency_key="idem_qg_compile_block",
                deadline_ms=8000,
                verify_asvp=False,
                public_keys_dir=None,
                backend="local_mock",
                planner="model_owned",
                model=None,
                remote_calls_armed=False,
                allow_network_egress=False,
                approved_by_human=False,
                replay_mode=False,
                conversation_id="chat_compile_block",
                message_received_at_utc="2026-03-07T12:34:56.400000Z",
            )
            res = await run_assistant_loop_async(req)
            self.assertFalse(res.ok)
            self.assertEqual(res.error_code, "E_INPUT_DEBOUNCED")

            snapshot = FileConversationStateStore(data_dir=data_dir).get(
                workspace_id="ws_qg",
                conversation_id="chat_compile_block",
            )
            self.assertIsNotNone(snapshot)
            self.assertEqual(snapshot.last_delivery_state, "blocker")  # type: ignore[union-attr]
            self.assertEqual(snapshot.expected_next_user_act, "clarify_or_retry")  # type: ignore[union-attr]
            self.assertEqual((snapshot.pending_contract or {}).get("objective"), "hello")  # type: ignore[union-attr]
            self.assertEqual(snapshot.last_user_query, "hello")  # type: ignore[union-attr]

    async def test_assistant_runtime_records_canonical_task_ingress(self) -> None:
        root = Path(__file__).resolve().parents[1]
        skill_dir = root / "examples" / "skills" / "personal_assistant_brief"

        with tempfile.TemporaryDirectory(prefix="agentos_next_t045_ingress_") as td:
            data_dir = Path(td) / "data"
            trace = TraceContext(trace_id="tr_qg_ingress", turn_id="turn_qg_ingress", span_id="span_qg_ingress")
            req = AssistantLoopRequest(
                query="hello",
                assistant_skill_dir=skill_dir,
                workspace_id="ws_qg",
                data_dir=data_dir,
                trace=trace,
                idempotency_key="idem_qg_ingress",
                deadline_ms=8000,
                verify_asvp=False,
                public_keys_dir=None,
                backend="local_mock",
                planner="model_owned",
                model=None,
                remote_calls_armed=False,
                allow_network_egress=False,
                approved_by_human=False,
                replay_mode=False,
            )
            ingress = build_canonical_task_ingress_request(
                req,
                submitter="test.submitter",
                consumer="test.consumer",
                raw_input="hello",
                metadata={"source": "unit"},
            )
            res = await run_assistant_runtime_async(ingress, runtime_mode="direct")
            self.assertTrue(res.ok)

            evidence = FileEvidenceStore(data_dir=data_dir)
            found_ingress = None
            for ref in res.evidence_refs:
                blob = evidence.get_blob(ref)
                if blob is None or blob.content_type != "application/json":
                    continue
                obj = json.loads(blob.content.decode("utf-8"))
                if isinstance(obj, dict) and obj.get("type") == "canonical_task_ingress_v1":
                    found_ingress = obj
                    break
            self.assertIsNotNone(found_ingress)
            self.assertEqual(found_ingress["submitter"], "test.submitter")
            self.assertEqual(found_ingress["consumer"], "test.consumer")
            self.assertEqual(found_ingress["ingress_envelope"]["submitter_metadata"]["source"], "unit")

    async def test_followup_schedule_uses_canonical_runtime_submitter(self) -> None:
        root = Path(__file__).resolve().parents[1]
        skill_dir = root / "examples" / "skills" / "personal_assistant_brief"

        with tempfile.TemporaryDirectory(prefix="agentos_next_t045_followup_") as td:
            data_dir = Path(td) / "data"
            trace = TraceContext(trace_id="tr_qg_followup", turn_id="turn_qg_followup", span_id="span_qg_followup")
            req = AssistantLoopRequest(
                query="hello",
                assistant_skill_dir=skill_dir,
                workspace_id="ws_qg",
                data_dir=data_dir,
                trace=trace,
                idempotency_key="idem_qg_followup",
                deadline_ms=8000,
                verify_asvp=False,
                public_keys_dir=None,
                backend="local_mock",
                planner="model_owned",
                model=None,
                remote_calls_armed=False,
                allow_network_egress=False,
                approved_by_human=False,
                replay_mode=False,
                followup_at="2026-03-08T09:00:01Z",
            )
            res = await run_assistant_loop_async(req)
            self.assertTrue(res.ok)

            store = FileSchedulerStore(data_dir=data_dir)
            tasks = store.list_tasks()
            self.assertEqual(len(tasks), 1)
            draft = dict(tasks[0].execute_request or {})
            self.assertEqual(draft.get("operator_ref"), "builtin://assistant.submit")
            self.assertEqual(draft.get("arguments", {}).get("submitter"), "scheduler.followup")
            caps = draft.get("policy_context", {}).get("capabilities")
            self.assertEqual(caps, [{"name": "assistant_runtime_submit", "scope": "workspace"}])

    async def test_assistant_loop_writes_hypothesis_record(self) -> None:
        root = Path(__file__).resolve().parents[1]
        skill_dir = root / "examples" / "skills" / "personal_assistant_brief"

        with tempfile.TemporaryDirectory(prefix="agentos_next_t045_hyp_") as td:
            data_dir = Path(td) / "data"
            trace = TraceContext(trace_id="tr_qg_hyp", turn_id="turn_qg_hyp", span_id="span_qg_hyp")
            req = AssistantLoopRequest(
                query="hello",
                assistant_skill_dir=skill_dir,
                workspace_id="ws_qg",
                data_dir=data_dir,
                trace=trace,
                idempotency_key="idem_qg_hyp",
                deadline_ms=8000,
                verify_asvp=False,
                public_keys_dir=None,
                backend="local_mock",
                planner="model_owned",
                model=None,
                remote_calls_armed=False,
                allow_network_egress=False,
                approved_by_human=False,
                replay_mode=False,
                message_received_at_utc="2026-03-07T12:00:00Z",
            )
            await run_assistant_loop_async(req)

            store = FileHypothesisStore(data_dir=data_dir)
            records = store.list_recent(workspace_id="ws_qg", limit=3)
            self.assertGreaterEqual(len(records), 1)
            self.assertEqual(records[0].turn_id, "turn_qg_hyp")
            self.assertTrue(records[0].hypothesis.startswith("mode="))
            self.assertEqual(records[0].verification_action, "verify_assistant_execution")

    async def test_assistant_loop_defaults_message_received_time_when_missing(self) -> None:
        root = Path(__file__).resolve().parents[1]
        skill_dir = root / "examples" / "skills" / "personal_assistant_brief"

        with tempfile.TemporaryDirectory(prefix="agentos_next_t045_time_default_") as td:
            data_dir = Path(td) / "data"
            trace = TraceContext(trace_id="tr_qg_time_default", turn_id="turn_qg_time_default", span_id="span_qg_time_default")
            req = AssistantLoopRequest(
                query="告诉我今天上海天气",
                assistant_skill_dir=skill_dir,
                workspace_id="ws_qg",
                data_dir=data_dir,
                trace=trace,
                idempotency_key="idem_qg_time_default",
                deadline_ms=8000,
                verify_asvp=False,
                public_keys_dir=None,
                backend="local_mock",
                planner="model_owned",
                model=None,
                remote_calls_armed=False,
                allow_network_egress=False,
                approved_by_human=False,
                replay_mode=False,
                capabilities="web_search,web_browse",
            )
            res = await run_assistant_loop_async(req)

            self.assertTrue(bool(res.evidence_refs))
            evidence = FileEvidenceStore(data_dir=data_dir)
            query_obj = None
            for ref in res.evidence_refs:
                blob = evidence.get_blob(ref)
                if blob is None or blob.content_type != "application/json":
                    continue
                obj = json.loads(blob.content.decode("utf-8"))
                if isinstance(obj, dict) and obj.get("type") == "query_gated_query_v1":
                    query_obj = obj
                    break
            self.assertIsNotNone(query_obj)
            workspace_snapshot = dict((query_obj or {}).get("workspace_snapshot") or {})
            self.assertTrue(str(workspace_snapshot.get("message_received_at_utc") or "").strip())
            temporal_anchor = dict(workspace_snapshot.get("temporal_anchor") or {})
            self.assertTrue(str(temporal_anchor.get("anchor_time_utc") or "").strip())
            self.assertIn("today", dict(temporal_anchor.get("relative_dates") or {}))

    async def test_assistant_loop_loads_agent_specific_profile_and_emits_axiom_review_candidate(self) -> None:
        root = Path(__file__).resolve().parents[1]
        skill_dir = root / "examples" / "skills" / "personal_assistant_brief"

        with tempfile.TemporaryDirectory(prefix="agentos_next_t045_profile_") as td:
            data_dir = Path(td) / "data"
            store = FileAgentProfileStore(data_dir=data_dir)
            profile = build_default_agent_profile_v1(agent_id="assistant_loop")
            profile["agent_id"] = "custom_agent"
            profile["reality_constraints"] = profile["reality_constraints"] + [
                {
                    "id": f"RC_EXTRA_{i}",
                    "statement": f"extra constraint {i}",
                    "source_ref": "test",
                    "effective_at_utc": "2026-03-07T00:00:00Z",
                }
                for i in range(6)
            ]
            store.put(profile=profile)

            trace = TraceContext(trace_id="tr_qg_profile", turn_id="turn_qg_profile", span_id="span_qg_profile")
            req = AssistantLoopRequest(
                query="hello",
                assistant_skill_dir=skill_dir,
                workspace_id="ws_qg",
                data_dir=data_dir,
                trace=trace,
                idempotency_key="idem_qg_profile",
                deadline_ms=8000,
                verify_asvp=False,
                public_keys_dir=None,
                backend="local_mock",
                planner="model_owned",
                model=None,
                remote_calls_armed=False,
                allow_network_egress=False,
                approved_by_human=False,
                replay_mode=False,
                agent_id="custom_agent",
            )
            res = await run_assistant_loop_async(req)
            self.assertTrue(res.ok)

            evidence = FileEvidenceStore(data_dir=data_dir)
            found_query = False
            found_axiom_candidate = False
            for ref in res.evidence_refs:
                blob = evidence.get_blob(ref)
                if blob is None or blob.content_type != "application/json":
                    continue
                obj = json.loads(blob.content.decode("utf-8"))
                if isinstance(obj, dict) and obj.get("type") == "query_gated_query_v1":
                    found_query = True
                    self.assertEqual(obj["agent_profile"]["agent_id"], "custom_agent")
                if isinstance(obj, dict) and obj.get("type") == "axiom_review_candidate_v1":
                    found_axiom_candidate = True
                    self.assertEqual(obj.get("agent_id"), "custom_agent")
                    self.assertEqual(
                        obj.get("meta_axioms"),
                        [
                            "MAX1_EVERYTHING_IS_REVISABLE",
                            "MAX2_CONSTRAINT_PRESSURE_PRECEDES_AXIOM_REVISION",
                            "MAX3_PRESERVE_COHERENCE_DURING_REVISION",
                        ],
                    )
                    pressure = obj.get("pressure") or {}
                    self.assertIn("constraint_pressure", pressure.get("reason_codes") or [])
                    self.assertGreaterEqual(float(pressure.get("pressure_score") or 0.0), 1.0)
                    self.assertEqual(int(pressure.get("threshold_constraints") or 0), 8)
                    self.assertEqual(int(pressure.get("threshold_recent_failures") or 0), 3)
                    self.assertIn("conflict_count", pressure)
                    self.assertIn("cost_score", pressure)
                    self.assertIn("recommended_action", obj)
            self.assertTrue(found_query)
            self.assertTrue(found_axiom_candidate)
            cache_dir = data_dir / "context_plane_cache"
            self.assertTrue(cache_dir.exists())
            self.assertGreaterEqual(len(list(cache_dir.glob("*.json"))), 1)

    async def test_assistant_loop_emits_research_pack_and_observation_learning_candidates(self) -> None:
        root = Path(__file__).resolve().parents[1]
        skill_dir = root / "examples" / "skills" / "personal_assistant_brief"
        original_execute = LocalExecutor.execute
        phase_outputs = {
            "intent_router": {"status": "done"},
            "planner": {
                "status": "continue",
                "worker_tasks": [
                    _worker_task(
                        worker_task_id="worker_research_weather",
                        objective="搜索并浏览北京天气来源",
                        allowed_operator_refs=["builtin://web.search", "builtin://web.browse"],
                    )
                ],
            },
            "executor": _worker_executor_from_batches(
                {
                    "worker_research_weather": [
                        [
                            {
                                "action_id": "lookup_web",
                                "operator_ref": "builtin://web.search",
                                "arguments": {"query": "北京 天气 来源 比较"},
                            }
                        ],
                        [
                            {
                                "action_id": "browse_page",
                                "operator_ref": "builtin://web.browse",
                                "arguments": {"url": {"$from_action": "lookup_web", "path": ["results", 0, "url"]}},
                                "depends_on": ["lookup_web"],
                            }
                        ],
                    ]
                }
            ),
            "verifier_replanner": {"status": "done"},
            "communicator": {
                "status": "done",
                "actions": [
                    {
                        "action_id": "final_message",
                        "operator_ref": "builtin://channel.send_message",
                        "arguments": {
                            "text": "我查阅了来源并整理好了结论。",
                            "channel": "assistant_runtime",
                        },
                    }
                ],
            },
        }

        with tempfile.TemporaryDirectory(prefix="agentos_next_t045_research_pack_") as td:
            data_dir = Path(td) / "data"
            trace = TraceContext(trace_id="tr_qg_research_pack", turn_id="turn_qg_research_pack", span_id="span_qg_research_pack")

            async def _fake_execute(self, req):  # noqa: ANN001
                if str(req.operator_ref or "") == "builtin://web.search":
                    evidence = FileEvidenceStore(data_dir=data_dir)
                    out_ref = evidence.add_json(
                        {
                            "schema_version": "1.0.0",
                            "ok": True,
                            "provider_used": "duckduckgo_html",
                            "degraded": True,
                            "expectation_mismatch": True,
                            "results": [
                                {
                                    "title": "Beijing Weather Source",
                                    "url": "https://weather.example.com/beijing",
                                    "snippet": "Weather facts",
                                }
                            ],
                        },
                        kind="tool_io",
                    )
                    return ExecuteResult(
                        status="accepted",
                        evidence_refs=(out_ref,),
                        artifact_refs=(),
                        error_code=None,
                        timing=ExecuteTiming(started_at="2026-03-10T00:00:00Z", ended_at="2026-03-10T00:00:01Z"),
                        target="local",
                    )
                if str(req.operator_ref or "") == "builtin://web.browse":
                    evidence = FileEvidenceStore(data_dir=data_dir)
                    out_ref = evidence.add_json(
                        {
                            "schema_version": "1.0.0",
                            "ok": True,
                            "provider_used": "playwright",
                            "url": "https://weather.example.com/beijing",
                            "final_url": "https://weather.example.com/beijing",
                            "title": "Weather Example",
                            "output": {
                                "reply": "Weather Example says Beijing is sunny.",
                                "url": "https://weather.example.com/beijing",
                                "title": "Weather Example",
                            },
                        },
                        kind="tool_io",
                    )
                    return ExecuteResult(
                        status="accepted",
                        evidence_refs=(out_ref,),
                        artifact_refs=(),
                        error_code=None,
                        timing=ExecuteTiming(started_at="2026-03-10T00:00:01Z", ended_at="2026-03-10T00:00:02Z"),
                        target="local",
                    )
                return await original_execute(self, req)

            req = AssistantLoopRequest(
                query="调研并比较今天北京天气来源，给我一个带引用的结论",
                assistant_skill_dir=skill_dir,
                workspace_id="ws_qg",
                data_dir=data_dir,
                trace=trace,
                idempotency_key="idem_qg_research_pack",
                deadline_ms=8000,
                verify_asvp=False,
                public_keys_dir=None,
                backend="local_mock",
                planner="model_owned",
                model=None,
                remote_calls_armed=False,
                allow_network_egress=False,
                approved_by_human=False,
                replay_mode=False,
                capabilities="web_search,web_browse",
            )
            with patch.object(LocalExecutor, "execute", new=_fake_execute):
                with patch(
                    "agentos_next.llm.backend.LocalMockLLMBackend.complete_json",
                    new=_complete_json_from_phase_outputs(phase_outputs),
                ):
                    res = await run_assistant_loop_async(req)

            self.assertTrue(res.ok, msg=f"error_code={res.error_code}")
            evidence = FileEvidenceStore(data_dir=data_dir)
            found_research_pack = False
            found_strategy_candidate = False
            found_sop_candidate = False
            for ref in res.evidence_refs:
                blob = evidence.get_blob(ref)
                if blob is None or blob.content_type != "application/json":
                    continue
                obj = json.loads(blob.content.decode("utf-8"))
                if isinstance(obj, dict) and obj.get("type") == "research_evidence_pack_v1":
                    found_research_pack = True
                    self.assertTrue(obj.get("citation_required"))
                    self.assertEqual(len(obj.get("final_citation_set") or []), 1)
                if isinstance(obj, dict) and obj.get("type") == "observation_learning_candidate_v1":
                    if obj.get("candidate_kind") == "search_research_strategy_candidate":
                        found_strategy_candidate = True
                    if obj.get("candidate_kind") == "sop_candidate":
                        found_sop_candidate = True
            self.assertTrue(found_research_pack)
            self.assertTrue(found_strategy_candidate)
            self.assertTrue(found_sop_candidate)


if __name__ == "__main__":  # pragma: no cover
    unittest.main(verbosity=2)
