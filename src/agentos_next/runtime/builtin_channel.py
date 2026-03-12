from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from agentos_next.kernel.evidence_store import FileEvidenceStore
from agentos_next.kernel.executor import ExecuteRequest, ExecuteResult, ExecuteTiming
from agentos_next.kernel.trace_logger import FileTraceLogger
from agentos_next.kernel.types import EvidenceRef, TraceEvent


@dataclass(frozen=True)
class BuiltinDispatchResult:
    handled: bool
    result: Optional[ExecuteResult] = None


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def maybe_execute_builtin_channel(*, req: ExecuteRequest, data_dir: str) -> BuiltinDispatchResult:
    if not req.operator_ref.startswith("builtin://channel."):
        return BuiltinDispatchResult(handled=False)

    name = req.operator_ref[len("builtin://") :].strip("/")
    evidence = FileEvidenceStore(data_dir=data_dir)
    trace = FileTraceLogger(data_dir=data_dir)
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
        if name != "channel.send_message":
            raise ValueError(f"unknown builtin: {name}")
        inp = dict(req.arguments or {})
        text = str(inp.get("text") or inp.get("message") or inp.get("reply") or "").strip()
        if not text:
            raise ValueError("text is required")
        delivery_stage = str(inp.get("delivery_stage") or "final").strip() or "final"
        if delivery_stage not in {"progress", "blocker", "need_context", "final"}:
            raise ValueError("delivery_stage must be one of progress|blocker|need_context|final")
        update_preference = str(inp.get("update_preference") or "prefer_update").strip() or "prefer_update"
        if update_preference not in {"prefer_update", "new_message"}:
            raise ValueError("update_preference must be prefer_update or new_message")
        message_key = str(inp.get("message_key") or "").strip()
        out_ref = evidence.add_json(
            {
                "schema_version": "1.0.0",
                "ok": True,
                "operator_ref": "builtin://channel.send_message",
                "channel": str(inp.get("channel") or "runtime").strip() or "runtime",
                "audience": str(inp.get("audience") or "user").strip() or "user",
                "delivery_kind": str(inp.get("delivery_kind") or "user_visible_answer").strip() or "user_visible_answer",
                "text": text,
                "message_key": message_key or None,
                "delivery_stage": delivery_stage,
                "update_preference": update_preference,
                "delivery_mode": "update" if update_preference == "prefer_update" and message_key else "create",
                "channel_message_id": (
                    str(inp.get("channel_message_id") or "").strip() or None
                ),
                "metadata": dict(inp.get("metadata") or {}) if isinstance(inp.get("metadata"), dict) else {},
            },
            kind="tool_io",
        )
        evidence_refs.append(out_ref)
    except Exception as e:
        err_ref = evidence.add_json(
            {"schema_version": "1.0.0", "ok": False, "error_code": "E_EXECUTION_FAILED", "message": str(e)},
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
