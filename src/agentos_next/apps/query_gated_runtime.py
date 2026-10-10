from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal

from agentos_next.kernel.agent_profile import (
    build_default_agent_profile_v1,
    make_axiom_review_candidate,
    validate_agent_profile_v1,
)
from agentos_next.kernel.context_graph import build_context_graph_v1, build_task_context_views_v1
from agentos_next.kernel.effective_runtime_capabilities import (
    capability_names_from_effective_runtime_capabilities,
)
from agentos_next.kernel.execution_lane import (
    default_stop_policy_for_lane,
    default_token_budget_for_lane,
    execution_lane_policy,
)
from agentos_next.kernel.operator_catalog import search_operator_catalog
from agentos_next.kernel.prompt_compiler import compile_prompt_bundle_v1
from agentos_next.kernel.research_doctrine import derive_research_requirements_v1
from agentos_next.kernel.runtime_policy_bundle import FileRuntimePolicyBundleStore
from agentos_next.kernel.soul_profile import FileSoulProfileStore, validate_soul_profile_v1
from agentos_next.kernel.types import TraceContext
from agentos_next.pa.task_graph import (
    build_task_bundle_v1,
    build_task_execution_policy_v1,
    make_file_ref_v1,
)

QueryMode = Literal["simple", "standard", "complex"]

QUERY_ERROR_SCHEMA_INVALID = "E_QUERY_SCHEMA_INVALID"
QUERY_ERROR_CONTEXT_EVIDENCE_BOUNDS = "E_CONTEXT_EVIDENCE_BOUNDS"
QUERY_ERROR_AGENT_PROFILE_INVALID = "E_AGENT_PROFILE_INVALID"
QUERY_ERROR_SOUL_PROFILE_INVALID = "E_SOUL_PROFILE_INVALID"
QUERY_ERROR_CONTEXT_PLANE_INVALID = "E_CONTEXT_PLANE_INVALID"
QUERY_ERROR_TASK_ENVELOPE_INVALID = "E_TASK_ENVELOPE_INVALID"
QUERY_ERROR_DELIVERY_CONTRACT_INVALID = "E_DELIVERY_CONTRACT_INVALID"
QUERY_ERROR_HYPOTHESIS_REPEAT = "E_HYPOTHESIS_REPEAT_WITHOUT_NEW_EVIDENCE"
QUERY_ERROR_INPUT_DEBOUNCED = "E_INPUT_DEBOUNCED"
INPUT_DEBOUNCE_WINDOW_MS = 1000
_FAILURE_MAPPING_CACHE: dict[str, Any] | None = None
_DEFAULT_EXTERNAL_EVIDENCE_POLICY_V1 = {
    "search_rounds_max": 2,
    "browse_candidates_per_search_max": 3,
    "total_browse_steps_max": 4,
}


@dataclass(frozen=True)
class QueryCompileResult:
    ok: bool
    error_code: str | None
    mode: QueryMode
    query: dict[str, Any]
    verification_report: dict[str, Any]


def _normalize_text(raw: Any) -> str:
    return " ".join(str(raw or "").split())


def _normalize_hypothesis_text(raw: Any) -> str:
    text = _normalize_text(raw).lower()
    text = re.sub(r"\s+", " ", text)
    return text[:160]


def _normalize_user_query_for_debounce(raw: Any) -> str:
    text = _normalize_text(raw).casefold()
    text = re.sub(r"\s+", " ", text)
    return text[:240]


def _normalize_bounded_int(
    value: Any,
    *,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    try:
        parsed = int(value)
    except Exception:
        return default
    if parsed < minimum:
        return minimum
    if parsed > maximum:
        return maximum
    return parsed


def _normalize_external_evidence_policy_v1(
    *,
    defaults: dict[str, Any] | None = None,
    override: dict[str, Any] | None = None,
) -> dict[str, int]:
    base = dict(_DEFAULT_EXTERNAL_EVIDENCE_POLICY_V1)
    if isinstance(defaults, dict):
        base.update(
            {
                "search_rounds_max": _normalize_bounded_int(
                    defaults.get("search_rounds_max"),
                    default=base["search_rounds_max"],
                    minimum=1,
                    maximum=6,
                ),
                "browse_candidates_per_search_max": _normalize_bounded_int(
                    defaults.get("browse_candidates_per_search_max"),
                    default=base["browse_candidates_per_search_max"],
                    minimum=1,
                    maximum=10,
                ),
                "total_browse_steps_max": _normalize_bounded_int(
                    defaults.get("total_browse_steps_max"),
                    default=base["total_browse_steps_max"],
                    minimum=1,
                    maximum=12,
                ),
            }
        )
    if isinstance(override, dict):
        base.update(
            {
                "search_rounds_max": _normalize_bounded_int(
                    override.get("search_rounds_max"),
                    default=base["search_rounds_max"],
                    minimum=1,
                    maximum=6,
                ),
                "browse_candidates_per_search_max": _normalize_bounded_int(
                    override.get("browse_candidates_per_search_max"),
                    default=base["browse_candidates_per_search_max"],
                    minimum=1,
                    maximum=10,
                ),
                "total_browse_steps_max": _normalize_bounded_int(
                    override.get("total_browse_steps_max"),
                    default=base["total_browse_steps_max"],
                    minimum=1,
                    maximum=12,
                ),
            }
        )
    return {
        "search_rounds_max": int(base["search_rounds_max"]),
        "browse_candidates_per_search_max": int(base["browse_candidates_per_search_max"]),
        "total_browse_steps_max": int(base["total_browse_steps_max"]),
    }


def _task_id_for_trace(trace: TraceContext) -> str:
    return f"task_{str(trace.trace_id).strip()}_{str(trace.turn_id).strip()}"


def _normalized_capability_signature(capability_names: list[str] | set[str] | tuple[str, ...] | None) -> str:
    names = sorted(
        {
            str(name).strip()
            for name in (capability_names or [])
            if str(name).strip()
        }
    )
    return "|".join(names)


def _utc_iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


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


def _format_utc_offset(dt: datetime) -> str:
    offset = dt.utcoffset() or timedelta(0)
    total_minutes = int(offset.total_seconds() // 60)
    sign = "+" if total_minutes >= 0 else "-"
    total_minutes = abs(total_minutes)
    hours, minutes = divmod(total_minutes, 60)
    return f"{sign}{hours:02d}:{minutes:02d}"


def _local_timezone_name(local_dt: datetime) -> str:
    env_tz = str(os.getenv("TZ") or "").strip()
    if env_tz:
        return env_tz
    tzinfo = local_dt.tzinfo
    zone_key = getattr(tzinfo, "key", None)
    if isinstance(zone_key, str) and zone_key.strip():
        return zone_key.strip()
    name = str(local_dt.tzname() or "").strip()
    return name or "local"


def build_temporal_anchor_v1(*, message_received_at_utc: str | None) -> dict[str, Any]:
    anchor_utc = _parse_utc_iso(message_received_at_utc) or datetime.now(timezone.utc)
    anchor_local = anchor_utc.astimezone()
    local_date = anchor_local.date()
    timezone_name = _local_timezone_name(anchor_local)
    return {
        "schema_version": "1.0.0",
        "type": "temporal_anchor_v1",
        "anchor_time_utc": _utc_iso(anchor_utc),
        "anchor_time_local": anchor_local.isoformat(),
        "timezone_local": timezone_name,
        "utc_offset_local": _format_utc_offset(anchor_local),
        "date_local": local_date.isoformat(),
        "time_local": anchor_local.strftime("%H:%M:%S"),
        "weekday_local": anchor_local.strftime("%A"),
        "relative_dates": {
            "yesterday": (local_date - timedelta(days=1)).isoformat(),
            "today": local_date.isoformat(),
            "tomorrow": (local_date + timedelta(days=1)).isoformat(),
        },
    }


def _temporal_anchor_known_facts(anchor: dict[str, Any] | None) -> list[str]:
    temporal = dict(anchor or {})
    relative = dict(temporal.get("relative_dates") or {})
    facts: list[str] = []
    if str(temporal.get("anchor_time_utc") or "").strip():
        facts.append(f"anchor_time_utc={str(temporal.get('anchor_time_utc')).strip()}")
    if str(temporal.get("timezone_local") or "").strip():
        facts.append(f"timezone_local={str(temporal.get('timezone_local')).strip()}")
    if str(temporal.get("date_local") or "").strip():
        facts.append(f"date_local={str(temporal.get('date_local')).strip()}")
    for key in ("today", "tomorrow", "yesterday"):
        value = str(relative.get(key) or "").strip()
        if value:
            facts.append(f"relative_date_{key}_local={value}")
    if str(temporal.get("weekday_local") or "").strip():
        facts.append(f"weekday_local={str(temporal.get('weekday_local')).strip()}")
    return facts


def build_query_hypothesis(
    *,
    query_text: str,
    mode: QueryMode,
    capability_names: list[str] | set[str] | tuple[str, ...] | None = None,
) -> str:
    hypothesis = f"mode={mode}; objective={_normalize_hypothesis_text(query_text)}"
    capability_signature = _normalized_capability_signature(capability_names)
    if capability_signature:
        hypothesis += f"; capabilities={capability_signature}"
    return hypothesis


def _should_enforce_input_debounce(
    *,
    context_planes: dict[str, Any],
    current_query_text: str,
    message_received_at_utc: str | None,
    debounce_window_ms: int = INPUT_DEBOUNCE_WINDOW_MS,
) -> bool:
    recovery_plane = dict((context_planes or {}).get("intent_recovery_plane") or {})
    last_user_query = _normalize_user_query_for_debounce(recovery_plane.get("last_user_query"))
    current_user_query = _normalize_user_query_for_debounce(current_query_text)
    if not last_user_query or not current_user_query or last_user_query != current_user_query:
        return False
    previous_at = _parse_utc_iso(recovery_plane.get("last_user_query_at_utc"))
    current_at = _parse_utc_iso(message_received_at_utc) or datetime.now(timezone.utc)
    if previous_at is None or current_at < previous_at:
        return False
    delta_ms = int((current_at - previous_at).total_seconds() * 1000)
    return 0 <= delta_ms <= max(0, int(debounce_window_ms))


def _default_acceptance_criteria(
    *,
    query_text: str,
    mode: QueryMode,
    needs_research: bool,
    should_write_memory: bool,
    task_requirements: dict[str, Any] | None = None,
) -> list[str]:
    criteria = [
        "result addresses the user's objective directly",
        "facts and uncertainty are separated clearly when evidence is incomplete",
    ]
    reqs = dict(task_requirements or {})
    if bool(reqs.get("requires_workspace_observation")):
        criteria.append("workspace-backed tasks must cite fresh workspace observations or stop with a blocker")
    if bool(reqs.get("forbid_speculation_without_evidence")):
        criteria.append("when required evidence is unavailable, stop instead of filling gaps with hypotheses")
    if bool(reqs.get("attachment_evidence_required")):
        criteria.append("when the task depends on attachments, use verified attachment evidence or stop with a blocker")
    if needs_research:
        criteria.append("live or external information gaps are reported explicitly")
    if bool(reqs.get("research_required")):
        criteria.append("research tasks must browse and compare bounded sources before claiming convergence")
    if bool(reqs.get("citation_required")):
        criteria.append("when citations are required, preserve a bounded citation set or stop with a blocker")
    if should_write_memory:
        criteria.append("any memory persistence is reported truthfully")
    if mode != "simple":
        criteria.append("response reflects retrieved context or explains why retrieval did not help")
    return criteria[:6]


def build_task_envelope_v1(
    *,
    query_text: str,
    req_trace: TraceContext,
    mode: QueryMode,
    scope: str,
    risk: str,
    needs_research: bool,
    should_write_memory: bool,
    message_received_at_utc: str | None = None,
    temporal_anchor: dict[str, Any] | None = None,
    task_requirements: dict[str, Any] | None = None,
) -> dict[str, Any]:
    objective = _normalize_text(query_text)
    known_facts: list[str] = [f"scope={scope}", f"risk={risk}", f"mode={mode}"]
    if str(message_received_at_utc or "").strip():
        known_facts.append(f"message_received_at_utc={str(message_received_at_utc).strip()}")
    known_facts.extend(_temporal_anchor_known_facts(temporal_anchor))
    if isinstance(task_requirements, dict):
        if bool(task_requirements.get("attachments_present")):
            known_facts.append("attachments_present=true")
            attachment_media_kinds = [
                str(x).strip()
                for x in (task_requirements.get("attachment_media_kinds") or [])
                if str(x).strip()
            ]
            if attachment_media_kinds:
                known_facts.append(f"attachment_media_kinds={'|'.join(attachment_media_kinds)}")
            known_facts.append(f"attachment_usage_mode={str(task_requirements.get('attachment_usage_mode') or 'none')}")
    open_questions: list[str] = []
    if objective.lower() in {"ok", "okay", "好的", "行", "嗯"}:
        open_questions.append("user intent may depend on prior context")
    retrieval_hints: list[str] = []
    if needs_research:
        retrieval_hints.append("external_facts")
    if should_write_memory:
        retrieval_hints.append("memory:user_note")
    return {
        "schema_version": "1.0.0",
        "task_id": _task_id_for_trace(req_trace),
        "objective": objective,
        "deliverable": "user_visible_answer",
        "acceptance_criteria": _default_acceptance_criteria(
            query_text=query_text,
            mode=mode,
            needs_research=needs_research,
            should_write_memory=should_write_memory,
            task_requirements=task_requirements,
        ),
        "constraints": [
            "stay_within_budget",
            "use_only_runtime_granted_actions",
            "surface_blockers_and_uncertainty",
        ],
        "source_inputs": [
            {
                "kind": "user_message",
                "ref": f"ingress:{req_trace.turn_id}",
                "summary": objective[:240],
            }
        ],
        "known_facts": known_facts,
        "open_questions": open_questions,
        "ambiguity_policy": "clarify_if_blocking",
        "retrieval_hints": retrieval_hints,
    }


def _normalized_attachments(attachments: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None) -> list[dict[str, Any]]:
    return [dict(item) for item in (attachments or []) if isinstance(item, dict)]


def _attachment_summary(item: dict[str, Any]) -> str | None:
    for key in ("summary", "caption", "name", "filename", "title"):
        value = str(item.get(key) or "").strip()
        if value:
            return value[:160]
    media_kind = str(item.get("media_kind") or "").strip()
    if media_kind:
        return f"attachment:{media_kind}"
    return None


def _build_task_file_refs_v1(
    *,
    attachments: list[dict[str, Any]],
    new_evidence_refs: list[str] | None,
    attachment_evidence_required: bool,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    def _add(ref: dict[str, Any]) -> None:
        ref_type = str(ref.get("ref_type") or "").strip()
        value = str(ref.get("value") or "").strip()
        key = (ref_type, value)
        if not ref_type or not value or key in seen:
            return
        out.append(ref)
        seen.add(key)

    default_usage = "required" if attachment_evidence_required else "optional"
    for item in attachments:
        summary = _attachment_summary(item)
        workspace_path = (
            str(item.get("workspace_path") or item.get("path") or item.get("relative_path") or "").strip()
        )
        if workspace_path:
            resolver = "fs.list" if workspace_path.endswith("/") else "fs.read"
            _add(
                make_file_ref_v1(
                    ref_type="workspace_path",
                    value=workspace_path,
                    usage=default_usage,
                    summary=summary,
                    resolver=resolver,
                )
            )
        evidence_ref = str(item.get("evidence_ref") or "").strip()
        if evidence_ref:
            _add(
                make_file_ref_v1(
                    ref_type="evidence_ref",
                    value=evidence_ref,
                    usage=default_usage,
                    summary=summary,
                )
            )
        artifact_ref = str(item.get("artifact_ref") or "").strip()
        if artifact_ref:
            _add(
                make_file_ref_v1(
                    ref_type="artifact_ref",
                    value=artifact_ref,
                    usage=default_usage,
                    summary=summary,
                )
            )

    for ref in [str(item).strip() for item in (new_evidence_refs or []) if str(item).strip()]:
        _add(
            make_file_ref_v1(
                ref_type="evidence_ref",
                value=ref,
                usage="hint",
                summary="new evidence from current turn",
            )
        )
    return out


def _derive_task_delegation_shape(*, task_requirements: dict[str, Any], mode: QueryMode) -> tuple[str, int, int, dict[str, Any]]:
    needs_decomposition = bool(
        task_requirements.get("requires_multi_step_plan")
        or task_requirements.get("requires_workspace_observation")
        or task_requirements.get("requires_external_evidence")
        or task_requirements.get("research_required")
    )
    task_mode = "decomposable" if needs_decomposition else "atomic"
    if not needs_decomposition:
        return task_mode, 0, 0, {"objective_locked": True, "acceptance_locked": True, "worker_split_requires_leader": True}
    delegation_budget = 3 if mode == "complex" else 2
    max_depth = 2 if bool(task_requirements.get("research_required")) else 1
    scope_guard = {
        "objective_locked": True,
        "acceptance_locked": True,
        "risk_escalation_requires_leader": True,
        "capability_escalation_requires_leader": True,
        "workspace_scope_locked": True,
        "conversation_scope_locked": True,
        "replan_requires_leader": True,
        "worker_split_requires_leader": True,
    }
    return task_mode, delegation_budget, max_depth, scope_guard


def _build_task_execution_policy_from_requirements(
    *,
    deadline_ms: int,
    mode: QueryMode,
    task_requirements: dict[str, Any],
) -> dict[str, Any]:
    base_deadline = max(1000, int(deadline_ms))
    llm_timeout = max(2000, base_deadline // (2 if mode == "simple" else 3))
    tool_timeout = max(3000, base_deadline // (3 if mode == "simple" else 4))
    if bool(task_requirements.get("requires_external_evidence")):
        tool_timeout = max(tool_timeout, 12000 if mode != "simple" else tool_timeout)
    if bool(task_requirements.get("requires_workspace_observation")):
        tool_timeout = max(tool_timeout, 8000)
    if bool(task_requirements.get("research_required")):
        llm_timeout = max(llm_timeout, 10000)
        tool_timeout = max(tool_timeout, 15000)
    return build_task_execution_policy_v1(
        deadline_ms=base_deadline,
        llm_timeout_ms=min(base_deadline, llm_timeout),
        tool_timeout_ms=min(base_deadline, tool_timeout),
        max_attempts=3 if bool(task_requirements.get("research_required")) else 2,
        side_effect_safe_retry=not bool(task_requirements.get("delivery_requires_send")),
    )


def _attachment_media_kinds(attachments: list[dict[str, Any]] | None) -> list[str]:
    out: list[str] = []
    for item in attachments or []:
        media_kind = str(item.get("media_kind") or "").strip().lower()
        if media_kind and media_kind not in out:
            out.append(media_kind)
    return out


def _infer_attachment_usage_mode(*, query_text: str, attachments: list[dict[str, Any]]) -> str:
    if not attachments:
        return "none"
    text = _normalize_text(query_text)
    lowered = text.lower()
    if not text or text.startswith("请处理我发送的附件"):
        return "primary_evidence"
    primary_hints = (
        "看图",
        "识别",
        "图里",
        "图片",
        "照片",
        "截图",
        "读一下这个文件",
        "这个文件",
        "这段语音",
        "这个视频",
        "what is in this image",
        "look at this image",
        "read this file",
        "what does this voice",
        "what is in this video",
    )
    if any(h in lowered or h in text for h in primary_hints):
        return "primary_evidence"
    if any(str(item.get("caption") or "").strip() for item in attachments):
        return "text_context"
    return "supplemental_evidence"


def _phase_supports_media(support: dict[str, Any], required_media_kinds: list[str]) -> bool:
    if not required_media_kinds:
        return True
    key_map = {
        "image": "supports_image",
        "document": "supports_document",
        "audio": "supports_audio",
        "video": "supports_video",
    }
    for media_kind in required_media_kinds:
        if not bool(support.get(key_map.get(media_kind, ""))):
            return False
    return True


def _derive_modality_reachability(
    *,
    effective_runtime_capabilities: dict[str, Any] | None,
    required_media_kinds: list[str],
    attachment_usage_mode: str,
    text_only_fallback_allowed: bool,
) -> tuple[dict[str, Any], bool, str | None]:
    multimodal = (
        dict((effective_runtime_capabilities or {}).get("multimodal") or {})
        if isinstance(effective_runtime_capabilities, dict)
        else {}
    )
    phase_support = dict(multimodal.get("phase_backend_support") or {})
    reachability: dict[str, Any] = {}
    for phase in ("intent_router", "planner", "executor", "verifier_replanner", "communicator"):
        support = dict(phase_support.get(phase) or {})
        reachability[phase] = {
            **support,
            "supports_required_media": _phase_supports_media(support, required_media_kinds),
        }
    if attachment_usage_mode in {"none", "text_context"}:
        return reachability, True, None
    required_phases = ("executor", "verifier_replanner")
    supported = all(bool((reachability.get(phase) or {}).get("supports_required_media")) for phase in required_phases)
    if supported:
        return reachability, True, None
    if text_only_fallback_allowed:
        return reachability, False, "attachment evidence is unavailable in the current backend/model chain; text-only fallback may continue"
    return reachability, False, "required attachment evidence cannot reach executor/verifier under the current backend/model chain"


def derive_task_requirements_v1(
    *,
    query_text: str,
    scope: str,
    capabilities: list[str],
    attachments: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None = None,
    effective_runtime_capabilities: dict[str, Any] | None = None,
    external_evidence_policy_defaults: dict[str, Any] | None = None,
    external_evidence_policy_override: dict[str, Any] | None = None,
) -> dict[str, Any]:
    text = _normalize_text(query_text)
    lowered = text.lower()
    caps = {str(x).strip() for x in capabilities if str(x).strip()}
    attachment_items = _normalized_attachments(attachments)
    attachment_media_kinds = _attachment_media_kinds(attachment_items)
    attachments_present = bool(attachment_items)
    attachment_usage_mode = _infer_attachment_usage_mode(query_text=text, attachments=attachment_items)
    attachment_evidence_required = attachment_usage_mode in {"primary_evidence", "supplemental_evidence"}
    required_media_kinds = list(attachment_media_kinds) if attachment_evidence_required else []
    text_only_fallback_allowed = attachment_usage_mode in {"text_context", "supplemental_evidence"}
    external_evidence_policy_v1 = _normalize_external_evidence_policy_v1(
        defaults=external_evidence_policy_defaults,
        override=external_evidence_policy_override,
    )
    workspace_analysis_hints = (
        "分析",
        "审查",
        "评审",
        "review",
        "analyze",
        "audit",
        "评价",
        "建议",
        "架构",
        "项目",
        "repo",
        "repository",
        "代码库",
        "codebase",
    )
    delivery_kind = "user_visible_answer"
    requires_workspace_observation = False
    requires_external_evidence = False
    requires_multi_step_plan = False
    required_operator_hints: list[str] = []

    if scope in {"current_project", "new_project"} and any(h in lowered or h in text for h in workspace_analysis_hints):
        requires_workspace_observation = True
        requires_multi_step_plan = True
        delivery_kind = "workspace_analysis"
        required_operator_hints.extend(["fs.list", "fs.read"])

    if _needs_research(text):
        requires_external_evidence = True
        requires_multi_step_plan = True
        required_operator_hints.append("web.browse")
    if attachment_evidence_required:
        requires_multi_step_plan = True

    if any(h in lowered or h in text for h in ("计划", "方案", "架构", "review", "audit", "analyze", "评估", "诊断")):
        requires_multi_step_plan = True

    missing_operator_hints: list[str] = []
    if requires_workspace_observation:
        if "fs_read" not in caps:
            missing_operator_hints.append("fs_read")
        if "shell_exec" not in caps and "fs_read" not in caps:
            missing_operator_hints.append("shell_exec")
    if requires_external_evidence and "web_browse" not in caps and "web_search" not in caps:
        missing_operator_hints.append("web_browse")
    downstream_modality_reachability, multimodal_chain_supported, multimodal_block_reason = _derive_modality_reachability(
        effective_runtime_capabilities=effective_runtime_capabilities,
        required_media_kinds=required_media_kinds,
        attachment_usage_mode=attachment_usage_mode,
        text_only_fallback_allowed=text_only_fallback_allowed,
    )
    attachment_phase_policy = {
        "intent_router": "metadata_only" if attachments_present else "none",
        "planner": "metadata_only" if attachments_present else "none",
        "executor": (
            "required"
            if attachment_usage_mode == "primary_evidence"
            else "optional"
            if attachment_usage_mode == "supplemental_evidence"
            else "none"
        ),
        "verifier_replanner": (
            "required"
            if attachment_usage_mode == "primary_evidence"
            else "optional"
            if attachment_usage_mode == "supplemental_evidence"
            else "none"
        ),
        "communicator": "none",
    }

    return {
        "schema_version": "1.0.0",
        "type": "task_requirements_v1",
        "delivery_kind": delivery_kind,
        "requires_workspace_observation": requires_workspace_observation,
        "requires_external_evidence": requires_external_evidence,
        "requires_multi_step_plan": requires_multi_step_plan,
        "forbid_speculation_without_evidence": bool(requires_workspace_observation or requires_external_evidence),
        "attachments_present": attachments_present,
        "attachment_media_kinds": attachment_media_kinds,
        "attachment_usage_mode": attachment_usage_mode,
        "attachment_evidence_required": attachment_evidence_required,
        "required_media_kinds": required_media_kinds,
        "downstream_modality_reachability": downstream_modality_reachability,
        "multimodal_chain_supported": bool(multimodal_chain_supported),
        "multimodal_block_reason": multimodal_block_reason,
        "text_only_fallback_allowed": bool(text_only_fallback_allowed),
        "attachment_phase_policy": attachment_phase_policy,
        "required_operator_hints": list(dict.fromkeys(required_operator_hints)),
        "missing_operator_hints": list(dict.fromkeys(missing_operator_hints)),
        "external_evidence_policy_v1": external_evidence_policy_v1,
        "research_required": False,
        "research_depth": "none",
        "selected_doctrine_pack": "fast_path_mode",
        "evidence_expectation": (
            "external_lookup"
            if requires_external_evidence
            else ("workspace_observation" if requires_workspace_observation else "local_state")
        ),
        "citation_required": False,
        "self_adversarial_required": False,
        "research_max_rounds": 1,
        "source_count_min": 0,
    }


def build_delivery_contract_v1(
    *,
    task_envelope: dict[str, Any],
    mode: QueryMode,
    should_write_memory: bool,
) -> dict[str, Any]:
    result_type = "action" if should_write_memory else "answer"
    done_definition = "produce a user-visible answer that satisfies acceptance criteria and reports blockers honestly"
    if should_write_memory:
        done_definition = (
            "produce a user-visible answer and truthfully report any memory persistence attempt or failure"
        )
    return {
        "schema_version": "1.0.0",
        "task_id": str(task_envelope.get("task_id") or ""),
        "result_type": result_type,
        "verification_plan": [
            "check acceptance_criteria",
            "check user-visible delivery passed through send_message task when applicable",
            "check final_output is non-empty when execution succeeds",
            "check blockers are reported explicitly on failure",
        ],
        "done_definition": done_definition,
        "retry_policy": {
            "max_repairs": 0 if mode == "simple" else 1,
            "stop_on_blocker": True,
        },
        "visibility_contract": {
            "ack": True,
            "progress": True,
            "blocker": True,
            "done": True,
        },
    }


def build_minimal_context_envelope(
    *,
    task_envelope: dict[str, Any],
    delivery_contract: dict[str, Any],
    context_planes: dict[str, Any],
    mode: QueryMode,
    current_hypothesis: str,
) -> str:
    def _render_list(items: list[str], *, limit: int = 5) -> list[str]:
        vals = [str(x).strip() for x in items if str(x).strip()]
        if not vals:
            return ["- none"]
        return [f"- {x}" for x in vals[:limit]]

    lines: list[str] = [
        "TASK",
        f"objective: {str(task_envelope.get('objective') or '').strip()}",
        f"deliverable: {str(task_envelope.get('deliverable') or '').strip()}",
        "",
        "ACCEPTANCE",
        *_render_list(list(task_envelope.get("acceptance_criteria") or [])),
        "",
        "CONSTRAINTS",
        *_render_list(
            list(task_envelope.get("constraints") or [])
            + list((context_planes.get("constraint_plane") or {}).get("active_constraint_ids") or []),
            limit=8,
        ),
        "",
        "FACTS",
        *_render_list(
            list(task_envelope.get("known_facts") or [])
            + [str((context_planes.get("execution_plane") or {}).get("state_summary") or "").strip()],
            limit=6,
        ),
        "",
        "HYPOTHESIS",
        f"- {current_hypothesis}",
        "",
        "NEXT",
        f"- execute in {mode} mode",
        f"- verify against done_definition: {str(delivery_contract.get('done_definition') or '').strip()}",
    ]
    open_questions = [str(x).strip() for x in (task_envelope.get("open_questions") or []) if str(x).strip()]
    if open_questions:
        lines.extend(["", "OPEN QUESTIONS", *_render_list(open_questions)])
    return "\n".join(lines)


def _compact_seq(values: list[str], *, limit: int) -> str:
    items = [str(x).strip() for x in values if str(x).strip()]
    if not items:
        return "-"
    return "|".join(items[:limit])


def _compact_fact_lines(task_envelope: dict[str, Any], context_planes: dict[str, Any]) -> str:
    facts = [
        *[str(x).strip() for x in (task_envelope.get("known_facts") or []) if str(x).strip()],
        str((context_planes.get("execution_plane") or {}).get("state_summary") or "").strip(),
    ]
    return _compact_seq(facts, limit=4)


def _execution_axiom_ids(context_planes: dict[str, Any]) -> list[str]:
    constraint_plane = context_planes.get("constraint_plane") or {}
    vals = constraint_plane.get("execution_axiom_ids")
    if not isinstance(vals, list):
        vals = constraint_plane.get("active_axiom_ids") or []
    return [str(x).strip() for x in vals if str(x).strip()]


def _communication_axiom_ids(context_planes: dict[str, Any]) -> list[str]:
    constraint_plane = context_planes.get("constraint_plane") or {}
    vals = constraint_plane.get("communication_axiom_ids") or []
    return [str(x).strip() for x in vals if str(x).strip()]


def _constraint_ids(context_planes: dict[str, Any]) -> list[str]:
    constraint_plane = context_planes.get("constraint_plane") or {}
    vals = constraint_plane.get("active_constraint_ids") or []
    return [str(x).strip() for x in vals if str(x).strip()]


def build_execution_prefix_v1(
    *,
    task_envelope: dict[str, Any],
    delivery_contract: dict[str, Any],
    context_planes: dict[str, Any],
    mode: QueryMode,
    current_hypothesis: str,
    intent_recovery: dict[str, Any] | None = None,
    task_requirements: dict[str, Any] | None = None,
    solution_query: dict[str, Any] | None = None,
) -> str:
    axiom_ids = _execution_axiom_ids(context_planes)
    constraint_ids = _constraint_ids(context_planes)
    task_constraints = [str(x).strip() for x in (task_envelope.get("constraints") or []) if str(x).strip()]
    lines = [
        "PHASE=EXEC",
        f"GOAL={str(task_envelope.get('objective') or '').strip()}",
        f"DELIVERABLE={str(task_envelope.get('deliverable') or '').strip()}",
        f"DONE={str(delivery_contract.get('done_definition') or '').strip()}",
        f"MODE={str(mode)}",
        f"INTENT={str((intent_recovery or {}).get('intent_option') or 'DIRECT_TASK')}",
        f"AX={_compact_seq(axiom_ids, limit=6)}",
        f"RC={_compact_seq(task_constraints + constraint_ids, limit=8)}",
        f"FACTS={_compact_fact_lines(task_envelope, context_planes)}",
        f"HYP={str(current_hypothesis or '').strip() or '-'}",
        "POLICY=retrieval_first|min_action|verify_before_done",
        "NEXT=execute|verify|stop_on_blocker",
    ]
    if isinstance(solution_query, dict):
        approach = str(solution_query.get("approach_strategy") or "").strip()
        plan_basis = str(solution_query.get("plan_basis") or "").strip()
        continuity = str(solution_query.get("continuity_binding") or "").strip()
        if approach or plan_basis or continuity:
            lines.append(
                "THINK="
                + _compact_seq(
                    [
                        f"approach:{approach}" if approach else "",
                        f"plan:{plan_basis}" if plan_basis else "",
                        f"bind:{continuity}" if continuity else "",
                    ],
                    limit=4,
                )
            )
    if isinstance(task_requirements, dict):
        req_bits: list[str] = []
        if bool(task_requirements.get("requires_workspace_observation")):
            req_bits.append("workspace_observation")
        if bool(task_requirements.get("requires_external_evidence")):
            req_bits.append("external_evidence")
        if bool(task_requirements.get("requires_multi_step_plan")):
            req_bits.append("multi_step")
        if bool(task_requirements.get("forbid_speculation_without_evidence")):
            req_bits.append("no_speculation_without_evidence")
        if req_bits:
            lines.append(f"REQ={_compact_seq(req_bits, limit=6)}")
    open_questions = [str(x).strip() for x in (task_envelope.get("open_questions") or []) if str(x).strip()]
    if open_questions:
        lines.append(f"OPEN={_compact_seq(open_questions, limit=3)}")
    return "\n".join(lines)


def build_communication_prefix_v1(
    *,
    context_planes: dict[str, Any],
    agent_profile: dict[str, Any],
) -> str:
    communication = context_planes.get("communication_plane") or {}
    global_capsule = communication.get("global_capsule") or {}
    soul_profile_id = str(communication.get("soul_profile_id") or "").strip()
    style_constraints = [
        str(x).strip() for x in (communication.get("communication_style") or []) if str(x).strip()
    ]
    if not soul_profile_id and not style_constraints and not isinstance(global_capsule, dict):
        return ""
    role_hint = str(global_capsule.get("identity_summary") or communication.get("role_hint") or "").strip()
    axiom_ids = _communication_axiom_ids(context_planes)
    lines = [
        "PHASE=COMM",
        f"AGENT={str(agent_profile.get('agent_id') or '').strip() or 'assistant'}",
        f"SOUL={soul_profile_id or str(agent_profile.get('soul_profile_id') or '').strip() or 'default_assistant'}",
        f"ROLE={role_hint or 'assistant'}",
        f"STYLE={_compact_seq(style_constraints or ['clear', 'honest', 'concise'], limit=6)}",
        f"AX={_compact_seq(axiom_ids, limit=6)}",
        "RULE=communication_style_must_not_override_execution_constraints",
    ]
    return "\n".join(lines)


def _extract_prefixed_note(query_text: str, prefixes: tuple[str, ...]) -> str:
    raw = _normalize_text(query_text)
    lowered = raw.lower()
    for prefix in prefixes:
        px = str(prefix or "").strip().lower()
        if not px:
            continue
        if lowered == px:
            return ""
        if lowered.startswith(px + " "):
            return raw[len(prefix) :].strip(" ,，:：")
    return ""


def _has_explicit_task_signal(query_text: str) -> bool:
    text = _normalize_text(query_text)
    lowered = text.lower()
    if not text:
        return False
    markers = (
        "写",
        "分析",
        "总结",
        "整理",
        "检查",
        "查看",
        "评审",
        "修复",
        "修改",
        "实现",
        "设计",
        "创建",
        "生成",
        "输出",
        "列出",
        "查",
        "搜",
        "搜索",
        "读取",
        "看看",
        "review",
        "analyze",
        "audit",
        "summarize",
        "write",
        "fix",
        "implement",
        "design",
        "create",
        "generate",
        "read",
        "search",
        "draft",
        "plan",
    )
    if any(token in lowered or token in text for token in markers):
        return True
    if _needs_research(text) or _should_write_memory(text):
        return True
    return bool(re.search(r"(https?://|[/~`]|[.][A-Za-z0-9]{1,8}\b|\bREADME\b|\bMakefile\b)", text))


def _has_continuity_signal(query_text: str) -> bool:
    text = _normalize_text(query_text)
    lowered = text.lower()
    markers = (
        "继续",
        "接着",
        "刚才",
        "之前",
        "上次",
        "那个",
        "这个",
        "标准",
        "进度",
        "结果",
        "想起来",
        "记得",
        "还记得",
        "还想得起来",
        "照刚才",
        "按刚才",
        "按标准",
        "status",
        "resume",
        "continue",
        "remember",
        "recall",
    )
    return any(token in lowered or token in text for token in markers)


def _task_specificity_level(query_text: str) -> str:
    text = _normalize_text(query_text)
    if not text:
        return "low"
    if _has_explicit_task_signal(text):
        return "high"
    if len(text) <= 18 and (("?" in text) or ("？" in text) or ("吗" in text) or ("呢" in text)):
        return "low"
    if len(text) <= 8:
        return "low"
    if len(text) >= 24:
        return "medium"
    return "medium"


def resolve_intent_recovery_v1(
    *,
    query_text: str,
    context_planes: dict[str, Any],
) -> dict[str, Any]:
    text = _normalize_text(query_text)
    lowered = text.lower()
    recovery_plane = dict((context_planes or {}).get("intent_recovery_plane") or {})
    pending_contract = dict(recovery_plane.get("pending_contract") or {}) if isinstance(recovery_plane.get("pending_contract"), dict) else {}
    contract_objective = str(pending_contract.get("objective") or "").strip()
    last_pending_task = contract_objective or str(recovery_plane.get("last_pending_task") or "").strip()
    expected_next_user_act = str(recovery_plane.get("expected_next_user_act") or "").strip()
    last_delivery_summary = str(recovery_plane.get("last_delivery_summary") or "").strip()
    active_project_id = str(recovery_plane.get("active_project_id") or "").strip()
    clarification = str(recovery_plane.get("last_clarification_question") or "").strip()

    ack_tokens = ("ok", "okay", "好的", "行", "嗯")
    execute_tokens = ("开始", "开始吧", "go ahead", "start")
    continue_tokens = ("继续", "继续吧", "继续一下", "resume")
    status_tokens = ("结果呢", "进度", "怎么样了", "status", "update")
    chat_tokens = ("哈哈", "lol", "hi", "hello", "你好", "在吗")

    option = "DIRECT_TASK"
    note = ""
    recovered_objective = text
    needs_model_fallback = False

    if lowered in status_tokens or any(token in text for token in ("结果呢", "进度", "怎么样了")):
        option = "ASK_STATUS"
        recovered_objective = (
            f"report current status for: {last_pending_task}"
            if last_pending_task
            else "report current status for the latest task"
        )
    elif lowered in execute_tokens or any(lowered.startswith(token + " ") for token in execute_tokens):
        option = "ACK_EXECUTE"
        note = _extract_prefixed_note(text, execute_tokens)
        if last_pending_task:
            recovered_objective = f"{last_pending_task} {note}".strip()
        else:
            needs_model_fallback = True
    elif lowered in continue_tokens or any(lowered.startswith(token + " ") for token in continue_tokens):
        option = "ACK_CONTINUE"
        note = _extract_prefixed_note(text, continue_tokens)
        if last_pending_task:
            recovered_objective = f"{last_pending_task} {note}".strip()
        else:
            needs_model_fallback = True
    elif lowered in ack_tokens or any(lowered.startswith(token + " ") for token in ack_tokens):
        option = "ACK_CONFIRM"
        note = _extract_prefixed_note(text, ack_tokens)
        if last_pending_task:
            recovered_objective = f"{last_pending_task} {note}".strip()
        else:
            needs_model_fallback = True
    elif lowered in chat_tokens:
        option = "CHAT_SMALLTALK"
    elif text in {"开始", "OK", "ok", "继续"} and not last_pending_task:
        option = "UNKNOWN"
        needs_model_fallback = True

    if option in {"ACK_EXECUTE", "ACK_CONTINUE", "ACK_CONFIRM"} and not last_pending_task:
        option = "UNKNOWN"
        recovered_objective = text
    if option == "UNKNOWN":
        recovered_objective = text

    return {
        "schema_version": "1.0.0",
        "type": "intent_recovery_v1",
        "intent_option": option,
        "intent_note": note or None,
        "recovered_objective": recovered_objective,
        "needs_model_fallback": bool(needs_model_fallback),
        "recovery_source": "conversation_state" if last_pending_task or clarification or active_project_id else "raw_input_only",
        "recovery_bindings": {
            "last_pending_task": last_pending_task or None,
            "expected_next_user_act": expected_next_user_act or None,
            "active_project_id": active_project_id or None,
            "last_delivery_summary": last_delivery_summary or None,
            "last_clarification_question": clarification or None,
            "pending_contract": pending_contract or None,
        },
    }


def derive_solution_query_v1(
    *,
    query_text: str,
    intent_recovery: dict[str, Any],
    context_planes: dict[str, Any],
    theorem_candidates: list[dict[str, Any]] | None = None,
    operator_catalog_results: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    text = _normalize_text(query_text)
    recovered_objective = str(intent_recovery.get("recovered_objective") or text).strip() or text
    resolved_intent_option = str(intent_recovery.get("intent_option") or "DIRECT_TASK").strip().upper() or "DIRECT_TASK"
    recovery_bindings = dict(intent_recovery.get("recovery_bindings") or {})
    pending_contract = (
        dict(recovery_bindings.get("pending_contract") or {})
        if isinstance(recovery_bindings.get("pending_contract"), dict)
        else {}
    )
    pending_objective = str(pending_contract.get("objective") or "").strip()
    specificity = _task_specificity_level(text)
    continuity_binding = "raw_input"
    preserve_pending_contract = False
    reason_codes: list[str] = []
    plan_basis = "answer_directly"
    approach_strategy = "llm_self_check"
    preferred_operator_hints: list[str] = []
    preferred_local_operator_refs: list[str] = []
    must_stop_without_evidence = False
    expected_next_user_act = str(recovery_bindings.get("expected_next_user_act") or "").strip()
    pending_requires_workspace = bool(pending_contract.get("requires_workspace_observation"))
    pending_requires_external = bool(pending_contract.get("requires_external_evidence"))
    theorem_summaries = [str(x.get("summary") or "").strip() for x in (theorem_candidates or []) if isinstance(x, dict)]
    theorem_ids = [str(x.get("theorem_id") or "").strip() for x in (theorem_candidates or []) if isinstance(x, dict)]

    if pending_requires_workspace:
        preferred_operator_hints.extend(["fs.list", "fs.read", "shell.exec"])
        preferred_local_operator_refs.extend(["builtin://fs.list", "builtin://shell.exec"])
        must_stop_without_evidence = True
    if pending_requires_external:
        preferred_operator_hints.append("web.browse")
        must_stop_without_evidence = True
    if _has_explicit_research_intent(recovered_objective):
        preferred_operator_hints.append("research.run")
        must_stop_without_evidence = True

    if pending_objective and resolved_intent_option in {"ACK_EXECUTE", "ACK_CONTINUE", "ACK_CONFIRM", "ASK_STATUS"}:
        continuity_binding = "pending_contract"
        preserve_pending_contract = True
        reason_codes.append("state_bound_followup")
        if resolved_intent_option != "ASK_STATUS":
            recovered_objective = str(intent_recovery.get("recovered_objective") or pending_objective).strip() or pending_objective
    elif (
        pending_objective
        and resolved_intent_option == "DIRECT_TASK"
        and specificity == "low"
        and _has_continuity_signal(text)
        and expected_next_user_act in {"followup_or_new_task", "clarify_or_retry", "ack_execute", "ack_continue", ""}
    ):
        continuity_binding = "pending_contract"
        preserve_pending_contract = True
        resolved_intent_option = "FOLLOWUP_PENDING"
        recovered_objective = pending_objective
        reason_codes.append("low_specificity_rebound")

    if continuity_binding == "pending_contract" and pending_objective:
        if pending_requires_workspace:
            plan_basis = "inspect_first"
            approach_strategy = "local_skill_first"
        elif pending_requires_external:
            plan_basis = "evidence_first"
            approach_strategy = "local_skill_first"
        elif resolved_intent_option == "ASK_STATUS":
            plan_basis = "status_from_state"
        else:
            plan_basis = "continue_pending_contract"
            approach_strategy = "local_skill_first"
    elif _has_explicit_task_signal(recovered_objective):
        approach_strategy = "local_skill_first"
    if theorem_summaries:
        approach_strategy = "theorem_guided"
        plan_basis = "reuse_sop_then_execute" if plan_basis == "answer_directly" else plan_basis
        reason_codes.append("theorem_match")

    return {
        "schema_version": "1.0.0",
        "type": "solution_query_v2",
        "raw_query_text": text,
        "specificity": specificity,
        "continuity_binding": continuity_binding,
        "resolved_intent_option": resolved_intent_option,
        "resolved_objective": recovered_objective,
        "approach_strategy": approach_strategy,
        "plan_basis": plan_basis,
        "preserve_pending_contract": preserve_pending_contract,
        "must_stop_without_evidence": must_stop_without_evidence,
        "preferred_operator_hints": list(dict.fromkeys(preferred_operator_hints)),
        "preferred_local_operator_refs": list(dict.fromkeys(preferred_local_operator_refs)),
        "retrieved_theorem_ids": [x for x in theorem_ids if x],
        "retrieved_theorem_summaries": [x for x in theorem_summaries if x][:4],
        "operator_search_results": [dict(x) for x in (operator_catalog_results or []) if isinstance(x, dict)][:6],
        "reason_codes": reason_codes,
    }


def infer_interaction_mode_v1(*, intent_recovery: dict[str, Any], mode: QueryMode) -> str:
    option = str(intent_recovery.get("intent_option") or "DIRECT_TASK").strip().upper()
    if option == "CHAT_SMALLTALK":
        return "chat"
    if option == "ASK_STATUS":
        return "status"
    if option == "FOLLOWUP_PENDING":
        return "task"
    if mode == "simple" and option in {"ACK_CONFIRM", "ACK_CONTINUE", "ACK_EXECUTE"}:
        return "confirm"
    return "task"


def build_model_routing_policy_v1(
    *,
    interaction_mode: str,
    mode: QueryMode,
    task_requirements: dict[str, Any] | None = None,
    solution_query: dict[str, Any] | None = None,
    execution_mode_policy: dict[str, Any] | None = None,
    user_preference_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    mode_policy = dict(execution_mode_policy or {})
    preference_profile = dict(user_preference_profile or {})
    requirements = dict(task_requirements or {})
    solution = dict(solution_query or {})
    execution_mode = str(mode_policy.get("default_mode") or "balanced").strip() or "balanced"
    allow_override = bool(mode_policy.get("allow_user_override", True))
    risk_tolerance = str(preference_profile.get("risk_tolerance") or "balanced").strip() or "balanced"

    strategy = "planner_first"
    planner_strategy = "model_owned"
    if execution_mode == "cost_saver":
        strategy = "weak_to_strong"
    elif execution_mode == "quality_first":
        strategy = "quality_first"
    elif execution_mode == "chat_first" and interaction_mode == "chat":
        strategy = "quality_first"

    if interaction_mode == "chat":
        strategy = "quality_first" if execution_mode != "cost_saver" else "weak_to_strong"
        planner_strategy = "model_owned"
    elif interaction_mode == "status":
        strategy = "weak_to_strong" if execution_mode != "quality_first" else "planner_first"
        planner_strategy = "model_owned"

    execution_lane = "standard_task"
    if str(solution.get("approach_strategy") or "").strip() == "local_skill_first" or bool(
        requirements.get("skill_first")
    ):
        execution_lane = "skill_exec"
    elif bool(requirements.get("requires_external_evidence")) or bool(requirements.get("research_required")):
        execution_lane = "research_task"
    elif bool(requirements.get("requires_workspace_observation")) or bool(requirements.get("requires_multi_step_plan")):
        execution_lane = "deep_task"
    elif interaction_mode in {"chat", "confirm", "status"} and mode == "simple":
        execution_lane = "fast_chat"

    source = "runtime_policy_bundle" if execution_mode_policy or user_preference_profile else "default"
    return {
        "schema_version": "1.0.0",
        "type": "model_routing_policy_v1",
        "interaction_mode": str(interaction_mode),
        "routing_strategy": strategy,
        "planner_strategy": planner_strategy,
        "execution_mode": execution_mode,
        "execution_lane": execution_lane,
        "risk_tolerance": risk_tolerance,
        "user_override_allowed": allow_override,
        "source": source,
        "notes": "runtime compiles context deterministically; controller routes tasks to an execution lane and worker executes within that lane",
    }


def build_context_plane_pack_v1(
    *,
    query_text: str,
    workspace_id: str,
    trace: TraceContext,
    active_axiom_ids: list[str] | None = None,
    execution_axiom_ids: list[str] | None = None,
    communication_axiom_ids: list[str] | None = None,
    active_constraint_ids: list[str] | None = None,
    recent_failures: list[str] | None = None,
    recent_success_patterns: list[str] | None = None,
    role_hint: str | None = None,
    style_constraints: list[str] | None = None,
    soul_profile_id: str | None = None,
    global_capsule: dict[str, Any] | None = None,
    project_capsule: dict[str, Any] | None = None,
    message_received_at_utc: str | None = None,
    temporal_anchor: dict[str, Any] | None = None,
    execution_evidence_refs: list[str] | None = None,
    active_project_id: str | None = None,
    last_pending_task: str | None = None,
    expected_next_user_act: str | None = None,
    last_clarification_question: str | None = None,
    last_delivery_state: str | None = None,
    last_delivery_summary: str | None = None,
    pending_contract: dict[str, Any] | None = None,
    blocker: dict[str, Any] | None = None,
    response_language: str | None = None,
    last_user_query: str | None = None,
    last_user_query_at_utc: str | None = None,
) -> dict[str, Any]:
    parts = [f"workspace={workspace_id}", f"turn={trace.turn_id}", f"query={_normalize_text(query_text)[:120]}"]
    if str(message_received_at_utc or "").strip():
        parts.append(f"message_received_at_utc={str(message_received_at_utc).strip()}")
    temporal = dict(
        temporal_anchor
        or (
            build_temporal_anchor_v1(message_received_at_utc=message_received_at_utc)
            if str(message_received_at_utc or "").strip()
            else {}
        )
    )
    if str(temporal.get("date_local") or "").strip():
        parts.append(f"date_local={str(temporal.get('date_local')).strip()}")
    if str(temporal.get("timezone_local") or "").strip():
        parts.append(f"timezone_local={str(temporal.get('timezone_local')).strip()}")
    exec_axioms = [str(x).strip() for x in (execution_axiom_ids or active_axiom_ids or []) if str(x).strip()]
    comm_axioms = [str(x).strip() for x in (communication_axiom_ids or []) if str(x).strip()]
    constraint_ids = [str(x).strip() for x in (active_constraint_ids or []) if str(x).strip()]
    return {
        "execution_plane": {
            "state_summary": "; ".join(parts),
            "evidence_refs": list(dict.fromkeys(str(x) for x in (execution_evidence_refs or []) if str(x).strip())),
            "message_received_at_utc": (
                str(message_received_at_utc).strip() if str(message_received_at_utc or "").strip() else None
            ),
            "temporal_anchor": temporal or None,
            "project_capsule": dict(project_capsule) if isinstance(project_capsule, dict) else None,
        },
        "communication_plane": {
            "role_hint": role_hint if isinstance(role_hint, str) and role_hint.strip() else None,
            "style_constraints": [
                str(x).strip() for x in (style_constraints or []) if str(x).strip()
            ],
            "response_language": str(response_language).strip() if str(response_language or "").strip() else None,
            "soul_profile_id": str(soul_profile_id).strip() if str(soul_profile_id or "").strip() else None,
            "global_capsule": dict(global_capsule) if isinstance(global_capsule, dict) else None,
            "communication_style": [
                str(x).strip()
                for x in (((global_capsule or {}).get("communication_style")) or [])
                if str(x).strip()
            ],
        },
        "retrospective_plane": {
            "recent_failures": [str(x).strip() for x in (recent_failures or []) if str(x).strip()],
            "recent_success_patterns": [
                str(x).strip() for x in (recent_success_patterns or []) if str(x).strip()
            ],
        },
        "constraint_plane": {
            "execution_axiom_ids": exec_axioms,
            "communication_axiom_ids": comm_axioms,
            "active_axiom_ids": exec_axioms,
            "active_constraint_ids": constraint_ids,
            "soul_profile_id": str(soul_profile_id).strip() if str(soul_profile_id or "").strip() else None,
        },
        "intent_recovery_plane": {
            "active_project_id": str(active_project_id).strip() if str(active_project_id or "").strip() else None,
            "last_pending_task": str(last_pending_task).strip() if str(last_pending_task or "").strip() else None,
            "expected_next_user_act": (
                str(expected_next_user_act).strip() if str(expected_next_user_act or "").strip() else None
            ),
            "last_clarification_question": (
                str(last_clarification_question).strip()
                if str(last_clarification_question or "").strip()
                else None
            ),
            "last_delivery_state": (
                str(last_delivery_state).strip() if str(last_delivery_state or "").strip() else None
            ),
            "last_delivery_summary": (
                str(last_delivery_summary).strip() if str(last_delivery_summary or "").strip() else None
            ),
            "pending_contract": dict(pending_contract) if isinstance(pending_contract, dict) else None,
            "blocker": dict(blocker) if isinstance(blocker, dict) else None,
            "last_user_query": str(last_user_query).strip() if str(last_user_query or "").strip() else None,
            "last_user_query_at_utc": (
                str(last_user_query_at_utc).strip() if str(last_user_query_at_utc or "").strip() else None
            ),
        },
    }

def _validate_context_planes(raw: dict[str, Any] | None) -> tuple[dict[str, Any] | None, str | None]:
    pack = dict(raw or {})
    execution = pack.get("execution_plane")
    communication = pack.get("communication_plane")
    retrospective = pack.get("retrospective_plane")
    constraint = pack.get("constraint_plane")
    intent_recovery = pack.get("intent_recovery_plane") or {}
    if not all(isinstance(x, dict) for x in (execution, communication, retrospective, constraint, intent_recovery)):
        return None, "all context plane sections are required"
    state_summary = str(execution.get("state_summary") or "").strip()
    if not state_summary:
        return None, "execution_plane.state_summary is required"
    evidence_refs = execution.get("evidence_refs") or []
    if not isinstance(evidence_refs, list):
        return None, "execution_plane.evidence_refs must be an array"
    role_hint = communication.get("role_hint")
    style_constraints = communication.get("style_constraints") or []
    response_language = communication.get("response_language")
    soul_profile_id = communication.get("soul_profile_id")
    global_capsule = communication.get("global_capsule")
    communication_style = communication.get("communication_style") or []
    recent_failures = retrospective.get("recent_failures") or []
    recent_success_patterns = retrospective.get("recent_success_patterns") or []
    active_axiom_ids = constraint.get("active_axiom_ids") or []
    execution_axiom_ids = constraint.get("execution_axiom_ids") or active_axiom_ids
    communication_axiom_ids = constraint.get("communication_axiom_ids") or []
    active_constraint_ids = constraint.get("active_constraint_ids") or []
    if not all(
        isinstance(x, list)
        for x in (
            style_constraints,
            communication_style,
            recent_failures,
            recent_success_patterns,
            active_axiom_ids,
            execution_axiom_ids,
            communication_axiom_ids,
            active_constraint_ids,
        )
    ):
        return None, "context plane list fields must be arrays"
    temporal_anchor = execution.get("temporal_anchor")
    if temporal_anchor is not None and not isinstance(temporal_anchor, dict):
        return None, "execution_plane.temporal_anchor must be an object when present"
    normalized = {
        "execution_plane": {
            "state_summary": state_summary,
            "evidence_refs": [str(x).strip() for x in evidence_refs if str(x).strip()],
            "message_received_at_utc": (
                str(execution.get("message_received_at_utc")).strip()
                if execution.get("message_received_at_utc") is not None and str(execution.get("message_received_at_utc")).strip()
                else None
            ),
            "temporal_anchor": dict(temporal_anchor) if isinstance(temporal_anchor, dict) else None,
            "project_capsule": dict(execution.get("project_capsule")) if isinstance(execution.get("project_capsule"), dict) else None,
        },
        "communication_plane": {
            "role_hint": str(role_hint).strip() if isinstance(role_hint, str) and role_hint.strip() else None,
            "style_constraints": [str(x).strip() for x in style_constraints if str(x).strip()],
            "response_language": (
                str(response_language).strip()
                if response_language is not None and str(response_language).strip()
                else None
            ),
            "soul_profile_id": (
                str(soul_profile_id).strip()
                if soul_profile_id is not None and str(soul_profile_id).strip()
                else None
            ),
            "global_capsule": dict(global_capsule) if isinstance(global_capsule, dict) else None,
            "communication_style": [str(x).strip() for x in communication_style if str(x).strip()],
        },
        "retrospective_plane": {
            "recent_failures": [str(x).strip() for x in recent_failures if str(x).strip()],
            "recent_success_patterns": [str(x).strip() for x in recent_success_patterns if str(x).strip()],
        },
        "constraint_plane": {
            "execution_axiom_ids": [str(x).strip() for x in execution_axiom_ids if str(x).strip()],
            "communication_axiom_ids": [str(x).strip() for x in communication_axiom_ids if str(x).strip()],
            "active_axiom_ids": [str(x).strip() for x in active_axiom_ids if str(x).strip()],
            "active_constraint_ids": [str(x).strip() for x in active_constraint_ids if str(x).strip()],
            "soul_profile_id": (
                str(constraint.get("soul_profile_id")).strip()
                if constraint.get("soul_profile_id") is not None and str(constraint.get("soul_profile_id")).strip()
                else None
            ),
        },
        "intent_recovery_plane": {
            "active_project_id": (
                str(intent_recovery.get("active_project_id")).strip()
                if intent_recovery.get("active_project_id") is not None and str(intent_recovery.get("active_project_id")).strip()
                else None
            ),
            "last_pending_task": (
                str(intent_recovery.get("last_pending_task")).strip()
                if intent_recovery.get("last_pending_task") is not None and str(intent_recovery.get("last_pending_task")).strip()
                else None
            ),
            "expected_next_user_act": (
                str(intent_recovery.get("expected_next_user_act")).strip()
                if intent_recovery.get("expected_next_user_act") is not None and str(intent_recovery.get("expected_next_user_act")).strip()
                else None
            ),
            "last_clarification_question": (
                str(intent_recovery.get("last_clarification_question")).strip()
                if intent_recovery.get("last_clarification_question") is not None and str(intent_recovery.get("last_clarification_question")).strip()
                else None
            ),
            "last_delivery_state": (
                str(intent_recovery.get("last_delivery_state")).strip()
                if intent_recovery.get("last_delivery_state") is not None and str(intent_recovery.get("last_delivery_state")).strip()
                else None
            ),
            "last_delivery_summary": (
                str(intent_recovery.get("last_delivery_summary")).strip()
                if intent_recovery.get("last_delivery_summary") is not None and str(intent_recovery.get("last_delivery_summary")).strip()
                else None
            ),
            "pending_contract": (
                dict(intent_recovery.get("pending_contract"))
                if isinstance(intent_recovery.get("pending_contract"), dict)
                else None
            ),
            "blocker": (
                dict(intent_recovery.get("blocker"))
                if isinstance(intent_recovery.get("blocker"), dict)
                else None
            ),
            "last_user_query": (
                str(intent_recovery.get("last_user_query")).strip()
                if intent_recovery.get("last_user_query") is not None and str(intent_recovery.get("last_user_query")).strip()
                else None
            ),
            "last_user_query_at_utc": (
                str(intent_recovery.get("last_user_query_at_utc")).strip()
                if intent_recovery.get("last_user_query_at_utc") is not None
                and str(intent_recovery.get("last_user_query_at_utc")).strip()
                else None
            ),
        },
    }
    return normalized, None


def _needs_research(query: str) -> bool:
    q = str(query or "").lower()
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


def _has_explicit_research_intent(query: str) -> bool:
    q = str(query or "").lower()
    hints = (
        "深入调研",
        "调研报告",
        "对比研究",
        "多来源",
        "带引用",
        "引用结论",
        "research report",
        "deep research",
        "multi-source",
        "multiple sources",
        "with citations",
        "sources",
        "citations",
        "report",
    )
    return any(h in q or h in query for h in hints)


def _should_write_memory(query: str) -> bool:
    q = str(query or "").lower()
    return ("记住" in query) or ("remember" in q) or ("保存" in query)


def _classify_scope(query: str) -> str:
    q = str(query or "").lower()
    if "new project" in q or "新项目" in query:
        return "new_project"
    if _needs_research(query):
        return "unrelated"
    return "current_project"


def _risk_level(query: str) -> str:
    q = str(query or "").lower()
    high_hints = (
        "delete all",
        "rm -rf",
        "drop table",
        "production",
        "转账",
        "支付",
        "密钥",
        "密码",
    )
    if any(h in q or h in query for h in high_hints):
        return "high"
    if _needs_research(query):
        return "medium"
    return "low"


def _steps_estimate(query: str) -> int:
    steps = 1
    if _should_write_memory(query):
        steps += 1
    if _needs_research(query):
        steps += 1
    q = str(query or "").lower()
    if any(h in q or h in query for h in ("计划", "分步", "复杂", "multi-step", "workflow", "pipeline")):
        steps += 1
    return max(1, min(8, steps))


def _needs_iteration(query: str) -> bool:
    q = str(query or "").lower()
    if _needs_research(query):
        return True
    return any(
        h in q or h in query
        for h in ("修正", "迭代", "决定", "要不要", "refine", "iterate", "retry", "decide", "whether")
    )


def _select_mode(
    *,
    risk: str,
    steps_estimate: int,
    cross_tool: bool,
    needs_iteration: bool,
) -> QueryMode:
    # Deterministic gate (MVP_045).
    if (
        risk == "low"
        and int(steps_estimate) <= 1
        and not bool(cross_tool)
        and not bool(needs_iteration)
    ):
        return "simple"
    if risk != "high" and int(steps_estimate) <= 4:
        return "standard"
    return "complex"


def _make_failure(
    *,
    gate: str,
    code: str,
    reason: str,
    evidence_refs: list[str],
    remediation: str,
) -> dict[str, Any]:
    return {
        "gate": gate,
        "code": code,
        "reason": reason,
        "evidence_refs": list(evidence_refs),
        "remediation": remediation,
    }


def _has_user_visible_output(final_output: Any) -> bool:
    if not isinstance(final_output, dict) or not final_output:
        return False
    if _is_send_message_operator(final_output.get("operator_ref")):
        return bool(str(final_output.get("text") or "").strip())
    for key in ("text", "reply", "message", "summary", "result"):
        if str(final_output.get(key) or "").strip():
            return True
    return False


def _is_send_message_operator(operator_ref: Any) -> bool:
    ref = str(operator_ref or "").strip()
    return ref == "builtin://channel.send_message"


def _has_accepted_send_message_step(exec_summaries: list[dict[str, Any]]) -> bool:
    return any(
        isinstance(item, dict)
        and _is_send_message_operator(item.get("operator_ref"))
        and str(item.get("status") or "").strip() == "accepted"
        for item in exec_summaries
    )


def _has_accepted_communicator_send_message_step(exec_summaries: list[dict[str, Any]]) -> bool:
    return any(
        isinstance(item, dict)
        and _is_send_message_operator(item.get("operator_ref"))
        and str(item.get("status") or "").strip() == "accepted"
        and (
            str(item.get("internal_role_phase") or "").strip() == "communicator"
            or str(item.get("source_phase") or "").strip() == "communicator"
        )
        for item in exec_summaries
    )


def _counts_toward_external_execution_budget(item: dict[str, Any]) -> bool:
    if not isinstance(item, dict):
        return False
    if _is_send_message_operator(item.get("operator_ref")):
        return False
    internal_role_phase = str(item.get("internal_role_phase") or "").strip()
    if internal_role_phase:
        return False
    return True


def _validate_task_envelope(task_envelope: Any) -> str | None:
    if not isinstance(task_envelope, dict):
        return "task_envelope must be an object"
    if not str(task_envelope.get("task_id") or "").strip():
        return "task_envelope.task_id is required"
    if not str(task_envelope.get("objective") or "").strip():
        return "task_envelope.objective is required"
    acceptance = task_envelope.get("acceptance_criteria")
    if not isinstance(acceptance, list) or not acceptance:
        return "task_envelope.acceptance_criteria must be a non-empty array"
    return None


def _validate_delivery_contract(delivery_contract: Any, *, task_id: str) -> str | None:
    if not isinstance(delivery_contract, dict):
        return "delivery_contract must be an object"
    if str(delivery_contract.get("task_id") or "").strip() != str(task_id).strip():
        return "delivery_contract.task_id must match task_envelope.task_id"
    if not str(delivery_contract.get("done_definition") or "").strip():
        return "delivery_contract.done_definition is required"
    return None


def _validate_query_schema(query: dict[str, Any]) -> list[dict[str, Any]]:
    failures: list[dict[str, Any]] = []
    required = (
        "task_envelope",
        "delivery_contract",
        "solution_query",
        "objective",
        "context_pack",
        "capabilities",
        "workspace_snapshot",
        "constraints",
        "acceptance_criteria",
        "budget",
        "termination_policy",
    )
    missing = [k for k in required if k not in query]
    if missing:
        failures.append(
            _make_failure(
                gate="schema",
                code=QUERY_ERROR_SCHEMA_INVALID,
                reason=f"missing required fields: {', '.join(missing)}",
                evidence_refs=["triage:v1"],
                remediation="populate all required StructuredQueryV1 fields before execution",
            )
        )
        return failures

    task_envelope = query.get("task_envelope")
    task_error = _validate_task_envelope(task_envelope)
    if task_error:
        failures.append(
            _make_failure(
                gate="schema",
                code=QUERY_ERROR_TASK_ENVELOPE_INVALID,
                reason=task_error,
                evidence_refs=["triage:v1"],
                remediation="provide a valid TaskEnvelopeV1 before execution",
            )
        )
        return failures

    delivery_contract = query.get("delivery_contract")
    delivery_error = _validate_delivery_contract(
        delivery_contract,
        task_id=str((task_envelope or {}).get("task_id") or ""),
    )
    if delivery_error:
        failures.append(
            _make_failure(
                gate="schema",
                code=QUERY_ERROR_DELIVERY_CONTRACT_INVALID,
                reason=delivery_error,
                evidence_refs=["triage:v1"],
                remediation="provide a valid DeliveryContractV1 before execution",
            )
        )
        return failures

    solution_query = query.get("solution_query")
    if not isinstance(solution_query, dict):
        failures.append(
            _make_failure(
                gate="schema",
                code=QUERY_ERROR_SCHEMA_INVALID,
                reason="solution_query must be an object",
                evidence_refs=["triage:v1"],
                remediation="provide a valid SolutionQueryV1 before planning",
            )
        )
        return failures
    if not str(solution_query.get("resolved_objective") or "").strip():
        failures.append(
            _make_failure(
                gate="schema",
                code=QUERY_ERROR_SCHEMA_INVALID,
                reason="solution_query.resolved_objective is required",
                evidence_refs=["triage:v1"],
                remediation="resolve a concrete objective before planning",
            )
        )
        return failures

    cp = query.get("context_pack")
    if not isinstance(cp, dict):
        failures.append(
            _make_failure(
                gate="schema",
                code=QUERY_ERROR_SCHEMA_INVALID,
                reason="context_pack must be an object",
                evidence_refs=["triage:v1"],
                remediation="set context_pack.state_summary and context_pack.evidence[]",
            )
        )
        return failures
    evs = cp.get("evidence")
    if not isinstance(evs, list):
        failures.append(
            _make_failure(
                gate="schema",
                code=QUERY_ERROR_SCHEMA_INVALID,
                reason="context_pack.evidence must be an array",
                evidence_refs=["triage:v1"],
                remediation="provide 5..10 evidence items",
            )
        )
        return failures

    if len(evs) < 5 or len(evs) > 10:
        failures.append(
            _make_failure(
                gate="schema",
                code=QUERY_ERROR_CONTEXT_EVIDENCE_BOUNDS,
                reason=f"context_pack.evidence length out of bounds: {len(evs)}",
                evidence_refs=["triage:v1"],
                remediation="enforce evidence count within [5, 10]",
            )
        )

    triage_decisions = [
        x
        for x in evs
        if isinstance(x, dict)
        and str(x.get("kind")) == "decision"
        and str(x.get("ref")) == "triage:v1"
    ]
    if len(triage_decisions) != 1:
        failures.append(
            _make_failure(
                gate="schema",
                code=QUERY_ERROR_SCHEMA_INVALID,
                reason=f"triage decision evidence must appear exactly once, got {len(triage_decisions)}",
                evidence_refs=["triage:v1"],
                remediation="add exactly one {kind=decision, ref=triage:v1} evidence item",
            )
        )

    context_graph = query.get("context_graph")
    if context_graph is not None:
        if not isinstance(context_graph, dict):
            failures.append(
                _make_failure(
                    gate="schema",
                    code=QUERY_ERROR_SCHEMA_INVALID,
                    reason="context_graph must be an object when present",
                    evidence_refs=["context_projection:v1"],
                    remediation="provide a valid ContextGraphV1 payload",
                )
            )
        elif not isinstance(context_graph.get("nodes"), list) or not isinstance(context_graph.get("edges"), list):
            failures.append(
                _make_failure(
                    gate="schema",
                    code=QUERY_ERROR_SCHEMA_INVALID,
                    reason="context_graph.nodes and context_graph.edges must be arrays",
                    evidence_refs=["context_projection:v1"],
                    remediation="populate ContextGraphV1 nodes/edges arrays",
                )
            )

    task_context_views = query.get("task_context_views")
    if task_context_views is not None:
        views = task_context_views.get("views") if isinstance(task_context_views, dict) else None
        required_views = {"intent_router", "planner", "executor", "verifier_replanner", "communicator"}
        missing_views = sorted(required_views - set(views.keys() if isinstance(views, dict) else []))
        if missing_views:
            failures.append(
                _make_failure(
                    gate="schema",
                    code=QUERY_ERROR_SCHEMA_INVALID,
                    reason=f"task_context_views missing required views: {', '.join(missing_views)}",
                    evidence_refs=["context_projection:v1"],
                    remediation="project all five canonical Prompt Profiles into TaskContextView payloads",
                )
            )

    prompt_profiles = query.get("prompt_profiles")
    if prompt_profiles is not None:
        required_profiles = {"intent_router", "planner", "executor", "verifier_replanner", "communicator"}
        missing_profiles = sorted(required_profiles - set(prompt_profiles.keys() if isinstance(prompt_profiles, dict) else []))
        if missing_profiles:
            failures.append(
                _make_failure(
                    gate="schema",
                    code=QUERY_ERROR_SCHEMA_INVALID,
                    reason=f"prompt_profiles missing required profiles: {', '.join(missing_profiles)}",
                    evidence_refs=["context_projection:v1"],
                    remediation="compile all five canonical Prompt Profiles before execution",
                )
            )

    return failures


def _step_output_for_index(step_outputs: list[dict[str, Any]] | None, index: int) -> dict[str, Any]:
    if not isinstance(step_outputs, list):
        return {}
    if index < 0 or index >= len(step_outputs):
        return {}
    item = step_outputs[index]
    return dict(item) if isinstance(item, dict) else {}


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _load_failure_mapping_table() -> dict[str, Any]:
    global _FAILURE_MAPPING_CACHE
    if isinstance(_FAILURE_MAPPING_CACHE, dict):
        return _FAILURE_MAPPING_CACHE
    path = _repo_root() / "configs" / "user_facing_failure_mapping_v1.json"
    try:
        _FAILURE_MAPPING_CACHE = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        _FAILURE_MAPPING_CACHE = {"schema_version": "1.0.0", "entries": []}
    return _FAILURE_MAPPING_CACHE


def _match_failure_mapping(
    *,
    source_phase: str,
    phase_outcome: str,
    stable_error_code: str,
    operator_ref: str,
    detail_text: str,
    reason_hint: str | None = None,
) -> dict[str, Any]:
    table = _load_failure_mapping_table()
    entries = table.get("entries") if isinstance(table, dict) else None
    if not isinstance(entries, list):
        return {}
    detail = str(detail_text or "")
    for item in entries:
        if not isinstance(item, dict):
            continue
        entry_phase = str(item.get("source_phase") or "").strip()
        entry_outcome = str(item.get("phase_outcome") or "").strip()
        entry_code = str(item.get("stable_error_code") or "").strip()
        entry_operator = str(item.get("operator_ref") or "").strip()
        entry_reason = str(item.get("reason_hint") or "").strip()
        pattern = str(item.get("message_regex") or "").strip()
        if entry_phase and entry_phase != source_phase:
            continue
        if entry_outcome and entry_outcome != phase_outcome:
            continue
        if entry_code and entry_code != stable_error_code:
            continue
        if entry_operator and entry_operator != operator_ref:
            continue
        if entry_reason and entry_reason != str(reason_hint or "").strip():
            continue
        if pattern and not re.search(pattern, detail, flags=re.IGNORECASE):
            continue
        return dict(item)
    return {}


def _latest_failed_step_with_output(
    *,
    exec_summaries: list[dict[str, Any]],
    step_outputs: list[dict[str, Any]] | None = None,
    phase_outcome: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if str(phase_outcome or "").strip() == "blocked":
        for idx in range(len(exec_summaries) - 1, -1, -1):
            output = _step_output_for_index(step_outputs, idx)
            if str(output.get("status") or "").strip() == "blocked":
                item = exec_summaries[idx]
                return (dict(item) if isinstance(item, dict) else {}), output
    for idx in range(len(exec_summaries) - 1, -1, -1):
        item = exec_summaries[idx]
        if not isinstance(item, dict):
            continue
        status = str(item.get("status") or "").strip()
        code = str(item.get("error_code") or "").strip()
        if code or status not in {"", "accepted"}:
            return dict(item), _step_output_for_index(step_outputs, idx)
    return {}, {}


def _classify_search_attempt_for_user(item: dict[str, Any]) -> str:
    provider = str(item.get("provider") or "").strip().lower()
    detail = " ".join(str(item.get("detail") or "").split()).strip()
    lowered = detail.lower()
    provider_label = {
        "brave": "Brave Search API",
        "duckduckgo_html": "DuckDuckGo HTTP search",
        "playwright_search": "Fallback search runtime",
    }.get(provider, provider or "search provider")
    if "network egress is disabled" in lowered:
        return "Network egress is disabled for web search."
    if provider == "brave" and ("brave_search_api_key" in lowered or "not configured" in lowered):
        return "Brave Search API is unavailable because BRAVE_SEARCH_API_KEY is not configured."
    if "homepage/search portal" in lowered or "no usable results" in lowered:
        return f"{provider_label} returned no usable results."
    if "runtime is unavailable" in lowered:
        return f"{provider_label} is unavailable in the current runtime."
    return f"{provider_label} failed before returning usable results."


def _normalized_failure_detail(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def _has_accepted_operator(exec_summaries: list[dict[str, Any]], operator_ref: str) -> bool:
    for item in exec_summaries:
        if not isinstance(item, dict):
            continue
        if str(item.get("operator_ref") or "").strip() != str(operator_ref).strip():
            continue
        if str(item.get("status") or "").strip() == "accepted":
            return True
    return False


def _search_candidate_urls(step_outputs: list[dict[str, Any]] | None = None) -> list[str]:
    out: list[str] = []
    for item in step_outputs or []:
        if not isinstance(item, dict):
            continue
        results = item.get("results")
        if not isinstance(results, list):
            continue
        for result in results:
            if not isinstance(result, dict):
                continue
            url = str(result.get("url") or "").strip()
            if url and url not in out:
                out.append(url)
    return out


def _browse_attempted_urls(
    *,
    exec_summaries: list[dict[str, Any]],
    step_outputs: list[dict[str, Any]] | None = None,
) -> list[str]:
    out: list[str] = []
    for index, step in enumerate(exec_summaries):
        if not isinstance(step, dict):
            continue
        if str(step.get("operator_ref") or "").strip() != "builtin://web.browse":
            continue
        args = dict(step.get("arguments") or {}) if isinstance(step.get("arguments"), dict) else {}
        output = _step_output_for_index(step_outputs, index)
        payload = dict(output.get("output") or {}) if isinstance(output.get("output"), dict) else {}
        url = str(
            payload.get("url")
            or output.get("url")
            or output.get("final_url")
            or args.get("url")
            or ""
        ).strip()
        if url and url not in out:
            out.append(url)
    return out


def _append_unique_fact(target: list[str], value: str) -> None:
    text = str(value or "").strip()
    if text and text not in target:
        target.append(text)


def _append_fact_if(target: list[str], *, prefix: str, value: Any) -> None:
    text = _normalized_failure_detail(value)
    if text:
        _append_unique_fact(target, f"{prefix}{text}.")


def _is_invalid_internal_plan_error_code(error_code: str | None) -> bool:
    return str(error_code or "").strip() in {
        "E_TASK_DEPENDENCY_CYCLE",
        "E_TASK_DEPENDENCY_UNRESOLVED",
        "E_TASK_BATCH_INVALID",
        "E_WORKER_TASK_GRAPH_INVALID",
        "E_WORKER_SPLIT_REQUIRES_LEADER",
        "E_ACTION_OPERATOR_UNSUPPORTED",
        "E_COMMUNICATOR_ACTION_INVALID",
        "E_MESSAGE_TASK_PHASE_VIOLATION",
    }


def _build_external_evidence_candidate_exhausted_summary(
    *,
    failed_phase: str,
    objective: str,
    disallowed_inferences: list[str],
    step_outputs: list[dict[str, Any]] | None = None,
    exec_summaries: list[dict[str, Any]],
    task_requirements: dict[str, Any],
    stable_error_code: str,
) -> dict[str, Any]:
    candidate_urls = _search_candidate_urls(step_outputs)
    attempted_urls = _browse_attempted_urls(exec_summaries=exec_summaries, step_outputs=step_outputs)
    policy = dict(task_requirements.get("external_evidence_policy_v1") or {})
    allowed_user_visible_facts = [
        "The assistant found external search candidates but did not verify a usable source page within the ordinary search and browse budget.",
        "Search results alone were not treated as verified evidence.",
    ]
    if candidate_urls:
        allowed_user_visible_facts.append(f"Verified candidate URL count: {len(candidate_urls)}.")
    if attempted_urls:
        allowed_user_visible_facts.append(f"Verified attempted source count: {len(attempted_urls)}.")
    if policy:
        allowed_user_visible_facts.append(
            "Verified ordinary evidence budget: "
            f"search_rounds_max={int(policy.get('search_rounds_max') or 0)}, "
            f"browse_candidates_per_search_max={int(policy.get('browse_candidates_per_search_max') or 0)}, "
            f"total_browse_steps_max={int(policy.get('total_browse_steps_max') or 0)}."
        )
    return {
        "schema_version": "1.0.0",
        "type": "user_facing_failure_summary_v1",
        "delivery_state": "blocker",
        "phase_outcome": "blocked",
        "primary_error_code": stable_error_code or "E_EXECUTION_BLOCKED",
        "reason_class": "external_evidence_candidate_exhausted",
        "template_key": "blocker.external_evidence_candidate_exhausted",
        "failure_scope": "verification",
        "failed_phase": failed_phase,
        "retryable": True,
        "user_actionability": "retry_or_change_source",
        "objective": objective,
        "allowed_user_visible_facts": allowed_user_visible_facts,
        "disallowed_inferences": disallowed_inferences,
        "next_step_hint": "Explain that candidate sources were tried within the ordinary search and browse budget but none became verified readable evidence.",
    }


def _build_web_browse_failure_summary(
    *,
    failed_step: dict[str, Any],
    failed_output: dict[str, Any],
    stable_error_code: str,
    failed_phase: str,
    objective: str,
    disallowed_inferences: list[str],
) -> dict[str, Any]:
    url = str(failed_output.get("url") or (failed_step.get("arguments") or {}).get("url") or "").strip()
    detail = _normalized_failure_detail(failed_output.get("message"))
    lowered = detail.lower()
    allowed_user_visible_facts = [
        "The assistant could not open a required web source needed for this request.",
    ]
    if url:
        allowed_user_visible_facts.append(f"Verified failed source URL: {url}.")
    reason_class = "web_navigation_failed"
    next_step_hint = "Ask the user to retry later after the web browsing runtime is repaired."
    user_actionability = "retry_after_runtime_repair"
    retryable = True
    if stable_error_code == "E_WEB_RUNTIME_UNAVAILABLE" or "runtime is unavailable" in lowered:
        reason_class = "web_browse_unavailable"
        allowed_user_visible_facts.append("The runtime could not access the required web browsing backend.")
    elif "no readable page text" in lowered or "empty html" in lowered:
        allowed_user_visible_facts.append("The runtime reached the source page but could not extract usable page content.")
        next_step_hint = "Ask the user to retry later or provide another source URL if they have one."
        user_actionability = "retry_or_change_source"
    else:
        allowed_user_visible_facts.append("The runtime could not extract usable content from the required web source.")
    return {
        "schema_version": "1.0.0",
        "type": "user_facing_failure_summary_v1",
        "delivery_state": "blocker",
        "phase_outcome": "failed",
        "primary_error_code": stable_error_code or "E_EXECUTION_FAILED",
        "reason_class": reason_class,
        "template_key": f"blocker.{reason_class}",
        "failure_scope": "web_browse",
        "failed_phase": failed_phase,
        "retryable": retryable,
        "user_actionability": user_actionability,
        "objective": objective,
        "allowed_user_visible_facts": allowed_user_visible_facts,
        "disallowed_inferences": disallowed_inferences,
        "next_step_hint": next_step_hint,
    }


def _build_shell_exec_failure_summary(
    *,
    failed_step: dict[str, Any],
    failed_output: dict[str, Any],
    stable_error_code: str,
    failed_phase: str,
    objective: str,
    disallowed_inferences: list[str],
) -> dict[str, Any]:
    args = dict(failed_step.get("arguments") or {}) if isinstance(failed_step.get("arguments"), dict) else {}
    command = str(failed_output.get("command") or args.get("command") or "").strip()
    cwd = str(failed_output.get("cwd") or args.get("cwd") or "").strip()
    detail = _normalized_failure_detail(failed_output.get("message"))
    lowered = detail.lower()
    allowed_user_visible_facts = [
        "The assistant could not complete a required workspace command for this request.",
    ]
    if command:
        allowed_user_visible_facts.append(f"Verified failed workspace command: {command}.")
    if cwd:
        allowed_user_visible_facts.append(f"Verified working directory: {cwd}.")
    reason_class = "workspace_command_failed"
    next_step_hint = "Ask the user to retry after the workspace runtime path is repaired."
    user_actionability = "retry_after_runtime_repair"
    retryable = True
    if stable_error_code == "E_TIMEOUT" or "timed out" in lowered:
        reason_class = "workspace_command_timeout"
        allowed_user_visible_facts.append("The command timed out before returning a result.")
        next_step_hint = "Ask the user to retry; if the task is heavy, mention that a larger deadline may help."
        user_actionability = "retry_or_increase_deadline"
    elif stable_error_code == "E_INPUT_SCHEMA" or "access denied" in lowered or "outside workspace root" in lowered:
        reason_class = "workspace_command_invalid_request"
        retryable = False
        user_actionability = "repair_request"
        allowed_user_visible_facts.append("The requested workspace command or path was invalid for the current workspace boundary.")
        next_step_hint = "Explain that the workspace command request must be repaired before retrying."
    elif "file not found" in lowered or "directory not found" in lowered or "not a directory" in lowered:
        reason_class = "workspace_context_missing"
        retryable = False
        user_actionability = "repair_request"
        allowed_user_visible_facts.append("The required workspace path was not available in the current workspace context.")
        next_step_hint = "Explain which workspace path is missing and ask the user to repair the request or workspace."
    else:
        allowed_user_visible_facts.append("The runtime failed before the workspace command completed.")
    disallowed = list(disallowed_inferences)
    _append_unique_fact(
        disallowed,
        "Do not claim the workspace command changed files or produced verified output unless the execution evidence explicitly says so.",
    )
    return {
        "schema_version": "1.0.0",
        "type": "user_facing_failure_summary_v1",
        "delivery_state": "blocker",
        "phase_outcome": "failed",
        "primary_error_code": stable_error_code or "E_EXECUTION_FAILED",
        "reason_class": reason_class,
        "template_key": f"blocker.{reason_class}",
        "failure_scope": "shell_exec",
        "failed_phase": failed_phase,
        "retryable": retryable,
        "user_actionability": user_actionability,
        "objective": objective,
        "allowed_user_visible_facts": allowed_user_visible_facts,
        "disallowed_inferences": disallowed,
        "next_step_hint": next_step_hint,
    }


def _build_memory_search_failure_summary(
    *,
    failed_step: dict[str, Any],
    failed_output: dict[str, Any],
    stable_error_code: str,
    failed_phase: str,
    objective: str,
    disallowed_inferences: list[str],
) -> dict[str, Any]:
    args = dict(failed_step.get("arguments") or {}) if isinstance(failed_step.get("arguments"), dict) else {}
    query = str(failed_output.get("query") or args.get("query") or "").strip()
    detail = _normalized_failure_detail(failed_output.get("message"))
    detail.lower()
    allowed_user_visible_facts = [
        "The assistant could not retrieve the saved memory evidence needed for this request.",
    ]
    if query:
        allowed_user_visible_facts.append(f"Verified failed memory lookup query: {query}.")
    reason_class = "memory_lookup_unavailable"
    next_step_hint = "Ask the user to retry later after the memory runtime path is repaired."
    user_actionability = "retry_after_runtime_repair"
    retryable = True
    if stable_error_code == "E_INPUT_SCHEMA":
        reason_class = "memory_lookup_invalid_request"
        retryable = False
        user_actionability = "repair_request"
        allowed_user_visible_facts.append("The memory lookup request was invalid for the current runtime contract.")
        next_step_hint = "Explain that the memory lookup query or limit must be repaired before retrying."
    else:
        allowed_user_visible_facts.append("The runtime failed before the memory lookup returned usable evidence.")
    disallowed = list(disallowed_inferences)
    _append_unique_fact(
        disallowed,
        "Do not claim that memory contained or lacked a specific fact unless the retrieval evidence explicitly confirms it.",
    )
    return {
        "schema_version": "1.0.0",
        "type": "user_facing_failure_summary_v1",
        "delivery_state": "blocker",
        "phase_outcome": "failed",
        "primary_error_code": stable_error_code or "E_EXECUTION_FAILED",
        "reason_class": reason_class,
        "template_key": f"blocker.{reason_class}",
        "failure_scope": "memory_search",
        "failed_phase": failed_phase,
        "retryable": retryable,
        "user_actionability": user_actionability,
        "objective": objective,
        "allowed_user_visible_facts": allowed_user_visible_facts,
        "disallowed_inferences": disallowed,
        "next_step_hint": next_step_hint,
    }


def build_user_facing_failure_summary_v1(
    *,
    compiled_query: dict[str, Any] | None = None,
    query_text: str | None = None,
    exec_summaries: list[dict[str, Any]],
    step_outputs: list[dict[str, Any]] | None = None,
    error_code: str | None,
    primary_failure_code: str | None = None,
    phase_outcome: str | None = None,
) -> dict[str, Any] | None:
    task_envelope = dict((compiled_query or {}).get("task_envelope") or {}) if isinstance(compiled_query, dict) else {}
    task_requirements = dict((compiled_query or {}).get("task_requirements") or {}) if isinstance(compiled_query, dict) else {}
    objective = str(query_text or task_envelope.get("objective") or "").strip()
    stable_error_code = str(error_code or primary_failure_code or "").strip()
    effective_phase_outcome = str(phase_outcome or "failed").strip() or "failed"
    failed_step, failed_output = _latest_failed_step_with_output(
        exec_summaries=exec_summaries,
        step_outputs=step_outputs,
        phase_outcome=effective_phase_outcome,
    )
    failed_phase = str(
        failed_step.get("source_phase")
        or failed_step.get("internal_role_phase")
        or "unknown"
    ).strip() or "unknown"
    operator_ref = str(failed_step.get("operator_ref") or "").strip()
    if not stable_error_code and not operator_ref:
        return None

    allowed_user_visible_facts: list[str] = []
    disallowed_inferences = [
        "Do not claim the requested factual answer was retrieved or verified unless verified evidence explicitly says so.",
        "Do not invent missing providers, bridges, or setup gaps that are absent from the verified summary.",
        "Do not describe any fallback or provider failure as a code bug unless the verified summary explicitly says implementation_bug.",
    ]
    next_step_hint = "Ask the user to retry after the runtime path or required configuration is repaired."
    reason_class = "runtime_failure"
    failure_scope = "runtime"
    retryable = True
    user_actionability = "retry"
    template_key = "blocker.runtime_failure"

    if effective_phase_outcome == "blocked":
        detail_text = _normalized_failure_detail(failed_output.get("reason") or failed_output.get("summary") or failed_output.get("message"))
        reason_hint = None
        if _is_invalid_internal_plan_error_code(stable_error_code):
            reason_class = "invalid_internal_plan"
            template_key = "blocker.invalid_internal_plan"
            failure_scope = "planning"
            retryable = True
            user_actionability = "retry_after_runtime_repair"
            next_step_hint = "Explain that the assistant produced an invalid or unfinished internal action plan before it could complete the request."
            allowed_user_visible_facts.extend(
                [
                    "The assistant produced an invalid or unfinished internal action plan before completing the request.",
                    f"Verified failed phase: {failed_phase}.",
                    f"Stable error code: {stable_error_code or 'E_EXECUTION_BLOCKED'}.",
                ]
            )
        elif bool(task_requirements.get("attachment_evidence_required")) and not bool(task_requirements.get("multimodal_chain_supported")):
            reason_hint = "multimodal_chain_unsupported"
            reason_class = "multimodal_chain_unsupported"
            failure_scope = "multimodal"
            retryable = False
            user_actionability = "change_backend_or_retry"
            next_step_hint = "Explain that the current backend/model path cannot verify the required attachments and a supporting model path is needed."
            allowed_user_visible_facts.append("The current runtime path cannot verify the required attachments for this request.")
            required_media_kinds = [
                str(x).strip()
                for x in (task_requirements.get("required_media_kinds") or [])
                if str(x).strip()
            ]
            if required_media_kinds:
                allowed_user_visible_facts.append(
                    f"Required attachment media kinds: {'|'.join(required_media_kinds)}."
                )
            block_reason = str(task_requirements.get("multimodal_block_reason") or "").strip()
            if block_reason:
                allowed_user_visible_facts.append(f"Verified blocker: {block_reason}.")
        elif bool(task_requirements.get("requires_external_evidence")) and not _has_accepted_operator(exec_summaries, "builtin://web.browse"):
            if _search_candidate_urls(step_outputs):
                return _build_external_evidence_candidate_exhausted_summary(
                    failed_phase=failed_phase,
                    objective=objective,
                    disallowed_inferences=disallowed_inferences,
                    step_outputs=step_outputs,
                    exec_summaries=exec_summaries,
                    task_requirements=task_requirements,
                    stable_error_code=stable_error_code,
                )
            reason_hint = "external_evidence_insufficient"
            reason_class = "external_evidence_insufficient"
            failure_scope = "verification"
            retryable = True
            user_actionability = "retry_or_change_source"
            next_step_hint = "Explain that the runtime did not verify a usable external source page before answering."
            allowed_user_visible_facts.extend(
                [
                    "The assistant did not have enough verified external evidence to answer safely.",
                    "Search results alone were not treated as verified evidence.",
                ]
            )
        else:
            reason_hint = "runtime_blocked"
            reason_class = "runtime_blocked"
            failure_scope = "verification"
            retryable = True
            user_actionability = "retry"
            next_step_hint = "Explain the blocker using only verified task state and ask the user to retry if appropriate."
            allowed_user_visible_facts.append("The assistant reached a verified blocker before it could complete the request.")
        mapping = _match_failure_mapping(
            source_phase=failed_phase,
            phase_outcome=effective_phase_outcome,
            stable_error_code=stable_error_code,
            operator_ref=operator_ref,
            detail_text=detail_text,
            reason_hint=reason_hint,
        )
        reason_class = str(mapping.get("reason_class") or reason_class).strip() or reason_class
        template_key = str(mapping.get("template_key") or template_key).strip() or template_key
        if mapping.get("retryable") is not None:
            retryable = bool(mapping.get("retryable"))
        user_actionability = str(mapping.get("user_actionability") or user_actionability).strip() or user_actionability
        next_step_hint = str(mapping.get("next_step_hint") or next_step_hint).strip() or next_step_hint
        return {
            "schema_version": "1.0.0",
            "type": "user_facing_failure_summary_v1",
            "delivery_state": "blocker",
            "phase_outcome": effective_phase_outcome,
            "primary_error_code": stable_error_code or "E_EXECUTION_BLOCKED",
            "reason_class": reason_class,
            "template_key": template_key,
            "failure_scope": failure_scope,
            "failed_phase": failed_phase,
            "retryable": retryable,
            "user_actionability": user_actionability,
            "objective": objective,
            "allowed_user_visible_facts": allowed_user_visible_facts,
            "disallowed_inferences": disallowed_inferences,
            "next_step_hint": next_step_hint,
        }

    if operator_ref == "builtin://web.search" or str(failed_output.get("operator_ref") or "").strip() == "builtin://web.search":
        failure_scope = "web_search"
        reason_class = "external_evidence_unavailable"
        template_key = "blocker.external_evidence_unavailable"
        user_actionability = "retry_after_runtime_repair"
        query = str(failed_output.get("query") or failed_step.get("arguments", {}).get("query") or "").strip()
        allowed_user_visible_facts.append("The assistant could not retrieve external web evidence needed for this request.")
        if query:
            allowed_user_visible_facts.append(f"Verified failed lookup query: {query}.")
        attempts = failed_output.get("provider_attempts")
        if isinstance(attempts, list):
            for item in attempts[:4]:
                if not isinstance(item, dict):
                    continue
                fact = _classify_search_attempt_for_user(item)
                if fact and fact not in allowed_user_visible_facts:
                    allowed_user_visible_facts.append(fact)
        if not any("configured" in item.lower() for item in allowed_user_visible_facts):
            next_step_hint = "Ask the user to retry later after the search runtime is repaired."
        return {
            "schema_version": "1.0.0",
            "type": "user_facing_failure_summary_v1",
            "delivery_state": "blocker",
            "phase_outcome": effective_phase_outcome,
            "primary_error_code": stable_error_code or "E_EXECUTION_FAILED",
            "reason_class": reason_class,
            "template_key": template_key,
            "failure_scope": failure_scope,
            "failed_phase": failed_phase,
            "retryable": retryable,
            "user_actionability": user_actionability,
            "objective": objective,
            "allowed_user_visible_facts": allowed_user_visible_facts,
            "disallowed_inferences": disallowed_inferences,
            "next_step_hint": next_step_hint,
        }

    if operator_ref == "builtin://web.browse" or str(failed_output.get("operator_ref") or "").strip() == "builtin://web.browse":
        if (
            bool(task_requirements.get("requires_external_evidence"))
            and not _has_accepted_operator(exec_summaries, "builtin://web.browse")
            and _search_candidate_urls(step_outputs)
        ):
            return _build_external_evidence_candidate_exhausted_summary(
                failed_phase=failed_phase,
                objective=objective,
                disallowed_inferences=disallowed_inferences,
                step_outputs=step_outputs,
                exec_summaries=exec_summaries,
                task_requirements=task_requirements,
                stable_error_code=stable_error_code,
            )
        return _build_web_browse_failure_summary(
            failed_step=failed_step,
            failed_output=failed_output,
            stable_error_code=stable_error_code,
            failed_phase=failed_phase,
            objective=objective,
            disallowed_inferences=disallowed_inferences,
        )

    if operator_ref == "builtin://research.run" or str(failed_output.get("operator_ref") or "").strip() == "builtin://research.run":
        allowed_user_visible_facts = [
            "The assistant could not complete the explicit research run requested for this task.",
        ]
        source_count = int(failed_output.get("source_count") or 0)
        min_sources = int(failed_output.get("min_sources") or 0)
        if min_sources > 0:
            allowed_user_visible_facts.append(
                f"Verified research progress: collected {source_count} readable sources out of required {min_sources}."
            )
        return {
            "schema_version": "1.0.0",
            "type": "user_facing_failure_summary_v1",
            "delivery_state": "blocker",
            "phase_outcome": effective_phase_outcome,
            "primary_error_code": stable_error_code or "E_RESEARCH_INCOMPLETE",
            "reason_class": "explicit_research_incomplete",
            "template_key": "blocker.explicit_research_incomplete",
            "failure_scope": "research",
            "failed_phase": failed_phase,
            "retryable": True,
            "user_actionability": "retry_or_reduce_scope",
            "objective": objective,
            "allowed_user_visible_facts": allowed_user_visible_facts,
            "disallowed_inferences": disallowed_inferences,
            "next_step_hint": "Explain that the explicit research run did not gather enough verified sources to produce the requested report.",
        }

    if operator_ref == "builtin://shell.exec" or str(failed_output.get("operator_ref") or "").strip() == "builtin://shell.exec":
        return _build_shell_exec_failure_summary(
            failed_step=failed_step,
            failed_output=failed_output,
            stable_error_code=stable_error_code,
            failed_phase=failed_phase,
            objective=objective,
            disallowed_inferences=disallowed_inferences,
        )

    if operator_ref == "builtin://memory.search" or str(failed_output.get("operator_ref") or "").strip() == "builtin://memory.search":
        return _build_memory_search_failure_summary(
            failed_step=failed_step,
            failed_output=failed_output,
            stable_error_code=stable_error_code,
            failed_phase=failed_phase,
            objective=objective,
            disallowed_inferences=disallowed_inferences,
        )

    if _is_invalid_internal_plan_error_code(stable_error_code):
        reason_class = "invalid_internal_plan"
        template_key = "blocker.invalid_internal_plan"
        failure_scope = "planning"
        user_actionability = "retry_after_runtime_repair"
        next_step_hint = "Explain that the assistant produced an invalid or unfinished internal action plan before it could complete the request."
        allowed_user_visible_facts.extend(
            [
                "The assistant produced an invalid or unfinished internal action plan before completing the request.",
                f"Verified failed phase: {failed_phase}.",
                f"Stable error code: {stable_error_code or 'E_EXECUTION_FAILED'}.",
            ]
        )
    else:
        allowed_user_visible_facts.extend(
            [
                "The assistant runtime hit an infrastructure failure before it could complete the request.",
                f"Verified failed phase: {failed_phase}.",
                f"Stable error code: {stable_error_code or 'E_EXECUTION_FAILED'}.",
            ]
        )

    return {
        "schema_version": "1.0.0",
        "type": "user_facing_failure_summary_v1",
        "delivery_state": "blocker",
        "phase_outcome": effective_phase_outcome,
        "primary_error_code": stable_error_code or "E_EXECUTION_FAILED",
        "reason_class": reason_class,
        "template_key": template_key,
        "failure_scope": failure_scope,
        "failed_phase": failed_phase,
        "retryable": retryable,
        "user_actionability": user_actionability,
        "objective": objective,
        "allowed_user_visible_facts": allowed_user_visible_facts,
        "disallowed_inferences": disallowed_inferences,
        "next_step_hint": next_step_hint,
    }


def compile_query_for_assistant_loop(
    *,
    query_text: str,
    req_trace: TraceContext,
    workspace_id: str,
    effective_runtime_capabilities: dict[str, Any] | None,
    deadline_ms: int,
    data_dir: str | os.PathLike[str] = "data",
    agent_profile: dict[str, Any] | None = None,
    soul_profile: dict[str, Any] | None = None,
    context_planes: dict[str, Any] | None = None,
    message_received_at_utc: str | None = None,
    response_language: str | None = None,
    new_evidence_refs: list[str] | None = None,
    theorem_candidates: list[dict[str, Any]] | None = None,
    attachments: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None = None,
    external_evidence_policy_override: dict[str, Any] | None = None,
) -> QueryCompileResult:
    mode: QueryMode = "simple"
    temporal_anchor = (
        build_temporal_anchor_v1(message_received_at_utc=message_received_at_utc)
        if str(message_received_at_utc or "").strip()
        else (
            dict((((context_planes or {}).get("execution_plane") or {}).get("temporal_anchor") or {}))
            if isinstance((((context_planes or {}).get("execution_plane") or {}).get("temporal_anchor")), dict)
            else None
        )
    )

    profile_obj, profile_err = validate_agent_profile_v1(
        agent_profile or build_default_agent_profile_v1(agent_id="assistant_loop")
    )
    if profile_obj is None:
        report = {
            "schema_valid": False,
            "acceptance_pass": False,
            "error_patterns": [],
            "failures": [
                _make_failure(
                    gate="schema",
                    code=QUERY_ERROR_AGENT_PROFILE_INVALID,
                    reason=profile_err or "invalid agent profile",
                    evidence_refs=["agent_profile:v1"],
                    remediation="provide a valid AgentProfileV1 payload",
                )
            ],
        }
        return QueryCompileResult(
            ok=False,
            error_code=QUERY_ERROR_AGENT_PROFILE_INVALID,
            mode=mode,
            query={},
            verification_report=report,
        )

    execution_axiom_ids = [str(x.get("id") or "").strip() for x in (profile_obj.get("execution_axioms") or []) if str(x.get("id") or "").strip()]
    communication_axiom_ids = [str(x.get("id") or "").strip() for x in (profile_obj.get("communication_axioms") or []) if str(x.get("id") or "").strip()]
    constraint_ids = [str(x.get("id") or "").strip() for x in (profile_obj.get("reality_constraints") or []) if str(x.get("id") or "").strip()]
    runtime_policy_bundle = FileRuntimePolicyBundleStore(data_dir=str(data_dir)).get_or_default(workspace_scope=workspace_id)
    user_preference_profile = dict(runtime_policy_bundle.get("user_preference_profile") or {})
    execution_mode_policy = dict(runtime_policy_bundle.get("execution_mode_policy") or {})
    data_sensitivity_policy = dict(runtime_policy_bundle.get("data_sensitivity_policy") or {})
    proactivity_policy = dict(runtime_policy_bundle.get("proactivity_policy") or {})
    external_evidence_policy = dict(runtime_policy_bundle.get("external_evidence_policy") or {})
    preferred_response_language = (
        str(response_language).strip()
        if str(response_language or "").strip()
        else (
            str(user_preference_profile.get("response_language")).strip()
            if str(user_preference_profile.get("response_language") or "").strip()
            else None
        )
    )
    default_global_capsule = {
        "schema_version": "1.0.0",
        "workspace_id": workspace_id,
        "soul_profile_id": str(profile_obj.get("soul_profile_id") or "").strip(),
        "identity_summary": f"agent:{str(profile_obj.get('agent_id') or '').strip() or 'assistant'}",
        "communication_style": list(user_preference_profile.get("communication_style") or ["clear", "honest", "concise"]),
    }
    context_obj, context_err = _validate_context_planes(
        context_planes
        or build_context_plane_pack_v1(
            query_text=query_text,
            workspace_id=workspace_id,
            trace=req_trace,
            execution_axiom_ids=execution_axiom_ids,
            communication_axiom_ids=communication_axiom_ids,
            active_constraint_ids=constraint_ids,
            soul_profile_id=str(profile_obj.get("soul_profile_id") or "").strip(),
            global_capsule=default_global_capsule,
            message_received_at_utc=message_received_at_utc,
            temporal_anchor=temporal_anchor,
            style_constraints=list(user_preference_profile.get("communication_style") or []),
            response_language=preferred_response_language,
        )
    )
    if context_obj is None:
        report = {
            "schema_valid": False,
            "acceptance_pass": False,
            "error_patterns": [],
            "failures": [
                _make_failure(
                    gate="schema",
                    code=QUERY_ERROR_CONTEXT_PLANE_INVALID,
                    reason=context_err or "invalid context planes",
                    evidence_refs=["context_planes:v1"],
                    remediation="provide a valid ContextPlanePackV1 payload",
                )
            ],
        }
        return QueryCompileResult(
            ok=False,
            error_code=QUERY_ERROR_CONTEXT_PLANE_INVALID,
            mode=mode,
            query={},
            verification_report=report,
        )

    soul_store = FileSoulProfileStore(data_dir="data")
    soul_obj, soul_err = validate_soul_profile_v1(
        soul_profile
        or soul_store.get(soul_profile_id=str(profile_obj.get("soul_profile_id") or "").strip())
        or {
            "schema_version": "1.0.0",
            "soul_profile_id": str(profile_obj.get("soul_profile_id") or "default_assistant"),
            "name": "Default Assistant",
            "identity_summary": str((context_obj.get("communication_plane") or {}).get("role_hint") or "assistant").strip()
            or "assistant",
            "principles": ["be genuinely helpful"],
            "communication_defaults": {"tone": "direct", "verbosity": "concise", "style": ["clear", "honest", "concise"]},
            "boundary_rules": ["do not send half-baked external replies"],
        }
    )
    if soul_obj is None:
        report = {
            "schema_valid": False,
            "acceptance_pass": False,
            "error_patterns": [],
            "failures": [
                _make_failure(
                    gate="schema",
                    code=QUERY_ERROR_SOUL_PROFILE_INVALID,
                    reason=soul_err or "invalid soul profile",
                    evidence_refs=["agent_profile:v1"],
                    remediation="provide a valid SoulProfile payload",
                )
            ],
        }
        return QueryCompileResult(
            ok=False,
            error_code=QUERY_ERROR_SOUL_PROFILE_INVALID,
            mode=mode,
            query={},
            verification_report=report,
        )

    intent_recovery = resolve_intent_recovery_v1(
        query_text=query_text,
        context_planes=context_obj,
    )
    capability_names = capability_names_from_effective_runtime_capabilities(effective_runtime_capabilities)
    operator_catalog_results = search_operator_catalog(
        query_text=query_text,
        available_capabilities=capability_names,
        limit=6,
    )
    solution_query = derive_solution_query_v1(
        query_text=query_text,
        intent_recovery=intent_recovery,
        context_planes=context_obj,
        theorem_candidates=theorem_candidates,
        operator_catalog_results=operator_catalog_results,
    )
    original_intent_option = str(intent_recovery.get("intent_option") or "").strip()
    resolved_intent_option = str(solution_query.get("resolved_intent_option") or "").strip()
    resolved_objective = str(solution_query.get("resolved_objective") or query_text).strip() or str(query_text)
    if resolved_intent_option:
        intent_recovery = dict(intent_recovery)
        intent_recovery["intent_option"] = resolved_intent_option
    intent_recovery["recovered_objective"] = resolved_objective
    if resolved_intent_option and resolved_intent_option != original_intent_option:
        intent_recovery["recovery_source"] = "solution_query"
    effective_query_text = resolved_objective
    scope = _classify_scope(effective_query_text)
    normalized_attachments = _normalized_attachments(attachments)
    task_requirements = derive_task_requirements_v1(
        query_text=effective_query_text,
        scope=scope,
        capabilities=capability_names,
        attachments=normalized_attachments,
        effective_runtime_capabilities=effective_runtime_capabilities,
        external_evidence_policy_defaults=external_evidence_policy,
        external_evidence_policy_override=external_evidence_policy_override,
    )
    preferred_operator_hints = [
        str(x).strip()
        for x in (solution_query.get("preferred_operator_hints") or [])
        if str(x).strip()
    ]
    preferred_operator_hints.extend(
        str(x).strip() for x in (task_requirements.get("required_operator_hints") or []) if str(x).strip()
    )
    if bool(task_requirements.get("requires_workspace_observation")):
        solution_query["approach_strategy"] = "local_skill_first"
        if str(solution_query.get("plan_basis") or "").strip() not in {"status_from_state"}:
            solution_query["plan_basis"] = "inspect_first"
    elif bool(task_requirements.get("requires_external_evidence")):
        solution_query["approach_strategy"] = "local_skill_first"
        if str(solution_query.get("plan_basis") or "").strip() not in {"status_from_state"}:
            solution_query["plan_basis"] = "evidence_first"
    elif bool(task_requirements.get("requires_multi_step_plan")) and str(solution_query.get("plan_basis") or "").strip() == "answer_directly":
        solution_query["plan_basis"] = "plan_then_execute"
    solution_query["must_stop_without_evidence"] = bool(task_requirements.get("forbid_speculation_without_evidence")) or bool(
        solution_query.get("must_stop_without_evidence")
    )
    solution_query["preferred_operator_hints"] = list(dict.fromkeys(preferred_operator_hints))
    solution_query["requires_workspace_observation"] = bool(task_requirements.get("requires_workspace_observation"))
    solution_query["requires_external_evidence"] = bool(task_requirements.get("requires_external_evidence"))
    solution_query["requires_multi_step_plan"] = bool(task_requirements.get("requires_multi_step_plan"))
    risk = _risk_level(effective_query_text)
    steps = _steps_estimate(effective_query_text)
    cross_tool = (
        _should_write_memory(effective_query_text)
        or _needs_research(effective_query_text)
        or bool(task_requirements.get("requires_workspace_observation"))
    )
    needs_iter = _needs_iteration(effective_query_text) or bool(task_requirements.get("requires_multi_step_plan"))
    mode = _select_mode(
        risk=risk,
        steps_estimate=max(steps, 2 if bool(task_requirements.get("requires_multi_step_plan")) else steps),
        cross_tool=cross_tool,
        needs_iteration=needs_iter,
    )
    research_requirements = derive_research_requirements_v1(
        query_text=effective_query_text,
        task_requirements=task_requirements,
        mode=mode,
        risk=risk,
        context_planes=context_obj,
    )
    task_requirements = {
        **task_requirements,
        "research_required": bool(research_requirements.get("research_required")),
        "research_depth": str(research_requirements.get("research_depth") or "none").strip() or "none",
        "selected_doctrine_pack": (
            str(research_requirements.get("selected_doctrine_pack") or "fast_path_mode").strip()
            or "fast_path_mode"
        ),
        "evidence_expectation": (
            str(research_requirements.get("evidence_expectation") or "local_state").strip() or "local_state"
        ),
        "citation_required": bool(research_requirements.get("citation_required")),
        "self_adversarial_required": bool(research_requirements.get("self_adversarial_required")),
        "research_max_rounds": max(1, int(research_requirements.get("research_max_rounds") or 1)),
        "source_count_min": max(0, int(research_requirements.get("source_count_min") or 0)),
    }
    solution_query["research_required"] = bool(task_requirements.get("research_required"))
    solution_query["citation_required"] = bool(task_requirements.get("citation_required"))
    interaction_mode = infer_interaction_mode_v1(intent_recovery=intent_recovery, mode=mode)
    model_routing_policy = build_model_routing_policy_v1(
        interaction_mode=interaction_mode,
        mode=mode,
        task_requirements=task_requirements,
        solution_query=solution_query,
        execution_mode_policy=execution_mode_policy,
        user_preference_profile=user_preference_profile,
    )
    execution_lane = str(model_routing_policy.get("execution_lane") or "standard_task").strip() or "standard_task"
    execution_lane_profile = execution_lane_policy(execution_lane)
    effective_response_language = (
        str(response_language).strip()
        if str(response_language or "").strip()
        else (
            str(((context_obj.get("communication_plane") or {}).get("response_language")) or "").strip()
            if str(((context_obj.get("communication_plane") or {}).get("response_language")) or "").strip()
            else None
        )
    )

    if mode == "simple":
        budget = {"loops_max": 1, "tool_calls_max": 1, "time_ms_max": max(1000, int(deadline_ms))}
        complexity = "simple"
    elif mode == "standard":
        budget = {"loops_max": 2, "tool_calls_max": 6, "time_ms_max": max(1000, int(deadline_ms))}
        complexity = "complex"
    else:
        budget = {"loops_max": 3, "tool_calls_max": 10, "time_ms_max": max(1000, int(deadline_ms))}
        complexity = "complex"

    if bool(task_requirements.get("requires_external_evidence")):
        external_evidence_policy_v1 = dict(task_requirements.get("external_evidence_policy_v1") or {})
        budget["loops_max"] = max(int(budget.get("loops_max") or 1), 3 if mode == "standard" else 4 if mode != "simple" else 1)
        budget["tool_calls_max"] = max(int(budget.get("tool_calls_max") or 1), 8 if mode == "standard" else 12 if mode != "simple" else 1)
        budget["loops_max"] = max(
            int(budget.get("loops_max") or 1),
            int(external_evidence_policy_v1.get("search_rounds_max") or 2) + 1,
        )
        budget["tool_calls_max"] = max(
            int(budget.get("tool_calls_max") or 1),
            int(external_evidence_policy_v1.get("search_rounds_max") or 2)
            + int(external_evidence_policy_v1.get("total_browse_steps_max") or 4)
            + 2,
        )
    if bool(task_requirements.get("research_required")):
        budget["loops_max"] = max(int(budget.get("loops_max") or 1), int(task_requirements.get("research_max_rounds") or 2))
        budget["tool_calls_max"] = max(int(budget.get("tool_calls_max") or 1), 10 if mode == "standard" else 14)
    token_budget = default_token_budget_for_lane(execution_lane)
    stop_policy = default_stop_policy_for_lane(execution_lane, deadline_ms=int(budget.get("time_ms_max") or deadline_ms))

    current_hypothesis = build_query_hypothesis(
        query_text=effective_query_text,
        mode=mode,
        capability_names=capability_names,
    )
    input_debounced = _should_enforce_input_debounce(
        context_planes=context_obj,
        current_query_text=query_text,
        message_received_at_utc=message_received_at_utc,
    )
    review_candidate = make_axiom_review_candidate(
        agent_profile=profile_obj,
        context_planes=context_obj,
    )
    task_envelope = build_task_envelope_v1(
        query_text=effective_query_text,
        req_trace=req_trace,
        mode=mode,
        scope=scope,
        risk=risk,
        needs_research=_needs_research(effective_query_text),
        should_write_memory=_should_write_memory(effective_query_text),
        message_received_at_utc=message_received_at_utc,
        temporal_anchor=temporal_anchor,
        task_requirements=task_requirements,
    )
    if bool(task_requirements.get("delivery_kind")):
        task_envelope["deliverable"] = str(task_requirements.get("delivery_kind"))
    delivery_contract = build_delivery_contract_v1(
        task_envelope=task_envelope,
        mode=mode,
        should_write_memory=_should_write_memory(effective_query_text),
    )
    task_execution_policy = _build_task_execution_policy_from_requirements(
        deadline_ms=deadline_ms,
        mode=mode,
        task_requirements=task_requirements,
    )
    task_mode, delegation_budget, max_depth, scope_guard = _derive_task_delegation_shape(
        task_requirements=task_requirements,
        mode=mode,
    )
    ancestor_context_refs = [
        *[
            str(item).strip()
            for item in (((context_obj.get("execution_plane") or {}).get("evidence_refs")) or [])
            if str(item).strip()
        ],
        *[str(item).strip() for item in (new_evidence_refs or []) if str(item).strip()],
    ]
    file_refs = _build_task_file_refs_v1(
        attachments=normalized_attachments,
        new_evidence_refs=new_evidence_refs,
        attachment_evidence_required=bool(task_requirements.get("attachment_evidence_required")),
    )
    context_graph = build_context_graph_v1(
        query_text=effective_query_text,
        workspace_id=workspace_id,
        trace_id=str(req_trace.trace_id),
        turn_id=str(req_trace.turn_id),
        task_envelope=task_envelope,
        context_planes=context_obj,
        task_requirements=task_requirements,
        solution_query=solution_query,
        intent_recovery=intent_recovery,
        interaction_mode=interaction_mode,
        agent_profile=profile_obj,
        soul_profile=soul_obj,
    )
    task_context_views = build_task_context_views_v1(
        context_graph=context_graph,
        task_envelope=task_envelope,
        delivery_contract=delivery_contract,
        context_planes=context_obj,
        task_requirements=task_requirements,
        solution_query=solution_query,
        intent_recovery=intent_recovery,
        interaction_mode=interaction_mode,
    )
    task_bundle = build_task_bundle_v1(
        objective=str(task_envelope.get("objective") or effective_query_text).strip(),
        completion_contract_ref="delivery_contract:v1",
        task_execution_policy=task_execution_policy,
        context_snapshot_ref="context_graph:v1",
        workspace_root=str(_repo_root()),
        allowed_capabilities=capability_names,
        file_refs=file_refs,
        dependency_result_refs=[str(item).strip() for item in (new_evidence_refs or []) if str(item).strip()],
        read_only_ancestor_context_refs=ancestor_context_refs,
        context_escalation_mode="auto",
        worker_task_admission_mode="leader_gate",
        bundle_generation="aggressive",
        sufficient_for_execution=(
            not bool(task_requirements.get("attachment_evidence_required"))
            or bool(file_refs)
        ),
        task_mode=task_mode,
        delegation_budget=delegation_budget,
        max_depth=max_depth,
        scope_guard=scope_guard,
    )
    task_bundle["execution_lane"] = execution_lane
    task_bundle["token_budget"] = dict(token_budget)
    task_bundle["stop_policy"] = dict(stop_policy)
    views_obj = task_context_views.get("views") if isinstance(task_context_views, dict) else None
    bundle_fact_lines = [
        f"task_mode={task_mode}",
        f"worker_task_admission_mode={task_bundle.get('worker_task_admission_mode')}",
        f"delegation_budget={int(task_bundle.get('delegation_budget') or 0)}",
        f"max_depth={int(task_bundle.get('max_depth') or 0)}",
        f"bundle_sufficient_for_execution={bool(task_bundle.get('sufficient_for_execution'))}",
        f"file_ref_count={len(file_refs)}",
    ]
    if isinstance(views_obj, dict):
        for profile_id in ("intent_router", "planner", "executor", "verifier_replanner", "communicator"):
            view_obj = views_obj.get(profile_id)
            if not isinstance(view_obj, dict):
                continue
            relevant_facts = list(view_obj.get("relevant_facts") or [])
            relevant_facts.extend(bundle_fact_lines)
            view_obj["relevant_facts"] = list(dict.fromkeys(str(item).strip() for item in relevant_facts if str(item).strip()))
            if profile_id == "executor":
                dependency_results = list(view_obj.get("dependency_task_results") or [])
                dependency_results.extend(
                    [
                        f"completion_contract_ref={str(task_bundle.get('completion_contract_ref') or '')}",
                        f"read_only_ancestor_context_ref_count={len(task_bundle.get('read_only_ancestor_context_refs') or [])}",
                        f"split_request_only={str(task_bundle.get('worker_task_admission_mode') or '') == 'leader_gate'}",
                    ]
                )
                view_obj["dependency_task_results"] = list(
                    dict.fromkeys(str(item).strip() for item in dependency_results if str(item).strip())
                )
    runtime_graph_seed = {
        "schema_version": "1.0.0",
        "type": "runtime_graph_v1",
        "root_task_id": str(task_envelope.get("task_id") or ""),
        "active_plan_revision": 0,
        "message_turn": {
            "trace_id": str(req_trace.trace_id),
            "turn_id": str(req_trace.turn_id),
            "workspace_id": str(workspace_id),
        },
        "leader_phases": ["planner", "verifier_replanner", "communicator"],
        "worker_phases": ["worker_react"],
        "task_bundle_ref": "task_bundle:v1",
    }
    prompt_compilation = compile_prompt_bundle_v1(
        agent_profile=profile_obj,
        soul_profile=soul_obj,
        context_planes=context_obj,
        context_graph=context_graph,
        task_context_views=task_context_views,
        interaction_mode=interaction_mode,
        mode=mode,
        task_requirements=task_requirements,
        solution_query=solution_query,
        response_language=effective_response_language,
    )
    compiled_profiles = dict(prompt_compilation.get("profiles") or {})
    resolution_obj = (
        profile_obj.get("operator_resolution")
        if isinstance(profile_obj.get("operator_resolution"), dict)
        else profile_obj.get("capability_resolution")
    ) or {"policy": "skill_first"}
    resolution_policy = str(resolution_obj.get("policy") or "skill_first")

    query_obj: dict[str, Any] = {
        "schema_version": "1.0.0",
        "type": "query_gated_query_v1",
        "agent_profile": profile_obj,
        "context_planes": context_obj,
        "task_envelope": task_envelope,
        "delivery_contract": delivery_contract,
        "task_bundle": task_bundle,
        "task_execution_policy": task_execution_policy,
        "file_refs": file_refs,
        "runtime_graph": runtime_graph_seed,
        "objective": str(task_envelope["objective"]),
        "raw_input": str(query_text),
        "intent_recovery": intent_recovery,
        "solution_query": solution_query,
        "task_requirements": task_requirements,
        "attachments": normalized_attachments,
        "research_required": bool(task_requirements.get("research_required")),
        "research_depth": str(task_requirements.get("research_depth") or "none").strip() or "none",
        "selected_doctrine_pack": str(task_requirements.get("selected_doctrine_pack") or "").strip() or None,
        "evidence_expectation": str(task_requirements.get("evidence_expectation") or "").strip() or None,
        "citation_required": bool(task_requirements.get("citation_required")),
        "soul_profile": soul_obj,
        "global_soul": dict(soul_obj.get("global_soul") or {}),
        "context_graph": context_graph,
        "task_context_views": task_context_views,
        "prompt_compilation": prompt_compilation,
        "prompt_profiles": compiled_profiles,
        "active_style_pack": dict(prompt_compilation.get("active_style_pack") or {}),
        "response_language": effective_response_language,
        "active_doctrine_pack": dict(prompt_compilation.get("active_doctrine_pack") or {}),
        "domain_policy_pack": dict(prompt_compilation.get("domain_policy_pack") or {}),
        "runtime_policy_bundle": runtime_policy_bundle,
        "interaction_mode": interaction_mode,
        "model_routing_policy": model_routing_policy,
        "execution_lane": execution_lane,
        "execution_lane_policy": {
            "lane": execution_lane_profile.lane,
            "reasoning_profile_ref": execution_lane_profile.reasoning_profile_ref,
            "model_pool_ref": execution_lane_profile.model_pool_ref,
            "max_reasoning_turns": int(execution_lane_profile.max_reasoning_turns),
            "tool_parallelism_cap": int(execution_lane_profile.tool_parallelism_cap),
            "verification_mode": execution_lane_profile.verification_mode,
            "on_lane_insufficient": execution_lane_profile.on_lane_insufficient,
        },
        "token_budget": token_budget,
        "stop_policy": stop_policy,
        "context_pack": {
            "state_summary": str(context_obj["execution_plane"]["state_summary"]),
            "evidence": [
                {"kind": "user_input", "ref": f"ingress:{req_trace.turn_id}", "data": {"len": len(query_text)}},
                {
                    "kind": "intent_recovery",
                    "ref": "intent_recovery:v1",
                    "data": {
                        "intent_option": str(intent_recovery.get("intent_option") or ""),
                        "needs_model_fallback": bool(intent_recovery.get("needs_model_fallback")),
                        "interaction_mode": interaction_mode,
                    },
                },
                {
                    "kind": "workspace_state",
                    "ref": f"workspace:{workspace_id}",
                    "data": {
                        "workspace_id": workspace_id,
                        "trace_id": req_trace.trace_id,
                        "message_received_at_utc": (
                            str(message_received_at_utc).strip() if str(message_received_at_utc or "").strip() else None
                        ),
                        "temporal_anchor": temporal_anchor,
                    },
                },
                {
                    "kind": "policy",
                    "ref": "agent_profile:v1",
                    "data": {
                        "agent_id": profile_obj["agent_id"],
                        "execution_axiom_ids": execution_axiom_ids,
                        "communication_axiom_ids": communication_axiom_ids,
                        "operator_resolution_policy": resolution_policy,
                        "soul_profile_id": str(profile_obj.get("soul_profile_id") or "").strip(),
                        "execution_mode": str(execution_mode_policy.get("default_mode") or "balanced"),
                        "risk_tolerance": str(user_preference_profile.get("risk_tolerance") or "balanced"),
                        "data_default_level": str(data_sensitivity_policy.get("default_level") or "L1"),
                        "proactivity_enabled": bool(proactivity_policy.get("enabled", False)),
                    },
                },
                {
                    "kind": "context_planes",
                    "ref": "context_planes:v1",
                    "data": {
                        "recent_failures_count": len(context_obj["retrospective_plane"]["recent_failures"]),
                        "recent_success_patterns_count": len(context_obj["retrospective_plane"]["recent_success_patterns"]),
                        "execution_axiom_ids": list(context_obj["constraint_plane"]["execution_axiom_ids"]),
                        "communication_axiom_ids": list(context_obj["constraint_plane"]["communication_axiom_ids"]),
                        "active_constraint_ids": list(context_obj["constraint_plane"]["active_constraint_ids"]),
                        "has_last_pending_task": bool((context_obj.get("intent_recovery_plane") or {}).get("last_pending_task")),
                    },
                },
                {
                    "kind": "solution_query",
                    "ref": "solution_query:v1",
                    "data": {
                        "continuity_binding": str(solution_query.get("continuity_binding") or ""),
                        "approach_strategy": str(solution_query.get("approach_strategy") or ""),
                        "plan_basis": str(solution_query.get("plan_basis") or ""),
                        "preserve_pending_contract": bool(solution_query.get("preserve_pending_contract")),
                        "research_required": bool(task_requirements.get("research_required")),
                        "research_depth": str(task_requirements.get("research_depth") or "none"),
                        "selected_doctrine_pack": str(task_requirements.get("selected_doctrine_pack") or ""),
                        "citation_required": bool(task_requirements.get("citation_required")),
                    },
                },
                {
                    "kind": "theorem_retrieval",
                    "ref": "theorem:v1",
                    "data": {
                        "matched_count": len(solution_query.get("retrieved_theorem_ids") or []),
                        "theorem_ids": list(solution_query.get("retrieved_theorem_ids") or [])[:4],
                    },
                },
                {
                    "kind": "operator_search",
                    "ref": "operator_search:v1",
                    "data": {
                        "results": [dict(x) for x in (solution_query.get("operator_search_results") or [])[:4]],
                    },
                },
                {
                    "kind": "prompt_compiler",
                    "ref": "context_projection:v1",
                    "data": {
                        "context_graph_nodes": len(context_graph.get("nodes") or []),
                        "context_graph_edges": len(context_graph.get("edges") or []),
                        "prompt_profiles": sorted(compiled_profiles.keys()),
                        "style_pack_id": str((prompt_compilation.get("active_style_pack") or {}).get("pack_id") or ""),
                        "doctrine_pack_id": str((prompt_compilation.get("active_doctrine_pack") or {}).get("pack_id") or ""),
                        "domain_tags": list(context_graph.get("domain_tags") or []),
                    },
                },
                {
                    "kind": "decision",
                    "ref": "triage:v1",
                    "data": {
                        "scope": scope,
                        "complexity": complexity,
                        "risk": risk,
                        "steps_estimate": int(steps),
                        "cross_tool": bool(cross_tool),
                        "needs_iteration": bool(needs_iter),
                        "requires_workspace_observation": bool(task_requirements.get("requires_workspace_observation")),
                        "research_required": bool(task_requirements.get("research_required")),
                        "requires_multi_step_plan": bool(task_requirements.get("requires_multi_step_plan")),
                        "forbid_speculation_without_evidence": bool(task_requirements.get("forbid_speculation_without_evidence")),
                    },
                },
            ],
        },
        "capabilities": capability_names,
        "workspace_snapshot": {
            "workspace_id": workspace_id,
            "trace_id": req_trace.trace_id,
            "turn_id": req_trace.turn_id,
            "span_id": req_trace.span_id,
            "message_received_at_utc": (
                str(message_received_at_utc).strip() if str(message_received_at_utc or "").strip() else None
            ),
            "temporal_anchor": temporal_anchor,
            "agent_profile": {
                "agent_id": profile_obj["agent_id"],
                "soul_profile_id": str(profile_obj.get("soul_profile_id") or "").strip(),
                "execution_axiom_ids": execution_axiom_ids,
                "communication_axiom_ids": communication_axiom_ids,
                "active_constraint_ids": constraint_ids,
            },
            "soul_profile": {
                "soul_profile_id": str(soul_obj.get("soul_profile_id") or "").strip(),
                "style_pack_ids": sorted(list((soul_obj.get("style_packs") or {}).keys())),
                "doctrine_pack_ids": sorted(list((soul_obj.get("doctrine_packs") or {}).keys())),
            },
            "runtime_policy_bundle": runtime_policy_bundle,
            "context_planes": context_obj,
        },
        "constraints": list(
            dict.fromkeys(
                [
                    "query_gated_execution",
                    "solution_query_before_plan",
                    "context_pack_evidence_5_10",
                    "context_graph_projection_enabled",
                    "prompt_compiler_profile_split",
                    *[f"execution_axiom:{x}" for x in execution_axiom_ids],
                    *[f"communication_axiom:{x}" for x in communication_axiom_ids],
                    *[f"constraint:{x}" for x in constraint_ids],
                    f"operator_resolution:{resolution_policy}",
                    f"soul_profile:{str(profile_obj.get('soul_profile_id') or '').strip()}",
                    f"execution_mode:{str(execution_mode_policy.get('default_mode') or 'balanced')}",
                    f"data_sensitivity_default:{str(data_sensitivity_policy.get('default_level') or 'L1')}",
                    f"doctrine_pack:{str(task_requirements.get('selected_doctrine_pack') or 'fast_path_mode')}",
                ]
            )
        ),
        "acceptance_criteria": list(task_envelope["acceptance_criteria"])
        + [
            "when execution budget is exhausted, transition to hold and wait for HITL instead of silently terminating",
            "rejected hypotheses require new evidence before retry",
            "context-dependent acknowledgments must bind to the active intent or request clarification",
            "planning must follow the resolved solution_query before execution starts",
            "task execution must honor derived task requirements before answering",
            "prompt compilation must keep global soul, role axioms, style, and doctrine separated",
            "research doctrine selection must remain inside the single canonical runtime",
        ],
        "budget": budget,
        "termination_policy": "on budget exhaustion, hold current execution state and raise HITL_REQUIRED with attempted_paths+evidence",
        "mode": mode,
        "hypothesis": {
            "current": current_hypothesis,
            "repeated_without_new_evidence": False,
            "new_evidence_refs": [str(x).strip() for x in (new_evidence_refs or []) if str(x).strip()],
        },
        "ingress_control": {
            "input_debounced": bool(input_debounced),
            "debounce_window_ms": int(INPUT_DEBOUNCE_WINDOW_MS),
        },
        "axiom_review_candidate": review_candidate,
    }

    failures = _validate_query_schema(query_obj)
    if input_debounced:
        failures.append(
            _make_failure(
                gate="ingress",
                code=QUERY_ERROR_INPUT_DEBOUNCED,
                reason="identical user input arrived within the debounce window",
                evidence_refs=["intent_recovery_plane:v1"],
                remediation="wait briefly or send a changed follow-up before retry",
            )
        )
    report = {
        "schema_valid": len(_validate_query_schema(query_obj)) == 0,
        "acceptance_pass": len(failures) == 0,
        "error_patterns": [],
        "failures": failures,
    }
    if failures:
        code = str(failures[0].get("code") or QUERY_ERROR_SCHEMA_INVALID)
        return QueryCompileResult(
            ok=False,
            error_code=code,
            mode=mode,
            query=query_obj,
            verification_report=report,
        )
    return QueryCompileResult(
        ok=True,
        error_code=None,
        mode=mode,
        query=query_obj,
        verification_report=report,
    )


def verify_assistant_execution(
    *,
    compiled_query: dict[str, Any],
    mode: QueryMode,
    exec_summaries: list[dict[str, Any]],
    step_outputs: list[dict[str, Any]] | None = None,
    error_code: str | None,
    final_output: dict[str, Any] | None,
) -> dict[str, Any]:
    failures = _validate_query_schema(compiled_query)
    error_patterns: list[str] = []
    task_envelope = compiled_query.get("task_envelope") if isinstance(compiled_query, dict) else None
    delivery_contract = compiled_query.get("delivery_contract") if isinstance(compiled_query, dict) else None
    task_requirements = compiled_query.get("task_requirements") if isinstance(compiled_query, dict) else None
    non_delivery_exec_summaries = [
        item for item in exec_summaries if isinstance(item, dict) and _counts_toward_external_execution_budget(item)
    ]
    send_message_accepted = _has_accepted_send_message_step(exec_summaries)
    communicator_send_message_accepted = _has_accepted_communicator_send_message_step(exec_summaries)

    budget = compiled_query.get("budget") if isinstance(compiled_query, dict) else None
    tool_calls_max = 0
    if isinstance(budget, dict):
        try:
            tool_calls_max = int(budget.get("tool_calls_max") or 0)
        except Exception:
            tool_calls_max = 0
    if tool_calls_max > 0 and len(non_delivery_exec_summaries) > tool_calls_max:
        error_patterns.append("EP_BUDGET_TOOL_CALLS")
        failures.append(
            _make_failure(
                gate="hitl",
                code="E_HITL_REQUIRED",
                reason=f"tool calls exceeded budget and execution must enter hold: used={len(non_delivery_exec_summaries)} limit={tool_calls_max}",
                evidence_refs=["triage:v1"],
                remediation="preserve current trace, evidence, and partial results, then wait for HITL",
            )
        )
    if isinstance(task_requirements, dict) and bool(task_requirements.get("requires_workspace_observation")):
        observed = any(
            str(item.get("operator_ref") or "").strip()
            in {"builtin://fs.list", "builtin://fs.read", "builtin://shell.exec"}
            and str(item.get("status") or "").strip() == "accepted"
            for item in exec_summaries
            if isinstance(item, dict)
        )
        if not observed:
            error_patterns.append("EP_MISSING_WORKSPACE_OBSERVATION")
            failures.append(
                _make_failure(
                    gate="requirements",
                    code="E_REQUIRED_WORKSPACE_OBSERVATION_MISSING",
                    reason="task required fresh workspace observation before answering",
                    evidence_refs=["triage:v1"],
                    remediation="run inspect-first operators or return an explicit blocker instead of speculative analysis",
                )
            )
    if isinstance(task_requirements, dict) and bool(task_requirements.get("research_required")):
        browsed = any(
            str(item.get("operator_ref") or "").strip() == "builtin://web.browse"
            and str(item.get("status") or "").strip() == "accepted"
            for item in exec_summaries
            if isinstance(item, dict)
        )
        if error_code is None and not browsed:
            error_patterns.append("EP_MISSING_RESEARCH_BROWSE")
            failures.append(
                _make_failure(
                    gate="requirements",
                    code="E_REQUIRED_RESEARCH_EVIDENCE_MISSING",
                    reason="task required research doctrine evidence before answering",
                    evidence_refs=["triage:v1"],
                    remediation="browse and compare bounded sources or return an explicit blocker instead of stopping at search results",
                )
            )

    has_final_output = isinstance(final_output, dict)
    final_has_user_visible_output = _has_user_visible_output(final_output)
    final_is_send_message = _is_send_message_operator((final_output or {}).get("operator_ref"))
    final_delivery_stage = str((final_output or {}).get("delivery_stage") or "").strip()
    acceptance_pass = bool(
        error_code is None
        and has_final_output
        and final_is_send_message
        and final_has_user_visible_output
        and final_delivery_stage in {"final", "need_context"}
    )
    if error_code is None and (not has_final_output or not final_has_user_visible_output):
        failures.append(
            _make_failure(
                gate="acceptance",
                code="E_DELIVERY_VERIFICATION_FAILED",
                reason="final output is empty while execution had no explicit error",
                evidence_refs=["triage:v1"],
                remediation="enforce final_output to be an accepted send_message result for successful execution",
            )
        )
    elif (
        error_code is None
        and has_final_output
        and final_has_user_visible_output
        and final_is_send_message
        and final_delivery_stage not in {"final", "need_context"}
    ):
        failures.append(
            _make_failure(
                gate="acceptance",
                code="E_DELIVERY_VERIFICATION_FAILED",
                reason=f"successful execution ended with non-terminal delivery_stage={final_delivery_stage or '-'}",
                evidence_refs=["triage:v1"],
                remediation="enforce final successful delivery to use delivery_stage=final, or need_context when clarification is required",
            )
        )

    acceptance_criteria = []
    if isinstance(task_envelope, dict):
        raw = task_envelope.get("acceptance_criteria") or []
        if isinstance(raw, list):
            acceptance_criteria = [str(x).strip() for x in raw if str(x).strip()]
    if acceptance_criteria:
        if not _has_user_visible_output(final_output):
            acceptance_pass = False
            failures.append(
                _make_failure(
                    gate="acceptance",
                    code="E_DELIVERY_VERIFICATION_FAILED",
                    reason="delivery contract requires non-empty user-visible output",
                    evidence_refs=["triage:v1"],
                    remediation="return non-empty user-visible output or explicit blocked explanation",
                )
            )
        elif not send_message_accepted:
            acceptance_pass = False
            failures.append(
                _make_failure(
                    gate="acceptance",
                    code="E_MESSAGE_TASK_MISSING",
                    reason="user-visible delivery did not pass through an accepted send_message task",
                    evidence_refs=["triage:v1"],
                    remediation="execute builtin://channel.send_message before marking done",
                )
            )
        elif not communicator_send_message_accepted:
            acceptance_pass = False
            failures.append(
                _make_failure(
                    gate="acceptance",
                    code="E_MESSAGE_TASK_PHASE_VIOLATION",
                    reason="user-visible delivery was not emitted by communicator",
                    evidence_refs=["triage:v1"],
                    remediation="route all user-visible natural language through communicator -> send_message",
                )
            )

    done_definition = ""
    if isinstance(delivery_contract, dict):
        done_definition = str(delivery_contract.get("done_definition") or "").strip()
    if done_definition and error_code is not None:
        acceptance_pass = False
        failures.append(
            _make_failure(
                gate="delivery_contract",
                code="E_DELIVERY_VERIFICATION_FAILED",
                reason=f"delivery contract not satisfied because execution ended with error_code={error_code}",
                evidence_refs=["triage:v1"],
                remediation="repair the execution path or terminate with an explicit blocked explanation",
            )
        )

    if failures:
        acceptance_pass = False

    pause_error_codes = {
        "E_HITL_REQUIRED",
        "E_DEADLINE_EXCEEDED",
        "E_TOKEN_BUDGET_EXHAUSTED",
        "E_NO_PROGRESS",
    }
    hold_required = str(error_code or "").strip() in pause_error_codes or any(
        str(item.get("code") or "").strip() in pause_error_codes for item in failures if isinstance(item, dict)
    )
    blocker = (str(error_code or "").strip() != "" and str(error_code or "").strip() not in pause_error_codes) or any(
        str(item.get("code") or "").strip() == "E_DELIVERY_VERIFICATION_FAILED" for item in failures if isinstance(item, dict)
    )
    delivery_state = "hold" if hold_required else ("done" if acceptance_pass else "blocker")
    if acceptance_pass and isinstance(final_output, dict) and str(final_output.get("delivery_stage") or "").strip() == "need_context":
        delivery_state = "need_context"
    primary_failure = failures[0] if failures else None
    primary_failure_code = str((primary_failure or {}).get("code") or "") if isinstance(primary_failure, dict) else ""
    user_facing_failure_summary = build_user_facing_failure_summary_v1(
        compiled_query=compiled_query,
        exec_summaries=exec_summaries,
        step_outputs=step_outputs,
        error_code=error_code,
        primary_failure_code=primary_failure_code,
    )

    out = {
        "schema_valid": len(_validate_query_schema(compiled_query)) == 0,
        "acceptance_pass": acceptance_pass,
        "error_patterns": error_patterns,
        "failures": failures,
        "delivery_state": delivery_state,
        "blocker": blocker,
        "hitl_required": hold_required,
        "done_definition": done_definition,
        "task_id": str((task_envelope or {}).get("task_id") or ""),
        "primary_failure_code": primary_failure_code,
    }
    if isinstance(user_facing_failure_summary, dict):
        out["user_facing_failure_summary"] = user_facing_failure_summary
    return out
