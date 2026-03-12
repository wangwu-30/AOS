from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any, Optional

from agentos_next.kernel.evidence_store import FileEvidenceStore
from agentos_next.kernel.memory_store import (
    MEMORY_V2_SCHEMA_VERSION,
    MemoryContextV2,
    MemoryHitV2,
    MemoryQueryV2,
    MemoryRetrieverV2,
    MemoryScopeV2,
    MemoryStoreV2,
)
from agentos_next.kernel.runtime_snapshot_store import ContinuityHeadV2, FileRuntimeSnapshotStore


PA_MEM_ERROR_SCHEMA_INVALID = "E_PA_MEM_SCHEMA_INVALID"
PA_MEM_ERROR_COMPILE_FAILED = "E_PA_MEM_COMPILE_FAILED"


@dataclass(frozen=True)
class PAMemoryPipelineConfig:
    enabled: bool = False
    retrieval_limit: int = 8
    include_stale: bool = False
    continuity_event_limit: int = 50
    audit_mode: bool = False


@dataclass(frozen=True)
class PAMemoryPipelineResult:
    ok: bool
    error_code: Optional[str]
    memory_context: Optional[dict[str, Any]] = None
    evidence_refs: tuple[str, ...] = ()


def _normalize_text(raw: Any) -> str:
    text = " ".join(str(raw or "").lower().split())
    text = re.sub(r"[^0-9a-z_\u4e00-\u9fff]+", " ", text)
    return " ".join(text.split())


def _extract_terms(text: str) -> tuple[str, ...]:
    if not text:
        return ()
    terms: set[str] = set(re.findall(r"[a-z0-9_]{2,}", text))
    for chunk in re.findall(r"[\u4e00-\u9fff]{2,}", text):
        terms.add(chunk)
        if len(chunk) > 4:
            terms.add(chunk[:4])
            terms.add(chunk[-4:])
    return tuple(sorted(terms, key=len, reverse=True))


def _has_continuity_signal(user_message: str) -> bool:
    raw = " ".join(str(user_message or "").split())
    lower = raw.lower()
    markers = (
        "刚才",
        "上次",
        "之前",
        "继续",
        "接着",
        "blocker",
        "pending",
        "resume",
        "continue",
        "status",
    )
    return any(token in raw or token in lower for token in markers)


def _is_same_task_query(current_query: str, previous_query: Any) -> bool:
    current_norm = _normalize_text(current_query)
    previous_norm = _normalize_text(previous_query)
    if not current_norm or not previous_norm:
        return False
    if current_norm == previous_norm:
        return True
    shorter, longer = sorted((current_norm, previous_norm), key=len)
    if len(shorter) >= 6 and shorter in longer:
        return True
    shared_terms = set(_extract_terms(current_norm)) & set(_extract_terms(previous_norm))
    return any(len(term) >= 4 for term in shared_terms)


def _should_include_recovery_context(
    *,
    intent: str,
    user_message: str,
    continuity_head: ContinuityHeadV2 | None,
) -> bool:
    if continuity_head is None:
        return False
    if intent == "continuity" or _has_continuity_signal(user_message):
        return True
    return _is_same_task_query(user_message, continuity_head.last_user_query)


def _filter_hits(
    *,
    hits: list[MemoryHitV2],
    user_message: str,
    include_recovery_context: bool,
) -> list[MemoryHitV2]:
    if include_recovery_context:
        return hits
    filtered: list[MemoryHitV2] = []
    for hit in hits:
        if hit.kind != "anti_pattern":
            filtered.append(hit)
            continue
        payload = hit.payload if isinstance(hit.payload, dict) else {}
        if _is_same_task_query(user_message, payload.get("query")):
            filtered.append(hit)
    return filtered


def _infer_memory_intent(user_message: str) -> str:
    raw = " ".join(str(user_message or "").split())
    lower = raw.lower()
    if any(token in raw or token in lower for token in ("我是谁", "名字", "name", "who am i", "我是")):
        return "identity"
    if any(token in raw or token in lower for token in ("喜欢", "偏好", "prefer", "favorite", "爱吃")):
        return "preference"
    if any(token in raw or token in lower for token in ("刚才", "上次", "进度", "继续", "blocker", "pending")):
        return "continuity"
    if any(token in raw or token in lower for token in ("步骤", "流程", "怎么做", "procedure", "how to")):
        return "procedure"
    if any(token in raw or token in lower for token in ("结果", "交付", "summary", "delivered")):
        return "delivery"
    return "generic"


def _intent_kinds(intent: str) -> tuple[str, ...]:
    if intent == "identity":
        return ("profile",)
    if intent == "preference":
        return ("preference",)
    if intent == "continuity":
        return ("delivery_summary", "note", "profile", "preference")
    if intent == "procedure":
        return ("procedure", "anti_pattern")
    if intent == "delivery":
        return ("delivery_summary", "procedure")
    return ("profile", "preference", "procedure", "anti_pattern", "delivery_summary", "note")


def _resolved_project_id(
    *,
    project_id: str | None,
    policy_context_passthrough: Optional[dict[str, Any]],
    continuity_head: ContinuityHeadV2 | None,
) -> Optional[str]:
    explicit = str(project_id or "").strip()
    if explicit:
        return explicit
    if continuity_head is not None and str(continuity_head.active_project_id or "").strip():
        return str(continuity_head.active_project_id).strip()
    passthrough = dict(policy_context_passthrough or {})
    context_planes = passthrough.get("context_planes")
    if isinstance(context_planes, dict):
        recovery_plane = context_planes.get("intent_recovery_plane")
        if isinstance(recovery_plane, dict):
            candidate = str(recovery_plane.get("active_project_id") or "").strip()
            if candidate:
                return candidate
    return None


def _continuity_payload(
    *,
    workspace_id: str,
    conversation_id: str,
    continuity_head: ContinuityHeadV2 | None,
    include_recovery_context: bool,
) -> dict[str, Any]:
    if continuity_head is None:
        return {
            "workspace_id": str(workspace_id),
            "conversation_id": str(conversation_id),
            "active_project_id": None,
            "pending_contract": None,
            "expected_next_user_act": None,
            "blocker": None,
            "last_delivery_state": None,
            "last_delivery_summary": None,
            "last_user_query": None,
            "last_user_query_at_utc": None,
        }
    return {
        "workspace_id": str(continuity_head.workspace_id),
        "conversation_id": str(continuity_head.conversation_id),
        "active_project_id": str(continuity_head.active_project_id).strip()
        if str(continuity_head.active_project_id or "").strip()
        else None,
        "pending_contract": dict(continuity_head.pending_contract)
        if isinstance(continuity_head.pending_contract, dict)
        else None,
        "expected_next_user_act": (
            str(continuity_head.expected_next_user_act).strip()
            if include_recovery_context and str(continuity_head.expected_next_user_act or "").strip()
            else None
        ),
        "blocker": (
            dict(continuity_head.blocker)
            if include_recovery_context and isinstance(continuity_head.blocker, dict)
            else None
        ),
        "last_delivery_state": (
            str(continuity_head.last_delivery_state).strip()
            if include_recovery_context and str(continuity_head.last_delivery_state or "").strip()
            else None
        ),
        "last_delivery_summary": (
            str(continuity_head.last_delivery_summary).strip()
            if include_recovery_context and str(continuity_head.last_delivery_summary or "").strip()
            else None
        ),
        "last_user_query": (
            str(continuity_head.last_user_query).strip()
            if include_recovery_context and str(continuity_head.last_user_query or "").strip()
            else None
        ),
        "last_user_query_at_utc": (
            str(continuity_head.last_user_query_at_utc).strip()
            if include_recovery_context and str(continuity_head.last_user_query_at_utc or "").strip()
            else None
        ),
    }


def build_memory_context_for_event(
    *,
    config: PAMemoryPipelineConfig,
    data_dir: Path,
    workspace_id: str,
    conversation_id: str = "",
    trace_id: str,
    turn_id: str,
    user_message: str,
    project_id: str | None = None,
    policy_context_passthrough: Optional[dict[str, Any]] = None,
    replay_mode: bool = False,
) -> PAMemoryPipelineResult:
    if not bool(config.enabled):
        return PAMemoryPipelineResult(ok=True, error_code=None, memory_context=None, evidence_refs=())
    workspace_text = str(workspace_id or "").strip()
    if not workspace_text:
        return PAMemoryPipelineResult(ok=False, error_code=PA_MEM_ERROR_SCHEMA_INVALID)
    retrieval_limit = int(config.retrieval_limit or 0)
    if retrieval_limit <= 0:
        return PAMemoryPipelineResult(ok=False, error_code=PA_MEM_ERROR_SCHEMA_INVALID)

    try:
        evidence = FileEvidenceStore(data_dir)
        memory_store = MemoryStoreV2(data_dir)
        retriever = MemoryRetrieverV2(memory_store)
        continuity_store = FileRuntimeSnapshotStore(data_dir)

        conversation_text = str(conversation_id or "").strip()
        continuity_head = (
            continuity_store.get(workspace_id=workspace_text, conversation_id=conversation_text)
            if conversation_text
            else None
        )
        resolved_project_id = _resolved_project_id(
            project_id=project_id,
            policy_context_passthrough=policy_context_passthrough,
            continuity_head=continuity_head,
        )
        intent = _infer_memory_intent(user_message)
        include_recovery_context = _should_include_recovery_context(
            intent=intent,
            user_message=user_message,
            continuity_head=continuity_head,
        )
        query_obj = MemoryQueryV2(
            schema_version=MEMORY_V2_SCHEMA_VERSION,
            query=str(user_message or ""),
            intent=intent,
            scope=MemoryScopeV2(
                schema_version=MEMORY_V2_SCHEMA_VERSION,
                workspace_id=workspace_text,
                conversation_id=conversation_text or None,
                project_id=resolved_project_id,
            ),
            kinds=_intent_kinds(intent),
            limit=retrieval_limit,
            include_stale=bool(config.include_stale),
            include_deleted=bool(config.audit_mode and replay_mode),
        )
        hits, conflicts = retriever.search(query=query_obj)
        hits = _filter_hits(
            hits=hits,
            user_message=user_message,
            include_recovery_context=include_recovery_context,
        )
        recent_events = (
            continuity_store.list_events(
                workspace_id=workspace_text,
                conversation_id=conversation_text,
                limit=int(config.continuity_event_limit or 50),
            )
            if conversation_text
            else []
        )
        retrieval_ref = evidence.add_json(
            {
                "schema_version": MEMORY_V2_SCHEMA_VERSION,
                "type": "memory_retrieval_v2",
                "workspace_id": workspace_text,
                "conversation_id": conversation_text or None,
                "trace_id": str(trace_id),
                "turn_id": str(turn_id),
                "replay_mode": bool(replay_mode),
                "l1_query": query_obj.to_json(),
                "selected_hits": [hit.to_json() for hit in hits],
                "conflicts": [conflict.to_json() for conflict in conflicts],
                "continuity_event_ids": [event.event_id for event in recent_events],
            },
            kind="routing",
        )
        context = MemoryContextV2(
            schema_version=MEMORY_V2_SCHEMA_VERSION,
            l0_continuity=_continuity_payload(
                workspace_id=workspace_text,
                conversation_id=conversation_text,
                continuity_head=continuity_head,
                include_recovery_context=include_recovery_context,
            ),
            l1_query=query_obj.to_json(),
            l2_hits=tuple(hits),
            conflicts=tuple(conflicts),
            retrieval_ref=retrieval_ref.ref,
        )
        context_ref = evidence.add_json(
            {
                "schema_version": MEMORY_V2_SCHEMA_VERSION,
                "type": "memory_context_v2",
                "workspace_id": workspace_text,
                "conversation_id": conversation_text or None,
                "trace_id": str(trace_id),
                "turn_id": str(turn_id),
                "memory_context": context.to_json(),
            },
            kind="context_routing",
        )
        return PAMemoryPipelineResult(
            ok=True,
            error_code=None,
            memory_context=context.to_json(),
            evidence_refs=tuple(
                dict.fromkeys(
                    [
                        context_ref.ref,
                        retrieval_ref.ref,
                        *(hit.evidence_ref for hit in hits),
                    ]
                )
            ),
        )
    except Exception:
        return PAMemoryPipelineResult(ok=False, error_code=PA_MEM_ERROR_COMPILE_FAILED)
