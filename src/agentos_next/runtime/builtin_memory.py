from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from agentos_next.kernel.evidence_store import FileEvidenceStore
from agentos_next.kernel.executor import ExecuteRequest, ExecuteResult, ExecuteTiming
from agentos_next.kernel.memory_store import (
    MEMORY_INTENT_SET,
    MEMORY_RECORD_KIND_SET,
    MEMORY_SOURCE_SET,
    MEMORY_V2_SCHEMA_VERSION,
    MemoryQueryV2,
    MemoryRetrieverV2,
    MemoryScopeV2,
    MemoryStoreV2,
)
from agentos_next.kernel.trace_logger import FileTraceLogger
from agentos_next.kernel.types import EvidenceRef, TraceEvent

LEGACY_MEMORY_SOURCE_MAP = {
    "legacy_import": "system_consolidated",
}


@dataclass(frozen=True)
class BuiltinDispatchResult:
    handled: bool
    result: Optional[ExecuteResult] = None


def _utc_iso(dt: datetime | None = None) -> str:
    value = dt or datetime.now(timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _build_structured_error_payload(
    *,
    operator_ref: str,
    error_code: str,
    message: str,
    payload: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    out = {
        "schema_version": MEMORY_V2_SCHEMA_VERSION,
        "ok": False,
        "error_code": str(error_code or "E_EXECUTION_FAILED").strip() or "E_EXECUTION_FAILED",
        "message": str(message or "").strip(),
        "operator_ref": str(operator_ref or "").strip(),
    }
    if isinstance(payload, dict):
        for key, value in payload.items():
            if key in out:
                continue
            out[key] = value
    return out


def _require_dict(obj: Any, *, name: str) -> dict[str, Any]:
    if not isinstance(obj, dict):
        raise ValueError(f"{name} must be a JSON object")
    return obj


def _require_str(obj: Any, *, name: str, nonempty: bool = True) -> str:
    if not isinstance(obj, str):
        raise ValueError(f"{name} must be a string")
    text = str(obj)
    if nonempty and not text.strip():
        raise ValueError(f"{name} must be non-empty")
    return text


def _opt_str(obj: Any) -> Optional[str]:
    text = str(obj or "").strip()
    return text or None


def _memory_key_from_content(*, workspace_id: str, content: str) -> str:
    digest = hashlib.sha256(f"{workspace_id}|{content}".encode("utf-8")).hexdigest()[:16]
    return f"legacy.note.{digest}"


def _normalize_memory_source(source: Optional[str]) -> str:
    raw = str(source or "").strip()
    if not raw:
        return "user_explicit"
    return LEGACY_MEMORY_SOURCE_MAP.get(raw, raw)


def _coerce_memory_write_record_input(*, req: ExecuteRequest) -> dict[str, Any]:
    arguments = _require_dict(req.arguments, name="arguments")
    record_input = arguments.get("record")
    if isinstance(record_input, dict):
        normalized = dict(record_input)
        if not isinstance(normalized.get("scope"), dict):
            normalized["scope"] = {"workspace_id": str(req.workspace_id)}
        if "source" not in normalized:
            normalized["source"] = "user_explicit"
        if not isinstance(normalized.get("payload"), dict):
            fallback = (
                _opt_str(normalized.get("content"))
                or _opt_str(normalized.get("text"))
                or _opt_str(normalized.get("statement"))
                or _opt_str(normalized.get("summary"))
                or ""
            )
            normalized["payload"] = {"statement": fallback} if fallback else {}
        if not str(normalized.get("memory_key") or "").strip():
            seed = _opt_str(normalized.get("summary")) or _opt_str(normalized.get("statement")) or "memory"
            normalized["memory_key"] = _memory_key_from_content(
                workspace_id=str(req.workspace_id),
                content=seed,
            )
        return normalized

    content = (
        _opt_str(arguments.get("content"))
        or _opt_str(arguments.get("text"))
        or _opt_str(arguments.get("statement"))
    )
    if not content:
        raise ValueError("record must be present or content must be non-empty")
    tags = arguments.get("tags") if isinstance(arguments.get("tags"), list) else []
    return {
        "kind": "note",
        "summary": content[:160],
        "payload": {"statement": content},
        "memory_key": _opt_str(arguments.get("memory_key"))
        or _memory_key_from_content(workspace_id=str(req.workspace_id), content=content),
        "scope": {"workspace_id": str(req.workspace_id)},
        "source": "user_explicit",
        "tags": list(tags),
        "ttl_seconds": _opt_int(arguments.get("ttl_seconds"), default=0),
    }


def _opt_bool(obj: Any, *, default: bool = False) -> bool:
    if obj is None:
        return bool(default)
    if isinstance(obj, bool):
        return obj
    raise ValueError("boolean field must be true or false")


def _opt_int(obj: Any, *, default: int = 0) -> int:
    if obj is None:
        return int(default)
    try:
        return int(obj)
    except Exception as exc:
        raise ValueError("integer field must be an integer") from exc


def _opt_str_list(obj: Any, *, field_name: str) -> tuple[str, ...]:
    if obj is None:
        return ()
    if not isinstance(obj, list):
        raise ValueError(f"{field_name} must be an array of strings")
    out: list[str] = []
    seen: set[str] = set()
    for item in obj:
        if not isinstance(item, str):
            raise ValueError(f"{field_name} must be an array of strings")
        text = item.strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return tuple(out)


def _require_scope(obj: Any, *, req_workspace_id: str) -> MemoryScopeV2:
    scope = MemoryScopeV2.from_json(obj or {}, default_workspace_id="")
    if str(scope.workspace_id) != str(req_workspace_id):
        raise ValueError("scope.workspace_id must match ExecuteRequest.workspace_id")
    return scope


def maybe_execute_builtin_memory(*, req: ExecuteRequest, data_dir: str) -> BuiltinDispatchResult:
    if not req.operator_ref.startswith("builtin://"):
        return BuiltinDispatchResult(handled=False)
    name = req.operator_ref[len("builtin://") :].strip("/")
    if not name.startswith("memory."):
        return BuiltinDispatchResult(handled=False)

    evidence = FileEvidenceStore(data_dir=data_dir)
    trace = FileTraceLogger(data_dir=data_dir)
    store = MemoryStoreV2(data_dir=data_dir)
    retriever = MemoryRetrieverV2(store)
    started_at = _utc_iso()
    evidence_refs: list[EvidenceRef] = []

    def _emit(event_type: str, *, ers: tuple[EvidenceRef, ...] = (), data: Optional[dict[str, Any]] = None) -> None:
        trace.emit(
            TraceEvent(
                schema_version="1.0.0",
                ctx=req.trace,
                event_type=event_type,
                ts=_utc_iso(),
                evidence_refs=ers,
                data=data,
            )
        )

    _emit("TOOL_CALL_STARTED", data={"builtin": name})
    try:
        if name == "memory.write":
            _memory_write(req=req, evidence=evidence, store=store, evidence_refs=evidence_refs)
        elif name == "memory.search":
            _memory_search(req=req, evidence=evidence, trace=trace, retriever=retriever, evidence_refs=evidence_refs)
        elif name == "memory.delete":
            _memory_delete(req=req, evidence=evidence, store=store, evidence_refs=evidence_refs)
        elif name == "memory.compact":
            _memory_compact(req=req, evidence=evidence, store=store, evidence_refs=evidence_refs)
        else:
            raise ValueError(f"unknown builtin: {name}")
    except ValueError as exc:
        err_ref = evidence.add_json(
            _build_structured_error_payload(
                operator_ref=req.operator_ref,
                error_code="E_INPUT_SCHEMA",
                message=str(exc),
            ),
            kind="error",
        )
        evidence_refs.append(err_ref)
        _emit("ERROR", ers=(err_ref,), data={"builtin": name, "error_code": "E_INPUT_SCHEMA"})
        ended_at = _utc_iso()
        return BuiltinDispatchResult(
            handled=True,
            result=ExecuteResult(
                status="rejected",
                evidence_refs=tuple(evidence_refs),
                artifact_refs=(),
                error_code="E_INPUT_SCHEMA",
                timing=ExecuteTiming(started_at=started_at, ended_at=ended_at),
                target="local",
            ),
        )
    except Exception as exc:
        err_ref = evidence.add_json(
            _build_structured_error_payload(
                operator_ref=req.operator_ref,
                error_code="E_EXECUTION_FAILED",
                message=str(exc),
            ),
            kind="error",
        )
        evidence_refs.append(err_ref)
        _emit("ERROR", ers=(err_ref,), data={"builtin": name, "error_code": "E_EXECUTION_FAILED"})
        ended_at = _utc_iso()
        return BuiltinDispatchResult(
            handled=True,
            result=ExecuteResult(
                status="failed",
                evidence_refs=tuple(evidence_refs),
                artifact_refs=(),
                error_code="E_EXECUTION_FAILED",
                timing=ExecuteTiming(started_at=started_at, ended_at=ended_at),
                target="local",
            ),
        )

    _emit("TOOL_CALL_FINISHED", data={"builtin": name, "ok": True})
    ended_at = _utc_iso()
    return BuiltinDispatchResult(
        handled=True,
        result=ExecuteResult(
            status="accepted",
            evidence_refs=tuple(evidence_refs),
            artifact_refs=(),
            error_code=None,
            timing=ExecuteTiming(started_at=started_at, ended_at=ended_at),
            target="local",
        ),
    )


def _memory_write(
    *,
    req: ExecuteRequest,
    evidence: FileEvidenceStore,
    store: MemoryStoreV2,
    evidence_refs: list[EvidenceRef],
) -> None:
    record_input = _coerce_memory_write_record_input(req=req)
    kind = _require_str(record_input.get("kind"), name="record.kind")
    if kind not in MEMORY_RECORD_KIND_SET:
        raise ValueError(f"record.kind must be one of {sorted(MEMORY_RECORD_KIND_SET)}")
    summary = _require_str(record_input.get("summary"), name="record.summary")
    memory_key = _require_str(record_input.get("memory_key"), name="record.memory_key")
    scope = _require_scope(record_input.get("scope"), req_workspace_id=str(req.workspace_id))
    source = _normalize_memory_source(_require_str(record_input.get("source"), name="record.source"))
    if source not in MEMORY_SOURCE_SET:
        raise ValueError(f"record.source must be one of {sorted(MEMORY_SOURCE_SET)}")
    record = store.create_record(
        evidence=evidence,
        kind=kind,
        summary=summary,
        payload=_require_dict(record_input.get("payload"), name="record.payload"),
        memory_key=memory_key,
        scope=scope,
        source=source,
        tags=_opt_str_list(record_input.get("tags"), field_name="record.tags"),
        ttl_seconds=_opt_int(record_input.get("ttl_seconds"), default=0),
        supersedes_refs=_opt_str_list(record_input.get("supersedes_refs"), field_name="record.supersedes_refs"),
    )
    record_blob = evidence.get_blob(record.evidence_ref)
    if record_blob is not None:
        evidence_refs.append(record_blob.to_ref())
    out_ref = evidence.add_json(
        {
            "schema_version": MEMORY_V2_SCHEMA_VERSION,
            "ok": True,
            "operator_ref": req.operator_ref,
            "record_id": record.record_id,
            "evidence_ref": record.evidence_ref,
            "indexed": True,
            "evidence_refs": [record.evidence_ref],
        },
        kind="tool_io",
    )
    evidence_refs.extend([out_ref])


def _memory_search(
    *,
    req: ExecuteRequest,
    evidence: FileEvidenceStore,
    trace: FileTraceLogger,
    retriever: MemoryRetrieverV2,
    evidence_refs: list[EvidenceRef],
) -> None:
    arguments = _require_dict(req.arguments, name="arguments")
    intent = _require_str(arguments.get("intent"), name="intent")
    if intent not in MEMORY_INTENT_SET:
        raise ValueError(f"intent must be one of {sorted(MEMORY_INTENT_SET)}")
    query = MemoryQueryV2(
        schema_version=MEMORY_V2_SCHEMA_VERSION,
        query=_require_str(arguments.get("query"), name="query"),
        intent=intent,
        scope=_require_scope(arguments.get("scope"), req_workspace_id=str(req.workspace_id)),
        kinds=_opt_str_list(arguments.get("kinds"), field_name="kinds"),
        limit=_opt_int(arguments.get("limit"), default=5),
        include_stale=_opt_bool(arguments.get("include_stale"), default=False),
        include_deleted=_opt_bool(arguments.get("include_deleted"), default=False),
    )
    if query.limit <= 0 or query.limit > 200:
        raise ValueError("limit must be in [1, 200]")
    hits, conflicts = retriever.search(query=query)
    retrieval_ref = evidence.add_json(
        {
            "schema_version": MEMORY_V2_SCHEMA_VERSION,
            "type": "memory_retrieval_v2",
            "operator_ref": req.operator_ref,
            "query": query.to_json(),
            "selected_hits": [hit.to_json() for hit in hits],
            "conflicts": [conflict.to_json() for conflict in conflicts],
        },
        kind="routing",
    )
    evidence_refs.append(retrieval_ref)
    trace.emit(
        TraceEvent(
            schema_version="1.0.0",
            ctx=req.trace,
            event_type="RETRIEVAL_CHAIN",
            ts=_utc_iso(),
            evidence_refs=(retrieval_ref,),
            data={"builtin": "memory.search", "schema_version": MEMORY_V2_SCHEMA_VERSION},
        )
    )
    out_ref = evidence.add_json(
        {
            "schema_version": MEMORY_V2_SCHEMA_VERSION,
            "ok": True,
            "operator_ref": req.operator_ref,
            "results": [hit.to_json() for hit in hits],
            "conflicts": [conflict.to_json() for conflict in conflicts],
            "retrieval_trace_ref": retrieval_ref.ref,
            "evidence_refs": [retrieval_ref.ref, *[hit.evidence_ref for hit in hits]],
        },
        kind="tool_io",
    )
    evidence_refs.append(out_ref)


def _memory_delete(
    *,
    req: ExecuteRequest,
    evidence: FileEvidenceStore,
    store: MemoryStoreV2,
    evidence_refs: list[EvidenceRef],
) -> None:
    arguments = _require_dict(req.arguments, name="arguments")
    record_ids = _opt_str_list(arguments.get("record_ids"), field_name="record_ids")
    if not record_ids:
        raise ValueError("record_ids must contain at least one record id")
    deleted: list[str] = []
    for record_id in record_ids:
        record = store.get_record(record_id=record_id)
        if record is None:
            raise ValueError(f"record_id not found: {record_id}")
        if str(record.scope.workspace_id) != str(req.workspace_id):
            raise ValueError("record_ids must belong to ExecuteRequest.workspace_id")
        store.mark_deleted(record_id=record_id)
        deleted.append(record_id)
    tombstone_ref = evidence.add_json(
        {
            "schema_version": MEMORY_V2_SCHEMA_VERSION,
            "type": "memory_delete_v2",
            "operator_ref": req.operator_ref,
            "deleted_record_ids": deleted,
            "deleted_at_utc": _utc_iso(),
        },
        kind="policy",
    )
    evidence_refs.append(tombstone_ref)
    out_ref = evidence.add_json(
        {
            "schema_version": MEMORY_V2_SCHEMA_VERSION,
            "ok": True,
            "operator_ref": req.operator_ref,
            "deleted_record_ids": deleted,
            "evidence_refs": [tombstone_ref.ref],
        },
        kind="tool_io",
    )
    evidence_refs.append(out_ref)


def _memory_compact(
    *,
    req: ExecuteRequest,
    evidence: FileEvidenceStore,
    store: MemoryStoreV2,
    evidence_refs: list[EvidenceRef],
) -> None:
    arguments = _require_dict(req.arguments, name="arguments")
    memory_key = _require_str(arguments.get("memory_key"), name="memory_key")
    scope = _require_scope(arguments.get("scope"), req_workspace_id=str(req.workspace_id))
    winner_input = _require_dict(arguments.get("winner"), name="winner")
    winner_kind = _require_str(winner_input.get("kind"), name="winner.kind")
    if winner_kind not in MEMORY_RECORD_KIND_SET:
        raise ValueError(f"winner.kind must be one of {sorted(MEMORY_RECORD_KIND_SET)}")
    winner_source = _require_str(winner_input.get("source"), name="winner.source")
    if winner_source not in MEMORY_SOURCE_SET:
        raise ValueError(f"winner.source must be one of {sorted(MEMORY_SOURCE_SET)}")
    active_records = [
        record
        for record in store.list_by_memory_key(memory_key=memory_key)
        if record.scope.to_json() == scope.to_json() and not record.deleted_at_utc and not record.superseded_by
    ]
    if not active_records:
        raise ValueError("memory.compact requires at least one active source record in the same scope")
    winner = store.create_record(
        evidence=evidence,
        kind=winner_kind,
        summary=_require_str(winner_input.get("summary"), name="winner.summary"),
        payload=winner_input.get("payload"),
        memory_key=memory_key,
        scope=scope,
        source=winner_source,
        tags=_opt_str_list(winner_input.get("tags"), field_name="winner.tags"),
        ttl_seconds=_opt_int(winner_input.get("ttl_seconds"), default=0),
        supersedes_refs=[record.record_id for record in active_records],
    )
    winner_blob = evidence.get_blob(winner.evidence_ref)
    if winner_blob is not None:
        evidence_refs.append(winner_blob.to_ref())
    compact_ref = evidence.add_json(
        {
            "schema_version": MEMORY_V2_SCHEMA_VERSION,
            "type": "memory_compaction_v2",
            "operator_ref": req.operator_ref,
            "memory_key": memory_key,
            "scope": scope.to_json(),
            "winner_record_id": winner.record_id,
            "superseded_record_ids": [record.record_id for record in active_records],
        },
        kind="policy",
    )
    evidence_refs.append(compact_ref)
    out_ref = evidence.add_json(
        {
            "schema_version": MEMORY_V2_SCHEMA_VERSION,
            "ok": True,
            "operator_ref": req.operator_ref,
            "winner_record_id": winner.record_id,
            "winner_evidence_ref": winner.evidence_ref,
            "superseded_record_ids": [record.record_id for record in active_records],
            "evidence_refs": [winner.evidence_ref, compact_ref.ref],
        },
        kind="tool_io",
    )
    evidence_refs.append(out_ref)
