from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from agentos_next.kernel.capabilities import capability_items_for_policy_context
from agentos_next.kernel.agent_profile import FileAgentProfileStore, make_axiom_review_candidate
from agentos_next.kernel.effective_runtime_capabilities import (
    build_effective_runtime_capabilities_v1,
    capability_items_from_effective_runtime_capabilities,
    capability_names_from_effective_runtime_capabilities,
    with_effective_runtime_capability_names,
)
from agentos_next.kernel.observation_learning import build_observation_learning_candidates_v1
from agentos_next.kernel.research_doctrine import build_research_evidence_pack_v1
from agentos_next.kernel.soul_profile import FileSoulProfileStore
from agentos_next.kernel.capsule_store import build_global_capsule_v1, build_project_capsule_v1, resolve_active_project_v1
from agentos_next.kernel.context_plane_cache import FileContextPlaneCache
from agentos_next.kernel.evidence_store import FileEvidenceStore
from agentos_next.kernel.executor import ExecuteRequest, ExecuteResult
from agentos_next.kernel.memory_store import MemoryConsolidatorV2
from agentos_next.kernel.orchestrator import Orchestrator
from agentos_next.kernel.trace_logger import FileTraceLogger
from agentos_next.kernel.types import TraceContext, TraceEvent
from agentos_next.kernel.hypothesis_store import FileHypothesisStore, HypothesisRecord
from agentos_next.kernel.theorem_store import FileTheoremStore, build_theorem_record_v1
from agentos_next.kernel.runtime_snapshot_store import FileRuntimeSnapshotStore
from agentos_next.kernel.runtime_event_log import FileRuntimeEventLog, emit_output_event
from agentos_next.kernel.execution_lane import (
    classify_execution_lane,
    clamp_tool_budget_for_lane,
    default_stop_policy_for_lane,
    default_token_budget_for_lane,
    execution_lane_policy_payload,
    next_execution_lane,
    normalize_execution_lane,
)
from agentos_next.kernel.task_service import KernelTaskService, TaskRecord, TaskRunResult, TaskSpec
from agentos_next.runtime.local_executor import LocalExecutor
from agentos_next.pa.runtime_graph_scheduler import RuntimeGraphSchedulerBootstrap
from agentos_next.apps.runtime_graph_session import (
    NullRuntimeGraphSession,
    RuntimeGraphSession,
    TaskGraphRuntimeGraphSession,
    WorkerTaskSpec,
)
from agentos_next.apps.worker_runtime import (
    WorkerReasonDecision,
    WorkerReActOutcome,
    WorkerReActRuntime,
    WorkerTaskRuntimeInput,
    WorkerStopPolicy,
    WorkerTokenBudget,
    WorkerToolBudget,
    WorkerToolCall,
    WorkerToolCallResult,
)
from agentos_next.llm.backend import (
    CodexOAuthLLMBackend,
    DoubaoArkLLMBackend,
    LLMCallError,
    LLMSafetyGate,
    LocalMockLLMBackend,
    MiniMaxLLMBackend,
    is_remote_llm_backend,
)
from agentos_next.llm.openai_codex_oauth import OpenAICodexOAuthProvider
from agentos_next.apps.query_gated_runtime import (
    build_user_facing_failure_summary_v1,
    build_context_plane_pack_v1,
    build_query_hypothesis,
    compile_query_for_assistant_loop,
    verify_assistant_execution,
)


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


CORRECTION_COALESCE_WINDOW_MS = 5000
_CORRECTION_MARKERS = (
    "不是",
    "不对",
    "更正",
    "改成",
    "改为",
    "补充",
    "纠正",
    "应该是",
    "actually",
    "instead",
    "correction",
    "update:",
)


def _parse_utc_iso(raw: Any) -> datetime | None:
    value = str(raw or "").strip()
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _looks_like_correction_text(raw: Any) -> bool:
    text = str(raw or "").strip().lower()
    if not text:
        return False
    return any(marker in text for marker in _CORRECTION_MARKERS)


def _repo_root() -> Path:
    # src/agentos_next/apps/assistant_loop.py -> repo root is 3 levels up.
    return Path(__file__).resolve().parents[3]


@dataclass(frozen=True)
class AssistantLoopRequest:
    """Single-turn assistant loop request (MVP)."""

    query: str

    # Default assistant skill package (LLM-only skeleton skill).
    assistant_skill_dir: Optional[Path] = None

    workspace_id: str = "local"
    data_dir: str | Path = "data"
    trace: Optional[TraceContext] = None
    idempotency_key: Optional[str] = None
    deadline_ms: int = 60000

    # Package execution policy knobs
    verify_asvp: bool = True
    public_keys_dir: Optional[Path] = None
    backend: str = "local_mock"  # local_mock | codex_oauth | doubao_ark | minimax
    planner: str = "model_owned"  # model_owned | llm | auto
    planner_backend: Optional[str] = None  # default: same as backend
    model: Optional[str] = None
    intent_backend: Optional[str] = None
    intent_model: Optional[str] = None
    communicator_backend: Optional[str] = None
    communicator_model: Optional[str] = None
    response_language: Optional[str] = None
    remote_calls_armed: bool = False
    allow_network_egress: bool = False
    approved_by_human: bool = False
    replay_mode: bool = False
    capabilities: Optional[str] = None
    effective_runtime_capabilities: Optional[dict[str, Any]] = None
    memory_context: Optional[dict[str, Any]] = None
    llm_stream_callback: Optional[Callable[[dict[str, Any]], None]] = None
    telegram_stream_session: Any = None
    output_event_sink: Optional[Callable[[dict[str, Any]], None]] = None
    external_evidence_policy_override: Optional[dict[str, Any]] = None

    # FU2: explicit follow-up scheduling (UTC ISO).
    followup_at: Optional[str] = None
    message_received_at_utc: Optional[str] = None
    agent_id: str = "assistant_loop"
    conversation_id: Optional[str] = None
    attachments: tuple[dict[str, Any], ...] = ()
    graph_id: Optional[str] = None


@dataclass(frozen=True)
class AssistantLoopResult:
    ok: bool
    final_output: Optional[dict[str, Any]]
    error_code: Optional[str]
    steps: list[dict[str, Any]]
    trace: TraceContext
    evidence_refs: list[str]
    followup_plan_ref: str
    followup_task_id: Optional[str] = None
    delivery_state: Optional[str] = None
    graph_id: Optional[str] = None


def _new_child_trace(parent: TraceContext, *, span_suffix: str) -> TraceContext:
    return TraceContext(
        trace_id=parent.trace_id,
        turn_id=parent.turn_id,
        span_id=f"{parent.span_id}_{span_suffix}",
        parent_span_id=parent.span_id,
    )


def _emit_delivery_state(
    *,
    trace_log: FileTraceLogger,
    ctx: TraceContext,
    task_id: str,
    state: str,
    summary: str,
    evidence_refs: tuple[Any, ...] = (),
    error_code: Optional[str] = None,
    final_snapshot_ref: Optional[str] = None,
) -> None:
    trace_log.emit(
        TraceEvent(
            schema_version="1.0.0",
            ctx=ctx,
            event_type="DIALOG_EVENT",  # type: ignore[arg-type]
            ts=_utc_iso(),
            evidence_refs=evidence_refs,
            data={
                "dialog_event_type": "DELIVERY_STATE",
                "dialog_id": ctx.trace_id,
                "task_id": str(task_id or "").strip() or f"task_{ctx.trace_id}_{ctx.turn_id}",
                "state": str(state).strip(),
                "summary": str(summary or "").strip(),
                "error_code": str(error_code).strip() if isinstance(error_code, str) and error_code.strip() else None,
                "final_snapshot_ref": (
                    str(final_snapshot_ref).strip()
                    if isinstance(final_snapshot_ref, str) and final_snapshot_ref.strip()
                    else None
                ),
            },
        )
    )


def _should_suggest_remote_lookup(query: str) -> bool:
    # Deterministic heuristic only; must not depend on runtime/tool outputs.
    q = query.lower()
    hints = (
        "latest",
        "today",
        "news",
        "weather",
        "price",
        "stock",
        "exchange rate",
        "查",
        "查询",
        "搜",
        "搜索",
        "最新",
        "今天",
        "天气",
        "价格",
        "股价",
        "汇率",
    )
    return any(h in q or h in query for h in hints)


def _update_stream_progress(session: Any, text: str) -> None:
    if session is None:
        return
    try:
        session.update_progress(str(text or "").strip())
    except Exception:
        return


def _capability_name_set(raw: str | None) -> set[str]:
    return {c.strip() for c in str(raw or "").split(",") if c.strip()}


def _normalized_attachments(raw: Any) -> list[dict[str, Any]]:
    return [dict(item) for item in (raw or []) if isinstance(item, dict)]


def _attachment_media_kinds(raw: Any) -> list[str]:
    out: list[str] = []
    for item in _normalized_attachments(raw):
        media_kind = str(item.get("media_kind") or "").strip().lower()
        if media_kind and media_kind not in out:
            out.append(media_kind)
    return out


def _supports_required_media(support: dict[str, Any], required_media_kinds: list[str]) -> bool:
    key_map = {
        "image": "supports_image",
        "document": "supports_document",
        "audio": "supports_audio",
        "video": "supports_video",
    }
    if not required_media_kinds:
        return True
    for media_kind in required_media_kinds:
        if not bool(support.get(key_map.get(media_kind, ""))):
            return False
    return True


def _selected_attachments_for_profile(
    *,
    attachments: list[dict[str, Any]],
    task_requirements: dict[str, Any],
    prompt_profile_id: str | None,
) -> list[dict[str, Any]]:
    if not prompt_profile_id or not attachments:
        return []
    phase_policy = dict(task_requirements.get("attachment_phase_policy") or {})
    mode = str(phase_policy.get(prompt_profile_id) or "none").strip()
    if mode not in {"required", "optional"}:
        return []
    reachability = dict(task_requirements.get("downstream_modality_reachability") or {})
    phase_support = dict(reachability.get(prompt_profile_id) or {})
    required_media_kinds = [
        str(x).strip()
        for x in (task_requirements.get("required_media_kinds") or [])
        if str(x).strip()
    ]
    if not _supports_required_media(phase_support, required_media_kinds):
        return []
    return [dict(item) for item in attachments]


_ACTION_OPERATOR_ALIASES: dict[str, str] = {
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
    "research_run": "builtin://research.run",
    "research.run": "builtin://research.run",
    "creator_plan": "builtin://creator.plan",
    "creator.plan": "builtin://creator.plan",
    "channel_send_message": "builtin://channel.send_message",
    "channel.send_message": "builtin://channel.send_message",
    "time_now": "builtin://time.now",
    "time.now": "builtin://time.now",
    "scheduler_at": "builtin://scheduler.at",
    "scheduler.at": "builtin://scheduler.at",
    "scheduler_cron": "builtin://scheduler.cron",
    "scheduler.cron": "builtin://scheduler.cron",
}

_CANONICAL_PROMPT_PROFILES = frozenset(
    {"intent_router", "planner", "executor", "verifier_replanner", "communicator"}
)


def _normalize_action_operator_ref(raw: Any) -> str:
    ref = str(raw or "").strip()
    if not ref:
        return ""
    if ref.startswith("builtin://"):
        return ref
    return _ACTION_OPERATOR_ALIASES.get(ref, ref)


def _extract_user_visible_text(output_obj: dict[str, Any] | None) -> str:
    if not isinstance(output_obj, dict):
        return ""
    for key in ("reply", "message", "summary", "text", "result"):
        value = str(output_obj.get(key) or "").strip()
        if value:
            return value
    return ""


def _extract_channel_send_actions(output_obj: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(output_obj, dict):
        return []
    actions: list[dict[str, Any]] = []
    for item in _normalize_emitted_actions(output_obj):
        operator_ref = str(item.get("operator_ref") or "").strip()
        arguments = dict(item.get("arguments") or {}) if isinstance(item.get("arguments"), dict) else {}
        if operator_ref != "builtin://channel.send_message":
            continue
        if str(arguments.get("text") or arguments.get("message") or arguments.get("reply") or "").strip():
            actions.append({"action_id": str(item.get("action_id") or "").strip(), "operator_ref": operator_ref, "arguments": arguments})
    return actions


def _normalize_emitted_actions(output_obj: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(output_obj, dict):
        return []
    raw_actions = output_obj.get("actions")
    if not isinstance(raw_actions, list):
        return []
    normalized: list[dict[str, Any]] = []
    seen_action_ids: set[str] = set()
    for idx, item in enumerate(raw_actions, start=1):
        if not isinstance(item, dict):
            continue
        operator_ref = _normalize_action_operator_ref(item.get("operator_ref"))
        if not operator_ref:
            continue
        raw_arguments = item.get("arguments")
        arguments = dict(raw_arguments) if isinstance(raw_arguments, dict) else {}
        raw_depends_on = item.get("depends_on") or []
        depends_on = [str(x).strip() for x in raw_depends_on if str(x).strip()] if isinstance(raw_depends_on, list) else []
        base_action_id = str(item.get("action_id") or "").strip() or f"action_{idx}"
        action_id = base_action_id
        if action_id in seen_action_ids:
            action_id = f"{base_action_id}_{idx}"
        seen_action_ids.add(action_id)
        normalized.append(
            {
                "action_id": action_id,
                "operator_ref": operator_ref,
                "arguments": arguments,
                "depends_on": depends_on,
                "kind": str(item.get("kind") or "").strip() or None,
            }
        )
    return normalized


def _normalize_emitted_worker_tasks(output_obj: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(output_obj, dict):
        return []
    raw_tasks = output_obj.get("worker_tasks")
    if not isinstance(raw_tasks, list):
        return []
    normalized: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for idx, item in enumerate(raw_tasks, start=1):
        if not isinstance(item, dict):
            continue
        worker_task_id = str(item.get("worker_task_id") or "").strip() or f"worker_task_{idx}"
        if worker_task_id in seen_ids:
            worker_task_id = f"{worker_task_id}_{idx}"
        seen_ids.add(worker_task_id)
        depends_on_raw = item.get("depends_on") or []
        allowed_raw = item.get("allowed_operator_refs") or []
        tool_budget = dict(item.get("tool_budget") or {}) if isinstance(item.get("tool_budget"), dict) else {}
        normalized.append(
            {
                "worker_task_id": worker_task_id,
                "objective": str(item.get("objective") or "").strip(),
                "depends_on": [str(x).strip() for x in depends_on_raw if str(x).strip()] if isinstance(depends_on_raw, list) else [],
                "allowed_operator_refs": [
                    _normalize_action_operator_ref(ref)
                    for ref in allowed_raw
                    if _normalize_action_operator_ref(ref)
                ]
                if isinstance(allowed_raw, list)
                else [],
                "scope_summary": str(item.get("scope_summary") or "").strip(),
                "completion_contract_ref": str(item.get("completion_contract_ref") or "").strip(),
                "tool_budget": {
                    "max_calls": max(1, int(tool_budget.get("max_calls") or 1)),
                    "max_parallel_calls": max(1, int(tool_budget.get("max_parallel_calls") or 1)),
                    "retry_read_only_tools": bool(tool_budget.get("retry_read_only_tools")),
                },
                "time_budget_ms": max(0, int(item.get("time_budget_ms") or 0)),
            }
        )
    return normalized


def _is_send_message_action(action_obj: dict[str, Any] | None) -> bool:
    if not isinstance(action_obj, dict):
        return False
    return str(action_obj.get("operator_ref") or "").strip() == "builtin://channel.send_message"


def _direct_reply_violation_text(output_obj: dict[str, Any] | None) -> str:
    if not isinstance(output_obj, dict):
        return ""
    for key in ("reply", "message", "summary", "result"):
        text = str(output_obj.get(key) or "").strip()
        if text:
            return text
    return ""


def _default_message_key(*, task_id: str, delivery_stage: str) -> str:
    base = str(task_id or "").strip() or "task"
    if delivery_stage in {"progress", "final", "blocker", "need_context"}:
        return base
    return f"{base}:{delivery_stage}"


def _augment_send_message_arguments(
    *,
    arguments: dict[str, Any],
    task_id: str,
    delivery_stage: str,
    source_phase: str,
) -> dict[str, Any]:
    payload = dict(arguments or {})
    text = str(payload.get("text") or payload.get("message") or payload.get("reply") or "").strip()
    if text:
        payload["text"] = text
    payload.setdefault("audience", "user")
    payload.setdefault("channel", "assistant_runtime")
    payload.setdefault("delivery_kind", "user_visible_answer")
    payload.setdefault("message_key", _default_message_key(task_id=task_id, delivery_stage=delivery_stage))
    payload["delivery_stage"] = delivery_stage
    payload.setdefault("update_preference", "prefer_update")
    metadata = dict(payload.get("metadata") or {}) if isinstance(payload.get("metadata"), dict) else {}
    metadata.setdefault("task_id", task_id)
    metadata.setdefault("source_phase", source_phase)
    payload["metadata"] = metadata
    return payload


def _action_call_idem_suffix(
    *,
    action_id: str,
    operator_ref: str,
    arguments: dict[str, Any],
) -> str:
    normalized = json.dumps(
        {
            "operator_ref": str(operator_ref or "").strip(),
            "arguments": dict(arguments or {}),
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:12]
    base = str(action_id or "").strip() or "action"
    return f"action_{base}_{digest}"


def _phase_output_violation(*, profile_id: str, output_obj: dict[str, Any] | None) -> str | None:
    direct_text = _direct_reply_violation_text(output_obj)
    actions = _normalize_emitted_actions(output_obj)
    worker_tasks = _normalize_emitted_worker_tasks(output_obj)
    send_actions = [item for item in actions if _is_send_message_action(item)]
    non_message_actions = [item for item in actions if not _is_send_message_action(item)]
    if profile_id != "communicator":
        if direct_text:
            return "E_DIRECT_REPLY_FORBIDDEN"
        if send_actions:
            return "E_MESSAGE_TASK_PHASE_VIOLATION"
        if profile_id == "executor" and worker_tasks:
            return "E_WORKER_SPLIT_REQUIRES_LEADER"
        if profile_id in {"intent_router", "planner", "verifier_replanner"} and non_message_actions:
            return "E_WORKER_TASK_GRAPH_INVALID"
        if profile_id in {"intent_router", "communicator"} and worker_tasks:
            return "E_WORKER_TASK_GRAPH_INVALID"
        return None
    if non_message_actions:
        return "E_COMMUNICATOR_ACTION_INVALID"
    if worker_tasks:
        return "E_COMMUNICATOR_ACTION_INVALID"
    return None


def _build_action_graph_capsule(*, actions: list[dict[str, Any]]) -> str:
    if not actions:
        return ""
    lines = ["ACTION GRAPH"]
    for item in actions[:8]:
        if not isinstance(item, dict):
            continue
        action_id = str(item.get("action_id") or "").strip() or "action"
        operator_ref = str(item.get("operator_ref") or "").strip() or "unknown"
        depends_on = [str(x).strip() for x in (item.get("depends_on") or []) if str(x).strip()]
        line = f"- {action_id}: {operator_ref}"
        if depends_on:
            line += " <- " + ",".join(depends_on)
        lines.append(line)
    return "\n".join(lines)


def _build_worker_task_graph_capsule(*, worker_tasks: list[dict[str, Any]]) -> str:
    if not worker_tasks:
        return ""
    lines = ["WORKER TASK GRAPH"]
    for item in worker_tasks[:8]:
        if not isinstance(item, dict):
            continue
        worker_task_id = str(item.get("worker_task_id") or "").strip() or "worker_task"
        objective = str(item.get("objective") or "").strip() or "objective missing"
        depends_on = [str(x).strip() for x in (item.get("depends_on") or []) if str(x).strip()]
        allowed = [str(x).strip() for x in (item.get("allowed_operator_refs") or []) if str(x).strip()]
        line = f"- {worker_task_id}: {objective}"
        if depends_on:
            line += " <- " + ",".join(depends_on)
        if allowed:
            line += " [" + ",".join(allowed[:6]) + "]"
        lines.append(line)
    return "\n".join(lines)


class _ActionArgumentReferenceError(ValueError):
    pass


def _lookup_structured_action_reference(
    *,
    ref_obj: dict[str, Any],
    action_outputs: dict[str, Any],
) -> Any:
    action_id = str(ref_obj.get("$from_action") or "").strip()
    if not action_id:
        raise _ActionArgumentReferenceError("$from_action is required")
    path = ref_obj.get("path")
    if not isinstance(path, list):
        raise _ActionArgumentReferenceError("path must be a list")
    current: Any = action_outputs.get(action_id)
    if current is None:
        raise _ActionArgumentReferenceError(f"upstream action output is unavailable: {action_id}")
    for segment in path:
        if isinstance(current, dict):
            if not isinstance(segment, str):
                raise _ActionArgumentReferenceError("dict path segments must be strings")
            if segment not in current:
                raise _ActionArgumentReferenceError(f"path segment not found: {segment}")
            current = current.get(segment)
            continue
        if isinstance(current, list):
            if not isinstance(segment, int):
                raise _ActionArgumentReferenceError("list path segments must be integers")
            if segment < 0 or segment >= len(current):
                raise _ActionArgumentReferenceError(f"list index out of range: {segment}")
            current = current[segment]
            continue
        raise _ActionArgumentReferenceError("path crosses a scalar value")
    return current


def _resolve_action_argument_references(
    value: Any,
    *,
    action_outputs: dict[str, Any],
) -> Any:
    if isinstance(value, dict):
        if "$from_action" in value:
            return _lookup_structured_action_reference(ref_obj=value, action_outputs=action_outputs)
        return {
            str(key): _resolve_action_argument_references(val, action_outputs=action_outputs)
            for key, val in value.items()
        }
    if isinstance(value, list):
        return [_resolve_action_argument_references(item, action_outputs=action_outputs) for item in value]
    if isinstance(value, str) and ("{{" in value or "${" in value):
        raise _ActionArgumentReferenceError("string template references are not supported")
    return value


def _extract_structured_output(*, evidence: FileEvidenceStore, result: ExecuteResult) -> dict[str, Any]:
    llm_io_refs = [er.ref for er in result.evidence_refs if er.kind == "llm_io"]
    tool_io_refs = [er.ref for er in result.evidence_refs if er.kind == "tool_io"]
    error_refs = [er.ref for er in result.evidence_refs if er.kind == "error"]
    if llm_io_refs:
        for ref in reversed(llm_io_refs):
            blob = evidence.get_blob(ref)
            if blob is None or blob.content_type != "application/json":
                continue
            try:
                obj = json.loads(blob.content.decode("utf-8"))
            except Exception:
                continue
            if isinstance(obj, dict) and isinstance(obj.get("output"), dict):
                return dict(obj.get("output") or {})
        return {}
    if tool_io_refs:
        blob = evidence.get_blob(tool_io_refs[-1])
        if blob is not None and blob.content_type == "application/json":
            try:
                parsed = json.loads(blob.content.decode("utf-8"))
            except Exception:
                return {}
            if isinstance(parsed, dict):
                return parsed
    if error_refs:
        for ref in reversed(error_refs):
            blob = evidence.get_blob(ref)
            if blob is None or blob.content_type != "application/json":
                continue
            try:
                parsed = json.loads(blob.content.decode("utf-8"))
            except Exception:
                continue
            if isinstance(parsed, dict):
                return parsed
    return {}


def _count_non_delivery_steps(exec_summaries: list[dict[str, Any]]) -> int:
    return sum(
        1
        for item in exec_summaries
        if isinstance(item, dict)
        and str(item.get("operator_ref") or "").strip().startswith("builtin://")
        and str(item.get("operator_ref") or "").strip() != "builtin://channel.send_message"
        and not str(item.get("internal_role_phase") or "").strip()
    )


def _phase_status(output_obj: dict[str, Any] | None, *, default: str = "done") -> str:
    if not isinstance(output_obj, dict):
        return default
    raw = str(output_obj.get("status") or "").strip().lower()
    if raw in {"continue", "done", "blocked", "need_context", "hold"}:
        return raw
    raw_worker_tasks = _normalize_emitted_worker_tasks(output_obj)
    if raw_worker_tasks:
        return "continue"
    raw_actions = _normalize_emitted_actions(output_obj)
    if raw_actions:
        if any(
            str(item.get("operator_ref") or "").strip() != "builtin://channel.send_message"
            for item in raw_actions
            if isinstance(item, dict)
        ):
            return "continue"
    return default


def _is_low_signal_continuation_text(raw: str) -> bool:
    text = " ".join(str(raw or "").split()).lower()
    if text in {"ok", "okay", "好的", "行", "嗯", "开始", "开始吧", "继续", "继续吧", "status", "结果呢", "进度"}:
        return True
    return not bool(re.search(r"\w", text, flags=re.UNICODE))


def _build_pending_contract(*, compiled_query: dict[str, Any], effective_query: str, interaction_mode: str) -> dict[str, Any] | None:
    intent = dict(compiled_query.get("intent_recovery") or {}) if isinstance(compiled_query, dict) else {}
    solution_query = dict(compiled_query.get("solution_query") or {}) if isinstance(compiled_query, dict) else {}
    requirements = dict(compiled_query.get("task_requirements") or {}) if isinstance(compiled_query, dict) else {}
    option = str(intent.get("intent_option") or "DIRECT_TASK").strip().upper()
    objective = str((compiled_query.get("task_envelope") or {}).get("objective") or effective_query).strip()
    if not objective or _is_low_signal_continuation_text(objective):
        return None
    if bool(solution_query.get("preserve_pending_contract")):
        prior_contract = (
            dict((((compiled_query.get("context_planes") or {}).get("intent_recovery_plane") or {}).get("pending_contract") or {}))
            if isinstance((((compiled_query.get("context_planes") or {}).get("intent_recovery_plane") or {}).get("pending_contract")), dict)
            else {}
        )
        if prior_contract:
            prior_contract["schema_version"] = "1.0.0"
            prior_contract["type"] = "continuation_contract_v1"
            prior_contract["objective"] = str(prior_contract.get("objective") or objective).strip() or objective
            prior_contract["intent_option"] = str(prior_contract.get("intent_option") or option).strip() or option
            prior_contract["interaction_mode"] = str(prior_contract.get("interaction_mode") or interaction_mode or "task").strip() or "task"
            prior_contract["delivery_kind"] = str(
                prior_contract.get("delivery_kind") or requirements.get("delivery_kind") or "user_visible_answer"
            )
            prior_contract["requires_workspace_observation"] = bool(
                prior_contract.get("requires_workspace_observation") or requirements.get("requires_workspace_observation")
            )
            prior_contract["requires_external_evidence"] = bool(
                prior_contract.get("requires_external_evidence") or requirements.get("requires_external_evidence")
            )
            return prior_contract
    return {
        "schema_version": "1.0.0",
        "type": "continuation_contract_v1",
        "objective": objective,
        "intent_option": option,
        "interaction_mode": str(interaction_mode or "task"),
        "delivery_kind": str(requirements.get("delivery_kind") or "user_visible_answer"),
        "requires_workspace_observation": bool(requirements.get("requires_workspace_observation")),
        "requires_external_evidence": bool(requirements.get("requires_external_evidence")),
    }


def _select_execution_lane(*, compiled_query: dict[str, Any], interaction_mode: str) -> str:
    hinted_lane = str(compiled_query.get("execution_lane") or "").strip()
    if hinted_lane:
        return normalize_execution_lane(hinted_lane)
    model_routing_policy = (
        dict(compiled_query.get("model_routing_policy") or {})
        if isinstance(compiled_query.get("model_routing_policy"), dict)
        else {}
    )
    hinted_lane = str(model_routing_policy.get("execution_lane") or "").strip()
    if hinted_lane:
        return normalize_execution_lane(hinted_lane)
    requirements = dict(compiled_query.get("task_requirements") or {}) if isinstance(compiled_query, dict) else {}
    solution_query = dict(compiled_query.get("solution_query") or {}) if isinstance(compiled_query, dict) else {}
    return classify_execution_lane(
        interaction_mode=interaction_mode,
        solution_query=solution_query,
        task_requirements=requirements,
        preferred_operator_refs=list(solution_query.get("preferred_operator_hints") or []),
        worker_task_count=0,
    )


def _resolved_execution_lane_policy(*, compiled_query: dict[str, Any], execution_lane: str) -> dict[str, Any]:
    raw = dict(compiled_query.get("execution_lane_policy") or {}) if isinstance(compiled_query, dict) else {}
    payload = execution_lane_policy_payload(execution_lane)
    payload.update({str(k): v for k, v in raw.items() if str(k).strip()})
    payload["lane"] = normalize_execution_lane(payload.get("lane") or execution_lane)
    return payload


def _worker_graph_fingerprint(worker_tasks: list[dict[str, Any]]) -> str:
    normalized = [dict(item) for item in worker_tasks if isinstance(item, dict)]
    payload = json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _build_task_token_budget(*, execution_lane: str, deadline_ms: int) -> dict[str, Any]:
    budget = dict(default_token_budget_for_lane(execution_lane))
    budget["deadline_ms"] = max(1000, int(deadline_ms or 0))
    return budget


def _build_task_stop_policy(*, execution_lane: str, deadline_ms: int) -> dict[str, Any]:
    return dict(default_stop_policy_for_lane(execution_lane, deadline_ms=max(1000, int(deadline_ms or 0))))


def _classify_ingress_decision(
    *,
    query_text: str,
    message_received_at_utc: str,
    runtime_snapshot: Any,
    active_submission_ids: tuple[str, ...],
) -> str:
    if not active_submission_ids:
        return "NEW_TASK"
    if _looks_like_correction_text(query_text):
        return "AMEND_ACTIVE_SUBMISSION"
    current_at = _parse_utc_iso(message_received_at_utc)
    previous_at = _parse_utc_iso(getattr(runtime_snapshot, "last_user_query_at_utc", None) if runtime_snapshot is not None else None)
    if current_at is not None and previous_at is not None:
        delta_ms = int((current_at - previous_at).total_seconds() * 1000)
        if 0 <= delta_ms <= CORRECTION_COALESCE_WINDOW_MS:
            return "AMEND_ACTIVE_SUBMISSION"
    return "FOLLOWUP_ACTIVE_SUBMISSION"


def _task_record_to_worker_task(record: TaskRecord) -> dict[str, Any]:
    return {
        "worker_task_id": str(record.worker_task_id or record.task_id).strip() or str(record.task_id),
        "objective": str(record.objective or "").strip(),
        "depends_on": list(record.depends_on),
        "allowed_operator_refs": list(record.allowed_operator_refs),
        "scope_summary": str(record.scope_summary or "").strip(),
        "completion_contract_ref": str(record.completion_contract_ref or "").strip(),
        "tool_budget": dict(record.tool_budget),
        "time_budget_ms": int(record.time_budget_ms),
        "submission_id": str(record.submission_id or "").strip(),
        "execution_lane": str(record.execution_lane or "standard_task").strip() or "standard_task",
        "effect_class": str(record.effect_class or "read_only").strip() or "read_only",
    }


def _required_inspection_steps(*, task_requirements: dict[str, Any], capabilities: set[str]) -> list[dict[str, Any]]:
    if not bool(task_requirements.get("requires_workspace_observation")):
        return []
    steps: list[dict[str, Any]] = []
    if "fs_read" in capabilities:
        steps.append(
            {
                "kind": "execute",
                "operator_ref": "builtin://fs.list",
                "arguments": {"path": "."},
            }
        )
    if "shell_exec" in capabilities:
        steps.append(
            {
                "kind": "execute",
                "operator_ref": "builtin://shell.exec",
                "arguments": {
                    "command": "find . -maxdepth 2 \\( -name README.md -o -name README -o -name pyproject.toml -o -name package.json -o -name Makefile \\) | sort",
                    "cwd": ".",
                },
            }
        )
    return steps


def _build_observation_capsule(*, operator_ref: str, output_obj: dict[str, Any]) -> str:
    if not isinstance(output_obj, dict):
        return ""
    if operator_ref == "builtin://fs.list":
        items = output_obj.get("items")
        if not isinstance(items, list):
            return ""
        names = []
        for item in items[:20]:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            if not name:
                continue
            suffix = "/" if bool(item.get("is_dir")) else ""
            names.append(name + suffix)
        return "WORKSPACE ROOT\n" + "\n".join(f"- {name}" for name in names) if names else ""
    if operator_ref == "builtin://fs.read":
        path = str(output_obj.get("path") or "").strip()
        content = str(output_obj.get("content") or "").strip()
        if not content:
            return ""
        lines = [ln.rstrip() for ln in content.splitlines() if ln.strip()][:24]
        if not lines:
            return ""
        header = f"FILE SNAPSHOT {path}" if path else "FILE SNAPSHOT"
        return header + "\n" + "\n".join(lines)
    if operator_ref == "builtin://shell.exec":
        stdout = str(output_obj.get("stdout") or "").strip()
        if not stdout:
            return ""
        lines = [ln.strip() for ln in stdout.splitlines() if ln.strip()]
        return "KEY FILE CANDIDATES\n" + "\n".join(f"- {ln}" for ln in lines[:20]) if lines else ""
    if operator_ref == "builtin://memory.search":
        results = output_obj.get("results")
        if not isinstance(results, list):
            return ""
        previews: list[str] = []
        for item in results[:5]:
            if not isinstance(item, dict):
                continue
            preview = str(item.get("summary") or "").strip()
            if preview:
                previews.append(preview)
        return "RETRIEVED MEMORY\n" + "\n".join(f"- {item}" for item in previews) if previews else ""
    if operator_ref == "builtin://web.search":
        if (output_obj.get("ok") is False) or str(output_obj.get("error_code") or "").strip():
            error_code = str(output_obj.get("error_code") or "").strip()
            header = "WEB SEARCH FAILED"
            if error_code:
                header += f" [{error_code}]"
            lines = [header]
            query = str(output_obj.get("query") or "").strip()
            if query:
                lines.append(f"query={query}")
            message = " ".join(str(output_obj.get("message") or "").split()).strip().replace(
                "playwright_search",
                "fallback_search",
            )
            if message:
                lines.append(f"! {message[:240]}")
            notices = output_obj.get("notices")
            if isinstance(notices, list):
                for notice in notices[:3]:
                    text = " ".join(str(notice).split()).strip().replace("playwright_search", "fallback_search")
                    if text:
                        lines.append(f"! {text}")
            attempts = output_obj.get("provider_attempts")
            if isinstance(attempts, list):
                for item in attempts[:4]:
                    if not isinstance(item, dict):
                        continue
                    provider = str(item.get("provider") or "unknown").strip()
                    if provider == "playwright_search":
                        provider = "fallback_search"
                    status = str(item.get("status") or "failed").strip()
                    provider_code = str(item.get("error_code") or "").strip()
                    detail = " ".join(str(item.get("detail") or "").split()).strip().replace(
                        "playwright_search",
                        "fallback_search",
                    )
                    bits = [provider, status]
                    if provider_code:
                        bits.append(provider_code)
                    line = "- " + " | ".join(bit for bit in bits if bit)
                    if detail:
                        line += f" | {detail[:180]}"
                    lines.append(line)
            return "\n".join(lines) if lines else header
        results = output_obj.get("results")
        if not isinstance(results, list):
            return ""
        meta_bits: list[str] = []
        if bool(output_obj.get("degraded")):
            meta_bits.append("degraded=true")
        if bool(output_obj.get("expectation_mismatch")):
            meta_bits.append("expectation_mismatch=true")
        header = "WEB SEARCH RESULTS"
        if meta_bits:
            header += " [" + ", ".join(meta_bits) + "]"
        lines = [header]
        notices = output_obj.get("notices")
        if isinstance(notices, list):
            for notice in notices[:3]:
                text = str(notice).strip()
                if text:
                    lines.append(f"! {text}")
        for item in results[:5]:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title") or "").strip()
            url = str(item.get("url") or "").strip()
            snippet = str(item.get("snippet") or "").strip()
            parts = [part for part in [title, url] if part]
            if parts:
                lines.append("- " + " | ".join(parts))
            if snippet:
                lines.append("  " + snippet[:240])
        return "\n".join(lines) if len(lines) > 1 else ""
    if operator_ref == "builtin://web.browse":
        payload = dict(output_obj.get("output") or {}) if isinstance(output_obj.get("output"), dict) else {}
        url = str(payload.get("url") or output_obj.get("url") or "").strip()
        text = str(payload.get("reply") or output_obj.get("reply") or output_obj.get("text") or "").strip()
        if not text:
            return ""
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()][:24]
        header = f"WEB PAGE SNAPSHOT {url}" if url else "WEB PAGE SNAPSHOT"
        return header + "\n" + "\n".join(lines) if lines else ""
    if operator_ref == "builtin://research.run":
        summary = str(output_obj.get("summary") or "").strip()
        citations = output_obj.get("citations")
        lines = ["RESEARCH REPORT"]
        if summary:
            lines.extend([ln.strip() for ln in summary.splitlines() if ln.strip()][:6])
        if isinstance(citations, list):
            for item in citations[:5]:
                if not isinstance(item, dict):
                    continue
                title = str(item.get("title") or "").strip()
                url = str(item.get("url") or "").strip()
                parts = [part for part in [str(item.get("id") or "").strip(), title, url] if part]
                if parts:
                    lines.append("- " + " | ".join(parts))
        return "\n".join(lines) if len(lines) > 1 else ""
    return ""


def _summarize_step_arguments(*, operator_ref: str, arguments: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(arguments, dict):
        return {}
    if operator_ref == "builtin://shell.exec":
        out: dict[str, Any] = {}
        command = str(arguments.get("command") or "").strip()
        cwd = str(arguments.get("cwd") or "").strip()
        if command:
            out["command"] = command
        if cwd:
            out["cwd"] = cwd
        return out
    if operator_ref == "builtin://memory.search":
        out = {}
        query = str(arguments.get("query") or "").strip()
        if query:
            out["query"] = query
        intent = str(arguments.get("intent") or "").strip()
        if intent:
            out["intent"] = intent
        if arguments.get("limit") is not None:
            try:
                out["limit"] = int(arguments.get("limit"))
            except Exception:
                pass
        kinds = arguments.get("kinds")
        if isinstance(kinds, list):
            compact_kinds = [str(item).strip() for item in kinds if str(item).strip()]
            if compact_kinds:
                out["kinds"] = compact_kinds[:8]
        scope = arguments.get("scope")
        if isinstance(scope, dict):
            compact_scope = {
                key: str(scope.get(key) or "").strip()
                for key in ("workspace_id", "conversation_id", "project_id")
                if str(scope.get(key) or "").strip()
            }
            if compact_scope:
                out["scope"] = compact_scope
        return out
    if operator_ref == "builtin://web.search":
        out: dict[str, Any] = {}
        query = str(arguments.get("query") or "").strip()
        if query:
            out["query"] = query
        if arguments.get("limit") is not None:
            try:
                out["limit"] = int(arguments.get("limit"))
            except Exception:
                pass
        return out
    if operator_ref == "builtin://web.browse":
        url = str(arguments.get("url") or "").strip()
        return {"url": url} if url else {}
    if operator_ref == "builtin://research.run":
        out: dict[str, Any] = {}
        objective = str(arguments.get("objective") or "").strip()
        if objective:
            out["objective"] = objective
        depth = str(arguments.get("depth") or "").strip()
        if depth:
            out["depth"] = depth
        if arguments.get("min_sources") is not None:
            try:
                out["min_sources"] = int(arguments.get("min_sources"))
            except Exception:
                pass
        return out
    return {}


def _build_research_observation_capsule(research_pack: dict[str, Any] | None) -> str:
    if not isinstance(research_pack, dict):
        return ""
    query_history = research_pack.get("query_history")
    visited_sources = research_pack.get("visited_sources")
    citations = research_pack.get("final_citation_set")
    gaps = research_pack.get("gaps")
    if not isinstance(query_history, list) and not isinstance(visited_sources, list):
        return ""
    lines = [
        "RESEARCH EVIDENCE PACK",
        f"research_depth={str(research_pack.get('research_depth') or 'lookup')}",
        f"citation_required={bool(research_pack.get('citation_required'))}",
    ]
    if isinstance(query_history, list):
        for item in query_history[:4]:
            if not isinstance(item, dict):
                continue
            query = str(item.get("query") or "").strip()
            if not query:
                continue
            lines.append(
                f"- query={query} | status={str(item.get('status') or 'unknown')} | results={int(item.get('result_count') or 0)}"
            )
    if isinstance(citations, list):
        for item in citations[:4]:
            if not isinstance(item, dict):
                continue
            url = str(item.get("url") or "").strip()
            title = str(item.get("title") or "").strip()
            if url or title:
                lines.append(f"- citation={title or url} | {url}")
    if isinstance(gaps, list):
        for gap in gaps[:3]:
            text = str(gap or "").strip()
            if text:
                lines.append(f"! {text}")
    return "\n".join(lines)


def _pick_planner_backend(*, backend_name: str, remote_calls_armed: bool, allow_network_egress: bool):
    name = str(backend_name or "local_mock").strip().lower()
    if name == "local_mock":
        return LocalMockLLMBackend()
    if name == "codex_oauth":
        provider = OpenAICodexOAuthProvider(
            remote_calls_armed=bool(remote_calls_armed),
            allow_network_egress=bool(allow_network_egress),
        )
        return CodexOAuthLLMBackend(provider)
    if name == "doubao_ark":
        return DoubaoArkLLMBackend()
    if name == "minimax":
        return MiniMaxLLMBackend()
    raise ValueError(f"unknown backend: {backend_name}")


def _planner_backend_gate_error(
    *,
    planner_mode: str,
    backend_name: str,
    remote_calls_armed: bool,
    allow_network_egress: bool,
    replay_mode: bool,
) -> str | None:
    if str(planner_mode or "").strip().lower() != "llm":
        return None
    name = str(backend_name or "local_mock").strip().lower()
    if name == "local_mock":
        return None
    if replay_mode:
        return "E_REPLAY_REMOTE_DISABLED"
    if not remote_calls_armed:
        return "E_REMOTE_CALL_NOT_ARMED"
    if not allow_network_egress:
        return "E_NETWORK_EGRESS_DENY"
    return None


def _llm_plan_decision(
    *,
    req: AssistantLoopRequest,
    compiled_query: dict[str, Any],
    evidence: FileEvidenceStore,
    trace_log: FileTraceLogger,
) -> tuple[bool, list[str]] | tuple[None, list[str], str]:
    """Return (should_write, evidence_refs) or (None, evidence_refs, error_code) on fail-closed error."""
    planner_backend = str(req.planner_backend or req.backend or "local_mock")
    backend = _pick_planner_backend(
        backend_name=planner_backend,
        remote_calls_armed=bool(req.remote_calls_armed),
        allow_network_egress=bool(req.allow_network_egress),
    )
    safety = LLMSafetyGate(
        remote_calls_armed=bool(req.remote_calls_armed),
        allow_network_egress=bool(req.allow_network_egress),
        requires_human_approval=False,
        approved_by_human=bool(req.approved_by_human),
        replay_mode=bool(req.replay_mode),
    )

    prompt = "\n".join(
        [
            "You are planning a minimal assistant loop. Return ONLY JSON.",
            "",
            "SOLUTION QUERY",
            json.dumps(compiled_query.get("solution_query") or {}, ensure_ascii=False, sort_keys=True),
            "",
            "TASK ENVELOPE",
            str(compiled_query.get("prompt_envelope") or "").strip(),
            "",
            "DECISION",
            "Set should_write=true only when the task explicitly asks to remember/save durable information.",
            "Do not infer memory persistence from generic summarization or one-off assistance.",
        ]
    )
    schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["should_write"],
        "properties": {"should_write": {"type": "boolean"}},
    }

    try:
        out = backend.complete_json(prompt=prompt, json_schema=schema, safety=safety, model_id=req.model)
    except LLMCallError as e:
        err_ref = evidence.add_json(
            {"schema_version": "1.0.0", "ok": False, "error_code": e.error_code, "message": str(e)},
            kind="error",
        )
        trace_log.emit(
            TraceEvent(
                schema_version="1.0.0",
                ctx=req.trace,  # type: ignore[arg-type]
                event_type="ERROR",
                ts=_utc_iso(),
                evidence_refs=(err_ref,),
                data={"component": "assistant_loop", "stage": "planner", "backend": planner_backend, "error_code": e.error_code},
            )
        )
        return None, [err_ref.ref], e.error_code

    prompt_ref = evidence.add_text(prompt, kind="llm_io")
    out_ref = evidence.add_json(
        {"schema_version": "1.0.0", "planner_backend": planner_backend, "output": out},
        kind="llm_io",
    )
    trace_log.emit(
        TraceEvent(
            schema_version="1.0.0",
            ctx=req.trace,  # type: ignore[arg-type]
            event_type="RETRIEVAL_CHAIN",  # type: ignore[arg-type]
            ts=_utc_iso(),
            evidence_refs=(prompt_ref, out_ref),
            data={"component": "assistant_loop", "stage": "planner", "backend": planner_backend},
        )
    )

    should_write = False
    if isinstance(out, dict):
        should_write = bool(out.get("should_write"))
    return should_write, [prompt_ref.ref, out_ref.ref]


def _build_followup_plan(*, query: str, ok: bool, error_code: Optional[str]) -> dict[str, Any]:
    # Constraint: deterministic (no ts), bounded (<=5), plan-only (no execution).
    steps: list[dict[str, Any]] = []

    steps.append(
        {
            "id": "review_output",
            "kind": "review",
            "description": "Review assistant final_output for correctness/completeness against the user query.",
        }
    )

    if not ok:
        steps.append(
            {
                "id": "triage_error",
                "kind": "debug",
                "description": f"Triage failure and map error_code={error_code or 'E_UNKNOWN'} to next action (retry, policy, or bugfix).",
            }
        )

    if _should_suggest_remote_lookup(query):
        steps.append(
            {
                "id": "consider_remote_lookup",
                "kind": "decision",
                "description": "If external/up-to-date info is required, rerun with an allowed remote backend after double-gate + HITL approvals.",
            }
        )

    steps.append(
        {
            "id": "package_evidence",
            "kind": "hygiene",
            "description": "If sharing results, bundle the relevant evidence/trace into a minimal reproducible pack.",
        }
    )

    steps = steps[:5]
    return {
        "schema_version": "1.0.0",
        "type": "assistant_loop_followup_plan",
        "plan_only": True,
        "constraints": {"deterministic": True, "max_steps": 5, "no_ts": True},
        "query": query,
        "ok": bool(ok),
        "error_code": error_code,
        "steps": steps,
    }


def _classify_operator_resolution(*, steps: list[dict[str, Any]]) -> str:
    refs = [
        str(st.get("operator_ref") or "").strip()
        for st in steps
        if isinstance(st, dict)
    ]
    refs = [ref for ref in refs if ref]
    if not refs:
        return "skill"
    non_builtin = [ref for ref in refs if not ref.startswith("builtin://")]
    if non_builtin:
        return "skill"
    return "tool_composition"


def _is_retryable_hypothesis_error(error_code: Optional[str]) -> bool:
    return str(error_code or "").strip() in {
        "E_TIMEOUT",
        "E_HITL_REQUIRED",
        "E_DEADLINE_EXCEEDED",
        "E_TOKEN_BUDGET_EXHAUSTED",
        "E_NO_PROGRESS",
        "E_BUDGET_EXHAUSTED",
        "E_REPLAN_BUDGET_EXHAUSTED",
    }


def _map_hypothesis_result(*, verify_report: dict[str, Any], error_code: Optional[str]) -> str:
    if bool(error_code):
        return "partial" if _is_retryable_hypothesis_error(error_code) else "rejected"
    if bool(verify_report.get("acceptance_pass")):
        return "confirmed"
    failures = verify_report.get("failures")
    if isinstance(failures, list) and failures:
        return "rejected"
    return "partial"


def _derive_hypothesis_revision(*, verify_report: dict[str, Any], error_code: Optional[str]) -> str:
    failures = verify_report.get("failures")
    if isinstance(failures, list):
        for failure in failures:
            if not isinstance(failure, dict):
                continue
            remediation = str(failure.get("remediation") or "").strip()
            if remediation:
                return remediation
            reason = str(failure.get("reason") or "").strip()
            if reason:
                return reason
    return f"error_code={error_code or 'none'}"


_INFRA_HYPOTHESIS_ERROR_CODES = {
    "E_EXECUTION_FAILED",
    "E_PROVIDER_BAD_RESPONSE",
    "E_PROVIDER_AUTH_MISSING",
    "E_MODEL_ID_REQUIRED",
    "E_REMOTE_CALL_NOT_ARMED",
    "E_NETWORK_EGRESS_DENY",
    "E_REPLAY_REMOTE_DISABLED",
    "E_HITL_REQUIRED",
    "E_DEADLINE_EXCEEDED",
    "E_TOKEN_BUDGET_EXHAUSTED",
    "E_NO_PROGRESS",
    "E_TIMEOUT",
    "E_BUDGET_EXHAUSTED",
}

_QUERY_GUARD_IGNORED_ERROR_CODES = _INFRA_HYPOTHESIS_ERROR_CODES | {
    "E_REPLAN_BUDGET_EXHAUSTED",
}


def _is_infra_error_code(error_code: Optional[str]) -> bool:
    return str(error_code or "").strip() in _INFRA_HYPOTHESIS_ERROR_CODES


def _is_structural_runtime_error_code(error_code: Optional[str]) -> bool:
    return str(error_code or "").strip() in {
        "E_TASK_DEPENDENCY_CYCLE",
        "E_TASK_DEPENDENCY_UNRESOLVED",
        "E_TASK_BATCH_INVALID",
        "E_WORKER_SPLIT_REQUIRES_LEADER",
        "E_ACTION_OPERATOR_UNSUPPORTED",
        "E_COMMUNICATOR_ACTION_INVALID",
        "E_MESSAGE_TASK_PHASE_VIOLATION",
    }


def _latest_failed_phase_summary(exec_summaries: list[dict[str, Any]]) -> dict[str, str] | None:
    for item in reversed(exec_summaries):
        if not isinstance(item, dict):
            continue
        phase = str(item.get("internal_role_phase") or item.get("source_phase") or "").strip()
        status = str(item.get("status") or "").strip()
        code = str(item.get("error_code") or "").strip()
        if not phase:
            continue
        if code or status not in {"", "accepted"}:
            return {
                "phase": phase,
                "status": status or "failed",
                "error_code": code,
            }
    return None


def _build_terminal_communicator_request(
    *,
    terminal_stage: str,
    error_code: Optional[str],
    exec_summaries: list[dict[str, Any]],
    query_text: str,
    verified_failure_summary: dict[str, Any] | None = None,
) -> str:
    if terminal_stage == "need_context":
        return (
            "Ask the user for the missing context needed to continue safely. "
            "Do not guess the missing facts. Final delivery MUST be send_message."
        )
    if terminal_stage != "blocker":
        return (
            "Prepare the final user-visible communication using only verified state. "
            "No further tool actions are allowed in this phase; if verified state is still insufficient, explain the blocker or uncertainty in the final message instead of planning more actions. "
            "You MAY mirror the outgoing text in reply for streaming, but final delivery MUST be send_message."
        )

    if isinstance(verified_failure_summary, dict):
        failed_phase = str(verified_failure_summary.get("failed_phase") or "unknown").strip() or "unknown"
        stable_error_code = str(verified_failure_summary.get("primary_error_code") or error_code or "E_EXECUTION_FAILED").strip() or "E_EXECUTION_FAILED"
        reason_class = str(verified_failure_summary.get("reason_class") or "runtime_failure").strip() or "runtime_failure"
        return (
            "Prepare a blocker explanation for the user using only verified state plus the Verified Failure Summary below. "
            "You MAY paraphrase the allowed_user_visible_facts, but MUST NOT introduce any new root-cause label, provider diagnosis, or remediation that is absent from that summary. "
            "If the summary includes disallowed_inferences, you MUST respect them even when raw observation text contains lower-level details. "
            f"RUNTIME_FAILURE phase={failed_phase} error_code={stable_error_code} reason_class={reason_class}. "
            f"USER_REQUEST={query_text}. "
            "Final delivery MUST be send_message."
        )

    failed = _latest_failed_phase_summary(exec_summaries=exec_summaries) or {}
    failed_phase = str(failed.get("phase") or "unknown").strip() or "unknown"
    failed_status = str(failed.get("status") or "failed").strip() or "failed"
    stable_error_code = str(error_code or failed.get("error_code") or "E_EXECUTION_FAILED").strip() or "E_EXECUTION_FAILED"
    if _is_infra_error_code(stable_error_code):
        next_step = "Ask the user to retry. If timeout happened, mention that increasing deadline_ms or switching to a faster model/backend may help."
        return (
            "Prepare a blocker explanation for the user using only verified state plus the runtime failure metadata below. "
            "Do NOT invent a blocked subtask, prior execution detail, or missing task description that is not present in verified state. "
            "Do NOT reframe this as a generic context gap if the failure happened before intent/planning completed. "
            f"RUNTIME_FAILURE phase={failed_phase} status={failed_status} error_code={stable_error_code}. "
            f"USER_REQUEST={query_text}. "
            "Explain plainly that the assistant runtime hit an infrastructure failure before it could finish processing the request, "
            "name the failed phase and error code, and give concrete next steps. "
            f"{next_step} Final delivery MUST be send_message."
        )
    if _is_structural_runtime_error_code(stable_error_code):
        return (
            "Prepare a blocker explanation for the user using only verified state plus the runtime failure metadata below. "
            "Do NOT ask for missing task details unless verified state actually proves a user-side context gap. "
            f"RUNTIME_FAILURE phase={failed_phase} status={failed_status} error_code={stable_error_code}. "
            f"USER_REQUEST={query_text}. "
            "Explain plainly that the assistant produced an invalid or unfinished internal action plan before completing the request, "
            "name the failed phase and error code, and ask the user to retry while the system path is being repaired. "
            "Final delivery MUST be send_message."
        )
    return (
        "Prepare the blocker explanation for the user using only verified state. "
        "Be explicit about what failed and what the user should do next. "
        "Final delivery MUST be send_message."
    )


def _recent_failure_texts_for_query_guard(records: list[HypothesisRecord]) -> list[str]:
    filtered: list[str] = []
    for rec in records:
        revision = str(rec.revision or "").strip()
        if revision.startswith("error_code="):
            code = revision.split("=", 1)[1].strip()
            if code in _QUERY_GUARD_IGNORED_ERROR_CODES:
                continue
        filtered.append(str(rec.hypothesis or "").strip())
    return filtered


def _recent_failure_texts_for_query_guard_with_evidence(
    *,
    records: list[HypothesisRecord],
    evidence: FileEvidenceStore,
) -> list[str]:
    filtered: list[str] = []
    for rec in records:
        if _is_infra_only_hypothesis_record(record=rec, evidence=evidence):
            continue
        filtered.append(str(rec.hypothesis or "").strip())
    return filtered


def _is_infra_only_hypothesis_record(*, record: HypothesisRecord, evidence: FileEvidenceStore) -> bool:
    revision = str(record.revision or "").strip()
    if revision.startswith("error_code="):
        code = revision.split("=", 1)[1].strip()
        if code in _QUERY_GUARD_IGNORED_ERROR_CODES:
            return True
    for ref in reversed(tuple(record.verification_evidence_refs)):
        blob = evidence.get_blob(str(ref))
        if blob is None or blob.content_type != "application/json":
            continue
        try:
            obj = json.loads(blob.content.decode("utf-8", errors="replace"))
        except Exception:
            continue
        if not isinstance(obj, dict):
            continue
        if str(obj.get("type") or "").strip() != "assistant_loop_result":
            continue
        error_code = str(obj.get("error_code") or "").strip()
        steps = list(obj.get("steps") or []) if isinstance(obj.get("steps"), list) else []
        has_accepted_step = any(str(step.get("status") or "").strip() == "accepted" for step in steps if isinstance(step, dict))
        if error_code in _QUERY_GUARD_IGNORED_ERROR_CODES:
            return True
        if error_code and not has_accepted_step:
            return True
        return False
    return False


def _persist_runtime_snapshot(
    *,
    snapshot_store: FileRuntimeSnapshotStore,
    req: AssistantLoopRequest,
    compiled_query: dict[str, Any] | None,
    effective_query: str,
    interaction_mode: str,
    error_code: Optional[str],
    summary: str,
    delivery_state: Optional[str] = None,
    active_submission_id: str | None = None,
    active_submission_generation: int | None = None,
) -> None:
    if not str(req.conversation_id or "").strip():
        return
    query_obj = dict(compiled_query or {})
    intent_recovery = dict(query_obj.get("intent_recovery") or {}) if isinstance(query_obj.get("intent_recovery"), dict) else {}
    context_planes = dict(query_obj.get("context_planes") or {}) if isinstance(query_obj.get("context_planes"), dict) else {}
    recovery_plane = (
        dict(context_planes.get("intent_recovery_plane") or {})
        if isinstance(context_planes.get("intent_recovery_plane"), dict)
        else {}
    )
    pending_contract = (
        _build_pending_contract(
            compiled_query=query_obj,
            effective_query=effective_query,
            interaction_mode=interaction_mode,
        )
        if query_obj
        else None
    )
    effective_delivery_state = str(delivery_state or ("done" if error_code is None else "blocker")).strip() or "done"
    snapshot_store.put(
        workspace_id=str(req.workspace_id),
        conversation_id=str(req.conversation_id),
        active_project_id=str(recovery_plane.get("active_project_id") or "").strip() or None,
        expected_next_user_act=("followup_or_new_task" if effective_delivery_state == "done" else "clarify_or_retry"),
        last_clarification_question=(
            str(summary or "").strip() or "Please clarify the intended task"
            if effective_delivery_state == "need_context"
            else ("Please clarify the intended task" if bool(intent_recovery.get("needs_model_fallback")) else None)
        ),
        blocker=(
            {
                "summary": str(summary or "").strip(),
                "reason": str(summary or "").strip(),
            }
            if effective_delivery_state in {"blocker", "need_context"} or error_code is not None
            else None
        ),
        last_delivery_state=effective_delivery_state,
        last_delivery_summary=str(summary or "").strip() or None,
        interaction_mode_preference=str(interaction_mode or "task").strip() or "task",
        pending_contract=pending_contract,
        last_user_query=str(req.query).strip() or None,
        last_user_query_at_utc=str(req.message_received_at_utc or "").strip() or _utc_iso(),
        active_submission_id=str(active_submission_id or "").strip() or None,
        active_submission_generation=(
            max(1, int(active_submission_generation or 1))
            if str(active_submission_id or "").strip()
            else None
        ),
    )

async def run_assistant_loop_async(req: AssistantLoopRequest) -> AssistantLoopResult:
    """Async wrapper that actually executes the plan."""
    if req.trace is None:
        raise ValueError("trace is required (TraceContext)")
    message_received_at_utc = str(req.message_received_at_utc or "").strip() or _utc_iso()

    root = _repo_root()
    data_dir = Path(req.data_dir)
    evidence = FileEvidenceStore(data_dir=data_dir)
    trace_log = FileTraceLogger(data_dir=data_dir)
    runtime_event_log = FileRuntimeEventLog(data_dir=data_dir)
    hypothesis_store = FileHypothesisStore(data_dir=data_dir)
    theorem_store = FileTheoremStore(data_dir=data_dir)
    profile_store = FileAgentProfileStore(data_dir=data_dir)
    soul_store = FileSoulProfileStore(data_dir=data_dir)
    context_cache = FileContextPlaneCache(data_dir=data_dir)
    snapshot_store = FileRuntimeSnapshotStore(data_dir=data_dir)
    memory_consolidator = MemoryConsolidatorV2(data_dir=data_dir)

    assistant_skill_dir = req.assistant_skill_dir or (root / "examples" / "skills" / "personal_assistant_brief")
    keys_dir = req.public_keys_dir or (root / "examples" / "keys")

    planner_evidence_refs: list[str] = []
    recent_rejected = hypothesis_store.list_recent(workspace_id=str(req.workspace_id), limit=5, result="rejected")
    recent_confirmed = hypothesis_store.list_recent(workspace_id=str(req.workspace_id), limit=5, result="confirmed")
    agent_profile = profile_store.get_or_default(agent_id=str(req.agent_id or "assistant_loop"))
    execution_axiom_ids = [
        str(x.get("id") or "").strip()
        for x in agent_profile.get("execution_axioms", [])
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
    soul_profile = soul_store.get(soul_profile_id=str(agent_profile.get("soul_profile_id") or "")) or {
        "soul_profile_id": str(agent_profile.get("soul_profile_id") or "default_assistant"),
        "identity_summary": f"agent:{str(agent_profile.get('agent_id') or '').strip() or 'assistant'}",
        "communication_defaults": {"style": ["clear", "honest", "concise"]},
        "principles": [],
        "boundary_rules": [],
    }
    recent_failure_texts = _recent_failure_texts_for_query_guard_with_evidence(
        records=recent_rejected,
        evidence=evidence,
    )
    recent_success_texts = [rec.revision or rec.hypothesis for rec in recent_confirmed]
    runtime_snapshot = None
    if str(req.conversation_id or "").strip():
        runtime_snapshot = snapshot_store.get(
            workspace_id=str(req.workspace_id),
            conversation_id=str(req.conversation_id),
        )
    global_capsule = build_global_capsule_v1(
        workspace_id=str(req.workspace_id),
        soul_profile=soul_profile,
    )
    active_project = resolve_active_project_v1(
        query_text=str(req.query),
        runtime_snapshot=(
            {
                "active_project_id": (runtime_snapshot.active_project_id if runtime_snapshot is not None else None),
                "pending_contract": (runtime_snapshot.pending_contract if runtime_snapshot is not None else None),
            }
        ),
        memory_context=req.memory_context,
    )
    project_capsule = build_project_capsule_v1(
        active_project_id=str(active_project.get("active_project_id") or "").strip() or None,
        memory_context=req.memory_context,
    )
    theorem_candidates = [
        {
            "theorem_id": rec.theorem_id,
            "theorem_type": rec.theorem_type,
            "summary": rec.summary,
            "operator_hints": list(rec.operator_hints),
        }
        for rec in theorem_store.search(
            workspace_id=str(req.workspace_id),
            query_text=str(req.query),
            project_id=(project_capsule.project_id if project_capsule is not None else None),
            limit=5,
        )
    ]
    cached_base = context_cache.get_base_pack(
        agent_id=str(req.agent_id or "assistant_loop"),
        workspace_id=str(req.workspace_id),
        execution_axiom_ids=execution_axiom_ids,
        communication_axiom_ids=communication_axiom_ids,
        constraint_ids=active_constraint_ids,
        soul_profile_id=str(soul_profile.get("soul_profile_id") or "").strip() or None,
        recent_failures=recent_failure_texts,
        recent_success_patterns=recent_success_texts,
    )
    if cached_base is None:
        context_planes = build_context_plane_pack_v1(
            query_text=str(req.query),
            workspace_id=str(req.workspace_id),
            trace=req.trace,
            execution_axiom_ids=execution_axiom_ids,
            communication_axiom_ids=communication_axiom_ids,
            active_constraint_ids=active_constraint_ids,
            recent_failures=recent_failure_texts,
            recent_success_patterns=recent_success_texts,
            message_received_at_utc=message_received_at_utc,
            soul_profile_id=str(soul_profile.get("soul_profile_id") or "").strip() or None,
            global_capsule={
                "schema_version": global_capsule.schema_version,
                "workspace_id": global_capsule.workspace_id,
                "soul_profile_id": global_capsule.soul_profile_id,
                "identity_summary": global_capsule.identity_summary,
                "communication_style": list(global_capsule.communication_style),
            },
            project_capsule=(
                {
                    "schema_version": project_capsule.schema_version,
                    "project_id": project_capsule.project_id,
                    "title": project_capsule.title,
                    "summary": project_capsule.summary,
                    "evidence_refs": list(project_capsule.evidence_refs),
                }
                if project_capsule is not None
                else None
            ),
            active_project_id=(runtime_snapshot.active_project_id if runtime_snapshot is not None else None),
            last_pending_task=(
                str((runtime_snapshot.pending_contract or {}).get("objective") or "").strip()
                if runtime_snapshot is not None and isinstance(runtime_snapshot.pending_contract, dict)
                else None
            ),
            expected_next_user_act=(runtime_snapshot.expected_next_user_act if runtime_snapshot is not None else None),
            last_clarification_question=(
                runtime_snapshot.last_clarification_question if runtime_snapshot is not None else None
            ),
            last_delivery_state=(runtime_snapshot.last_delivery_state if runtime_snapshot is not None else None),
            last_delivery_summary=(runtime_snapshot.last_delivery_summary if runtime_snapshot is not None else None),
            pending_contract=(runtime_snapshot.pending_contract if runtime_snapshot is not None else None),
            blocker=(runtime_snapshot.blocker if runtime_snapshot is not None else None),
            last_user_query=(runtime_snapshot.last_user_query if runtime_snapshot is not None else None),
            last_user_query_at_utc=(runtime_snapshot.last_user_query_at_utc if runtime_snapshot is not None else None),
        )
        context_cache.put_base_pack(
            agent_id=str(req.agent_id or "assistant_loop"),
            workspace_id=str(req.workspace_id),
            execution_axiom_ids=execution_axiom_ids,
            communication_axiom_ids=communication_axiom_ids,
            constraint_ids=active_constraint_ids,
            soul_profile_id=str(soul_profile.get("soul_profile_id") or "").strip() or None,
            recent_failures=recent_failure_texts,
            recent_success_patterns=recent_success_texts,
            base_pack={
                "communication_plane": dict(context_planes["communication_plane"]),
                "retrospective_plane": dict(context_planes["retrospective_plane"]),
                "constraint_plane": dict(context_planes["constraint_plane"]),
            },
        )
    else:
        context_planes = {
            "execution_plane": build_context_plane_pack_v1(
                query_text=str(req.query),
                workspace_id=str(req.workspace_id),
                trace=req.trace,
                execution_axiom_ids=execution_axiom_ids,
                communication_axiom_ids=communication_axiom_ids,
                active_constraint_ids=active_constraint_ids,
                recent_failures=recent_failure_texts,
                recent_success_patterns=recent_success_texts,
                message_received_at_utc=message_received_at_utc,
                soul_profile_id=str(soul_profile.get("soul_profile_id") or "").strip() or None,
                global_capsule={
                    "schema_version": global_capsule.schema_version,
                    "workspace_id": global_capsule.workspace_id,
                    "soul_profile_id": global_capsule.soul_profile_id,
                    "identity_summary": global_capsule.identity_summary,
                    "communication_style": list(global_capsule.communication_style),
                },
                project_capsule=(
                    {
                        "schema_version": project_capsule.schema_version,
                        "project_id": project_capsule.project_id,
                        "title": project_capsule.title,
                        "summary": project_capsule.summary,
                        "evidence_refs": list(project_capsule.evidence_refs),
                    }
                    if project_capsule is not None
                    else None
                ),
                active_project_id=(runtime_snapshot.active_project_id if runtime_snapshot is not None else None),
                last_pending_task=(
                    str((runtime_snapshot.pending_contract or {}).get("objective") or "").strip()
                    if runtime_snapshot is not None and isinstance(runtime_snapshot.pending_contract, dict)
                    else None
                ),
                expected_next_user_act=(runtime_snapshot.expected_next_user_act if runtime_snapshot is not None else None),
                last_clarification_question=(
                    runtime_snapshot.last_clarification_question if runtime_snapshot is not None else None
                ),
                last_delivery_state=(runtime_snapshot.last_delivery_state if runtime_snapshot is not None else None),
                last_delivery_summary=(runtime_snapshot.last_delivery_summary if runtime_snapshot is not None else None),
                pending_contract=(runtime_snapshot.pending_contract if runtime_snapshot is not None else None),
                blocker=(runtime_snapshot.blocker if runtime_snapshot is not None else None),
            )["execution_plane"],
            "communication_plane": dict(cached_base.get("communication_plane") or {}),
            "retrospective_plane": dict(cached_base.get("retrospective_plane") or {}),
            "constraint_plane": dict(cached_base.get("constraint_plane") or {}),
            "intent_recovery_plane": {
                "active_project_id": (runtime_snapshot.active_project_id if runtime_snapshot is not None else None),
                "last_pending_task": (
                    str((runtime_snapshot.pending_contract or {}).get("objective") or "").strip()
                    if runtime_snapshot is not None and isinstance(runtime_snapshot.pending_contract, dict)
                    else None
                ),
                "expected_next_user_act": (
                    runtime_snapshot.expected_next_user_act if runtime_snapshot is not None else None
                ),
                "last_clarification_question": (
                    runtime_snapshot.last_clarification_question if runtime_snapshot is not None else None
                ),
                "last_delivery_state": (
                    runtime_snapshot.last_delivery_state if runtime_snapshot is not None else None
                ),
                "last_delivery_summary": (
                    runtime_snapshot.last_delivery_summary if runtime_snapshot is not None else None
                ),
                "pending_contract": (runtime_snapshot.pending_contract if runtime_snapshot is not None else None),
                "blocker": (runtime_snapshot.blocker if runtime_snapshot is not None else None),
                "last_user_query": (runtime_snapshot.last_user_query if runtime_snapshot is not None else None),
                "last_user_query_at_utc": (
                    runtime_snapshot.last_user_query_at_utc if runtime_snapshot is not None else None
                ),
            },
        }
    agent_profile_ref = evidence.add_json(agent_profile, kind="policy")
    context_planes_ref = evidence.add_json(context_planes, kind="snapshot")
    planner_evidence_refs.extend([agent_profile_ref.ref, context_planes_ref.ref])
    effective_runtime_capabilities = (
        dict(req.effective_runtime_capabilities or {})
        if isinstance(req.effective_runtime_capabilities, dict) and req.effective_runtime_capabilities
        else build_effective_runtime_capabilities_v1(
            requested_capabilities=sorted(_capability_name_set(req.capabilities)),
            allow_network_egress=bool(req.allow_network_egress),
            submitter="runtime.direct",
            attachment_media_kinds=_attachment_media_kinds(req.attachments),
            backend=str(req.backend or "local_mock"),
            model=req.model,
            planner_backend=req.planner_backend,
            planner_model=req.model,
            intent_backend=req.intent_backend,
            intent_model=req.intent_model,
            communicator_backend=req.communicator_backend,
            communicator_model=req.communicator_model,
        )
    )
    query_compile = compile_query_for_assistant_loop(
        query_text=str(req.query),
        req_trace=req.trace,
        workspace_id=str(req.workspace_id),
        effective_runtime_capabilities=effective_runtime_capabilities,
        deadline_ms=int(req.deadline_ms),
        data_dir=str(req.data_dir),
        agent_profile=agent_profile,
        soul_profile=soul_profile,
        context_planes=context_planes,
        message_received_at_utc=message_received_at_utc,
        response_language=req.response_language,
        theorem_candidates=theorem_candidates,
        attachments=req.attachments,
        external_evidence_policy_override=(
            dict(req.external_evidence_policy_override)
            if isinstance(req.external_evidence_policy_override, dict)
            else None
        ),
    )
    axiom_review_candidate = make_axiom_review_candidate(
        agent_profile=agent_profile,
        context_planes=context_planes,
    )
    query_ref = evidence.add_json(query_compile.query, kind="routing")
    query_verify_ref = evidence.add_json(query_compile.verification_report, kind="policy")
    planner_evidence_refs.extend([query_ref.ref, query_verify_ref.ref])
    if axiom_review_candidate is not None:
        planner_evidence_refs.append(evidence.add_json(axiom_review_candidate, kind="artifact_draft").ref)
    trace_log.emit(
        TraceEvent(
            schema_version="1.0.0",
            ctx=req.trace,
            event_type="ROUTED",
            ts=_utc_iso(),
            evidence_refs=(query_ref, query_verify_ref),
            data={"component": "query_gated_runtime", "mode": query_compile.mode},
        )
    )
    task_id = ""
    if isinstance(query_compile.query, dict):
        task_id = str(((query_compile.query.get("task_envelope") or {}).get("task_id")) or "").strip()
    if not task_id:
        task_id = f"task_{req.trace.trace_id}_{req.trace.turn_id}"
    compiled_task_bundle = (
        dict(query_compile.query.get("task_bundle") or {})
        if isinstance(query_compile.query.get("task_bundle"), dict)
        else {}
    )
    compiled_task_execution_policy = (
        dict(query_compile.query.get("task_execution_policy") or {})
        if isinstance(query_compile.query.get("task_execution_policy"), dict)
        else {}
    )
    compiled_file_refs = list(query_compile.query.get("file_refs") or []) if isinstance(query_compile.query.get("file_refs"), list) else []
    runtime_graph_seed = (
        dict(query_compile.query.get("runtime_graph") or {})
        if isinstance(query_compile.query.get("runtime_graph"), dict)
        else {}
    )
    interaction_mode = str(query_compile.query.get("interaction_mode") or "task").strip() or "task"
    runtime_graph_id = (
        str(req.graph_id or "").strip()
        or str(runtime_graph_seed.get("graph_id") or "").strip()
        or str(req.trace.turn_id or "").strip()
        or str(task_id)
    )
    kernel_graph_id = (
        str(req.graph_id or "").strip()
        or str(req.conversation_id or "").strip()
        or str(req.trace.trace_id or "").strip()
        or str(runtime_graph_id)
    )
    runtime_session: RuntimeGraphSession = NullRuntimeGraphSession()
    if not bool(req.replay_mode) and runtime_graph_id:
        runtime_session = TaskGraphRuntimeGraphSession.bootstrap_for_assistant_loop(
            RuntimeGraphSchedulerBootstrap(
                data_dir=str(data_dir),
                workspace_id=str(req.workspace_id),
                graph_id=runtime_graph_id,
                logical_task_id=task_id,
                query=str(req.query),
                objective=str(((query_compile.query.get("task_envelope") or {}).get("objective")) or req.query).strip() or str(req.query),
                trace_id=str(req.trace.trace_id),
                turn_id=str(req.trace.turn_id),
                conversation_id=str(req.conversation_id or ""),
                interaction_mode=interaction_mode,
                query_ref=str(query_ref.ref),
                active_plan_revision=int(runtime_graph_seed.get("active_plan_revision") or 0),
                task_bundle=(compiled_task_bundle if compiled_task_bundle else None),
                task_execution_policy=(compiled_task_execution_policy if compiled_task_execution_policy else None),
                file_refs=tuple(dict(item) for item in compiled_file_refs if isinstance(item, dict)),
                now_utc=_utc_iso(),
            )
        )
    execution_lane = _select_execution_lane(compiled_query=query_compile.query, interaction_mode=interaction_mode)
    execution_lane_policy = _resolved_execution_lane_policy(
        compiled_query=query_compile.query,
        execution_lane=execution_lane,
    )
    token_budget = (
        dict(query_compile.query.get("token_budget") or {})
        if isinstance(query_compile.query.get("token_budget"), dict)
        else _build_task_token_budget(execution_lane=execution_lane, deadline_ms=int(req.deadline_ms))
    )
    stop_policy = (
        dict(query_compile.query.get("stop_policy") or {})
        if isinstance(query_compile.query.get("stop_policy"), dict)
        else _build_task_stop_policy(execution_lane=execution_lane, deadline_ms=int(req.deadline_ms))
    )
    stop_policy["deadline_ms"] = max(
        1000,
        int(stop_policy.get("deadline_ms") or req.deadline_ms or 1000),
    )
    compiled_task_bundle["execution_lane"] = execution_lane
    compiled_task_bundle["token_budget"] = dict(token_budget)
    compiled_task_bundle["stop_policy"] = dict(stop_policy)
    compiled_task_execution_policy["execution_lane_policy"] = dict(execution_lane_policy)
    compiled_task_execution_policy["controller_execution_mode"] = "token_time_progress"
    compiled_task_execution_policy["stop_policy"] = dict(stop_policy)
    compiled_task_execution_policy["token_budget"] = dict(token_budget)
    kernel_task_service = (
        None
        if bool(req.replay_mode)
        else KernelTaskService.for_graph(
            data_dir=str(data_dir),
            workspace_id=str(req.workspace_id),
            graph_id=kernel_graph_id,
            max_parallel_workers=1,
        )
    )
    active_submission_ids = kernel_task_service.active_submission_ids() if kernel_task_service is not None else ()
    submission_id = f"submission_{req.trace.turn_id}"
    compiled_task_execution_policy["submission_id"] = submission_id
    ingress_decision = _classify_ingress_decision(
        query_text=str(req.query),
        message_received_at_utc=message_received_at_utc,
        runtime_snapshot=runtime_snapshot,
        active_submission_ids=active_submission_ids,
    )
    amendment_decisions: list[str] = []
    if ingress_decision == "AMEND_ACTIVE_SUBMISSION" and kernel_task_service is not None:
        for active_submission_id in active_submission_ids:
            supersede_result = kernel_task_service.supersede_submission(
                old_submission_id=active_submission_id,
                new_submission_id=submission_id,
                reason="user_amendment",
            )
            amendment_decisions.extend(["superseded" for _ in supersede_result.superseded_task_ids])
            amendment_decisions.extend(["hold" for _ in supersede_result.held_task_ids])
    routing_decision_ref = evidence.add_json(
        {
            "schema_version": "1.0.0",
            "type": "controller_routing_decision_v1",
            "task_id": task_id,
            "graph_id": kernel_graph_id,
            "submission_id": submission_id,
            "ingress_decision": ingress_decision,
            "execution_lane": execution_lane,
            "execution_lane_policy": dict(execution_lane_policy),
            "token_budget": dict(token_budget),
            "stop_policy": dict(stop_policy),
            "controller_execution_mode": "token_time_progress",
            "active_submission_ids": list(active_submission_ids),
            "amendment_decisions": list(amendment_decisions),
        },
        kind="routing",
    )
    planner_evidence_refs.append(routing_decision_ref.ref)
    if not query_compile.ok:
        error_code = str(query_compile.error_code or "E_QUERY_SCHEMA_INVALID")
        compile_summary = _derive_hypothesis_revision(
            verify_report=query_compile.verification_report,
            error_code=error_code,
        )
        runtime_session.record_compile_failure(
            error_code=error_code,
            query_ref=str(query_ref.ref),
            verification_ref=str(query_verify_ref.ref),
        )
        _emit_delivery_state(
            trace_log=trace_log,
            ctx=req.trace,
            task_id=task_id,
            state="blocker",
            summary="task compilation failed before execution",
            evidence_refs=(query_ref, query_verify_ref),
            error_code=error_code,
        )
        followup_plan = _build_followup_plan(query=req.query, ok=False, error_code=error_code)
        followup_ref = evidence.add_json(followup_plan, kind="artifact_draft")
        final_ref = evidence.add_json(
            {
                "schema_version": "1.0.0",
                "type": "assistant_loop_result",
                "ts": _utc_iso(),
                "ok": False,
                "error_code": error_code,
                "query_ref": query_ref.ref,
                "steps": [],
                "followup_plan_ref": followup_ref.ref,
            },
            kind="snapshot",
        )
        _persist_runtime_snapshot(
            snapshot_store=snapshot_store,
            req=req,
            compiled_query=query_compile.query,
            effective_query=str(query_compile.query.get("objective") or req.query).strip() or str(req.query),
            interaction_mode=str(query_compile.query.get("interaction_mode") or "task").strip() or "task",
            error_code=error_code,
            summary=compile_summary,
            active_submission_id=submission_id,
            active_submission_generation=1,
        )
        consolidated_refs: tuple[str, ...] = ()
        if not bool(req.replay_mode):
            consolidated_refs = memory_consolidator.consolidate_turn(
                workspace_id=str(req.workspace_id),
                conversation_id=str(req.conversation_id or "").strip() or None,
                project_id=None,
                query=str(req.query),
                reply_text="",
                error_code=error_code,
            )
        return AssistantLoopResult(
            ok=False,
            final_output=None,
            error_code=error_code,
            steps=[],
            trace=req.trace,
            evidence_refs=list(
                dict.fromkeys(planner_evidence_refs + [followup_ref.ref, final_ref.ref, *list(consolidated_refs)])
            ),
            followup_plan_ref=followup_ref.ref,
            followup_task_id=None,
            delivery_state="blocker",
            graph_id=kernel_graph_id or None,
        )
    query_mode = str(query_compile.mode)
    planner_gate_error = _planner_backend_gate_error(
        planner_mode=str(req.planner or ""),
        backend_name=str(req.planner_backend or req.backend or "local_mock"),
        remote_calls_armed=bool(req.remote_calls_armed),
        allow_network_egress=bool(req.allow_network_egress),
        replay_mode=bool(req.replay_mode),
    )
    if planner_gate_error is not None:
        err_ref = evidence.add_json(
            {
                "schema_version": "1.0.0",
                "ok": False,
                "error_code": planner_gate_error,
                "message": "planner backend gated before execution",
                "planner": str(req.planner or ""),
                "planner_backend": str(req.planner_backend or req.backend or "local_mock"),
            },
            kind="error",
        )
        planner_evidence_refs.append(err_ref.ref)
        trace_log.emit(
            TraceEvent(
                schema_version="1.0.0",
                ctx=req.trace,
                event_type="ERROR",
                ts=_utc_iso(),
                evidence_refs=(err_ref,),
                data={
                    "component": "assistant_loop",
                    "stage": "planner",
                    "backend": str(req.planner_backend or req.backend or "local_mock"),
                    "error_code": planner_gate_error,
                },
            )
        )
        compile_summary = _derive_hypothesis_revision(
            verify_report=query_compile.verification_report,
            error_code=planner_gate_error,
        )
        followup_plan = _build_followup_plan(query=req.query, ok=False, error_code=planner_gate_error)
        followup_ref = evidence.add_json(followup_plan, kind="artifact_draft")
        final_ref = evidence.add_json(
            {
                "schema_version": "1.0.0",
                "type": "assistant_loop_result",
                "ts": _utc_iso(),
                "ok": False,
                "error_code": planner_gate_error,
                "query_ref": query_ref.ref,
                "steps": [],
                "followup_plan_ref": followup_ref.ref,
            },
            kind="snapshot",
        )
        _persist_runtime_snapshot(
            snapshot_store=snapshot_store,
            req=req,
            compiled_query=query_compile.query,
            effective_query=str(query_compile.query.get("objective") or req.query).strip() or str(req.query),
            interaction_mode=str(query_compile.query.get("interaction_mode") or "task").strip() or "task",
            error_code=planner_gate_error,
            summary=compile_summary,
            active_submission_id=submission_id,
            active_submission_generation=1,
        )
        consolidated_refs: tuple[str, ...] = ()
        if not bool(req.replay_mode):
            consolidated_refs = memory_consolidator.consolidate_turn(
                workspace_id=str(req.workspace_id),
                conversation_id=str(req.conversation_id or "").strip() or None,
                project_id=None,
                query=str(req.query),
                reply_text="",
                error_code=planner_gate_error,
            )
        return AssistantLoopResult(
            ok=False,
            final_output=None,
            error_code=planner_gate_error,
            steps=[],
            trace=req.trace,
            evidence_refs=list(
                dict.fromkeys(planner_evidence_refs + [followup_ref.ref, final_ref.ref, *list(consolidated_refs)])
            ),
            followup_plan_ref=followup_ref.ref,
            followup_task_id=None,
            delivery_state="blocker",
            graph_id=kernel_graph_id or None,
        )
    query_budget = query_compile.query.get("budget", {}) if isinstance(query_compile.query, dict) else {}
    effective_query = str(query_compile.query.get("objective") or req.query).strip() or str(req.query)
    model_routing_policy = (
        dict(query_compile.query.get("model_routing_policy") or {})
        if isinstance(query_compile.query.get("model_routing_policy"), dict)
        else {}
    )
    task_requirements = (
        dict(query_compile.query.get("task_requirements") or {})
        if isinstance(query_compile.query.get("task_requirements"), dict)
        else {}
    )
    solution_query = (
        dict(query_compile.query.get("solution_query") or {})
        if isinstance(query_compile.query.get("solution_query"), dict)
        else {}
    )
    if bool(task_requirements.get("attachments_present")) and not bool(task_requirements.get("multimodal_chain_supported")):
        attachment_mode = str(task_requirements.get("attachment_usage_mode") or "none").strip() or "none"
        if attachment_mode == "primary_evidence" and not bool(task_requirements.get("text_only_fallback_allowed")):
            error_code = "E_MULTIMODAL_UNSUPPORTED"
            terminal_phase_outcome = "blocked"
    granted_capabilities = set(capability_names_from_effective_runtime_capabilities(effective_runtime_capabilities))
    _emit_delivery_state(
        trace_log=trace_log,
        ctx=req.trace,
        task_id=task_id,
        state="ack",
        summary=f"task compiled in {query_mode} mode",
        evidence_refs=(query_ref, query_verify_ref),
    )
    emit_output_event(
        sink=req.output_event_sink,
        event_log=runtime_event_log,
        trace_id=req.trace.trace_id,
        turn_id=req.trace.turn_id,
        event_type="ack",
        payload={"task_id": task_id, "mode": query_mode},
    )
    _update_stream_progress(req.telegram_stream_session, f"已接收任务，模式={query_mode}")

    planner_mode = "model_owned"
    if str(req.planner or "").strip().lower() not in {"", "auto", "llm", "model_owned"}:
        planner_note_ref = evidence.add_json(
            {
                "schema_version": "1.0.0",
                "type": "planner_override_ignored",
                "requested_planner": str(req.planner),
                "effective_planner": planner_mode,
            },
            kind="policy",
        )
        planner_evidence_refs.append(planner_note_ref.ref)
    plan_ref = query_ref

    local_exec = LocalExecutor.for_data_dir(data_dir)
    orch = Orchestrator.for_data_dir(str(data_dir), local_executor=local_exec)

    root_idem = req.idempotency_key or f"idem_assistant_loop_{req.trace.trace_id}_{req.trace.turn_id}"
    try:
        _budgeted_tool_calls = max(1, int(query_budget.get("tool_calls_max") or 4))
    except Exception:
        _budgeted_tool_calls = 4
    step_deadline_ms = max(1000, int(req.deadline_ms) // max(1, _budgeted_tool_calls + 6))

    exec_summaries: list[dict[str, Any]] = []
    step_outputs: list[dict[str, Any]] = []
    error_code: Optional[str] = None
    final_output: Optional[dict[str, Any]] = None
    completed_action_states: dict[str, str] = {}
    completed_action_outputs: dict[str, Any] = {}
    observation_capsules: list[str] = []
    research_evidence_pack_ref: str | None = None
    terminal_failure_summary: dict[str, Any] | None = None
    terminal_phase_outcome = "failed"

    def _runtime_role_for_step(*, operator_ref: str, prompt_profile_id: str | None = None, source_phase: str | None = None) -> str:
        profile = str(prompt_profile_id or "").strip()
        phase = str(source_phase or "").strip()
        if profile in {"intent_router", "planner", "verifier_replanner", "communicator"}:
            return "leader"
        if profile == "executor":
            return "worker"
        if operator_ref == "builtin://channel.send_message" and phase == "communicator":
            return "leader"
        return "worker"

    def _resolve_step_backend_model(*, prompt_profile_id: str | None = None) -> tuple[str, Optional[str]]:
        step_backend = str(req.backend or "local_mock")
        step_model = req.model
        if prompt_profile_id == "planner" and str(req.planner_backend or "").strip():
            step_backend = str(req.planner_backend)
        if prompt_profile_id == "intent_router":
            if str(req.intent_backend or "").strip():
                step_backend = str(req.intent_backend)
            if str(req.intent_model or "").strip():
                step_model = str(req.intent_model)
        elif prompt_profile_id == "communicator":
            if str(req.communicator_backend or "").strip():
                step_backend = str(req.communicator_backend)
            if str(req.communicator_model or "").strip():
                step_model = str(req.communicator_model)
        return step_backend, step_model

    def _compute_step_deadline_ms(
        *,
        operator_ref: str,
        prompt_profile_id: str | None = None,
        source_phase: str | None = None,
    ) -> int:
        total_deadline_ms = max(1000, int(req.deadline_ms))
        phase_deadline_ms = int(step_deadline_ms)
        step_backend, _ = _resolve_step_backend_model(prompt_profile_id=prompt_profile_id)
        task_policy = dict(compiled_task_execution_policy or {})
        role = _runtime_role_for_step(operator_ref=operator_ref, prompt_profile_id=prompt_profile_id, source_phase=source_phase)
        if operator_ref.startswith("builtin://"):
            phase_deadline_ms = max(phase_deadline_ms, int(task_policy.get("tool_timeout_ms") or phase_deadline_ms))
        elif role == "leader":
            phase_deadline_ms = max(phase_deadline_ms, int(task_policy.get("llm_timeout_ms") or phase_deadline_ms))
        elif role == "worker":
            phase_deadline_ms = max(phase_deadline_ms, int(task_policy.get("llm_timeout_ms") or phase_deadline_ms))
        if (
            operator_ref == str(assistant_skill_dir)
            and prompt_profile_id in _CANONICAL_PROMPT_PROFILES
            and is_remote_llm_backend(step_backend)
        ):
            # Remote role phases need a larger floor than the generic per-step slice.
            phase_deadline_ms = max(phase_deadline_ms, max(5000, total_deadline_ms // 3))
        return min(total_deadline_ms, phase_deadline_ms)

    def _make_step_policy(
        *,
        operator_ref: str,
        prompt_profile_id: str | None = None,
        source_phase: str | None = None,
    ) -> dict[str, Any]:
        step_backend, step_model = _resolve_step_backend_model(prompt_profile_id=prompt_profile_id)
        runtime_role = _runtime_role_for_step(
            operator_ref=operator_ref,
            prompt_profile_id=prompt_profile_id,
            source_phase=source_phase,
        )
        step_policy: dict[str, Any] = {
            "verify_asvp": bool(req.verify_asvp),
            "public_keys_dir": str(keys_dir),
            "backend": step_backend,
            "model": step_model,
            "remote_calls_armed": bool(req.remote_calls_armed),
            "allow_network_egress": bool(req.allow_network_egress),
            "approved_by_human": bool(req.approved_by_human),
            "replay_mode": bool(req.replay_mode),
            "runtime_role": runtime_role,
            "execution_lane": execution_lane,
            "execution_lane_policy": dict(execution_lane_policy),
        }
        if prompt_profile_id == "executor":
            step_policy["execution_lane_selected_backend"] = step_backend
            step_policy["execution_lane_selected_model"] = step_model
            step_policy["lane_locked"] = True
        if isinstance(query_compile.query.get("agent_profile"), dict):
            step_policy["agent_profile"] = query_compile.query["agent_profile"]
        if isinstance(query_compile.query.get("context_planes"), dict):
            step_policy["context_planes"] = query_compile.query["context_planes"]
        if isinstance(query_compile.query.get("context_graph"), dict):
            step_policy["context_graph"] = query_compile.query["context_graph"]
        if isinstance(query_compile.query.get("task_context_views"), dict):
            step_policy["task_context_views"] = query_compile.query["task_context_views"]
        if isinstance(query_compile.query.get("prompt_profiles"), dict):
            step_policy["prompt_profiles"] = query_compile.query["prompt_profiles"]
        if isinstance(query_compile.query.get("prompt_compilation"), dict):
            step_policy["prompt_compilation"] = query_compile.query["prompt_compilation"]
        if isinstance(query_compile.query.get("soul_profile"), dict):
            step_policy["soul_profile"] = query_compile.query["soul_profile"]
        step_runtime_caps = dict(effective_runtime_capabilities)

        extra_caps: list[str] = []
        if is_remote_llm_backend(step_backend) or bool(req.remote_calls_armed):
            extra_caps.append("llm_remote")
        if bool(req.allow_network_egress):
            extra_caps.append("net_egress")
        if operator_ref.startswith("builtin://memory."):
            op = operator_ref[len("builtin://memory.") :].strip().lower()
            if op in {"write", "delete", "compact"}:
                extra_caps.append("memory_write")
        if operator_ref.startswith("builtin://scheduler."):
            op = operator_ref[len("builtin://scheduler.") :].strip().lower()
            if op in {"at", "cron"}:
                extra_caps.append("scheduler_write")
        if operator_ref.startswith("builtin://channel."):
            extra_caps.append("channel_send")
        if (
            operator_ref == str(assistant_skill_dir)
            and isinstance(query_compile.query.get("task_requirements"), dict)
            and bool((query_compile.query.get("task_requirements") or {}).get("research_required"))
        ):
            current_effective = capability_names_from_effective_runtime_capabilities(step_runtime_caps)
            if "web_search" in current_effective and "web_browse" in current_effective:
                extra_caps.append("research_run")
        if extra_caps:
            step_runtime_caps = with_effective_runtime_capability_names(
                step_runtime_caps,
                additional_names=extra_caps,
            )
        step_policy["effective_runtime_capabilities"] = step_runtime_caps
        step_policy["capabilities"] = capability_items_from_effective_runtime_capabilities(step_runtime_caps)

        if operator_ref == str(assistant_skill_dir):
            if isinstance(query_compile.query.get("task_requirements"), dict):
                step_policy["task_requirements"] = query_compile.query["task_requirements"]
            if isinstance(query_compile.query.get("task_envelope"), dict):
                step_policy["task_envelope"] = query_compile.query["task_envelope"]
            if isinstance(query_compile.query.get("delivery_contract"), dict):
                step_policy["delivery_contract"] = query_compile.query["delivery_contract"]
            if compiled_task_bundle:
                step_policy["task_bundle"] = compiled_task_bundle
            if compiled_task_execution_policy:
                step_policy["task_execution_policy"] = compiled_task_execution_policy
            if compiled_file_refs:
                step_policy["file_refs"] = list(compiled_file_refs)
            if runtime_graph_seed:
                step_policy["runtime_graph"] = runtime_graph_seed
            if isinstance(query_compile.query.get("intent_recovery"), dict):
                step_policy["intent_recovery"] = query_compile.query["intent_recovery"]
            if model_routing_policy:
                step_policy["model_routing_policy"] = model_routing_policy
            if isinstance(query_compile.query.get("active_style_pack"), dict):
                step_policy["active_style_pack"] = query_compile.query["active_style_pack"]
            if str(req.response_language or "").strip():
                step_policy["response_language"] = str(req.response_language).strip()
            if isinstance(query_compile.query.get("active_doctrine_pack"), dict):
                step_policy["active_doctrine_pack"] = query_compile.query["active_doctrine_pack"]
            if isinstance(query_compile.query.get("domain_policy_pack"), dict):
                step_policy["domain_policy_pack"] = query_compile.query["domain_policy_pack"]
            compiled_profiles = (
                dict(query_compile.query.get("prompt_profiles") or {})
                if isinstance(query_compile.query.get("prompt_profiles"), dict)
                else {}
            )
            compiled_profile = (
                dict(compiled_profiles.get(prompt_profile_id) or {})
                if prompt_profile_id and isinstance(compiled_profiles.get(prompt_profile_id), dict)
                else {}
            )
            compiled_prompt = str(compiled_profile.get("reasoning_prompt") or "").strip()
            if prompt_profile_id:
                step_policy["active_prompt_profile"] = str(prompt_profile_id)
                step_policy["leader_worker_boundary"] = {
                    "phase": str(prompt_profile_id),
                    "runtime_role": runtime_role,
                    "worker_split_requires_leader": bool(
                        ((compiled_task_bundle.get("scope_guard") or {}).get("worker_split_requires_leader"))
                    ),
                }
            if compiled_prompt:
                step_policy["reasoning_prompt"] = compiled_prompt
            else:
                step_policy.pop("reasoning_prompt", None)
            selected_attachments = _selected_attachments_for_profile(
                attachments=_normalized_attachments(req.attachments),
                task_requirements=task_requirements,
                prompt_profile_id=prompt_profile_id,
            )
            if req.attachments:
                step_policy["attachment_context"] = {
                    "attachments_present": bool(task_requirements.get("attachments_present")),
                    "attachment_usage_mode": str(task_requirements.get("attachment_usage_mode") or "none"),
                    "required_media_kinds": list(task_requirements.get("required_media_kinds") or []),
                    "text_only_fallback_allowed": bool(task_requirements.get("text_only_fallback_allowed")),
                    "multimodal_chain_supported": bool(task_requirements.get("multimodal_chain_supported")),
                    "multimodal_block_reason": task_requirements.get("multimodal_block_reason"),
                    "available_attachments": _normalized_attachments(req.attachments),
                    "selected_attachments": selected_attachments,
                    "phase_backend_support": dict(
                        (task_requirements.get("downstream_modality_reachability") or {}).get(prompt_profile_id or "", {})
                    ),
                }
                if selected_attachments:
                    step_policy["selected_attachments"] = selected_attachments
            if isinstance(req.memory_context, dict) and req.memory_context:
                step_policy["memory_context"] = dict(req.memory_context)
            merged_observation_capsules = list(observation_capsules)
            research_pack = build_research_evidence_pack_v1(
                task_id=task_id,
                objective=effective_query,
                task_requirements=task_requirements,
                exec_summaries=exec_summaries,
                step_outputs=step_outputs,
                error_code=error_code,
            )
            if research_pack is not None:
                step_policy["research_evidence_pack"] = research_pack
                research_capsule = _build_research_observation_capsule(research_pack)
                if research_capsule:
                    merged_observation_capsules.append(research_capsule)
            if merged_observation_capsules:
                step_policy["execution_observation_capsule"] = "\n\n".join(merged_observation_capsules)
            if prompt_profile_id == "communicator" and isinstance(terminal_failure_summary, dict):
                step_policy["verified_failure_summary"] = dict(terminal_failure_summary)
            if callable(req.llm_stream_callback) and prompt_profile_id == "communicator":

                def _combined_stream_callback(event: dict[str, Any]) -> None:
                    req.llm_stream_callback(event)
                    if str(event.get("type") or "").strip() == "delta":
                        emit_output_event(
                            sink=req.output_event_sink,
                            event_log=runtime_event_log,
                            trace_id=req.trace.trace_id,
                            turn_id=req.trace.turn_id,
                            event_type="reply_delta",
                            payload={"delta": str(event.get("delta") or "")},
                        )

                step_policy["llm_stream_callback"] = _combined_stream_callback
            if req.telegram_stream_session is not None and prompt_profile_id == "communicator":
                step_policy["telegram_stream_session"] = req.telegram_stream_session
        return step_policy

    def _record_step_effects(*, operator_ref: str, output_obj: dict[str, Any]) -> None:
        obs_capsule = _build_observation_capsule(operator_ref=operator_ref, output_obj=output_obj)
        if obs_capsule:
            observation_capsules.append(obs_capsule)

    def _has_accepted_browse() -> bool:
        for item in exec_summaries:
            if not isinstance(item, dict):
                continue
            if str(item.get("operator_ref") or "").strip() != "builtin://web.browse":
                continue
            if str(item.get("status") or "").strip() == "accepted":
                return True
        return False

    def _external_evidence_policy() -> dict[str, int]:
        raw = dict(task_requirements.get("external_evidence_policy_v1") or {})
        return {
            "search_rounds_max": max(1, int(raw.get("search_rounds_max") or 2)),
            "browse_candidates_per_search_max": max(1, int(raw.get("browse_candidates_per_search_max") or 3)),
            "total_browse_steps_max": max(1, int(raw.get("total_browse_steps_max") or 4)),
        }

    def _browse_attempt_count() -> int:
        count = 0
        for item in exec_summaries:
            if not isinstance(item, dict):
                continue
            if str(item.get("operator_ref") or "").strip() == "builtin://web.browse":
                count += 1
        return count

    def _attempted_browse_urls() -> set[str]:
        urls: set[str] = set()
        for index, item in enumerate(exec_summaries):
            if not isinstance(item, dict):
                continue
            if str(item.get("operator_ref") or "").strip() != "builtin://web.browse":
                continue
            arguments = dict(item.get("arguments") or {}) if isinstance(item.get("arguments"), dict) else {}
            output_obj = step_outputs[index] if index < len(step_outputs) and isinstance(step_outputs[index], dict) else {}
            payload = dict(output_obj.get("output") or {}) if isinstance(output_obj.get("output"), dict) else {}
            url = str(
                payload.get("url")
                or output_obj.get("url")
                or output_obj.get("final_url")
                or arguments.get("url")
                or ""
            ).strip()
            if url:
                urls.add(url)
        return urls

    def _runtime_browse_candidates() -> list[str]:
        policy = _external_evidence_policy()
        remaining_total = max(0, int(policy["total_browse_steps_max"]) - _browse_attempt_count())
        if remaining_total <= 0:
            return []
        attempted_urls = _attempted_browse_urls()
        candidates: list[str] = []
        search_rounds_seen = 0
        for index in range(len(exec_summaries) - 1, -1, -1):
            step = exec_summaries[index]
            if not isinstance(step, dict):
                continue
            if str(step.get("operator_ref") or "").strip() != "builtin://web.search":
                continue
            if str(step.get("status") or "").strip() != "accepted":
                continue
            output_obj = step_outputs[index] if index < len(step_outputs) and isinstance(step_outputs[index], dict) else {}
            results = output_obj.get("results")
            if not isinstance(results, list) or not results:
                continue
            search_rounds_seen += 1
            per_search_count = 0
            for result in results:
                if not isinstance(result, dict):
                    continue
                url = str(result.get("url") or "").strip()
                if not url or url in attempted_urls or url in candidates:
                    continue
                candidates.append(url)
                per_search_count += 1
                if per_search_count >= int(policy["browse_candidates_per_search_max"]):
                    break
                if len(candidates) >= remaining_total:
                    return candidates
            if search_rounds_seen >= int(policy["search_rounds_max"]):
                break
            if len(candidates) >= remaining_total:
                break
        return candidates[:remaining_total]

    async def _maybe_execute_runtime_browse_bridge(*, reserve_non_delivery_tail: int) -> None:
        nonlocal error_code
        if error_code is not None:
            return
        if not bool(task_requirements.get("requires_external_evidence")):
            return
        if "web_browse" not in granted_capabilities:
            return
        if _has_accepted_browse():
            return
        candidate_urls = _runtime_browse_candidates()
        if not candidate_urls:
            return
        base_attempt = _browse_attempt_count()
        for offset, candidate_url in enumerate(candidate_urls, start=1):
            prior_error_code = error_code
            await _execute_action_batch(
                actions=[
                    {
                        "action_id": f"runtime_auto_browse_{base_attempt + offset}",
                        "operator_ref": "builtin://web.browse",
                        "arguments": {"url": candidate_url},
                        "depends_on": [],
                    }
                ],
                source_phase="runtime_browse_bridge",
                reserve_non_delivery_tail=reserve_non_delivery_tail,
                allow_when_error=True,
            )
            if _has_accepted_browse():
                return
            if error_code == "E_HITL_REQUIRED":
                return
            error_code = prior_error_code

    async def _execute_runtime_step(
        *,
        operator_ref: str,
        arguments: dict[str, Any],
        idem_suffix: str,
        span_suffix: str,
        progress_summary: str,
        progress_payload: dict[str, Any],
        prompt_profile_id: str | None = None,
        source_phase: str | None = None,
        runtime_task_id: str | None = None,
        runtime_action_id: str | None = None,
        emit_progress: bool = True,
    ) -> tuple[ExecuteRequest, ExecuteResult, dict[str, Any]]:
        phase_deadline_ms = _compute_step_deadline_ms(
            operator_ref=operator_ref,
            prompt_profile_id=prompt_profile_id,
            source_phase=source_phase,
        )
        step_req = ExecuteRequest(
            workspace_id=req.workspace_id,
            operator_ref=operator_ref,
            arguments=dict(arguments or {}),
            idempotency_key=f"{root_idem}:{idem_suffix}",
            deadline_ms=phase_deadline_ms,
            trace=_new_child_trace(req.trace, span_suffix=span_suffix),
            policy_context=_make_step_policy(
                operator_ref=operator_ref,
                prompt_profile_id=prompt_profile_id,
                source_phase=source_phase,
            ),
            preferred_target="local",
        )
        res: ExecuteResult = await orch.execute(step_req)
        output_obj = _extract_structured_output(evidence=evidence, result=res)
        runtime_role = _runtime_role_for_step(
            operator_ref=operator_ref,
            prompt_profile_id=prompt_profile_id,
            source_phase=source_phase,
        )
        step_summary: dict[str, Any] = {
            "i": len(exec_summaries) + 1,
            "operator_ref": step_req.operator_ref,
            "status": res.status,
            "error_code": res.error_code,
            "target": res.target,
            "evidence_refs": [er.ref for er in res.evidence_refs],
            "deadline_ms": int(step_req.deadline_ms),
            "internal_role_phase": (str(prompt_profile_id) if prompt_profile_id else None),
            "source_phase": (str(source_phase) if source_phase else None),
            "runtime_role": runtime_role,
            "task_id": (str(runtime_task_id).strip() if str(runtime_task_id or "").strip() else None),
            "action_id": (str(runtime_action_id).strip() if str(runtime_action_id or "").strip() else None),
            "arguments": _summarize_step_arguments(operator_ref=step_req.operator_ref, arguments=arguments),
        }
        if compiled_task_bundle:
            step_summary["task_bundle"] = {
                "task_mode": str(compiled_task_bundle.get("task_mode") or ""),
                "worker_task_admission_mode": str(compiled_task_bundle.get("worker_task_admission_mode") or ""),
                "delegation_budget": int(compiled_task_bundle.get("delegation_budget") or 0),
                "max_depth": int(compiled_task_bundle.get("max_depth") or 0),
                "sufficient_for_execution": bool(compiled_task_bundle.get("sufficient_for_execution")),
                "file_ref_count": len(compiled_task_bundle.get("file_refs") or []),
            }
        if compiled_task_execution_policy:
            step_summary["task_execution_policy"] = {
                "llm_timeout_ms": int(compiled_task_execution_policy.get("llm_timeout_ms") or 0),
                "tool_timeout_ms": int(compiled_task_execution_policy.get("tool_timeout_ms") or 0),
                "max_attempts": int(compiled_task_execution_policy.get("max_attempts") or 0),
                "side_effect_safe_retry": bool(compiled_task_execution_policy.get("side_effect_safe_retry")),
            }
        if _is_send_message_action({"operator_ref": step_req.operator_ref}) and isinstance(output_obj, dict) and res.status == "accepted":
            step_summary["delivery"] = dict(output_obj)
        exec_summaries.append(step_summary)
        step_outputs.append(output_obj)
        if str(runtime_task_id or "").strip():
            runtime_session.record_reasoning_step(
                task_id=str(runtime_task_id),
                step_summary=step_summary,
                output_summary=(
                    _extract_user_visible_text(output_obj)
                    if isinstance(output_obj, dict)
                    else ""
                ),
                leader_phase=(
                    str(prompt_profile_id or source_phase or "").strip()
                    if runtime_role == "leader" and str(prompt_profile_id or source_phase or "").strip()
                    else None
                ),
                phase_status=(
                    _phase_status(output_obj, default="done")
                    if isinstance(output_obj, dict)
                    else ""
                ),
            )
        _record_step_effects(operator_ref=step_req.operator_ref, output_obj=output_obj)
        if emit_progress:
            _emit_delivery_state(
                trace_log=trace_log,
                ctx=req.trace,
                task_id=task_id,
                state="progress",
                summary=progress_summary,
            )
            emit_output_event(
                sink=req.output_event_sink,
                event_log=runtime_event_log,
                trace_id=req.trace.trace_id,
                turn_id=req.trace.turn_id,
                event_type="progress",
                payload={"task_id": task_id, **dict(progress_payload)},
            )
        return step_req, res, output_obj

    def _record_phase_violation(*, phase: str, code: str, reason: str, output_obj: dict[str, Any] | None) -> None:
        nonlocal error_code
        error_code = code
        violation_ref = evidence.add_json(
            {
                "schema_version": "1.0.0",
                "type": "phase_violation_v1",
                "phase": str(phase),
                "error_code": code,
                "reason": reason,
                "output": dict(output_obj or {}),
            },
            kind="policy",
        )
        planner_evidence_refs.append(violation_ref.ref)
        emit_output_event(
            sink=req.output_event_sink,
            event_log=runtime_event_log,
            trace_id=req.trace.trace_id,
            turn_id=req.trace.turn_id,
            event_type="blocker",
            payload={"task_id": task_id, "error_code": code, "phase": phase},
        )

    async def _run_profile_phase(
        *,
        prompt_profile_id: str,
        request_text: str,
        phase_label: str,
    ) -> tuple[ExecuteResult, dict[str, Any]]:
        _, phase_res, phase_output = await _execute_runtime_step(
            operator_ref=str(assistant_skill_dir),
            arguments={"request": request_text},
            idem_suffix=phase_label,
            span_suffix=phase_label,
            progress_summary=f"executed {prompt_profile_id} phase",
            progress_payload={"phase": prompt_profile_id, "operator_ref": str(assistant_skill_dir)},
            prompt_profile_id=prompt_profile_id,
            source_phase=prompt_profile_id,
            runtime_task_id=runtime_session.root_task_id or None,
        )
        if phase_res.status != "accepted":
            return phase_res, phase_output
        if prompt_profile_id != "communicator":
            violation_text = _direct_reply_violation_text(phase_output)
            if violation_text:
                _record_phase_violation(
                    phase=prompt_profile_id,
                    code="E_DIRECT_REPLY_FORBIDDEN",
                    reason="non-communicator phase emitted user-visible text",
                    output_obj=phase_output,
                )
            if any(_is_send_message_action(item) for item in _normalize_emitted_actions(phase_output)):
                _record_phase_violation(
                    phase=prompt_profile_id,
                    code="E_MESSAGE_TASK_FORBIDDEN",
                    reason="non-communicator phase emitted send_message action",
                    output_obj=phase_output,
                )
        return phase_res, phase_output

    def _inject_available_dependencies(
        *,
        actions: list[dict[str, Any]],
        available_actions: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        if not actions or not available_actions:
            return [dict(item) for item in actions if isinstance(item, dict)]
        available_map: dict[str, dict[str, Any]] = {}
        for item in available_actions:
            if not isinstance(item, dict):
                continue
            action_id = str(item.get("action_id") or "").strip()
            if action_id:
                available_map[action_id] = dict(item)
        emitted_ids = {
            str(item.get("action_id") or "").strip()
            for item in actions
            if isinstance(item, dict) and str(item.get("action_id") or "").strip()
        }
        injected: list[dict[str, Any]] = []
        seen_injected: set[str] = set()

        def _add_dep(dep_id: str) -> None:
            dep = str(dep_id or "").strip()
            if (
                not dep
                or dep in completed_action_states
                or dep in emitted_ids
                or dep in seen_injected
                or dep not in available_map
            ):
                return
            dep_action = dict(available_map[dep])
            for upstream in [str(x).strip() for x in (dep_action.get("depends_on") or []) if str(x).strip()]:
                _add_dep(upstream)
            injected.append(dep_action)
            seen_injected.add(dep)

        for item in actions:
            if not isinstance(item, dict):
                continue
            for dep in [str(x).strip() for x in (item.get("depends_on") or []) if str(x).strip()]:
                _add_dep(dep)
        return injected + [dict(item) for item in actions if isinstance(item, dict)]

    async def _execute_action_batch(
        *,
        actions: list[dict[str, Any]],
        source_phase: str,
        delivery_stage: str | None = None,
        require_message: bool = False,
        reserve_non_delivery_tail: int = 0,
        allow_delivery: bool = False,
        allow_when_error: bool = False,
    ) -> tuple[list[dict[str, Any]], bool]:
        nonlocal error_code
        nonlocal final_output
        nonlocal terminal_phase_outcome
        raw_actions = [dict(item) for item in actions if isinstance(item, dict)]
        if not raw_actions or (error_code is not None and not allow_when_error):
            if require_message and error_code is None:
                error_code = "E_MESSAGE_TASK_MISSING"
            return [], False

        already_seen: set[tuple[str, str]] = set()
        action_states: dict[str, str] = dict(completed_action_states)
        action_outputs: dict[str, Any] = dict(completed_action_outputs)
        action_notes: list[dict[str, Any]] = []
        delivered: list[dict[str, Any]] = []
        executed_non_delivery = False
        loops_max = 1
        tool_calls_max = 0
        try:
            loops_max = max(1, int(query_budget.get("loops_max") or 1))
        except Exception:
            loops_max = 1
        try:
            tool_calls_max = int(query_budget.get("tool_calls_max") or 0)
        except Exception:
            tool_calls_max = 0

        non_delivery_budget = None
        if tool_calls_max > 0:
            remaining = max(0, tool_calls_max - _count_non_delivery_steps(exec_summaries))
            non_delivery_budget = max(0, remaining - max(0, int(reserve_non_delivery_tail)))

        pending = [dict(item) for item in raw_actions]
        while pending:
            progressed = False
            still_pending: list[dict[str, Any]] = []
            for action in pending:
                operator_ref = str(action.get("operator_ref") or "").strip()
                action_id = str(action.get("action_id") or "").strip() or f"action_{len(action_states) + 1}"
                depends_on = [str(x).strip() for x in (action.get("depends_on") or []) if str(x).strip()]
                unresolved = [dep for dep in depends_on if dep not in action_states]
                if unresolved:
                    still_pending.append(action)
                    continue
                failed_deps = [dep for dep in depends_on if action_states.get(dep) != "accepted"]
                if failed_deps:
                    action_states[action_id] = "skipped_dependency"
                    action_notes.append(
                        {
                            "action_id": action_id,
                            "operator_ref": operator_ref,
                            "status": "skipped_dependency",
                            "depends_on": failed_deps,
                        }
                    )
                    progressed = True
                    continue
                try:
                    resolved_arguments = _resolve_action_argument_references(
                        dict(action.get("arguments") or {}),
                        action_outputs=action_outputs,
                    )
                except _ActionArgumentReferenceError as exc:
                    action_states[action_id] = "rejected_invalid_arguments"
                    action_notes.append(
                        {
                            "action_id": action_id,
                            "operator_ref": operator_ref,
                            "status": "rejected_invalid_arguments",
                            "error_code": "E_TASK_ARGUMENT_REFERENCE_INVALID",
                            "message": str(exc),
                        }
                    )
                    error_code = "E_TASK_ARGUMENT_REFERENCE_INVALID"
                    progressed = True
                    break
                is_delivery = _is_send_message_action(action)
                prepared_arguments = (
                    _augment_send_message_arguments(
                        arguments=(
                            dict(resolved_arguments)
                            if isinstance(resolved_arguments, dict)
                            else {}
                        ),
                        task_id=task_id,
                        delivery_stage=str(delivery_stage or "final"),
                        source_phase=source_phase,
                    )
                    if is_delivery
                    else (
                        dict(resolved_arguments)
                        if isinstance(resolved_arguments, dict)
                        else {}
                    )
                )
                fingerprint = (
                    operator_ref,
                    json.dumps(prepared_arguments, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
                )
                if fingerprint in already_seen:
                    action_states[action_id] = "skipped_duplicate"
                    action_notes.append(
                        {
                            "action_id": action_id,
                            "operator_ref": operator_ref,
                            "status": "skipped_duplicate",
                        }
                    )
                    progressed = True
                    continue
                if not operator_ref.startswith("builtin://"):
                    action_states[action_id] = "rejected_unsupported"
                    action_notes.append(
                        {
                            "action_id": action_id,
                            "operator_ref": operator_ref,
                            "status": "rejected_unsupported",
                        }
                    )
                    error_code = "E_ACTION_OPERATOR_UNSUPPORTED"
                    progressed = True
                    break
                if is_delivery and not allow_delivery:
                    action_states[action_id] = "rejected_phase_violation"
                    action_notes.append(
                        {
                            "action_id": action_id,
                            "operator_ref": operator_ref,
                            "status": "rejected_phase_violation",
                        }
                    )
                    error_code = "E_MESSAGE_TASK_PHASE_VIOLATION"
                    progressed = True
                    break
                if not is_delivery and non_delivery_budget is not None and non_delivery_budget <= 0:
                    action_states[action_id] = "hold_budget_exhausted"
                    action_notes.append(
                        {
                            "action_id": action_id,
                            "operator_ref": operator_ref,
                            "status": "hold_budget_exhausted",
                            "error_code": "E_HITL_REQUIRED",
                        }
                    )
                    error_code = "E_HITL_REQUIRED"
                    terminal_phase_outcome = "hold"
                    progressed = True
                    break

                retry_policy = (
                    dict(compiled_task_execution_policy.get("tool_retry_policy") or {})
                    if isinstance(compiled_task_execution_policy, dict)
                    else {}
                )
                read_only_retry_safe = operator_ref.startswith(
                    (
                        "builtin://web.",
                        "builtin://fs.read",
                        "builtin://fs.list",
                        "builtin://memory.search",
                        "builtin://time.",
                    )
                )
                retry_attempts = 1
                if not is_delivery and read_only_retry_safe:
                    retry_attempts = max(1, int(retry_policy.get("max_retries") or 0) + 1)
                final_attempt_index = 1
                action_output: dict[str, Any] | Any = {}
                runtime_task_for_action = (
                    runtime_session.root_task_id or None
                    if is_delivery and source_phase == "communicator"
                    else None
                )
                for attempt_index in range(1, retry_attempts + 1):
                    final_attempt_index = attempt_index
                    step_req, res, action_output = await _execute_runtime_step(
                        operator_ref=operator_ref,
                        arguments=prepared_arguments,
                        idem_suffix=_action_call_idem_suffix(
                            action_id=action_id,
                            operator_ref=operator_ref,
                            arguments=prepared_arguments,
                        ),
                        span_suffix=f"action_{action_id}_attempt_{attempt_index}",
                        progress_summary=f"executed {source_phase} action {action_id}: {operator_ref}",
                        progress_payload={
                            "action_id": action_id,
                            "operator_ref": operator_ref,
                            "phase": "action_batch",
                            "source_phase": source_phase,
                            "attempt": attempt_index,
                        },
                        source_phase=source_phase,
                        runtime_task_id=runtime_task_for_action,
                        runtime_action_id=action_id,
                        emit_progress=not is_delivery,
                    )
                    if res.status == "accepted" or attempt_index >= retry_attempts or res.status not in {"failed", "timeout"}:
                        break
                already_seen.add(fingerprint)
                action_states[action_id] = str(res.status or "")
                progressed = True
                if not is_delivery and non_delivery_budget is not None:
                    non_delivery_budget = max(0, non_delivery_budget - 1)
                if res.status == "accepted":
                    action_outputs[action_id] = dict(action_output or {}) if isinstance(action_output, dict) else action_output
                    completed_action_states[action_id] = str(res.status or "")
                    completed_action_outputs[action_id] = action_outputs[action_id]
                    if is_delivery:
                        final_output = action_output or final_output
                        delivered.append(dict(action_output or {}))
                        emit_output_event(
                            sink=req.output_event_sink,
                            event_log=runtime_event_log,
                            trace_id=req.trace.trace_id,
                            turn_id=req.trace.turn_id,
                            event_type="artifact",
                            payload={
                                "task_id": task_id,
                                "artifact_type": "channel_message",
                                "delivery": dict(action_output or {}),
                            },
                        )
                    else:
                        executed_non_delivery = True
                else:
                    if error_code is None:
                        error_code = res.error_code or "E_TASK_EXECUTION_FAILED"
                action_notes.append(
                    {
                        "action_id": action_id,
                        "operator_ref": step_req.operator_ref,
                        "status": res.status,
                        "error_code": res.error_code,
                        "depends_on": depends_on,
                        "attempts": final_attempt_index,
                        "retry_enabled": retry_attempts > 1,
                        "worker_task_admission_mode": str(compiled_task_bundle.get("worker_task_admission_mode") or "leader_gate"),
                        "worker_split_requires_leader": bool(
                            ((compiled_task_bundle.get("scope_guard") or {}).get("worker_split_requires_leader"))
                        ),
                    }
                )
                if error_code is not None:
                    break
            if error_code is not None:
                break
            if not progressed:
                pending_ids = {
                    str(item.get("action_id") or "").strip()
                    for item in still_pending
                    if isinstance(item, dict) and str(item.get("action_id") or "").strip()
                }
                unresolved_dependency = False
                for action in still_pending:
                    depends_on = [str(x).strip() for x in (action.get("depends_on") or []) if str(x).strip()]
                    unknown = [
                        dep for dep in depends_on
                        if dep not in action_states and dep not in pending_ids
                    ]
                    if unknown:
                        unresolved_dependency = True
                    action_notes.append(
                        {
                            "action_id": str(action.get("action_id") or "").strip(),
                            "operator_ref": str(action.get("operator_ref") or "").strip(),
                            "status": "skipped_unresolved_dependency",
                            "depends_on": list(action.get("depends_on") or []),
                            "resolved_depends_on": depends_on,
                            "unknown_dependencies": unknown,
                        }
                    )
                error_code = (
                    "E_TASK_DEPENDENCY_UNRESOLVED"
                    if unresolved_dependency
                    else "E_TASK_DEPENDENCY_CYCLE"
                )
                break
            pending = still_pending

        if action_notes:
            planner_evidence_refs.append(
                evidence.add_json(
                    {
                        "schema_version": "1.0.0",
                        "type": "assistant_loop_action_batch",
                        "task_id": task_id,
                        "source_phase": source_phase,
                        "actions": action_notes,
                    },
                    kind="routing",
                ).ref
            )
        if require_message and not delivered and error_code is None:
            error_code = "E_MESSAGE_TASK_MISSING"
        return delivered, executed_non_delivery

    legacy_loops_max = 1
    try:
        legacy_loops_max = max(1, int(query_budget.get("loops_max") or 1))
    except Exception:
        legacy_loops_max = 1
    controller_started_monotonic = time.monotonic()
    controller_no_progress_window = max(1, int(stop_policy.get("no_progress_window") or 3))
    controller_repeated_graph_cap = max(1, int(stop_policy.get("max_repeated_action_fingerprint_hits") or 2))
    controller_no_progress_streak = 0
    controller_repeated_graph_hits = 0
    controller_lane_replans = 0
    last_worker_graph_fingerprint = ""

    def _controller_deadline_exceeded() -> bool:
        deadline_ms = max(0, int(stop_policy.get("deadline_ms") or req.deadline_ms or 0))
        if deadline_ms <= 0:
            return False
        elapsed_ms = int((time.monotonic() - controller_started_monotonic) * 1000)
        return elapsed_ms >= deadline_ms

    def _controller_record_progress(*, progress_made: bool, graph_fingerprint: str = "") -> None:
        nonlocal controller_no_progress_streak
        nonlocal controller_repeated_graph_hits
        nonlocal last_worker_graph_fingerprint
        if graph_fingerprint:
            if graph_fingerprint == last_worker_graph_fingerprint:
                controller_repeated_graph_hits += 1
            else:
                controller_repeated_graph_hits = 0
                last_worker_graph_fingerprint = graph_fingerprint
        if progress_made:
            controller_no_progress_streak = 0
        else:
            controller_no_progress_streak += 1

    def _controller_stop_code() -> str:
        if controller_repeated_graph_hits >= controller_repeated_graph_cap:
            if execution_lane in {"fast_chat", "standard_task"}:
                return "E_REASONING_LANE_INSUFFICIENT"
            return "E_NO_PROGRESS"
        if controller_no_progress_streak >= controller_no_progress_window:
            return "E_NO_PROGRESS"
        if _controller_deadline_exceeded():
            return "E_DEADLINE_EXCEEDED"
        return ""

    def _controller_maybe_promote_lane(*, reason: str, source_phase: str) -> bool:
        nonlocal execution_lane
        nonlocal execution_lane_policy
        nonlocal token_budget
        nonlocal stop_policy
        nonlocal controller_lane_replans
        nonlocal controller_no_progress_streak
        nonlocal controller_repeated_graph_hits
        prefer_research = bool(task_requirements.get("requires_external_evidence")) or bool(
            task_requirements.get("research_required")
        )
        next_lane = next_execution_lane(execution_lane, prefer_research=prefer_research)
        if not next_lane or next_lane == execution_lane:
            return False
        previous_lane = execution_lane
        execution_lane = next_lane
        execution_lane_policy = execution_lane_policy_payload(execution_lane)
        token_budget = _build_task_token_budget(execution_lane=execution_lane, deadline_ms=int(req.deadline_ms))
        stop_policy = _build_task_stop_policy(execution_lane=execution_lane, deadline_ms=int(req.deadline_ms))
        compiled_task_bundle["execution_lane"] = execution_lane
        compiled_task_bundle["token_budget"] = dict(token_budget)
        compiled_task_bundle["stop_policy"] = dict(stop_policy)
        compiled_task_execution_policy["execution_lane_policy"] = dict(execution_lane_policy)
        compiled_task_execution_policy["token_budget"] = dict(token_budget)
        compiled_task_execution_policy["stop_policy"] = dict(stop_policy)
        controller_lane_replans += 1
        controller_no_progress_streak = 0
        controller_repeated_graph_hits = 0
        lane_replan_ref = evidence.add_json(
            {
                "schema_version": "1.0.0",
                "type": "execution_lane_replan_v1",
                "task_id": task_id,
                "submission_id": submission_id,
                "reason": str(reason or "").strip() or "lane_insufficient",
                "source_phase": str(source_phase or "").strip() or "controller",
                "previous_lane": previous_lane,
                "next_lane": execution_lane,
                "execution_lane_policy": dict(execution_lane_policy),
                "controller_lane_replans": int(controller_lane_replans),
                "legacy_loops_max": int(legacy_loops_max),
            },
            kind="routing",
        )
        planner_evidence_refs.append(lane_replan_ref.ref)
        runtime_session.record_reasoning_step(
            task_id=runtime_session.root_task_id or "",
            step_summary={
                "i": len(exec_summaries) + 1,
                "operator_ref": "routing_policy://execution_lane",
                "runtime_role": "leader",
                "status": "accepted",
                "error_code": None,
                "evidence_refs": [lane_replan_ref.ref],
                "previous_lane": previous_lane,
                "next_lane": execution_lane,
            },
            output_summary=f"controller promoted execution_lane from {previous_lane} to {execution_lane}",
            leader_phase="routing_policy",
            phase_status="continue",
        )
        return True

    def _is_pause_error_code(error_code: str | None) -> bool:
        return str(error_code or "").strip() in {
            "E_HITL_REQUIRED",
            "E_DEADLINE_EXCEEDED",
            "E_TOKEN_BUDGET_EXHAUSTED",
            "E_NO_PROGRESS",
        }

    current_worker_task_graph: list[dict[str, Any]] = []
    completed_worker_states: dict[str, str] = {}
    completed_worker_result_refs: dict[str, list[str]] = {}
    runtime_worker_task_ids: dict[str, str] = {}
    terminal_stage = "final"
    if kernel_task_service is not None:
        for existing_task in kernel_task_service.list_tasks(states=("succeeded", "failed", "hold", "superseded")):
            existing_worker_task_id = str(existing_task.worker_task_id or "").strip()
            existing_state = str(existing_task.status or "").strip()
            if not existing_worker_task_id:
                continue
            completed_worker_states[existing_worker_task_id] = (
                "accepted"
                if existing_state == "succeeded"
                else ("hold" if existing_state == "hold" else ("superseded" if existing_state == "superseded" else "blocked"))
            )

    async def _execute_worker_task(worker_task: dict[str, Any], *, source_phase: str) -> WorkerReActOutcome:
        worker_task_id = str(worker_task.get("worker_task_id") or "").strip()
        if not worker_task_id:
            return WorkerReActOutcome(
                status="blocked",
                error_code="E_WORKER_TASK_GRAPH_INVALID",
                final_summary="worker_task_id is required",
                result_refs=(),
                tool_call_count=0,
                iteration_count=0,
            )
        if kernel_task_service is None:
            return WorkerReActOutcome(
                status="blocked",
                error_code="E_EXECUTION_FAILED",
                final_summary="kernel task service is unavailable",
                result_refs=(),
                tool_call_count=0,
                iteration_count=0,
            )
        runtime_task_id = f"{submission_id}:{worker_task_id}"
        kernel_task_service.submit_task(
            TaskSpec(
                task_idempotency_key=runtime_task_id,
                workspace_id=str(req.workspace_id),
                objective=str(worker_task.get("objective") or "").strip(),
                worker_task_id=worker_task_id,
                scope_summary=str(worker_task.get("scope_summary") or "").strip(),
                depends_on=tuple(
                    f"{submission_id}:{str(x).strip()}"
                    for x in (worker_task.get("depends_on") or [])
                    if str(x).strip()
                ),
                allowed_operator_refs=tuple(
                    str(x).strip() for x in (worker_task.get("allowed_operator_refs") or []) if str(x).strip()
                ),
                input_refs=(),
                completion_contract_ref=str(worker_task.get("completion_contract_ref") or "").strip(),
                submission_id=submission_id,
                execution_lane=execution_lane,
                tool_budget=clamp_tool_budget_for_lane(
                    tool_budget=dict(worker_task.get("tool_budget") or {}),
                    lane=execution_lane,
                ),
                token_budget=dict(token_budget),
                stop_policy=dict(stop_policy),
                time_budget_ms=int(worker_task.get("time_budget_ms") or 0),
                task_execution_policy=dict(compiled_task_execution_policy or {}),
                trace={"worker_task_id": worker_task_id, "source_phase": source_phase},
                submitter="assistant.controller",
                source_phase=source_phase,
                effect_class=str(worker_task.get("effect_class") or "").strip(),
            )
        )
        current_record = kernel_task_service.get_task(runtime_task_id)
        if current_record is None:
            return WorkerReActOutcome(
                status="blocked",
                error_code="E_EXECUTION_FAILED",
                final_summary="kernel task record is unavailable",
                result_refs=(),
                tool_call_count=0,
                iteration_count=0,
            )
        return WorkerReActOutcome(
            status="accepted",
            error_code=None,
            final_summary=f"submitted worker task {worker_task_id} to kernel task service",
            result_refs=(),
            tool_call_count=0,
            iteration_count=0,
        )

    async def _execute_worker_task_graph(
        *,
        worker_tasks: list[dict[str, Any]],
        source_phase: str,
    ) -> tuple[bool, bool]:
        nonlocal error_code
        nonlocal terminal_phase_outcome
        if not worker_tasks:
            return False, False
        if kernel_task_service is None:
            error_code = "E_EXECUTION_FAILED"
            return False, False
        pending = [dict(item) for item in worker_tasks if isinstance(item, dict)]
        worker_notes: list[dict[str, Any]] = []
        executed_any = False
        leader_review_needed = False
        for worker_task in pending:
            worker_task_id = str(worker_task.get("worker_task_id") or "").strip()
            if not worker_task_id:
                error_code = "E_WORKER_TASK_GRAPH_INVALID"
                return False, False
            await _execute_worker_task(worker_task, source_phase=source_phase)

        async def _run_kernel_task(record: TaskRecord, record_event: Any) -> TaskRunResult:
            worker_input = _task_record_to_worker_task(record)
            allowed_operator_refs = {
                str(x).strip() for x in (worker_input.get("allowed_operator_refs") or []) if str(x).strip()
            }
            record_execution_lane_policy = (
                dict((record.task_execution_policy or {}).get("execution_lane_policy") or {})
                if isinstance(record.task_execution_policy, dict)
                else {}
            )
            runtime_view_task_id = runtime_session.ensure_worker_task(
                spec=WorkerTaskSpec(
                    worker_task_id=str(record.worker_task_id or record.task_id).strip() or str(record.task_id),
                    objective=str(record.objective or "").strip(),
                    depends_on=tuple(
                        str(dep).split(":", 1)[-1].strip()
                        for dep in record.depends_on
                        if str(dep).strip()
                    ),
                    allowed_operator_refs=tuple(sorted(allowed_operator_refs)),
                    scope_summary=str(record.scope_summary or "").strip(),
                    completion_contract_ref=str(record.completion_contract_ref or "").strip(),
                    tool_budget=dict(record.tool_budget or {}),
                    time_budget_ms=int(record.time_budget_ms or 0),
                    source_phase=source_phase,
                )
            ) or ""
            if runtime_view_task_id:
                runtime_worker_task_ids[record.task_id] = runtime_view_task_id
                runtime_session.set_task_state(task_id=runtime_view_task_id, state="running")

            def _record_worker_event(**kwargs: Any) -> str:
                kernel_event_id = record_event(**kwargs)
                if runtime_view_task_id:
                    runtime_session.record_worker_event(
                        task_id=runtime_view_task_id,
                        worker_task_id=str(record.worker_task_id or record.task_id).strip() or str(record.task_id),
                        event_kind=str(kwargs.get("event_kind") or "").strip(),
                        status=str(kwargs.get("status") or "").strip(),
                        evidence_refs=list(kwargs.get("evidence_refs") or []),
                        output_summary=str(kwargs.get("output_summary") or "").strip(),
                        operator_ref=str(kwargs.get("operator_ref") or "").strip(),
                        error_code=(str(kwargs.get("error_code")).strip() if kwargs.get("error_code") is not None else None),
                        event_id=str(kwargs.get("event_id") or kernel_event_id).strip() or kernel_event_id,
                        sequence=int(kwargs.get("sequence") or 0),
                        extra=dict(kwargs.get("extra") or {}),
                    )
                return kernel_event_id

            async def _worker_reason_step(
                iteration: int,
                worker_observations: tuple[str, ...],
                call_outputs: dict[str, Any],
                call_states: dict[str, str],
            ) -> WorkerReasonDecision:
                request_lines = [
                    "Execute the approved worker task using bounded ReAct within the declared scope.",
                    f"WORKER_TASK_ID={str(record.worker_task_id or record.task_id)}",
                    f"OBJECTIVE={str(record.objective or '').strip()}",
                    f"SCOPE_SUMMARY={str(record.scope_summary or '').strip() or '-'}",
                    "ALLOWED_OPERATOR_REFS=" + (" | ".join(sorted(allowed_operator_refs)) if allowed_operator_refs else "-"),
                    f"EXECUTION_LANE={record.execution_lane}",
                    "REASONING_PROFILE_REF="
                    + str(record_execution_lane_policy.get("reasoning_profile_ref") or "-").strip(),
                    "MODEL_POOL_REF="
                    + str(record_execution_lane_policy.get("model_pool_ref") or "-").strip(),
                    "VERIFICATION_MODE="
                    + str(record_execution_lane_policy.get("verification_mode") or "final_only").strip(),
                    f"ITERATION={iteration}",
                    f"TIME_BUDGET_MS={int(record.time_budget_ms or 0)}",
                    "Return status=continue with worker-local tool actions under actions when more evidence is needed.",
                    "Return status=done when this worker task has gathered enough verified evidence for controller review.",
                    "Return status=blocked or need_context when the current scope cannot proceed safely.",
                    "Do not emit send_message and do not speak to the user directly.",
                ]
                if call_states:
                    request_lines.extend(["", "COMPLETED_TOOL_CALLS:"])
                    request_lines.extend(
                        f"- {call_id}: {str(call_states.get(call_id) or '').strip()}"
                        for call_id in sorted(call_states.keys())
                    )
                if call_outputs:
                    request_lines.extend(["", "TOOL_OUTPUT_KEYS:"])
                    request_lines.extend(f"- {call_id}" for call_id in sorted(call_outputs.keys()))
                if worker_observations:
                    request_lines.extend(["", "VERIFIED_OBSERVATIONS:", "\n\n".join(worker_observations[-8:])])
                _, worker_res, worker_output = await _execute_runtime_step(
                    operator_ref=str(assistant_skill_dir),
                    arguments={"request": "\n".join(line for line in request_lines if line is not None).strip()},
                    idem_suffix=f"worker_{record.worker_task_id}_{iteration}",
                    span_suffix=f"worker_{record.worker_task_id}_{iteration}",
                    progress_summary=f"executed worker task {record.worker_task_id} iteration {iteration}",
                    progress_payload={
                        "phase": "worker_iteration",
                        "source_phase": source_phase,
                        "worker_task_id": record.worker_task_id,
                        "operator_ref": str(assistant_skill_dir),
                    },
                    prompt_profile_id="executor",
                    source_phase=source_phase,
                    runtime_task_id=None,
                    emit_progress=False,
                )
                if worker_res.status != "accepted":
                    return WorkerReasonDecision(
                        status="blocked",
                        reasoning_summary="worker reasoning call failed",
                        raw_output=worker_output,
                        error_code=worker_res.error_code or "E_EXECUTION_FAILED",
                    )
                violation = _phase_output_violation(profile_id="executor", output_obj=worker_output)
                if violation:
                    return WorkerReasonDecision(
                        status="blocked",
                        reasoning_summary="worker emitted invalid output",
                        raw_output=worker_output,
                        error_code=violation,
                    )
                tool_calls: list[WorkerToolCall] = []
                for action in _normalize_emitted_actions(worker_output):
                    operator_ref = str(action.get("operator_ref") or "").strip()
                    if allowed_operator_refs and operator_ref not in allowed_operator_refs:
                        return WorkerReasonDecision(
                            status="blocked",
                            reasoning_summary=f"worker requested a new tool outside approved scope: {operator_ref}",
                            raw_output=worker_output,
                            error_code="E_WORKER_SPLIT_REQUIRES_LEADER",
                        )
                    tool_calls.append(
                        WorkerToolCall(
                            call_id=str(action.get("action_id") or "").strip()
                            or f"{record.worker_task_id}_tool_{len(tool_calls) + 1}",
                            operator_ref=operator_ref,
                            arguments=dict(action.get("arguments") or {}),
                            depends_on=tuple(str(x).strip() for x in (action.get("depends_on") or []) if str(x).strip()),
                        )
                    )
                return WorkerReasonDecision(
                    status=_phase_status(worker_output, default="done"),
                    tool_calls=tuple(tool_calls),
                    reasoning_summary=(
                        str(worker_output.get("reasoning") or "").strip()
                        or str(worker_output.get("summary") or "").strip()
                    ),
                    raw_output=worker_output,
                    error_code=str(worker_output.get("error_code") or "").strip() or None,
                )

            async def _worker_execute_tool_call(
                call: WorkerToolCall,
                call_outputs: dict[str, Any],
                sequence: int,
                attempt: int,
            ) -> WorkerToolCallResult:
                try:
                    prepared_arguments = _resolve_action_argument_references(
                        dict(call.arguments or {}),
                        action_outputs=call_outputs,
                    )
                except _ActionArgumentReferenceError as exc:
                    return WorkerToolCallResult(
                        call_id=call.call_id,
                        operator_ref=call.operator_ref,
                        status="failed",
                        error_code="E_TASK_ARGUMENT_REFERENCE_INVALID",
                        evidence_refs=(),
                        output_summary=str(exc),
                        extra={"attempt": attempt, "sequence": sequence},
                    )
                step_req, res, tool_output = await _execute_runtime_step(
                    operator_ref=call.operator_ref,
                    arguments=(dict(prepared_arguments) if isinstance(prepared_arguments, dict) else {}),
                    idem_suffix=f"worker_{record.worker_task_id}_{_action_call_idem_suffix(action_id=call.call_id, operator_ref=call.operator_ref, arguments=dict(prepared_arguments) if isinstance(prepared_arguments, dict) else {})}_{attempt}",
                    span_suffix=f"worker_{record.worker_task_id}_{call.call_id}_{attempt}",
                    progress_summary=f"executed worker tool {call.call_id}: {call.operator_ref}",
                    progress_payload={
                        "phase": "worker_tool",
                        "source_phase": source_phase,
                        "worker_task_id": record.worker_task_id,
                        "call_id": call.call_id,
                        "operator_ref": call.operator_ref,
                        "attempt": attempt,
                    },
                    source_phase=source_phase,
                    runtime_task_id=None,
                    runtime_action_id=call.call_id,
                    emit_progress=False,
                )
                observation_capsule = _build_observation_capsule(
                    operator_ref=call.call_id and step_req.operator_ref or call.operator_ref,
                    output_obj=(tool_output if isinstance(tool_output, dict) else {}),
                )
                return WorkerToolCallResult(
                    call_id=call.call_id,
                    operator_ref=step_req.operator_ref,
                    status=str(res.status or ""),
                    error_code=res.error_code,
                    evidence_refs=tuple(er.ref for er in res.evidence_refs),
                    output_obj=(dict(tool_output) if isinstance(tool_output, dict) else {}),
                    output_summary=(
                        observation_capsule
                        or _extract_user_visible_text(tool_output if isinstance(tool_output, dict) else None)
                        or f"{step_req.operator_ref}:{str(res.status or '')}"
                    ),
                    observation_capsule=observation_capsule,
                    extra={"attempt": attempt, "sequence": sequence},
                )

            runtime = WorkerReActRuntime(
                worker_input=WorkerTaskRuntimeInput(
                    worker_task_id=str(record.worker_task_id or record.task_id),
                    runtime_task_id=record.task_id,
                    objective=str(record.objective or "").strip(),
                    scope_summary=str(record.scope_summary or "").strip(),
                    allowed_operator_refs=tuple(sorted(allowed_operator_refs)),
                    tool_budget=WorkerToolBudget(
                        max_calls=max(1, int((record.tool_budget or {}).get("max_calls") or 1)),
                        max_parallel_calls=min(
                            max(1, int((record.tool_budget or {}).get("max_parallel_calls") or 1)),
                            max(1, int(record_execution_lane_policy.get("tool_parallelism_cap") or 1)),
                        ),
                        retry_read_only_tools=bool((record.tool_budget or {}).get("retry_read_only_tools")),
                    ),
                    submission_id=str(record.submission_id or "").strip(),
                    execution_lane=str(record.execution_lane or "standard_task").strip() or "standard_task",
                    token_budget=WorkerTokenBudget(
                        max_total_tokens=max(0, int((record.token_budget or {}).get("max_total_tokens") or 0)),
                        reserve_tokens=max(0, int((record.token_budget or {}).get("reserve_tokens") or 0)),
                    ),
                    stop_policy=WorkerStopPolicy(
                        deadline_ms=max(0, int((record.stop_policy or {}).get("deadline_ms") or 0)),
                        no_progress_window=max(1, int((record.stop_policy or {}).get("no_progress_window") or 3)),
                        max_repeated_action_fingerprint_hits=max(
                            1,
                            int((record.stop_policy or {}).get("max_repeated_action_fingerprint_hits") or 2),
                        ),
                        verification_mode=str((record.stop_policy or {}).get("verification_mode") or "final_only").strip()
                        or "final_only",
                        continue_until_terminal=bool((record.stop_policy or {}).get("continue_until_terminal", True)),
                    ),
                    effect_class=str(record.effect_class or "read_only").strip() or "read_only",
                    generation=int(record.generation or 1),
                    time_budget_ms=int(record.time_budget_ms or 0),
                ),
                reason_step=_worker_reason_step,
                execute_tool_call=_worker_execute_tool_call,
                record_event=_record_worker_event,
                generation_guard=lambda generation: kernel_task_service.is_task_current(
                    task_id=record.task_id,
                    generation=generation,
                ),
                check_current=lambda task_id, generation, _stage: kernel_task_service.is_task_current(
                    task_id=task_id,
                    generation=generation,
                ),
                mark_side_effect_boundary=lambda operator_ref, generation: kernel_task_service.mark_side_effect_boundary(
                    task_id=record.task_id,
                    generation=generation,
                    operator_ref=operator_ref,
                ),
            )
            outcome = await runtime.run()
            return TaskRunResult(
                task_id=record.task_id,
                status=str(outcome.status or ""),
                error_code=outcome.error_code,
                evidence_refs=tuple(outcome.result_refs),
                output_summary=str(outcome.final_summary or "").strip(),
                tool_call_count=int(outcome.tool_call_count),
                iteration_count=int(outcome.iteration_count),
                needs_controller_review=bool(outcome.needs_leader_review),
                stale=bool(outcome.stale),
            )

        while True:
            batch_results = await kernel_task_service.execute_ready_batch(
                run_task=_run_kernel_task,
                max_tasks=1,
            )
            if not batch_results:
                break
            executed_any = True
            for batch_result in batch_results:
                record = kernel_task_service.get_task(batch_result.task_id)
                if record is None:
                    continue
                worker_task_id = str(record.worker_task_id or record.task_id).strip()
                runtime_view_task_id = runtime_worker_task_ids.get(record.task_id, "")
                completed_worker_states[worker_task_id] = str(batch_result.status or "")
                completed_worker_result_refs[worker_task_id] = list(batch_result.evidence_refs)
                if runtime_view_task_id:
                    runtime_state = (
                        "succeeded"
                        if str(batch_result.status or "") == "accepted"
                        else (
                            "awaiting_leader"
                            if str(batch_result.status or "") in {"hold", "need_context"}
                            else ("interrupted" if str(batch_result.status or "") == "superseded" else "failed")
                        )
                    )
                    runtime_session.finalize_worker_task(
                        task_id=runtime_view_task_id,
                        worker_task_id=worker_task_id,
                        state=runtime_state,
                        error_code=batch_result.error_code,
                        result_refs=list(batch_result.evidence_refs),
                        output_summary=str(batch_result.output_summary or "").strip(),
                        extra={
                            "tool_call_count": int(batch_result.tool_call_count),
                            "iteration_count": int(batch_result.iteration_count),
                            "execution_lane": record.execution_lane,
                            "submission_id": record.submission_id,
                            "worker_status": str(batch_result.status or ""),
                            "stale": bool(batch_result.stale),
                        },
                    )
                worker_notes.append(
                    {
                        "worker_task_id": worker_task_id,
                        "status": batch_result.status,
                        "error_code": batch_result.error_code,
                        "tool_call_count": int(batch_result.tool_call_count),
                        "iteration_count": int(batch_result.iteration_count),
                        "execution_lane": record.execution_lane,
                        "submission_id": record.submission_id,
                    }
                )
                if str(batch_result.output_summary or "").strip():
                    observation_capsules.append(
                        "\n".join(
                            [
                                f"WORKER RESULT {worker_task_id}",
                                f"status={batch_result.status}",
                                str(batch_result.output_summary or "").strip(),
                            ]
                        )
                    )
                if batch_result.status == "hold":
                    error_code = str(batch_result.error_code or "").strip() or "E_HITL_REQUIRED"
                    terminal_phase_outcome = "hold"
                    leader_review_needed = True
                    break
                if batch_result.status in {"blocked", "need_context"}:
                    leader_review_needed = True
                    structural_worker_error = str(batch_result.error_code or "").strip()
                    if structural_worker_error in {
                        "E_WORKER_SPLIT_REQUIRES_LEADER",
                        "E_TASK_DEPENDENCY_UNRESOLVED",
                        "E_TASK_DEPENDENCY_CYCLE",
                        "E_TASK_ARGUMENT_REFERENCE_INVALID",
                        "E_REASONING_LANE_INSUFFICIENT",
                    }:
                        error_code = structural_worker_error
                        terminal_phase_outcome = "blocked"
                        break
            if error_code is not None:
                break
        if error_code is None:
            remaining = kernel_task_service.list_submission_tasks(
                submission_id=submission_id,
                states=("queued", "running"),
            )
            if remaining:
                error_code = "E_TASK_DEPENDENCY_UNRESOLVED"
        if worker_notes:
            planner_evidence_refs.append(
                evidence.add_json(
                    {
                        "schema_version": "1.0.0",
                        "type": "worker_task_runtime_batch",
                        "task_id": task_id,
                        "graph_id": kernel_graph_id,
                        "submission_id": submission_id,
                        "execution_lane": execution_lane,
                        "source_phase": source_phase,
                        "worker_tasks": worker_notes,
                    },
                    kind="routing",
                ).ref
            )
        return executed_any, leader_review_needed

    async def _execute_controller_managed_worker_graph(
        *,
        worker_tasks: list[dict[str, Any]],
        source_phase: str,
    ) -> tuple[bool, bool]:
        nonlocal error_code
        nonlocal terminal_phase_outcome
        if not worker_tasks:
            return False, False
        graph_fingerprint = _worker_graph_fingerprint(worker_tasks)
        while True:
            executed_any, leader_review_needed = await _execute_worker_task_graph(
                worker_tasks=worker_tasks,
                source_phase=source_phase,
            )
            progress_made = error_code is None and executed_any and not leader_review_needed
            _controller_record_progress(
                progress_made=progress_made,
                graph_fingerprint=graph_fingerprint,
            )
            current_error_code = str(error_code or "").strip()
            if current_error_code == "E_REASONING_LANE_INSUFFICIENT":
                if _controller_maybe_promote_lane(reason=current_error_code, source_phase=source_phase):
                    error_code = None
                    terminal_phase_outcome = "failed"
                    continue
            if not current_error_code:
                stop_code = _controller_stop_code()
                if stop_code == "E_REASONING_LANE_INSUFFICIENT":
                    if _controller_maybe_promote_lane(reason=stop_code, source_phase=source_phase):
                        continue
                elif stop_code:
                    error_code = stop_code
                    current_error_code = stop_code
            if current_error_code:
                terminal_phase_outcome = "hold" if _is_pause_error_code(current_error_code) else "blocked"
                return executed_any, leader_review_needed
            if executed_any:
                await _maybe_execute_runtime_browse_bridge(reserve_non_delivery_tail=1)
            return executed_any, leader_review_needed

    binder_output = {
        "schema_version": "1.0.0",
        "type": "intent_decision_v1",
        "status": (
            "hold"
            if "hold" in amendment_decisions
            else (
                "need_context"
                if bool((query_compile.query.get("intent_recovery") or {}).get("needs_model_fallback"))
                else "done"
            )
        ),
        "ingress_decision": ingress_decision,
        "submission_id": submission_id,
        "execution_lane": execution_lane,
        "continuity_binding": str((query_compile.query.get("solution_query") or {}).get("continuity_binding") or "").strip(),
        "bound_contract_ref": "pending_contract" if _build_pending_contract(
            compiled_query=query_compile.query,
            effective_query=effective_query,
            interaction_mode=interaction_mode,
        ) else None,
    }
    binder_ref = evidence.add_json(binder_output, kind="routing")
    planner_evidence_refs.append(binder_ref.ref)
    runtime_session.record_reasoning_step(
        task_id=runtime_session.root_task_id or "",
        step_summary={
            "i": len(exec_summaries) + 1,
            "operator_ref": "binder://intent",
            "runtime_role": "leader",
            "status": "accepted",
            "error_code": None if binder_output["status"] != "hold" else "E_HITL_REQUIRED",
            "evidence_refs": [binder_ref.ref],
            "ingress_decision": ingress_decision,
            "execution_lane": execution_lane,
        },
        output_summary=f"binder resolved ingress_decision={ingress_decision} lane={execution_lane}",
        leader_phase="binder",
        phase_status=str(binder_output.get("status") or "done"),
    )
    if str(binder_output.get("status") or "").strip() == "need_context":
        terminal_stage = "need_context"
    elif str(binder_output.get("status") or "").strip() == "hold":
        terminal_phase_outcome = "hold"
        error_code = "E_HITL_REQUIRED"

    if error_code is None and terminal_stage == "final":
        recovered_worker_tasks = (
            kernel_task_service.list_submission_tasks(
                submission_id=submission_id,
                states=("queued", "running"),
            )
            if kernel_task_service is not None
            else []
        )
        if recovered_worker_tasks:
            current_worker_task_graph = [_task_record_to_worker_task(item) for item in recovered_worker_tasks]
            observation_capsules.append(_build_worker_task_graph_capsule(worker_tasks=current_worker_task_graph))
            planner_evidence_refs.append(
                evidence.add_json(
                    {
                        "schema_version": "1.0.0",
                        "type": "worker_task_recovery_batch",
                        "task_id": task_id,
                        "graph_id": kernel_graph_id,
                        "submission_id": submission_id,
                        "worker_tasks": current_worker_task_graph,
                    },
                    kind="routing",
                ).ref
            )
            executed_any, leader_review_needed = await _execute_controller_managed_worker_graph(
                worker_tasks=current_worker_task_graph,
                source_phase="worker_recovery",
            )
            if error_code is None and leader_review_needed and not executed_any:
                terminal_phase_outcome = "blocked"

    if error_code is None and terminal_stage == "final" and not current_worker_task_graph:
        planner_request = (
            "Generate WorkerTaskGraphV1 for the current task. "
            "Emit top-level worker_tasks only, with precise depends_on, allowed_operator_refs, scope_summary, completion_contract_ref, tool_budget, and time_budget_ms. "
            "Do not emit direct tool actions at the planner phase. "
            "Return status=need_context or blocked when planning cannot proceed safely. "
            "Do not speak to the user and do not emit send_message."
        )
        _, planner_res, planner_output = await _execute_runtime_step(
            operator_ref=str(assistant_skill_dir),
            arguments={"request": planner_request},
            idem_suffix="planner",
            span_suffix="planner",
            progress_summary="executed planner phase",
            progress_payload={"phase": "planner", "operator_ref": str(assistant_skill_dir)},
            prompt_profile_id="planner",
            runtime_task_id=runtime_session.root_task_id or None,
        )
        if planner_res.status != "accepted":
            error_code = planner_res.error_code or "E_EXECUTION_FAILED"
        else:
            violation = _phase_output_violation(profile_id="planner", output_obj=planner_output)
            if violation:
                error_code = violation
            else:
                planner_status = _phase_status(planner_output, default="done")
                current_worker_task_graph = _normalize_emitted_worker_tasks(planner_output)
                worker_task_graph_obj = {
                    "schema_version": "1.0.0",
                    "type": "worker_task_graph_v1",
                    "workspace_id": req.workspace_id,
                    "task_id": task_id,
                    "query": effective_query,
                    "query_mode": query_mode,
                    "interaction_mode": interaction_mode,
                    "query_ref": query_ref.ref,
                    "planner_mode": planner_mode,
                    "planner_status": planner_status,
                    "worker_tasks": current_worker_task_graph,
                    "context_need": planner_output.get("context_need"),
                    "domain_shift": planner_output.get("domain_shift"),
                    "policy": {
                        "backend": req.backend,
                        "model": req.model or "",
                        "verify_asvp": bool(req.verify_asvp),
                        "replay_mode": bool(req.replay_mode),
                        "solution_query": solution_query,
                        "model_routing_policy": model_routing_policy,
                        "prompt_compilation": {
                            "profile_ids": sorted(
                                list((dict(query_compile.query.get("prompt_profiles") or {})).keys())
                                if isinstance(query_compile.query.get("prompt_profiles"), dict)
                                else []
                            ),
                            "style_pack_id": str((query_compile.query.get("active_style_pack") or {}).get("pack_id") or "").strip()
                            if isinstance(query_compile.query.get("active_style_pack"), dict)
                            else "",
                            "doctrine_pack_id": str((query_compile.query.get("active_doctrine_pack") or {}).get("pack_id") or "").strip()
                            if isinstance(query_compile.query.get("active_doctrine_pack"), dict)
                            else "",
                        },
                    },
                }
                plan_ref = evidence.add_json(worker_task_graph_obj, kind="routing")
                planner_evidence_refs.append(plan_ref.ref)
                runtime_session.append_plan_revision(
                    record={
                        "id": f"revision:{int(runtime_session.active_plan_revision)}",
                        "plan_revision": int(runtime_session.active_plan_revision),
                        "task_id": task_id,
                        "objective": effective_query,
                        "planner_status": planner_status,
                        "worker_task_count": len(current_worker_task_graph),
                        "plan_ref": str(plan_ref.ref),
                        "worker_tasks": [dict(item) for item in current_worker_task_graph if isinstance(item, dict)],
                        "status": "active",
                    }
                )
                trace_log.emit(
                    TraceEvent(
                        schema_version="1.0.0",
                        ctx=req.trace,
                        event_type="ROUTED",
                        ts=_utc_iso(),
                        evidence_refs=(plan_ref,),
                        data={
                            "component": "assistant_loop",
                            "steps": len(current_worker_task_graph),
                            "plan_type": "worker_task_graph_v1",
                        },
                    )
                )
                if current_worker_task_graph:
                    observation_capsules.append(_build_worker_task_graph_capsule(worker_tasks=current_worker_task_graph))
                    executed_any, leader_review_needed = await _execute_controller_managed_worker_graph(
                        worker_tasks=current_worker_task_graph,
                        source_phase="planner",
                    )
                    if error_code is None and leader_review_needed and not executed_any:
                        terminal_phase_outcome = "blocked"
                if planner_status == "need_context":
                    terminal_stage = "need_context"
                elif planner_status == "blocked":
                    terminal_phase_outcome = "blocked"
                    error_code = str(planner_output.get("error_code") or "E_PLANNER_BLOCKED").strip() or "E_PLANNER_BLOCKED"

    if error_code is None and terminal_stage == "final":
        verifier_round = 0
        communicator_progress_round = 0
        while True:
            controller_stop_code = _controller_stop_code()
            if controller_stop_code == "E_REASONING_LANE_INSUFFICIENT":
                if _controller_maybe_promote_lane(reason=controller_stop_code, source_phase="verifier_replanner"):
                    continue
            elif controller_stop_code:
                error_code = controller_stop_code
                terminal_phase_outcome = "hold" if _is_pause_error_code(controller_stop_code) else "blocked"
                break
            verifier_round += 1
            verifier_request = (
                "Review the latest verified execution state against the user's objective and delivery contract. "
                "Return status=done only when the current verified evidence is already sufficient for communicator to answer the user's objective directly without more worker tasks. "
                "Return status=done, blocked, need_context, or continue. "
                "When returning continue, emit worker_tasks only. "
                "Do not speak to the user and do not emit send_message."
            )
            _, verifier_res, verifier_output = await _execute_runtime_step(
                operator_ref=str(assistant_skill_dir),
                arguments={"request": verifier_request},
                idem_suffix=f"verify_{verifier_round}",
                span_suffix=f"verify_{verifier_round}",
                progress_summary="executed verifier_replanner phase",
                progress_payload={"phase": "verifier_replanner", "operator_ref": str(assistant_skill_dir)},
                prompt_profile_id="verifier_replanner",
                runtime_task_id=runtime_session.root_task_id or None,
            )
            if verifier_res.status != "accepted":
                error_code = verifier_res.error_code or "E_EXECUTION_FAILED"
                break
            violation = _phase_output_violation(profile_id="verifier_replanner", output_obj=verifier_output)
            if violation:
                error_code = violation
                break
            verifier_status = _phase_status(verifier_output, default="done")
            if verifier_status == "need_context":
                terminal_stage = "need_context"
                break
            if verifier_status == "blocked":
                terminal_phase_outcome = "blocked"
                error_code = str(verifier_output.get("error_code") or "E_VERIFICATION_BLOCKED").strip() or "E_VERIFICATION_BLOCKED"
                break
            if verifier_status != "continue":
                break
            revised_worker_tasks = _normalize_emitted_worker_tasks(verifier_output)
            if not revised_worker_tasks:
                error_code = "E_WORKER_TASK_GRAPH_INVALID"
                break
            runtime_session.advance_plan_revision(
                record={
                    "task_id": task_id,
                    "objective": effective_query,
                    "planner_status": verifier_status,
                    "worker_task_count": len(revised_worker_tasks),
                    "worker_tasks": [dict(item) for item in revised_worker_tasks if isinstance(item, dict)],
                    "source_phase": "verifier_replanner",
                    "status": "active",
                }
            )
            progress_deliveries, worker_tasks_executed = [], False
            executed_any, leader_review_needed = await _execute_controller_managed_worker_graph(
                worker_tasks=revised_worker_tasks,
                source_phase="verifier_replanner",
            )
            worker_tasks_executed = executed_any
            if error_code is not None:
                break
            if worker_tasks_executed and not progress_deliveries:
                communicator_progress_round += 1
                _, progress_res, progress_output = await _execute_runtime_step(
                    operator_ref=str(assistant_skill_dir),
                    arguments={
                        "request": (
                            "Prepare a concise progress update using only verified state. "
                            "If there is no meaningful progress to report, you MAY omit send_message."
                        )
                    },
                    idem_suffix=f"communicator_progress_{communicator_progress_round}",
                    span_suffix=f"communicator_progress_{communicator_progress_round}",
                    progress_summary="executed communicator progress phase",
                    progress_payload={
                        "phase": "communicator",
                        "operator_ref": str(assistant_skill_dir),
                        "delivery_stage": "progress",
                    },
                    prompt_profile_id="communicator",
                    runtime_task_id=runtime_session.root_task_id or None,
                )
                if progress_res.status == "accepted":
                    progress_actions = [
                        _augment_send_message_arguments(
                            arguments=dict(item.get("arguments") or {}),
                            task_id=task_id,
                            delivery_stage="progress",
                            source_phase="communicator",
                        )
                        for item in _extract_channel_send_actions(progress_output)
                    ]
                    if progress_actions:
                        progress_deliveries, _ = await _execute_action_batch(
                            actions=[
                                {
                                    "action_id": str(item.get("message_key") or item.get("text") or "").strip() or f"progress_{idx}",
                                    "operator_ref": "builtin://channel.send_message",
                                    "arguments": item,
                                    "depends_on": [],
                                    "kind": "send_message",
                                }
                                for idx, item in enumerate(progress_actions, start=1)
                            ],
                            source_phase="communicator",
                            delivery_stage="progress",
                            allow_delivery=True,
                        )
                        if error_code is not None:
                            break

    if error_code is not None:
        terminal_stage = "hold" if _is_pause_error_code(error_code) else "blocker"
        terminal_failure_summary = build_user_facing_failure_summary_v1(
            compiled_query=query_compile.query,
            query_text=effective_query,
            exec_summaries=exec_summaries,
            step_outputs=step_outputs,
            error_code=error_code,
            primary_failure_code=error_code,
            phase_outcome=terminal_phase_outcome,
        )
        if isinstance(terminal_failure_summary, dict):
            failure_summary_ref = evidence.add_json(terminal_failure_summary, kind="policy")
            planner_evidence_refs.append(failure_summary_ref.ref)
    if terminal_stage == "need_context":
        emit_output_event(
            sink=req.output_event_sink,
            event_log=runtime_event_log,
            trace_id=req.trace.trace_id,
            turn_id=req.trace.turn_id,
            event_type="need_context",
            payload={"task_id": task_id},
        )
    if terminal_stage != "hold":
        _, communicator_res, communicator_output = await _execute_runtime_step(
            operator_ref=str(assistant_skill_dir),
            arguments={
                "request": _build_terminal_communicator_request(
                    terminal_stage=terminal_stage,
                    error_code=error_code,
                    exec_summaries=exec_summaries,
                    query_text=effective_query,
                    verified_failure_summary=terminal_failure_summary,
                )
            },
            idem_suffix="communicator",
            span_suffix="communicator",
            progress_summary=f"executed communicator phase ({terminal_stage})",
            progress_payload={
                "phase": "communicator",
                "operator_ref": str(assistant_skill_dir),
                "delivery_stage": terminal_stage,
            },
            prompt_profile_id="communicator",
            runtime_task_id=runtime_session.root_task_id or None,
        )
        if communicator_res.status != "accepted":
            error_code = communicator_res.error_code or "E_EXECUTION_FAILED"
            final_output = None
        else:
            violation = _phase_output_violation(profile_id="communicator", output_obj=communicator_output)
            if violation:
                error_code = violation
            else:
                message_actions = [
                    _augment_send_message_arguments(
                        arguments=dict(item.get("arguments") or {}),
                        task_id=task_id,
                        delivery_stage=terminal_stage,
                        source_phase="communicator",
                    )
                    for item in _extract_channel_send_actions(communicator_output)
                ]
                if not message_actions:
                    error_code = "E_MESSAGE_TASK_MISSING"
                    final_output = None
                else:
                    final_output = None
                    final_deliveries, _ = await _execute_action_batch(
                        actions=[
                            {
                                "action_id": str(item.get("message_key") or item.get("text") or "").strip() or f"message_{idx}",
                                "operator_ref": "builtin://channel.send_message",
                                "arguments": item,
                                "depends_on": [],
                                "kind": "send_message",
                            }
                            for idx, item in enumerate(message_actions, start=1)
                        ],
                        source_phase="communicator",
                        delivery_stage=terminal_stage,
                        require_message=True,
                        allow_delivery=True,
                        allow_when_error=True,
                    )
                    if final_deliveries:
                        final_output = dict(final_deliveries[-1])
    else:
        final_output = None

    followup_task_id: Optional[str] = None
    final_verify = verify_assistant_execution(
        compiled_query=query_compile.query,
        mode=query_compile.mode,
        exec_summaries=exec_summaries,
        step_outputs=step_outputs,
        error_code=error_code,
        final_output=final_output,
    )
    final_verify_ref = evidence.add_json(final_verify, kind="policy")
    planner_evidence_refs.append(final_verify_ref.ref)
    research_evidence_pack = build_research_evidence_pack_v1(
        task_id=task_id,
        objective=effective_query,
        task_requirements=task_requirements,
        exec_summaries=exec_summaries,
        step_outputs=step_outputs,
        error_code=error_code,
    )
    if research_evidence_pack is not None:
        research_evidence_pack_ref = evidence.add_json(research_evidence_pack, kind="artifact_draft").ref
        planner_evidence_refs.append(research_evidence_pack_ref)
    if error_code is None and not bool(final_verify.get("acceptance_pass")):
        fail_code = str(final_verify.get("primary_failure_code") or "").strip()
        error_code = fail_code or "E_DELIVERY_VERIFICATION_FAILED"

    # FU2: schedule follow-up only after delivery verification passes and only when not in replay_mode.
    if req.followup_at and (error_code is None):
        if bool(req.replay_mode):
            note_ref = evidence.add_json(
                {
                    "schema_version": "1.0.0",
                    "type": "followup_schedule_skipped",
                    "reason": "replay_mode=true",
                    "followup_at": str(req.followup_at),
                },
                kind="policy",
            )
            planner_evidence_refs.append(note_ref.ref)
        else:
            sched_trace = _new_child_trace(req.trace, span_suffix="followup_schedule")
            sched_req = ExecuteRequest(
                workspace_id=req.workspace_id,
                operator_ref="builtin://scheduler.at",
                arguments={
                    "schema_version": "1.0.0",
                    "run_at": str(req.followup_at),
                    "execute_request": {
                        "operator_ref": "builtin://assistant.submit",
                        "arguments": {
                            "schema_version": "1.0.0",
                            "query": f"[Follow-up] {req.query}",
                            "assistant_skill_dir": str(assistant_skill_dir),
                            "submitter": "scheduler.followup",
                            "consumer": "scheduler.execute_result",
                            "metadata": {
                                "scheduled_by": "assistant_loop",
                                "parent_trace_id": req.trace.trace_id,
                                "parent_turn_id": req.trace.turn_id,
                            },
                        },
                        "deadline_ms": 5000,
                        "policy_context": {
                            "verify_asvp": bool(req.verify_asvp),
                            "public_keys_dir": str(keys_dir),
                            "backend": req.backend,
                            "model": req.model,
                            "remote_calls_armed": bool(req.remote_calls_armed),
                            "allow_network_egress": bool(req.allow_network_egress),
                            "approved_by_human": bool(req.approved_by_human),
                            "replay_mode": bool(req.replay_mode),
                            "dialog_trace_id": req.trace.trace_id,
                            "capabilities": capability_items_for_policy_context(["assistant_runtime_submit"]),
                        },
                        "preferred_target": "local",
                    },
                    "idempotency_root": f"{root_idem}:followup_task",
                },
                idempotency_key=f"{root_idem}:followup_schedule",
                deadline_ms=min(5000, int(req.deadline_ms)),
                trace=sched_trace,
                policy_context={
                    "replay_mode": bool(req.replay_mode),
                    "capabilities": capability_items_for_policy_context(["scheduler_write"]),
                },
                preferred_target="local",
            )
            sched_res = await orch.execute(sched_req)
            if sched_res.status == "accepted":
                tool_io_refs = [er.ref for er in sched_res.evidence_refs if er.kind == "tool_io"]
                if tool_io_refs:
                    blob = evidence.get_blob(tool_io_refs[-1])
                    if blob is not None and blob.content_type == "application/json":
                        try:
                            obj = json.loads(blob.content.decode("utf-8"))
                            tid = obj.get("task_id")
                            if isinstance(tid, str) and tid.strip():
                                followup_task_id = tid.strip()
                        except Exception:
                            pass
                planner_evidence_refs.extend([er.ref for er in sched_res.evidence_refs])
            else:
                error_code = sched_res.error_code or "E_EXECUTION_FAILED"

    final_delivery_state = (
        "hold"
        if terminal_stage == "hold" or _is_pause_error_code(error_code) or str(final_verify.get("delivery_state") or "").strip() == "hold"
        else ("need_context" if error_code is None and terminal_stage == "need_context" else ("done" if error_code is None else "blocker"))
    )

    # Write a final snapshot for audit after verification and optional scheduling.
    final_snapshot = {
        "schema_version": "1.0.0",
        "type": "assistant_loop_result",
        "ts": _utc_iso(),
        "ok": error_code is None,
        "error_code": error_code,
        "plan_ref": plan_ref.ref,
        "steps": exec_summaries,
        "delivery_state": final_delivery_state,
        "task_id": task_id,
        "verification_ref": final_verify_ref.ref,
    }

    followup_plan = _build_followup_plan(query=req.query, ok=error_code is None, error_code=error_code)
    followup_ref = evidence.add_json(followup_plan, kind="artifact_draft")
    final_snapshot["followup_plan_ref"] = followup_ref.ref
    final_ref = evidence.add_json(final_snapshot, kind="snapshot")
    runtime_session.finalize_root(
        final_delivery_state=final_delivery_state,
        error_code=error_code,
        result_refs=[str(plan_ref.ref), str(final_verify_ref.ref), str(final_ref.ref)],
        output_summary=_extract_user_visible_text(final_output if isinstance(final_output, dict) else None),
    )
    _emit_delivery_state(
        trace_log=trace_log,
        ctx=req.trace,
        task_id=task_id,
        state=final_delivery_state,
        summary=(
            "clarification requested and delivered"
            if final_delivery_state == "need_context"
            else (
                "execution paused for HITL after budget exhaustion"
                if final_delivery_state == "hold"
                else ("delivery verified successfully" if error_code is None else _derive_hypothesis_revision(verify_report=final_verify, error_code=error_code))
            )
        ),
        evidence_refs=(final_ref,),
        error_code=error_code,
        final_snapshot_ref=final_ref.ref,
    )
    emit_output_event(
        sink=req.output_event_sink,
        event_log=runtime_event_log,
        trace_id=req.trace.trace_id,
        turn_id=req.trace.turn_id,
        event_type=final_delivery_state if final_delivery_state in {"need_context", "blocker", "hold"} else "done",
        payload={
            "task_id": task_id,
            "error_code": error_code,
            "final_output": dict(final_output or {}),
        },
    )
    if not bool(req.replay_mode):
        hypothesis_record = HypothesisRecord(
            schema_version="1.0.0",
            turn_id=str(req.trace.turn_id),
            iteration=max(1, len(exec_summaries) or 1),
            hypothesis=build_query_hypothesis(
                query_text=str(req.query),
                mode=query_compile.mode,
                capability_names=sorted(granted_capabilities),
            ),
            verification_action="verify_assistant_execution",
            verification_evidence_refs=tuple(
                dict.fromkeys([query_ref.ref, plan_ref.ref, final_verify_ref.ref, final_ref.ref])
            ),
            result=_map_hypothesis_result(verify_report=final_verify, error_code=error_code),  # type: ignore[arg-type]
            revision=_derive_hypothesis_revision(verify_report=final_verify, error_code=error_code),
        )
        hypothesis_store.put_if_absent(workspace_id=str(req.workspace_id), record=hypothesis_record)
        hypothesis_ref = evidence.add_json(
            {
                "schema_version": "1.0.0",
                "type": "hypothesis_record_v1",
                **hypothesis_record.to_json(),
            },
            kind="snapshot",
        )
        planner_evidence_refs.append(hypothesis_ref.ref)
        theorem_type = "sop" if hypothesis_record.result == "confirmed" else "anti_pattern"
        theorem_summary = (
            hypothesis_record.revision
            if theorem_type == "sop" and str(hypothesis_record.revision or "").strip()
            else hypothesis_record.hypothesis
        )
        theorem_record = build_theorem_record_v1(
            theorem_type=theorem_type,
            workspace_id=str(req.workspace_id),
            project_id=(project_capsule.project_id if project_capsule is not None else None),
            summary=str(theorem_summary or "").strip(),
            operator_hints=[
                str(x).strip()
                for x in (query_compile.query.get("solution_query") or {}).get("preferred_operator_hints", [])
                if str(x).strip()
            ],
            source_ref=hypothesis_ref.ref,
        )
        theorem_store.put_if_absent(record=theorem_record)
        for candidate in build_observation_learning_candidates_v1(
            workspace_id=str(req.workspace_id),
            task_id=task_id,
            objective=effective_query,
            delivery_state=final_delivery_state,
            error_code=error_code,
            research_evidence_pack_ref=research_evidence_pack_ref,
            hypothesis_ref=hypothesis_ref.ref,
        ):
            planner_evidence_refs.append(evidence.add_json(candidate, kind="artifact_draft").ref)

    _persist_runtime_snapshot(
        snapshot_store=snapshot_store,
        req=req,
        compiled_query=query_compile.query,
        effective_query=effective_query,
        interaction_mode=interaction_mode,
        error_code=error_code,
        summary=(
            "clarification requested and delivered"
            if final_delivery_state == "need_context"
            else ("delivery verified successfully" if error_code is None else _derive_hypothesis_revision(verify_report=final_verify, error_code=error_code))
        ),
        delivery_state=final_delivery_state,
        active_submission_id=submission_id,
        active_submission_generation=1,
    )

    consolidation_refs: tuple[str, ...] = ()
    if not bool(req.replay_mode):
        consolidation_refs = memory_consolidator.consolidate_turn(
            workspace_id=str(req.workspace_id),
            conversation_id=str(req.conversation_id or "").strip() or None,
            project_id=(project_capsule.project_id if project_capsule is not None else None),
            query=str(req.query),
            reply_text=_extract_user_visible_text(final_output if isinstance(final_output, dict) else None),
            error_code=error_code,
        )

    return AssistantLoopResult(
        ok=error_code is None,
        final_output=final_output,
        error_code=error_code,
        steps=exec_summaries,
        trace=req.trace,
        evidence_refs=list(
            dict.fromkeys(planner_evidence_refs + list(consolidation_refs) + [plan_ref.ref, followup_ref.ref, final_ref.ref])
        ),
        followup_plan_ref=followup_ref.ref,
        followup_task_id=followup_task_id,
        delivery_state=final_delivery_state,
        graph_id=kernel_graph_id or None,
    )
