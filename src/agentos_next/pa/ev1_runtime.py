from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from agentos_next.kernel.executor import ExecuteRequest, ExecuteResult, ExecuteTiming
from agentos_next.kernel.orchestrator import Orchestrator
from agentos_next.kernel.agent_profile import FileAgentProfileStore, make_axiom_review_candidate
from agentos_next.kernel.context_plane_cache import FileContextPlaneCache
from agentos_next.kernel.hypothesis_store import FileHypothesisStore, HypothesisRecord
from agentos_next.kernel.types import TraceContext
from agentos_next.kernel.capabilities import capability_items_for_policy_context
from agentos_next.runtime.local_executor import LocalExecutor
from agentos_next.kernel.evidence_store import FileEvidenceStore
from agentos_next.kernel.memory_store import MemoryConsolidatorV2
from agentos_next.kernel.trace_logger import FileTraceLogger
from agentos_next.kernel.types import TraceEvent

from agentos_next.pa.event_envelope import envelope_to_dict, validate_envelope_v0
from agentos_next.pa.event_log import FileEventLog
from agentos_next.pa.outbox_store import FileOutboxStore, OutboxItem
from agentos_next.pa.metering import write_metering_evidence_v0
from agentos_next.pa.memory_pipeline import (
    PAMemoryPipelineConfig,
    build_memory_context_for_event,
)
from agentos_next.apps.query_gated_runtime import build_context_plane_pack_v1
from agentos_next.pa.task_graph import (
    FileTaskGraphStore,
    TaskGraph,
    TaskGraphError,
    TaskNode,
    TASK_GRAPH_ERROR_CYCLE_DETECTED,
    add_task,
    compute_task_fingerprint,
    recover_incomplete,
    set_task_state,
    TASK_GRAPH_SCHEMA_VERSION,
)
from agentos_next.pa.runtime_error_codes import (
    PA_RUNTIME_ERROR_CONTEXT_FAILED,
    PA_RUNTIME_ERROR_IO_FAILED,
    PA_RUNTIME_ERROR_REPLAY_DENY,
    PA_RUNTIME_ERROR_SCHEMA_INVALID,
)


PA_EV_ERROR_SCHEMA_INVALID = PA_RUNTIME_ERROR_SCHEMA_INVALID
PA_EV_ERROR_REPLAY_DENY = PA_RUNTIME_ERROR_REPLAY_DENY
PA_EV_ERROR_IO_FAILED = PA_RUNTIME_ERROR_IO_FAILED
PA_EV_ERROR_CONTEXT_FAILED = PA_RUNTIME_ERROR_CONTEXT_FAILED
PA_EV_ERROR_HYPOTHESIS_REPEAT = "E_HYPOTHESIS_REPEAT_WITHOUT_NEW_EVIDENCE"

_ACTION_SKILL_REF_ALIASES: dict[str, str] = {
    "fs_read": "builtin://fs.read",
    "fs_write": "builtin://fs.write",
    "fs_list": "builtin://fs.list",
    "fs.read": "builtin://fs.read",
    "fs.write": "builtin://fs.write",
    "fs.list": "builtin://fs.list",
    "shell_exec": "builtin://shell.exec",
    "shell.exec": "builtin://shell.exec",
    "memory_write": "builtin://memory.write",
    "memory_search": "builtin://memory.search",
    "memory_compact": "builtin://memory.compact",
    "memory_delete": "builtin://memory.delete",
    "memory.write": "builtin://memory.write",
    "memory.search": "builtin://memory.search",
    "memory.compact": "builtin://memory.compact",
    "memory.delete": "builtin://memory.delete",
    "web_search": "builtin://web.search",
    "web.search": "builtin://web.search",
    "web_browse": "builtin://web.browse",
    "web.browse": "builtin://web.browse",
    "creator_plan": "builtin://creator.plan",
    "creator.plan": "builtin://creator.plan",
    "skillcreator": "builtin://creator.plan",
    "skill_creator": "builtin://creator.plan",
    "channel_send_message": "builtin://channel.send_message",
    "channel.send_message": "builtin://channel.send_message",
    "scheduler_write": "builtin://scheduler.at",
    "scheduler.at": "builtin://scheduler.at",
    "scheduler.cron": "builtin://scheduler.cron",
}


@dataclass(frozen=True)
class EV1Config:
    data_dir: str | os.PathLike[str] = "data"
    operator_ref: str = ""
    skill_ref: str = ""
    # Map inbound message_text into ExecuteRequest.input using this key.
    # Default aligns with PAWebhookServiceConfig/PAPollingServiceConfig and
    # the default personal_assistant_brief skill (expects {"request": ...}).
    message_input_key: str = "request"
    # Task graph cycle threshold (same fingerprint repeated triggers block).
    task_cycle_threshold: int = 3
    verify_asvp: bool = False
    keys_dir: Optional[str] = None
    backend: str = "local_mock"
    model: Optional[str] = None
    remote_calls_armed: bool = False
    allow_network_egress: bool = False
    approved_by_human: bool = False
    preferred_target: str = "local"
    deadline_ms: int = 60000
    # Optional fixed capabilities for policy_context["capabilities"].
    # Use explicit names from THREAD-030 capability schema.
    capabilities: tuple[str, ...] = ()
    # Memory V2 context assembly
    memory_context_enabled: bool = False
    memory_context_retrieval_limit: int = 8
    memory_context_include_stale: bool = False
    memory_context_continuity_event_limit: int = 50
    memory_context_audit_mode: bool = False
    bot_token: Optional[str] = None
    agent_id: str = "pa_ev1"
    telegram_reply_adapter: Any = None

    @property
    def resolved_operator_ref(self) -> str:
        return str(self.operator_ref or self.skill_ref).strip()


@dataclass(frozen=True)
class _ReminderRequest:
    run_at_utc: str
    reminder_text: str
    delay_label: str


class EV1Runtime:
    """THREAD-033: Event-driven runtime (minimal).

    - Dedup key: event_id (short-circuit by outbox existence).
    - ExecuteRequest.idempotency_key: MUST be provided by envelope/adapter and passed through.
    - replay-mode: strict zero-write (deny).
    """

    def __init__(self, config: EV1Config) -> None:
        self._cfg = config
        self._data_dir = Path(config.data_dir)
        self._event_log_obj: FileEventLog | None = None
        self._outbox_obj: FileOutboxStore | None = None
        self._task_graph_obj: FileTaskGraphStore | None = None
        self._hypothesis_store_obj: FileHypothesisStore | None = None
        self._trace_log_obj: FileTraceLogger | None = None
        self._profile_store_obj: FileAgentProfileStore | None = None
        self._context_cache_obj: FileContextPlaneCache | None = None
        self._memory_consolidator_obj: MemoryConsolidatorV2 | None = None

    @property
    def _event_log(self) -> FileEventLog:
        if self._event_log_obj is None:
            self._event_log_obj = FileEventLog(self._data_dir)
        return self._event_log_obj

    @property
    def _outbox(self) -> FileOutboxStore:
        if self._outbox_obj is None:
            self._outbox_obj = FileOutboxStore(self._data_dir)
        return self._outbox_obj

    @property
    def _task_graph(self) -> FileTaskGraphStore:
        if self._task_graph_obj is None:
            self._task_graph_obj = FileTaskGraphStore(self._data_dir)
        return self._task_graph_obj

    @property
    def _hypothesis_store(self) -> FileHypothesisStore:
        if self._hypothesis_store_obj is None:
            self._hypothesis_store_obj = FileHypothesisStore(self._data_dir)
        return self._hypothesis_store_obj

    @property
    def _trace_log(self) -> FileTraceLogger:
        if self._trace_log_obj is None:
            self._trace_log_obj = FileTraceLogger(self._data_dir)
        return self._trace_log_obj

    @property
    def _profile_store(self) -> FileAgentProfileStore:
        if self._profile_store_obj is None:
            self._profile_store_obj = FileAgentProfileStore(self._data_dir)
        return self._profile_store_obj

    @property
    def _context_cache(self) -> FileContextPlaneCache:
        if self._context_cache_obj is None:
            self._context_cache_obj = FileContextPlaneCache(self._data_dir)
        return self._context_cache_obj

    @property
    def _memory_consolidator(self) -> MemoryConsolidatorV2:
        if self._memory_consolidator_obj is None:
            self._memory_consolidator_obj = MemoryConsolidatorV2(data_dir=self._data_dir)
        return self._memory_consolidator_obj

    def _build_task_hypothesis(self, *, task: TaskNode, task_input: dict[str, Any]) -> str:
        payload = json.dumps(dict(task_input or {}), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        payload_fp = hashlib.sha256(payload.encode("utf-8", errors="replace")).hexdigest()[:16]
        task_type = str(task.payload.get("type") or "task").strip() or "task"
        operator_ref = _task_payload_operator_ref(task.payload) or "missing"
        return f"type={task_type}; operator_ref={operator_ref}; arguments_fp={payload_fp}"

    def _collect_sibling_action_summaries(
        self,
        *,
        graph: TaskGraph,
        task: TaskNode,
        workspace_id: str,
        event_id: str,
        orch: Orchestrator,
    ) -> list[str]:
        summaries: list[str] = []
        if not hasattr(orch, "_idempotency_store") or orch._idempotency_store is None:
            return summaries
        evidence = FileEvidenceStore(data_dir=self._data_dir)
        for sibling in graph.tasks.values():
            if sibling.task_id == task.task_id:
                continue
            if sibling.parent_task_id != task.parent_task_id:
                continue
            if sibling.payload.get("type") != "action":
                continue
            if sibling.state not in ("succeeded", "failed"):
                continue
            cached = orch._idempotency_store.get(
                workspace_id=workspace_id,
                idempotency_key=f"tg_{event_id}_{sibling.task_id}",
            )
            if cached is None:
                continue
            operator_ref = _task_payload_operator_ref(sibling.payload) or "unknown"
            action_lines: list[str] = []
            for ref in cached.evidence_refs:
                if ref.kind not in ("tool_io", "llm_io", "error"):
                    continue
                blob = evidence.get_blob(ref.ref)
                if blob is None or blob.content_type != "application/json":
                    continue
                try:
                    obj = json.loads(blob.content.decode("utf-8"))
                except Exception:
                    continue
                if ref.kind == "error":
                    msg = str(obj.get("message") or obj.get("error_code") or "unknown error").strip()
                    if msg:
                        action_lines.append(f"status=failed; detail={msg}")
                    continue
                if "output" in obj:
                    action_lines.append(f"status=success; output={json.dumps(obj['output'], ensure_ascii=False)}")
                elif "results" in obj:
                    action_lines.append(f"status=success; output={json.dumps(obj['results'], ensure_ascii=False)}")
                else:
                    action_lines.append(f"status={'success' if sibling.state == 'succeeded' else sibling.state}; output={json.dumps(obj, ensure_ascii=False)}")
            if not action_lines:
                fallback = "status=failed; detail=no stable evidence found" if sibling.state == "failed" else f"status={sibling.state}"
                action_lines.append(fallback)
            summaries.append(f"Action {operator_ref}\n" + "\n".join(action_lines))
        return summaries

    def _augment_reasoning_request(
        self,
        *,
        base_request: str,
        sibling_summaries: list[str],
        recent_failures: list[str],
        aggregate: bool,
    ) -> str:
        request = str(base_request or "")
        if sibling_summaries:
            request += "\n\nTool execution audit:\n" + "\n\n".join(sibling_summaries)
        if recent_failures:
            request += (
                "\n\nRecent failed hypotheses to avoid repeating without new evidence:\n- "
                + "\n- ".join(recent_failures[:3])
            )
        if aggregate:
            request += (
                "\n\nReturn a final answer for the user now."
                " You MUST explicitly report relevant tool successes and tool failures."
                " If a failure indicates missing path, wrong workspace, missing file, or missing user input,"
                " tell the user exactly which tool failed and ask for the minimum correction needed."
                " Do not hide failed steps."
                " Do not emit further actions."
            )
        return request

    def _maybe_start_telegram_stream(self, *, env: dict[str, Any]) -> Any:
        adapter = self._cfg.telegram_reply_adapter
        if adapter is None:
            return None
        if str(env.get("source") or "").strip() != "telegram":
            return None
        if str(self._cfg.backend or "").strip().lower() != "codex_oauth":
            return None
        chat_id = str(env.get("conversation_id") or "").strip()
        if not chat_id:
            return None
        try:
            return adapter.start_stream_session(chat_id)
        except Exception:
            return None

    def _maybe_start_telegram_typing(self, *, env: dict[str, Any]) -> Any:
        adapter = self._cfg.telegram_reply_adapter
        if adapter is None:
            return None
        if str(env.get("source") or "").strip() != "telegram":
            return None
        chat_id = str(env.get("conversation_id") or "").strip()
        if not chat_id:
            return None
        try:
            return adapter.start_typing_session(chat_id)
        except Exception:
            return None

    @staticmethod
    def _stream_progress(stream_session: Any, text: str) -> None:
        if stream_session is None:
            return
        try:
            stream_session.update_progress(str(text))
        except Exception:
            return

    @staticmethod
    def _describe_ready_batch(tasks: list[TaskNode]) -> str:
        if not tasks:
            return "正在处理..."
        labels: list[str] = []
        for task in tasks[:3]:
            task_type = str(task.payload.get("type") or "").strip()
            operator_ref = _task_payload_operator_ref(task.payload)
            if task_type == "aggregate_reasoning":
                labels.append("正在整理结果...")
            elif task_type == "reasoning":
                labels.append("正在思考下一步...")
            elif operator_ref:
                labels.append(f"正在执行 {operator_ref}...")
        if not labels:
            return "正在处理中..."
        if len(tasks) > 1:
            return "；".join(labels) + f"（并行 {len(tasks)} 个任务）"
        return labels[0]

    def _recent_hypothesis_texts(self, *, workspace_id: str, result: str, limit: int = 5) -> list[str]:
        records = self._hypothesis_store.list_recent(workspace_id=workspace_id, limit=limit, result=result)  # type: ignore[arg-type]
        if result == "confirmed":
            return [str(rec.revision or rec.hypothesis).strip() for rec in records if str(rec.revision or rec.hypothesis).strip()]
        return [str(rec.hypothesis).strip() for rec in records if str(rec.hypothesis).strip()]

    def _build_runtime_context_planes(
        self,
        *,
        workspace_id: str,
        trace: TraceContext,
        query_text: str,
        message_received_at_utc: str | None,
        execution_evidence_refs: list[str] | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any] | None]:
        agent_profile = self._profile_store.get_or_default(agent_id=str(self._cfg.agent_id or "pa_ev1"))
        execution_axiom_ids = [
            str(x.get("id") or "").strip()
            for x in agent_profile.get("execution_axioms", agent_profile.get("axioms", []))
            if isinstance(x, dict)
        ]
        communication_axiom_ids = [
            str(x.get("id") or "").strip()
            for x in agent_profile.get("communication_axioms", [])
            if isinstance(x, dict)
        ]
        active_constraint_ids = [
            str(x.get("id") or "").strip() for x in agent_profile.get("reality_constraints", []) if isinstance(x, dict)
        ]
        recent_failures = self._recent_hypothesis_texts(workspace_id=workspace_id, result="rejected")
        recent_success = self._recent_hypothesis_texts(workspace_id=workspace_id, result="confirmed")
        cached_base = self._context_cache.get_base_pack(
            agent_id=str(self._cfg.agent_id or "pa_ev1"),
            workspace_id=workspace_id,
            execution_axiom_ids=execution_axiom_ids,
            communication_axiom_ids=communication_axiom_ids,
            constraint_ids=active_constraint_ids,
            soul_profile_id=str(agent_profile.get("soul_profile_id") or "").strip() or None,
            recent_failures=recent_failures,
            recent_success_patterns=recent_success,
        )
        fresh = build_context_plane_pack_v1(
            query_text=query_text,
            workspace_id=workspace_id,
            trace=trace,
            execution_axiom_ids=execution_axiom_ids,
            communication_axiom_ids=communication_axiom_ids,
            active_constraint_ids=active_constraint_ids,
            recent_failures=recent_failures,
            recent_success_patterns=recent_success,
            soul_profile_id=str(agent_profile.get("soul_profile_id") or "").strip() or None,
            message_received_at_utc=message_received_at_utc,
            execution_evidence_refs=execution_evidence_refs or [],
        )
        if cached_base is None:
            self._context_cache.put_base_pack(
                agent_id=str(self._cfg.agent_id or "pa_ev1"),
                workspace_id=workspace_id,
                execution_axiom_ids=execution_axiom_ids,
                communication_axiom_ids=communication_axiom_ids,
                constraint_ids=active_constraint_ids,
                soul_profile_id=str(agent_profile.get("soul_profile_id") or "").strip() or None,
                recent_failures=recent_failures,
                recent_success_patterns=recent_success,
                base_pack={
                    "communication_plane": dict(fresh["communication_plane"]),
                    "retrospective_plane": dict(fresh["retrospective_plane"]),
                    "constraint_plane": dict(fresh["constraint_plane"]),
                },
            )
            context_planes = fresh
        else:
            context_planes = {
                "execution_plane": dict(fresh["execution_plane"]),
                "communication_plane": dict(cached_base.get("communication_plane") or {}),
                "retrospective_plane": dict(cached_base.get("retrospective_plane") or {}),
                "constraint_plane": dict(cached_base.get("constraint_plane") or {}),
            }
        return agent_profile, context_planes, make_axiom_review_candidate(
            agent_profile=agent_profile,
            context_planes=context_planes,
        )

    def _has_recent_rejected_hypothesis(self, *, workspace_id: str, hypothesis: str) -> bool:
        recent = self._hypothesis_store.list_recent(workspace_id=workspace_id, limit=12, result="rejected")
        target = str(hypothesis or "").strip()
        if not target:
            return False
        for rec in recent:
            if str(rec.hypothesis or "").strip() == target:
                return True
        return False

    def _write_hypothesis_record(
        self,
        *,
        workspace_id: str,
        turn_id: str,
        iteration: int,
        hypothesis: str,
        verification_action: str,
        verification_evidence_refs: tuple[str, ...],
        result: str,
        revision: str,
    ) -> None:
        if not hypothesis:
            return
        record = HypothesisRecord(
            schema_version="1.0.0",
            turn_id=str(turn_id),
            iteration=max(1, int(iteration)),
            hypothesis=str(hypothesis),
            verification_action=str(verification_action),
            verification_evidence_refs=tuple(str(x) for x in verification_evidence_refs if str(x).strip()),
            result=str(result) if str(result) in {"confirmed", "rejected", "partial"} else "partial",  # type: ignore[arg-type]
            revision=str(revision or ""),
        )
        self._hypothesis_store.put_if_absent(workspace_id=str(workspace_id), record=record)

    def _emit_capability_resolution_evidence(
        self,
        *,
        workspace_id: str,
        event_id: str,
        parent_task_id: str,
        action_skill_refs: tuple[str, ...],
    ) -> None:
        refs = tuple(str(x).strip() for x in action_skill_refs if str(x).strip())
        if not refs:
            return
        non_builtin = [x for x in refs if not x.startswith("builtin://")]
        selected_strategy = "skill" if non_builtin else "tool_composition"
        evidence = FileEvidenceStore(data_dir=self._data_dir)
        ev_ref = evidence.add_json(
            {
                "schema_version": "1.0.0",
                "type": "capability_resolution_decision_v1",
                "canonical_type": "operator_resolution_decision_v1",
                "workspace_id": str(workspace_id),
                "event_id": str(event_id),
                "parent_task_id": str(parent_task_id),
                "policy": "skill_first",
                "operator_resolution_policy": "skill_first",
                "selected_strategy": selected_strategy,
                "action_skill_refs": list(refs),
            },
            kind="routing",
        )
        ctx = TraceContext(
            trace_id=f"tr_pa_{event_id}",
            turn_id=f"turn_pa_{event_id}",
            span_id=f"span_pa_{event_id}_capres_{parent_task_id}",
            parent_span_id=f"span_pa_{event_id}",
        )
        self._trace_log.emit(
            TraceEvent(
                schema_version="1.0.0",
                ctx=ctx,
                event_type="ROUTED",
                ts=_utc_iso(),
                evidence_refs=(ev_ref,),
                data={
                    "component": "pa_ev1",
                    "policy": "skill_first",
                    "selected_strategy": selected_strategy,
                },
            )
        )

    def _make_hypothesis_repeat_result(
        self,
        *,
        workspace_id: str,
        trace_context: TraceContext,
        hypothesis: str,
    ) -> ExecuteResult:
        evidence = FileEvidenceStore(data_dir=self._data_dir)
        err_ref = evidence.add_json(
            {
                "schema_version": "1.0.0",
                "error_code": PA_EV_ERROR_HYPOTHESIS_REPEAT,
                "message": "rejected hypothesis repeated without new evidence",
                "hypothesis": str(hypothesis),
            },
            kind="error",
        )
        self._trace_log.emit(
            TraceEvent(
                schema_version="1.0.0",
                ctx=trace_context,
                event_type="ERROR",
                ts=_utc_iso(),
                evidence_refs=(err_ref,),
                data={
                    "component": "pa_ev1",
                    "error_code": PA_EV_ERROR_HYPOTHESIS_REPEAT,
                },
            )
        )
        now = _utc_iso()
        return ExecuteResult(
            status="rejected",
            evidence_refs=(err_ref,),
            artifact_refs=(),
            error_code=PA_EV_ERROR_HYPOTHESIS_REPEAT,
            timing=ExecuteTiming(started_at=now, ended_at=now),
            target="local",
        )

    def _extract_scheduler_task_info(self, *, res: ExecuteResult) -> tuple[Optional[str], Optional[str]]:
        evidence = FileEvidenceStore(data_dir=self._data_dir)
        for er in reversed(tuple(res.evidence_refs)):
            if er.kind != "tool_io":
                continue
            blob = evidence.get_blob(er.ref)
            if blob is None or blob.content_type != "application/json":
                continue
            try:
                obj = json.loads(blob.content.decode("utf-8", errors="replace"))
            except Exception:
                continue
            if not isinstance(obj, dict):
                continue
            task_id = obj.get("task_id")
            next_run_at = obj.get("next_run_at")
            if isinstance(task_id, str) and task_id.strip():
                return task_id.strip(), str(next_run_at) if isinstance(next_run_at, str) else None
        return None, None

    def _parse_reminder_request(self, *, message_text: str) -> Optional[_ReminderRequest]:
        text = " ".join(str(message_text or "").split())
        if not text:
            return None

        def _mk_from_delta(*, seconds: int, body: str, label: str) -> Optional[_ReminderRequest]:
            if seconds <= 0:
                return None
            reminder_body = _clean_reminder_body(body)
            if not reminder_body:
                reminder_body = "查看你之前设置的事项"
            run_at = datetime.now(timezone.utc) + timedelta(seconds=seconds)
            return _ReminderRequest(
                run_at_utc=run_at.isoformat().replace("+00:00", "Z"),
                reminder_text=reminder_body,
                delay_label=label,
            )

        pat_min_1 = re.search(
            r"(?P<num>\d{1,4})\s*(分钟|分)\s*后(?:提醒我?|提醒)?(?P<body>.*)",
            text,
            flags=re.IGNORECASE,
        )
        if pat_min_1 is not None:
            num = int(pat_min_1.group("num") or "0")
            out = _mk_from_delta(seconds=num * 60, body=str(pat_min_1.group("body") or ""), label=f"{num} 分钟")
            if out is not None:
                return out

        pat_min_2 = re.search(
            r"提醒我?(?P<num>\d{1,4})\s*(分钟|分)\s*后(?P<body>.*)",
            text,
            flags=re.IGNORECASE,
        )
        if pat_min_2 is not None:
            num = int(pat_min_2.group("num") or "0")
            out = _mk_from_delta(seconds=num * 60, body=str(pat_min_2.group("body") or ""), label=f"{num} 分钟")
            if out is not None:
                return out

        pat_hour_1 = re.search(
            r"(?P<num>\d{1,4})\s*(小时|h)\s*后(?:提醒我?|提醒)?(?P<body>.*)",
            text,
            flags=re.IGNORECASE,
        )
        if pat_hour_1 is not None:
            num = int(pat_hour_1.group("num") or "0")
            out = _mk_from_delta(seconds=num * 3600, body=str(pat_hour_1.group("body") or ""), label=f"{num} 小时")
            if out is not None:
                return out

        pat_hour_2 = re.search(
            r"提醒我?(?P<num>\d{1,4})\s*(小时|h)\s*后(?P<body>.*)",
            text,
            flags=re.IGNORECASE,
        )
        if pat_hour_2 is not None:
            num = int(pat_hour_2.group("num") or "0")
            out = _mk_from_delta(seconds=num * 3600, body=str(pat_hour_2.group("body") or ""), label=f"{num} 小时")
            if out is not None:
                return out
        return None

    def _maybe_schedule_reminder_fallback(
        self,
        *,
        event_id: str,
        workspace_id: str,
        message_text: str,
        chat_id: str,
        trace: TraceContext,
        orch: Orchestrator,
    ) -> tuple[Optional[str], tuple[str, ...]]:
        reminder = self._parse_reminder_request(message_text=message_text)
        if reminder is None:
            return None, ()
        if not str(chat_id or "").strip():
            return "我识别到你在设置提醒，但未获取到 chat_id，提醒未创建。", ()
        sched_trace = TraceContext(
            trace_id=trace.trace_id,
            turn_id=trace.turn_id,
            span_id=f"{trace.span_id}_reminder_sched",
            parent_span_id=trace.span_id,
        )
        sched_req = ExecuteRequest(
            workspace_id=workspace_id,
            operator_ref="builtin://scheduler.at",
            arguments={
                "schema_version": "1.0.0",
                "run_at": reminder.run_at_utc,
                "execute_request": {
                    "operator_ref": "builtin://channel.send_message",
                    "arguments": {
                        "text": f"提醒你：{reminder.reminder_text}",
                        "audience": "user",
                        "delivery_stage": "final",
                        "update_preference": "new_message",
                        "metadata": {
                            "source": "scheduler.reminder",
                            "channel": "telegram",
                            "conversation_id": str(chat_id),
                        },
                    },
                    "deadline_ms": 15000,
                    "policy_context": {
                        "capabilities": capability_items_for_policy_context(["channel_send"]),
                    },
                    "preferred_target": "local",
                },
                "idempotency_root": f"sched:ev1:{event_id}:reminder",
            },
            idempotency_key=f"sched_{event_id}_reminder",
            deadline_ms=15000,
            trace=sched_trace,
            policy_context={
                "replay_mode": False,
                "capabilities": capability_items_for_policy_context(["scheduler_write"]),
            },
            preferred_target="local",
            budget_slice=0,
        )
        sched_res: ExecuteResult = _run_async(orch.execute(sched_req))
        refs = tuple(er.ref for er in sched_res.evidence_refs)
        if sched_res.status != "accepted":
            return f"提醒创建失败（{sched_res.error_code or 'E_EXECUTION_FAILED'}）。请再试一次。", refs
        task_id, _next_run = self._extract_scheduler_task_info(res=sched_res)
        if task_id:
            return f"已设置提醒：{reminder.delay_label}后提醒你{reminder.reminder_text}。", refs
        return "已创建提醒任务，但未读取到任务编号。", refs

    def handle_envelope(self, envelope: Any, *, replay_mode: bool = False) -> dict[str, Any]:
        # Strict replay: no filesystem writes, no execution.
        if replay_mode:
            return {"ok": False, "error_code": PA_EV_ERROR_REPLAY_DENY}

        env = envelope_to_dict(envelope)
        ok, _reason = validate_envelope_v0(env)
        if not ok:
            return {"ok": False, "error_code": PA_EV_ERROR_SCHEMA_INVALID}

        workspace_id = str(env["workspace_id"])
        event_id = str(env["event_id"])

        # Dedup short-circuit: return the previously stored outbox result.
        existing = self._outbox.get(workspace_id=workspace_id, event_id=event_id)
        if existing is not None:
            return {"ok": True, "outbox": existing.to_json(), "dedup": True}

        # Write event record (write-once). If exists concurrently, fall back to outbox read.
        try:
            self._event_log.write_once(workspace_id=workspace_id, event_id=event_id, envelope=env)
        except FileExistsError:
            existing2 = self._outbox.get(workspace_id=workspace_id, event_id=event_id)
            if existing2 is not None:
                return {"ok": True, "outbox": existing2.to_json(), "dedup": True}
        except Exception:
            return {"ok": False, "error_code": PA_EV_ERROR_IO_FAILED}

        # Task graph: root node captures the "execute this event" step. Recover running->queued first.
        try:
            root_fp = compute_task_fingerprint(
                kind="ev1_root",
                payload={
                    "schema_version": TASK_GRAPH_SCHEMA_VERSION,
                    "operator_ref": str(self._cfg.resolved_operator_ref),
                    "event_id": event_id,
                },
            )
            tg = self._task_graph.load_or_create(
                workspace_id=workspace_id,
                graph_id=event_id,
                root_fingerprint=root_fp,
                root_payload={"type": "ev1_root", "event_id": event_id},
                cycle_threshold=int(self._cfg.task_cycle_threshold),
                replay_mode=False,
            )
            tg = recover_incomplete(tg)
            # Mark root running before executing (recoverable state).
            tg = set_task_state(graph=tg, task_id=tg.root_task_id, state="running")
            self._task_graph.save(graph=tg, replay_mode=False)
        except TaskGraphError as e:
            # Fail-closed: do not execute if we cannot persist task graph state.
            return {"ok": False, "error_code": str(e.error_code or PA_EV_ERROR_IO_FAILED)}
        except Exception:
            return {"ok": False, "error_code": PA_EV_ERROR_IO_FAILED}

        # Execute via kernel Orchestrator.
        try:
            trace = TraceContext(
                trace_id=f"tr_pa_{event_id}",
                turn_id=f"turn_pa_{event_id}",
                span_id=f"span_pa_{event_id}",
            )
            agent_profile, context_planes, axiom_review_candidate = self._build_runtime_context_planes(
                workspace_id=workspace_id,
                trace=trace,
                query_text=str(env["message_text"]),
                message_received_at_utc=str(env.get("received_at_utc") or "").strip() or None,
            )
            policy_context: dict[str, Any] = {
                "verify_asvp": bool(self._cfg.verify_asvp),
                "public_keys_dir": self._cfg.keys_dir,
                "backend": str(self._cfg.backend),
                "model": self._cfg.model,
                "remote_calls_armed": bool(self._cfg.remote_calls_armed),
                "allow_network_egress": bool(self._cfg.allow_network_egress),
                "approved_by_human": bool(self._cfg.approved_by_human),
                "replay_mode": False,
                "agent_profile": agent_profile,
                "context_planes": context_planes,
                "workspace_root": str(Path.cwd().resolve()),
            }
            typing_session = self._maybe_start_telegram_typing(env=env)
            stream_session = self._maybe_start_telegram_stream(env=env)
            if stream_session is not None:
                policy_context["llm_stream_callback"] = stream_session.handle_event
                policy_context["telegram_stream_session"] = stream_session
                self._stream_progress(stream_session, "正在分析请求...")
            # Forward-compatible passthrough (policy-only). Must not grant privileges by itself.
            passthrough = env.get("policy_context_passthrough")
            if isinstance(passthrough, dict):
                policy_context.update(dict(passthrough))
            configured_caps = tuple(
                str(name).strip() for name in tuple(self._cfg.capabilities) if str(name).strip()
            )
            if configured_caps:
                policy_context["capabilities"] = capability_items_for_policy_context(
                    sorted(set(configured_caps))
                )
            context_evidence_refs: tuple[str, ...] = ()
            user_request_text = str(env["message_text"])
            if bool(self._cfg.memory_context_enabled):
                mem_cfg = PAMemoryPipelineConfig(
                    enabled=True,
                    retrieval_limit=int(self._cfg.memory_context_retrieval_limit),
                    include_stale=bool(self._cfg.memory_context_include_stale),
                    continuity_event_limit=int(self._cfg.memory_context_continuity_event_limit),
                    audit_mode=bool(self._cfg.memory_context_audit_mode),
                )
                mem_out = build_memory_context_for_event(
                    config=mem_cfg,
                    data_dir=self._data_dir,
                    workspace_id=workspace_id,
                    conversation_id=str(env.get("conversation_id") or ""),
                    trace_id=trace.trace_id,
                    turn_id=trace.turn_id,
                    user_message=str(env["message_text"]),
                    project_id=str(env.get("project_id") or "").strip() or None,
                    policy_context_passthrough=policy_context,
                    replay_mode=False,
                )
                if not mem_out.ok:
                    return {
                        "ok": False,
                        "error_code": PA_EV_ERROR_CONTEXT_FAILED,
                        "context_error_code": mem_out.error_code,
                    }
                if mem_out.memory_context is not None:
                    policy_context["memory_context"] = mem_out.memory_context
                context_evidence_refs = tuple(mem_out.evidence_refs)
            if axiom_review_candidate is not None:
                review_ref = FileEvidenceStore(data_dir=str(self._data_dir)).add_json(
                    axiom_review_candidate,
                    kind="artifact_draft",
                )
                context_evidence_refs = tuple(dict.fromkeys([*context_evidence_refs, review_ref.ref]))

            req = ExecuteRequest(
                workspace_id=workspace_id,
                operator_ref=str(self._cfg.resolved_operator_ref),
                arguments={
                    _input_key(self._cfg.message_input_key): user_request_text,
                    "metadata": {
                        "source": str(env.get("source", "telegram")),
                        "sender_id": str(env.get("sender_id", "")),
                        "chat_id": str(env.get("conversation_id", "")),
                        "received_at_utc": str(env.get("received_at_utc", "")),
                    }
                },
                idempotency_key=str(env["idempotency_key"]),
                deadline_ms=int(self._cfg.deadline_ms),
                trace=trace,
                policy_context={**policy_context, "bot_token": self._cfg.bot_token},
                preferred_target=str(self._cfg.preferred_target),
                budget_slice=int(env["budget_slice_remote_llm_calls"]),
            )

            local_exec = LocalExecutor.for_data_dir(self._data_dir)
            orch = Orchestrator.for_data_dir(str(self._data_dir), local_executor=local_exec)
            self._stream_progress(stream_session, "正在生成回复...")
            res: ExecuteResult = _run_async(orch.execute(req))

            # Update task graph root state.
            try:
                tg_graph = self._task_graph.load(workspace_id=workspace_id, graph_id=event_id)
                if tg_graph is not None:
                    # Update root status
                    tg_graph = set_task_state(
                        graph=tg_graph,
                        task_id=tg_graph.root_task_id,
                        state="succeeded" if res.status == "accepted" else "failed",
                        error_code=res.error_code,
                    )
                    self._task_graph.save(graph=tg_graph, replay_mode=False)
                    # --- ACTION EXPANSION (AgentOS Spec) ---
                    # If the skill produced autonomous 'actions', expand the graph.
                    self._maybe_expand_graph(workspace_id, event_id, tg_graph.root_task_id, res)
            except Exception as e:
                print(f"[TG] IO Failure: {e}")
                return {"ok": False, "error_code": PA_EV_ERROR_IO_FAILED}

            # --- RUN STATE MACHINE ---
            # Now we drive the pending tasks (if any)
            final_res = self.run_pending_tasks(
                workspace_id=workspace_id,
                event_id=event_id,
                trace_context=trace,
                policy_context=policy_context,
            )
            if final_res is not None:
                res = final_res
            # --- END ---

            reminder_evidence_refs: tuple[str, ...] = ()
            reply_text = _default_reply_text(res=res, msg=str(env["message_text"]), data_dir=self._data_dir)
            if res.status == "accepted":
                sched_task_id, _sched_next = self._extract_scheduler_task_info(res=res)
                if sched_task_id is None:
                    reminder_reply, reminder_refs = self._maybe_schedule_reminder_fallback(
                        event_id=event_id,
                        workspace_id=workspace_id,
                        message_text=str(env.get("message_text") or ""),
                        chat_id=str(env.get("conversation_id") or ""),
                        trace=trace,
                        orch=orch,
                    )
                    if reminder_reply:
                        reply_text = reminder_reply
                    reminder_evidence_refs = tuple(reminder_refs)

            memory_consolidation_refs = self._memory_consolidator.consolidate_turn(
                workspace_id=workspace_id,
                conversation_id=str(env.get("conversation_id") or "").strip() or None,
                project_id=None,
                query=str(env.get("message_text") or ""),
                reply_text=reply_text,
                error_code=res.error_code,
            )

            # Metering v0: evidence only (no billing).
            evidence = FileEvidenceStore(data_dir=str(self._data_dir))
            mref = write_metering_evidence_v0(
                evidence=evidence,
                workspace_id=workspace_id,
                event_id=event_id,
                trace_id=req.trace.trace_id,
                turn_id=req.trace.turn_id,
                op="outbox_write",
                ok=(res.status == "accepted"),
                error_code=res.error_code,
                budget_slice_remote_llm_calls=int(env["budget_slice_remote_llm_calls"]),
            )

            reply_sent_live = bool(stream_session.finish(final_text=reply_text)) if stream_session is not None else False
            out = OutboxItem(
                schema_version="1.0.0",
                stored_at_utc=_utc_iso(),
                workspace_id=workspace_id,
                event_id=event_id,
                idempotency_key=req.idempotency_key,
                trace_id=req.trace.trace_id,
                turn_id=req.trace.turn_id,
                span_id=req.trace.span_id,
                execute_status=res.status,
                execute_error_code=res.error_code,
                evidence_refs=tuple(
                    dict.fromkeys(
                        [
                            *context_evidence_refs,
                            *[er.ref for er in res.evidence_refs],
                            *reminder_evidence_refs,
                            *memory_consolidation_refs,
                        ]
                    )
                ),
                reply_text=reply_text,
                metering_evidence_refs=(mref.ref,),
                reply_sent_live=reply_sent_live,
                reply_delivery_mode=("telegram_stream" if stream_session is not None else None),
            )
            self._outbox.put_if_absent(item=out)
            root_hypothesis = (
                f"event_message={_normalize_retrieval_text(env['message_text'])[:160]}; "
                f"source={str(env.get('source') or 'telegram').strip() or 'telegram'}"
            )
            self._write_hypothesis_record(
                workspace_id=workspace_id,
                turn_id=req.trace.turn_id,
                iteration=1,
                hypothesis=root_hypothesis,
                verification_action=f"root_execute:{self._cfg.resolved_operator_ref}",
                verification_evidence_refs=tuple(
                    dict.fromkeys(
                        [*context_evidence_refs, *[er.ref for er in res.evidence_refs], *memory_consolidation_refs, mref.ref]
                    )
                ),
                result="confirmed" if res.status == "accepted" else "rejected",
                revision=(
                    "accepted"
                    if res.status == "accepted"
                    else str(res.error_code or f"status={res.status}")
                ),
            )
            return {"ok": True, "outbox": out.to_json(), "dedup": False}
        except Exception as _exc:
            # Fail-closed stable error; print traceback for debug.
            import traceback
            print(f"[EV1] CRITICAL handle_envelope exception: {_exc}")
            traceback.print_exc()
            return {"ok": False, "error_code": PA_EV_ERROR_IO_FAILED}
        finally:
            try:
                if "typing_session" in locals() and typing_session is not None:
                    typing_session.stop()
            except Exception:
                pass

    def _maybe_expand_graph(self, workspace_id: str, event_id: str, parent_task_id: str, res: ExecuteResult) -> None:
        """Parse skill output and expand the graph with actions if found."""
        try:
            tg_graph = self._task_graph.load(workspace_id=workspace_id, graph_id=event_id)
            if not tg_graph:
                return

            parent_node = tg_graph.tasks.get(parent_task_id)
            parent_type = ""
            if parent_node is not None:
                parent_type = str(parent_node.payload.get("type") or "")
            # Guardrail: aggregate_reasoning is a terminal summarization step.
            # It must not trigger another expansion wave, otherwise PA can loop.
            if parent_type == "aggregate_reasoning":
                print(f"[TG] Expansion skipped: parent={parent_task_id} type=aggregate_reasoning (terminal)")
                return

            actions = _extract_actions_from_result(res=res, data_dir=self._data_dir)
            if not actions:
                return

            print(f"[TG] Expanding {parent_task_id} with {len(actions)} actions (parallel)")

            # Idempotent expansion: skip action fingerprints already present in graph.
            # This prevents repeated planner outputs from growing the graph forever.
            existing_fingerprints = _task_graph_semantic_fingerprints(tg_graph)
            added_actions = 0
            skipped_duplicates = 0
            skipped_cycle = 0

            # All actions and the final reasoning wait for the same parent (Root or Reasoning task)
            for action in actions:
                if not isinstance(action, dict):
                    continue
                operator_ref = _normalize_action_skill_ref(action.get("operator_ref") or action.get("skill_ref"))
                if not operator_ref:
                    continue

                action_arguments = action.get("arguments")
                if not isinstance(action_arguments, dict):
                    action_arguments = action.get("input")
                if not isinstance(action_arguments, dict):
                    action_arguments = {}

                decorated_payload = {
                    "type": "action",
                    "operator_ref": operator_ref,
                    "arguments": dict(action_arguments),
                }
                fp = _canonical_task_fingerprint(kind="action", payload=decorated_payload)
                if fp in existing_fingerprints:
                    skipped_duplicates += 1
                    continue
                try:
                    tg_graph = add_task(
                        graph=tg_graph,
                        fingerprint=fp,
                        payload=decorated_payload,
                        parent_task_id=parent_task_id
                    )
                    existing_fingerprints.add(fp)
                    added_actions += 1
                except TaskGraphError as e:
                    if str(e.error_code or "") == TASK_GRAPH_ERROR_CYCLE_DETECTED:
                        skipped_cycle += 1
                        continue
                    raise

            action_skill_refs = tuple(
                str(a.get("operator_ref") or a.get("skill_ref") or "").strip()
                for a in actions
                if isinstance(a, dict) and str(a.get("operator_ref") or a.get("skill_ref") or "").strip()
            )
            self._emit_capability_resolution_evidence(
                workspace_id=workspace_id,
                event_id=event_id,
                parent_task_id=parent_task_id,
                action_skill_refs=tuple(_normalize_action_skill_ref(x) for x in action_skill_refs),
            )

            # No new action -> no aggregate node (avoid empty reasoning chains).
            if added_actions <= 0:
                if skipped_duplicates > 0 or skipped_cycle > 0:
                    print(
                        f"[TG] Expansion skipped: parent={parent_task_id} "
                        f"duplicates={skipped_duplicates} cycle={skipped_cycle}"
                    )
                return

            # Add Final Aggregate Reasoning node as a sibling (it will wait due to TaskGraph logic)
            final_reasoning_payload = {
                "type": "aggregate_reasoning",
                "operator_ref": self._cfg.resolved_operator_ref,
                "arguments": {
                    "request": "Tool execution block finished. Please check outcomes and decide next steps."
                },
                "parent_task_id": parent_task_id,
            }
            aggregate_fp = _canonical_task_fingerprint(kind="reasoning", payload=final_reasoning_payload)
            if aggregate_fp not in existing_fingerprints:
                tg_graph = add_task(
                    graph=tg_graph,
                    fingerprint=aggregate_fp,
                    payload=final_reasoning_payload,
                    parent_task_id=parent_task_id
                )
            self._task_graph.save(graph=tg_graph, replay_mode=False)
            print(
                f"[TG] Expansion applied: parent={parent_task_id} "
                f"added_actions={added_actions} skipped_duplicates={skipped_duplicates} skipped_cycle={skipped_cycle}"
            )
        except Exception as e:
            print(f"[TG] Expansion failure: {e}")

    async def _execute_task(self, task: TaskNode, workspace_id: str, event_id: str, trace_context: TraceContext, policy_context: dict[str, Any], orch: Orchestrator) -> ExecuteResult:
        # 1. Mark Running
        actual_tg = self._task_graph.load(workspace_id=workspace_id, graph_id=event_id)
        if not actual_tg: return
        actual_tg = set_task_state(graph=actual_tg, task_id=task.task_id, state="running")
        self._task_graph.save(graph=actual_tg)

        # 2. Execute
        operator_ref = _task_payload_operator_ref(task.payload)
        print(f"[TG] Executing {task.task_id}: {operator_ref}")
            
        step_trace = TraceContext(
            trace_id=trace_context.trace_id,
            turn_id=trace_context.turn_id,
            span_id=f"{trace_context.span_id}_{task.task_id}",
            parent_span_id=trace_context.span_id
        )
            
        task_input = _task_payload_arguments(task.payload)
        recent_failures = self._recent_hypothesis_texts(workspace_id=workspace_id, result="rejected", limit=3)
        
        if task.payload.get("type") in ("aggregate_reasoning", "reasoning"):
            sibling_summaries = self._collect_sibling_action_summaries(
                graph=actual_tg,
                task=task,
                workspace_id=workspace_id,
                event_id=event_id,
                orch=orch,
            )
            task_input["request"] = self._augment_reasoning_request(
                base_request=str(task_input.get("request") or ""),
                sibling_summaries=sibling_summaries,
                recent_failures=recent_failures,
                aggregate=bool(task.payload.get("type") == "aggregate_reasoning"),
            )
        hypothesis = self._build_task_hypothesis(task=task, task_input=task_input)
        if self._has_recent_rejected_hypothesis(workspace_id=workspace_id, hypothesis=hypothesis):
            res = self._make_hypothesis_repeat_result(
                workspace_id=workspace_id,
                trace_context=step_trace,
                hypothesis=hypothesis,
            )
            actual_tg = self._task_graph.load(workspace_id=workspace_id, graph_id=event_id)
            if actual_tg:
                actual_tg = set_task_state(
                    graph=actual_tg,
                    task_id=task.task_id,
                    state="failed",
                    error_code=res.error_code,
                )
                self._task_graph.save(graph=actual_tg)
            self._write_hypothesis_record(
                workspace_id=workspace_id,
                turn_id=trace_context.turn_id,
                iteration=max(1, int(task.seq) + 1),
                hypothesis=hypothesis,
                verification_action=f"execute:{operator_ref}",
                verification_evidence_refs=tuple(er.ref for er in res.evidence_refs),
                result="rejected",
                revision="provide new evidence before retrying the same task hypothesis",
            )
            return res
        
        step_policy_context = dict(policy_context or {})
        if task.payload.get("type") not in ("reasoning", "aggregate_reasoning"):
            step_policy_context.pop("llm_stream_callback", None)

        action_req = ExecuteRequest(
            workspace_id=workspace_id,
            operator_ref=operator_ref,
            arguments=task_input,
            idempotency_key=f"tg_{event_id}_{task.task_id}",
            deadline_ms=120000,
            trace=step_trace,
            policy_context=step_policy_context,
            preferred_target="local",
        )
            
        res = await orch.execute(action_req)
            
        # 3. Update Result
        actual_tg = self._task_graph.load(workspace_id=workspace_id, graph_id=event_id)
        if not actual_tg: return
        actual_tg = set_task_state(
            graph=actual_tg,
            task_id=task.task_id,
            state="succeeded" if res.status == "accepted" else "failed",
            error_code=res.error_code
        )
        self._task_graph.save(graph=actual_tg)
        self._write_hypothesis_record(
            workspace_id=workspace_id,
            turn_id=trace_context.turn_id,
            iteration=max(1, int(task.seq) + 1),
            hypothesis=hypothesis,
            verification_action=f"execute:{operator_ref}",
            verification_evidence_refs=tuple(er.ref for er in res.evidence_refs),
            result="confirmed" if res.status == "accepted" else "rejected",
            revision=(
                "accepted"
                if res.status == "accepted"
                else str(res.error_code or f"status={res.status}")
            ),
        )

        # 4. Recursive Expansion
        if task.payload.get("type") == "reasoning":
             self._maybe_expand_graph(workspace_id, event_id, task.task_id, res)
        
        return res

    def run_pending_tasks(self, workspace_id: str, event_id: str, trace_context: TraceContext, policy_context: dict[str, Any]) -> ExecuteResult | None:
        """Drive the TaskGraph state machine batch-by-batch."""
        import asyncio
        local_exec = LocalExecutor.for_data_dir(self._data_dir)
        orch = Orchestrator.for_data_dir(str(self._data_dir), local_executor=local_exec)
        
        last_reasoning_res: ExecuteResult | None = None

        while True:
            tg = self._task_graph.load(workspace_id=workspace_id, graph_id=event_id)
            if not tg: break
            
            from agentos_next.pa.task_graph import get_ready_tasks
            ready = get_ready_tasks(tg)
            if not ready: break
            self._stream_progress(policy_context.get("telegram_stream_session"), self._describe_ready_batch(ready))
            
            print(f"[TG] Launching parallel batch: {[t.task_id for t in ready]}")
            # Build gather inside a coroutine so Python 3.14 does not require
            # a pre-existing event loop at creation time.
            async def _run_batch() -> list[ExecuteResult]:
                return await asyncio.gather(*[
                    self._execute_task(t, workspace_id, event_id, trace_context, policy_context, orch)
                    for t in ready
                ])

            batch_results = _run_async(_run_batch())
            for t, r in zip(ready, batch_results):
                if t.payload.get("type") in ("reasoning", "aggregate_reasoning"):
                    last_reasoning_res = r

        return last_reasoning_res



def _input_key(value: Any) -> str:
    try:
        s = str(value or "").strip()
    except Exception:
        s = ""
    return s or "request"


def _clean_reminder_body(raw: str) -> str:
    text = " ".join(str(raw or "").split())
    text = re.sub(r"^[，,。.!！?:：\s]+", "", text)
    text = re.sub(r"[，,。.!！?:：\s]+$", "", text)
    if text.startswith("提醒我"):
        text = text[3:]
    if text.startswith("提醒"):
        text = text[2:]
    return text.strip()


def _normalize_retrieval_text(raw: Any) -> str:
    text = " ".join(str(raw or "").lower().split())
    text = re.sub(r"[^0-9a-z_\u4e00-\u9fff]+", " ", text)
    return " ".join(text.split())


def _extract_retrieval_query_terms(query_norm: str) -> tuple[str, ...]:
    if not query_norm:
        return ()
    terms: set[str] = set(re.findall(r"[a-z0-9_]{2,}", query_norm))
    for chunk in re.findall(r"[\u4e00-\u9fff]{2,}", query_norm):
        terms.add(chunk)
        if len(chunk) > 4:
            terms.add(chunk[:4])
            terms.add(chunk[-4:])
    return tuple(sorted(terms, key=len, reverse=True))


def _score_retrieval_text(*, query_norm: str, query_terms: tuple[str, ...], text_norm: str) -> int:
    score = 0
    if query_norm and query_norm in text_norm:
        score += 64
    for term in query_terms:
        if term in text_norm:
            score += min(len(term), 12)
    return score


def _safe_parse_utc_iso(value: Any) -> datetime:
    s = str(value or "").strip()
    if not s:
        return datetime.fromtimestamp(0, tz=timezone.utc)
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return datetime.fromtimestamp(0, tz=timezone.utc)


def _utc_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _default_reply_text(*, res: ExecuteResult, msg: str, data_dir: Path) -> str:
    # Prefer tool_io output if available and accepted.
    if res.status == "accepted":
        evidence = FileEvidenceStore(data_dir=data_dir)
        # Priority: llm_io contains the actual model output. 
        # tool_io in PackageRunner currently stores the Echo of the input.
        io_refs = [er for er in res.evidence_refs if er.kind in ("llm_io", "tool_io")]
        if not io_refs:
            return f"Execution {res.status}. Error: {res.error_code or 'None'}"
            
        # Prioritize llm_io if present (it's usually added after input snapshots)
        llm_ios = [er for er in io_refs if er.kind == "llm_io"]
        target_ref = llm_ios[-1] if llm_ios else io_refs[-1]
        
        blob = evidence.get_blob(target_ref.ref)
        if blob and blob.content_type == "application/json":
            try:
                obj = json.loads(blob.content.decode("utf-8"))
                # PackageRunner outputs commonly nest user-visible content under {"output": {...}}.
                for key in ("reply", "message", "summary", "text", "result"):
                    reply = obj.get(key) or (obj.get("output") or {}).get(key)
                    if isinstance(reply, str) and reply.strip():
                        return reply.strip()
                artifacts = obj.get("artifacts") or (obj.get("output") or {}).get("artifacts")
                if isinstance(artifacts, list) and artifacts:
                    return "Execution completed with artifacts."
                # Fallback to dump if it's the only thing we have
                return json.dumps(obj, ensure_ascii=False)
            except Exception:
                pass
    
    if res.error_code == "E_POLICY_DENY":
        return "I'm sorry, my safety policy prevents me from satisfying that request."
    if res.error_code == "E_PROVIDER_BAD_RESPONSE":
        return "远端模型服务返回异常，请稍后再试。"
    return f"Execution {res.status}. Error: {res.error_code or 'None'}"


def _extract_actions_from_result(*, res: ExecuteResult, data_dir: Path) -> list[dict[str, Any]]:
    evidence = FileEvidenceStore(data_dir=data_dir)
    io_refs = [er for er in res.evidence_refs if er.kind in ("llm_io", "tool_io")]
    if not io_refs:
        return []

    llm_refs = [er for er in io_refs if er.kind == "llm_io"]
    tool_refs = [er for er in io_refs if er.kind == "tool_io"]
    search_order = [*reversed(llm_refs), *reversed(tool_refs)]
    for ref in search_order:
        blob = evidence.get_blob(ref.ref)
        if not blob or blob.content_type != "application/json":
            continue
        try:
            obj = json.loads(blob.content.decode("utf-8"))
        except Exception:
            continue
        if not isinstance(obj, dict):
            continue
        actions = obj.get("actions")
        output = obj.get("output")
        if not isinstance(actions, list) and isinstance(output, dict):
            actions = output.get("actions")
        if not isinstance(actions, list):
            continue
        return [a for a in actions if isinstance(a, dict)]
    return []


def _normalize_action_skill_ref(raw: Any) -> str:
    skill_ref = str(raw or "").strip()
    if not skill_ref:
        return ""
    if skill_ref.startswith("builtin://"):
        return skill_ref
    if skill_ref in _ACTION_SKILL_REF_ALIASES:
        return _ACTION_SKILL_REF_ALIASES[skill_ref]
    return skill_ref


def _task_payload_operator_ref(payload: Any) -> str:
    if not isinstance(payload, dict):
        return ""
    return str(payload.get("operator_ref") or payload.get("skill_ref") or "").strip()


def _task_payload_arguments(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    raw = payload.get("arguments")
    if not isinstance(raw, dict):
        raw = payload.get("input")
    return dict(raw) if isinstance(raw, dict) else {}


def _canonicalize_task_payload(payload: dict[str, Any]) -> dict[str, Any]:
    out = dict(payload)
    operator_ref = _task_payload_operator_ref(payload)
    if operator_ref:
        out["operator_ref"] = operator_ref
    if "arguments" in payload or "input" in payload:
        out["arguments"] = _task_payload_arguments(payload)
    out.pop("skill_ref", None)
    out.pop("input", None)
    return out


def _canonical_task_fingerprint(*, kind: str, payload: dict[str, Any]) -> str:
    return compute_task_fingerprint(kind=kind, payload=_canonicalize_task_payload(payload))


def _task_graph_semantic_fingerprints(graph: TaskGraph) -> set[str]:
    fingerprints = {str(task.fingerprint) for task in graph.tasks.values() if str(task.fingerprint).strip()}
    for task in graph.tasks.values():
        task_type = str(task.payload.get("type") or "").strip()
        kind: Optional[str] = None
        if task_type == "action":
            kind = "action"
        elif task_type in {"reasoning", "aggregate_reasoning"}:
            kind = "reasoning"
        if kind is None:
            continue
        fingerprints.add(_canonical_task_fingerprint(kind=kind, payload=task.payload))
    return fingerprints


def _run_async(coro: Any) -> Any:
    import asyncio
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    
    if loop.is_running():
        import nest_asyncio
        nest_asyncio.apply()
        return loop.run_until_complete(coro)
    return asyncio.run(coro)
