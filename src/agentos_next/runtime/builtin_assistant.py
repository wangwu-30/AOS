from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from agentos_next.kernel.evidence_store import FileEvidenceStore
from agentos_next.kernel.executor import ExecuteRequest, ExecuteResult, ExecuteTiming
from agentos_next.kernel.trace_logger import FileTraceLogger
from agentos_next.kernel.types import EvidenceRef, TraceEvent


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class BuiltinDispatchResult:
    handled: bool
    result: Optional[ExecuteResult] = None


def maybe_execute_builtin_assistant(*, req: ExecuteRequest, data_dir: str) -> BuiltinDispatchResult:
    """Handle builtin://assistant.* skills."""
    if not req.operator_ref.startswith("builtin://"):
        return BuiltinDispatchResult(handled=False)

    name = req.operator_ref[len("builtin://") :].strip("/")
    if not name.startswith("assistant."):
        return BuiltinDispatchResult(handled=False)

    evidence = FileEvidenceStore(data_dir=data_dir)
    trace = FileTraceLogger(data_dir=data_dir)

    started_at = _utc_iso()
    evidence_refs: list[EvidenceRef] = []

    def _emit(event_type: str, *, ers: tuple[EvidenceRef, ...] = (), data: Optional[dict[str, Any]] = None) -> None:
        trace.emit(
            TraceEvent(
                schema_version="1.0.0",
                ctx=req.trace,
                event_type=event_type,  # type: ignore[arg-type]
                ts=_utc_iso(),
                evidence_refs=ers,
                data=data,
            )
        )

    _emit("TOOL_CALL_STARTED", data={"builtin": name})

    try:
        if name != "assistant.submit":
            raise ValueError(f"unknown builtin: {name}")
        out_ref, nested_refs, runtime_error = _assistant_submit(
            req=req,
            evidence=evidence,
            data_dir=data_dir,
            evidence_refs=evidence_refs,
        )
        evidence_refs.append(out_ref)
        evidence_refs.extend(nested_refs)
        status = "accepted" if runtime_error is None else "failed"
        error_code = runtime_error
    except ValueError as e:
        err_ref = evidence.add_json(
            {"schema_version": "1.0.0", "ok": False, "error_code": "E_INPUT_SCHEMA", "message": str(e)},
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

    _emit("TOOL_CALL_FINISHED", ers=(out_ref,), data={"builtin": name, "ok": runtime_error is None})
    ended_at = _utc_iso()
    return BuiltinDispatchResult(
        handled=True,
        result=ExecuteResult(
            status=status,
            evidence_refs=tuple(evidence_refs),
            artifact_refs=(),
            error_code=error_code,
            timing=ExecuteTiming(started_at=started_at, ended_at=ended_at),
            target="local",
        ),
    )


def _assistant_submit(
    *,
    req: ExecuteRequest,
    evidence: FileEvidenceStore,
    data_dir: str,
    evidence_refs: list[EvidenceRef],
) -> tuple[EvidenceRef, list[EvidenceRef], Optional[str]]:
    from agentos_next.apps.assistant_loop import AssistantLoopRequest
    from agentos_next.apps.assistant_runtime import run_assistant_runtime_async
    from agentos_next.apps.canonical_task_ingress import build_canonical_task_ingress_request
    from agentos_next.kernel.effective_runtime_capabilities import (
        capability_names_from_effective_runtime_capabilities,
    )

    inp = _require_dict(req.arguments, name="arguments")
    query = _require_str(inp.get("query"), name="query", max_bytes=32768)
    submitter = str(inp.get("submitter") or "builtin://assistant.submit").strip() or "builtin://assistant.submit"
    consumer = str(inp.get("consumer") or "execute_result").strip() or "execute_result"
    runtime_mode = str(inp.get("runtime_mode") or "hybrid").strip().lower()
    if runtime_mode not in {"direct", "hybrid"}:
        runtime_mode = "hybrid"
    direct_fallback = _as_bool(inp.get("direct_fallback"), default=True)

    assistant_skill_dir = _optional_path(inp.get("assistant_skill_dir"))
    loop_req = AssistantLoopRequest(
        query=query,
        assistant_skill_dir=assistant_skill_dir,
        workspace_id=req.workspace_id,
        data_dir=data_dir,
        trace=req.trace,
        idempotency_key=req.idempotency_key,
        deadline_ms=int(req.deadline_ms),
        verify_asvp=_as_bool(req.policy_context.get("verify_asvp"), default=True),
        public_keys_dir=_optional_path(req.policy_context.get("public_keys_dir")),
        backend=str(req.policy_context.get("backend") or "local_mock"),
        planner=str(req.policy_context.get("planner") or "deterministic"),
        planner_backend=(
            str(req.policy_context.get("planner_backend")).strip()
            if isinstance(req.policy_context.get("planner_backend"), str) and str(req.policy_context.get("planner_backend")).strip()
            else None
        ),
        model=(str(req.policy_context.get("model")).strip() if req.policy_context.get("model") else None),
        intent_backend=(
            str(req.policy_context.get("intent_backend")).strip()
            if isinstance(req.policy_context.get("intent_backend"), str) and str(req.policy_context.get("intent_backend")).strip()
            else None
        ),
        intent_model=(
            str(req.policy_context.get("intent_model")).strip()
            if isinstance(req.policy_context.get("intent_model"), str) and str(req.policy_context.get("intent_model")).strip()
            else None
        ),
        communicator_backend=(
            str(req.policy_context.get("communicator_backend")).strip()
            if isinstance(req.policy_context.get("communicator_backend"), str)
            and str(req.policy_context.get("communicator_backend")).strip()
            else None
        ),
        communicator_model=(
            str(req.policy_context.get("communicator_model")).strip()
            if isinstance(req.policy_context.get("communicator_model"), str)
            and str(req.policy_context.get("communicator_model")).strip()
            else None
        ),
        response_language=(
            str(req.policy_context.get("response_language")).strip()
            if isinstance(req.policy_context.get("response_language"), str)
            and str(req.policy_context.get("response_language")).strip()
            else None
        ),
        remote_calls_armed=_as_bool(req.policy_context.get("remote_calls_armed"), default=False),
        allow_network_egress=_as_bool(req.policy_context.get("allow_network_egress"), default=False),
        approved_by_human=_as_bool(req.policy_context.get("approved_by_human"), default=False),
        replay_mode=_as_bool(req.policy_context.get("replay_mode"), default=False),
        capabilities=(
            ",".join(capability_names_from_effective_runtime_capabilities(req.policy_context.get("effective_runtime_capabilities")))
            or _capabilities_csv(req.policy_context.get("capabilities"))
        ),
        effective_runtime_capabilities=(
            dict(req.policy_context.get("effective_runtime_capabilities") or {})
            if isinstance(req.policy_context.get("effective_runtime_capabilities"), dict)
            else None
        ),
        followup_at=(str(inp.get("followup_at")).strip() if inp.get("followup_at") else None),
        message_received_at_utc=(
            str(inp.get("message_received_at_utc")).strip() if inp.get("message_received_at_utc") else None
        ),
        agent_id=(str(inp.get("agent_id")).strip() if inp.get("agent_id") else "assistant_loop"),
    )
    ingress = build_canonical_task_ingress_request(
        loop_req,
        submitter=submitter,
        consumer=consumer,
        raw_input=query,
        metadata=_opt_dict(inp.get("metadata")),
    )
    res = asyncio.run(
        run_assistant_runtime_async(
            ingress,
            runtime_mode=runtime_mode,  # type: ignore[arg-type]
            direct_fallback=direct_fallback,
        )
    )

    nested_refs: list[EvidenceRef] = []
    for ref in list(res.evidence_refs):
        blob = evidence.get_blob(str(ref))
        if blob is not None:
            nested_refs.append(blob.to_ref())

    out_ref = evidence.add_json(
        {
            "schema_version": "1.0.0",
            "ok": bool(res.ok),
            "error_code": res.error_code,
            "trace_id": res.trace.trace_id,
            "turn_id": res.trace.turn_id,
            "span_id": res.trace.span_id,
            "submitter": submitter,
            "consumer": consumer,
            "followup_plan_ref": res.followup_plan_ref,
            "followup_task_id": res.followup_task_id,
            "final_output": res.final_output,
            "evidence_refs": list(res.evidence_refs),
        },
        kind="tool_io",
    )
    return out_ref, nested_refs, res.error_code


def _require_dict(obj: Any, *, name: str) -> dict[str, Any]:
    if not isinstance(obj, dict):
        raise ValueError(f"{name} must be a JSON object")
    return obj


def _require_str(obj: Any, *, name: str, max_bytes: Optional[int] = None) -> str:
    if not isinstance(obj, str):
        raise ValueError(f"{name} must be a string")
    s = obj.strip()
    if not s:
        raise ValueError(f"{name} must be non-empty")
    if max_bytes is not None and len(s.encode("utf-8")) > max_bytes:
        raise ValueError(f"{name} exceeds max_bytes={max_bytes}")
    return s


def _optional_path(value: Any) -> Path | None:
    if value is None:
        return None
    if isinstance(value, Path):
        return value
    if isinstance(value, str) and value.strip():
        return Path(value).expanduser().resolve()
    return None


def _as_bool(value: Any, *, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        s = value.strip().lower()
        if s in {"1", "true", "yes", "on"}:
            return True
        if s in {"0", "false", "no", "off", ""}:
            return False
        return default
    return bool(value)


def _opt_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    return {}


def _capabilities_csv(value: Any) -> Optional[str]:
    if isinstance(value, str):
        out = ",".join(x.strip() for x in value.split(",") if x.strip())
        return out or None
    if isinstance(value, list):
        names: list[str] = []
        for item in value:
            if isinstance(item, str) and item.strip():
                names.append(item.strip())
            elif isinstance(item, dict):
                name = item.get("name")
                if isinstance(name, str) and name.strip():
                    names.append(name.strip())
        out = ",".join(sorted(dict.fromkeys(names)))
        return out or None
    return None
