from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional
from uuid import uuid4

from agentos_next.kernel.evidence_store import FileEvidenceStore
from agentos_next.kernel.executor import ExecuteRequest, ExecuteResult
from agentos_next.kernel.orchestrator import Orchestrator
from agentos_next.kernel.types import TraceContext
from agentos_next.runtime.local_executor import LocalExecutor


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


def _parse_json(text: str) -> Optional[Any]:
    try:
        return json.loads(text)
    except Exception:
        return None


def _read_json_evidence(data_dir: str | Path, ref: str) -> Optional[dict[str, Any]]:
    store = FileEvidenceStore(data_dir=str(data_dir))
    blob = store.get_blob(ref)
    if blob is None:
        return None
    if "json" not in str(blob.content_type):
        return None
    obj = _parse_json(blob.content.decode("utf-8", errors="replace"))
    if not isinstance(obj, dict):
        return None
    return obj


def _extract_reason_from_evidence(data_dir: str | Path, evidence_refs: list[str]) -> tuple[str, str]:
    # Best-effort: scan policy evidence for reason_code / error_code.
    for ref in reversed(evidence_refs):
        obj = _read_json_evidence(data_dir, ref)
        if not obj:
            continue
        if "reason_code" in obj:
            rc = str(obj.get("reason_code") or "").strip() or "unknown"
            ec = str(obj.get("error_code") or "").strip()
            msg = ec if ec else rc
            return rc, msg
    return "unknown", "unknown"


def _extract_user_facing_message(data_dir: str | Path, evidence_refs: list[str]) -> str:
    # Best-effort: find the last llm_io output blob and display its reply-like field.
    store = FileEvidenceStore(data_dir=str(data_dir))
    for ref in reversed(evidence_refs):
        blob = store.get_blob(ref)
        if blob is None:
            continue
        if "json" not in str(blob.content_type):
            continue
        obj = _parse_json(blob.content.decode("utf-8", errors="replace"))
        if not isinstance(obj, dict):
            continue
        output = obj.get("output")
        if not isinstance(output, dict):
            continue
        for k in ("reply", "text", "message", "result"):
            v = output.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()
        # Fallback: stringify bounded output.
        try:
            s = json.dumps(output, ensure_ascii=False, sort_keys=True)
        except Exception:
            s = str(output)
        if len(s) > 800:
            s = s[:800] + "..."
        return s
    return ""


@dataclass(frozen=True)
class UI1RunOnceRequest:
    message: str
    operator_ref: str
    workspace_id: str
    data_dir: str
    keys_dir: Optional[str]
    verify_asvp: bool
    backend: str
    model: Optional[str]
    preferred_target: str
    deadline_ms: int
    remote_calls_armed: bool
    allow_network_egress: bool
    approved_by_human: bool
    replay_mode: bool
    trace_id: Optional[str] = None
    turn_id: Optional[str] = None
    span_id: Optional[str] = None
    parent_span_id: Optional[str] = None
    idempotency_key: Optional[str] = None


@dataclass(frozen=True)
class UI1Result:
    ok: bool
    status: str
    error_code: Optional[str]
    reason_code: str
    reason_message: str
    user_facing_message: str
    action: list[dict[str, Any]]
    evidence_refs: list[str]
    expires_at: Optional[str]
    trace_id: str
    turn_id: str
    span_id: str
    approval_id: Optional[str] = None

    def to_json(self) -> dict[str, Any]:
        return {
            "schema_version": "1.0.0",
            "type": "ui1_result",
            "ok": self.ok,
            "status": self.status,
            "error_code": self.error_code,
            "reason_code": self.reason_code,
            "reason_message": self.reason_message,
            "user_facing_message": self.user_facing_message,
            "action": list(self.action),
            "evidence_refs": list(self.evidence_refs),
            "expires_at": self.expires_at,
            "trace_id": self.trace_id,
            "turn_id": self.turn_id,
            "span_id": self.span_id,
            "approval_id": self.approval_id,
        }


class ApprovalStoreError(RuntimeError):
    pass


class ApprovalStore:
    """Append-only approval event log for UI1 (local-only).

    Layout (relative to data_dir):
    - ui/approvals.jsonl
    """

    def __init__(self, *, data_dir: str | Path) -> None:
        self._data_dir = Path(data_dir)
        self._path = self._data_dir / "ui" / "approvals.jsonl"

    def _append(self, obj: dict[str, Any]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
        with self._path.open("a", encoding="utf-8") as f:
            f.write(line)

    def create_pending(
        self,
        *,
        run_req: UI1RunOnceRequest,
        blocked_trace: TraceContext,
        blocked_evidence_refs: list[str],
        reason_code: str,
        reason_message: str,
        expires_at: str,
        approval_evidence_ref: Optional[str],
    ) -> str:
        approval_id = _new_id("ap")
        self._append(
            {
                "schema_version": "1.0.0",
                "type": "ui1_approval_event",
                "event": "created",
                "ts": _utc_iso(),
                "approval_id": approval_id,
                "status": "pending",
                "expires_at": expires_at,
                "reason_code": reason_code,
                "reason_message": reason_message,
                "blocked": {
                    "trace_id": blocked_trace.trace_id,
                    "turn_id": blocked_trace.turn_id,
                    "span_id": blocked_trace.span_id,
                    "evidence_refs": list(blocked_evidence_refs),
                    "approval_evidence_ref": approval_evidence_ref,
                },
                "request": {
                    "message": run_req.message,
                    "operator_ref": run_req.operator_ref,
                    "arguments": {"request": run_req.message},
                    "workspace_id": run_req.workspace_id,
                    "keys_dir": run_req.keys_dir,
                    "verify_asvp": bool(run_req.verify_asvp),
                    "backend": run_req.backend,
                    "model": run_req.model,
                    "preferred_target": run_req.preferred_target,
                    "deadline_ms": int(run_req.deadline_ms),
                    "remote_calls_armed": bool(run_req.remote_calls_armed),
                    "allow_network_egress": bool(run_req.allow_network_egress),
                    "idempotency_key": run_req.idempotency_key,
                },
            }
        )
        return approval_id

    def mark(self, *, approval_id: str, event: str, detail: dict[str, Any]) -> None:
        if event not in {"approved", "rejected"}:
            raise ValueError("invalid event")
        self._append(
            {
                "schema_version": "1.0.0",
                "type": "ui1_approval_event",
                "event": event,
                "ts": _utc_iso(),
                "approval_id": approval_id,
                **detail,
            }
        )

    def load_state(self) -> dict[str, dict[str, Any]]:
        if not self._path.exists():
            return {}
        out: dict[str, dict[str, Any]] = {}
        for raw in self._path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except Exception:
                continue
            if not isinstance(obj, dict):
                continue
            aid = obj.get("approval_id")
            if not isinstance(aid, str) or not aid.strip():
                continue
            out[aid] = obj
        return out


def ui1_run_once(req: UI1RunOnceRequest) -> UI1Result:
    # Stronger than kernel replay-mode: UI1 must be zero-write and must not execute.
    if bool(req.replay_mode):
        trace = TraceContext(
            trace_id=req.trace_id or _new_id("tr"),
            turn_id=req.turn_id or _new_id("turn"),
            span_id=req.span_id or _new_id("span"),
            parent_span_id=req.parent_span_id,
        )
        return UI1Result(
            ok=False,
            status="rejected",
            error_code="E_POLICY_DENY",
            reason_code="replay_mode_no_side_effects",
            reason_message="UI1 forbids execution and writes in replay-mode",
            user_facing_message="UI1 blocks execution and writes in replay-mode (zero-write).",
            action=[{"kind": "execute", "operator_ref": req.operator_ref}],
            evidence_refs=[],
            expires_at=None,
            trace_id=trace.trace_id,
            turn_id=trace.turn_id,
            span_id=trace.span_id,
            approval_id=None,
        )

    trace = TraceContext(
        trace_id=req.trace_id or _new_id("tr"),
        turn_id=req.turn_id or _new_id("turn"),
        span_id=req.span_id or _new_id("span"),
        parent_span_id=req.parent_span_id,
    )

    operator_ref = str(req.operator_ref).strip()
    arguments: dict[str, Any] = {"request": str(req.message)}
    idem = req.idempotency_key or _new_id("idem")

    ex_req = ExecuteRequest(
        workspace_id=str(req.workspace_id),
        operator_ref=operator_ref,
        arguments=arguments,
        idempotency_key=str(idem),
        deadline_ms=int(req.deadline_ms),
        trace=trace,
        policy_context={
            "verify_asvp": bool(req.verify_asvp),
            "public_keys_dir": req.keys_dir,
            "backend": str(req.backend),
            "model": req.model,
            "remote_calls_armed": bool(req.remote_calls_armed),
            "allow_network_egress": bool(req.allow_network_egress),
            "approved_by_human": bool(req.approved_by_human),
            "replay_mode": False,
        },
        preferred_target=str(req.preferred_target or "auto"),
    )

    local_exec = LocalExecutor.for_data_dir(req.data_dir)
    orch = Orchestrator.for_data_dir(req.data_dir, local_executor=local_exec)
    res: ExecuteResult = asyncio.run(orch.execute(ex_req))

    evidence_refs = [er.ref for er in res.evidence_refs]
    reason_code, reason_msg = _extract_reason_from_evidence(req.data_dir, evidence_refs)

    user_msg = ""
    if res.status == "accepted":
        user_msg = _extract_user_facing_message(req.data_dir, evidence_refs) or "ok"
    else:
        # For policy rejects, surface the reason code.
        user_msg = reason_code

    base = UI1Result(
        ok=res.status == "accepted",
        status=res.status,
        error_code=res.error_code,
        reason_code=reason_code,
        reason_message=reason_msg,
        user_facing_message=user_msg,
        action=[{"kind": "execute", "operator_ref": operator_ref}],
        evidence_refs=evidence_refs,
        expires_at=None,
        trace_id=trace.trace_id,
        turn_id=trace.turn_id,
        span_id=trace.span_id,
        approval_id=None,
    )

    if str(res.error_code or "") == "E_HITL_REQUIRED":
        # Create a pending approval record + write an approval snapshot evidence for audit.
        expires_at = (_utc_iso_dt() + timedelta(hours=24)).isoformat().replace("+00:00", "Z")
        evidence = FileEvidenceStore(data_dir=req.data_dir)
        appr_ref = evidence.add_json(
            {
                "schema_version": "1.0.0",
                "type": "ui1_approval_request",
                "ts": _utc_iso(),
                "expires_at": expires_at,
                "blocked_trace": {"trace_id": trace.trace_id, "turn_id": trace.turn_id, "span_id": trace.span_id},
                "blocked_evidence_refs": list(evidence_refs),
                "request": {"operator_ref": operator_ref, "arguments": arguments, "workspace_id": req.workspace_id},
                "reason_code": reason_code,
                "reason_message": reason_msg,
            },
            kind="policy",
        )

        store = ApprovalStore(data_dir=req.data_dir)
        approval_id = store.create_pending(
            run_req=req,
            blocked_trace=trace,
            blocked_evidence_refs=evidence_refs,
            reason_code=reason_code,
            reason_message=reason_msg,
            expires_at=expires_at,
            approval_evidence_ref=appr_ref.ref,
        )

        return UI1Result(
            ok=False,
            status="pending_approval",
            error_code="E_HITL_REQUIRED",
            reason_code=reason_code,
            reason_message=reason_msg,
            user_facing_message="Human approval required (HITL).",
            action=[{"kind": "hitl_approval_required", "approval_id": approval_id, "operator_ref": operator_ref}],
            evidence_refs=list(dict.fromkeys(evidence_refs + [appr_ref.ref])),
            expires_at=expires_at,
            trace_id=trace.trace_id,
            turn_id=trace.turn_id,
            span_id=trace.span_id,
            approval_id=approval_id,
        )

    return base


def _utc_iso_dt() -> datetime:
    return datetime.now(timezone.utc)


def ui1_list_approvals(*, data_dir: str | Path) -> dict[str, Any]:
    store = ApprovalStore(data_dir=data_dir)
    state = store.load_state()
    items: list[dict[str, Any]] = []
    for aid, last in sorted(state.items(), key=lambda kv: str(kv[0])):
        if not isinstance(last, dict):
            continue
        event = str(last.get("event") or "")
        status = "pending"
        if event == "approved":
            status = "approved"
        elif event == "rejected":
            status = "rejected"
        elif isinstance(last.get("status"), str):
            status = str(last.get("status"))
        items.append(
            {
                "approval_id": aid,
                "status": status,
                "event": event,
                "expires_at": last.get("expires_at"),
                "reason_code": last.get("reason_code"),
                "reason_message": last.get("reason_message"),
            }
        )
    return {"schema_version": "1.0.0", "type": "ui1_approvals", "items": items}


def ui1_reject(*, data_dir: str | Path, approval_id: str, replay_mode: bool = False) -> dict[str, Any]:
    if bool(replay_mode):
        return {
            "schema_version": "1.0.0",
            "type": "ui1_reject_result",
            "ok": False,
            "error_code": "E_POLICY_DENY",
            "reason_code": "replay_mode_no_side_effects",
            "reason_message": "UI1 forbids writes in replay-mode",
        }

    store = ApprovalStore(data_dir=data_dir)
    state = store.load_state()
    last = state.get(approval_id)
    if not isinstance(last, dict) or str(last.get("event") or "") != "created":
        return {
            "schema_version": "1.0.0",
            "type": "ui1_reject_result",
            "ok": False,
            "error_code": "E_EXECUTION_FAILED",
            "reason_code": "approval_not_pending",
            "reason_message": "approval id not found or not pending",
        }

    store.mark(approval_id=approval_id, event="rejected", detail={"status": "rejected"})
    return {"schema_version": "1.0.0", "type": "ui1_reject_result", "ok": True, "approval_id": approval_id}


def ui1_approve(*, data_dir: str | Path, approval_id: str, replay_mode: bool = False) -> dict[str, Any]:
    if bool(replay_mode):
        return {
            "schema_version": "1.0.0",
            "type": "ui1_approve_result",
            "ok": False,
            "error_code": "E_POLICY_DENY",
            "reason_code": "replay_mode_no_side_effects",
            "reason_message": "UI1 forbids execution and writes in replay-mode",
        }

    store = ApprovalStore(data_dir=data_dir)
    state = store.load_state()
    last = state.get(approval_id)
    if not isinstance(last, dict) or str(last.get("event") or "") != "created":
        return {
            "schema_version": "1.0.0",
            "type": "ui1_approve_result",
            "ok": False,
            "error_code": "E_EXECUTION_FAILED",
            "reason_code": "approval_not_pending",
            "reason_message": "approval id not found or not pending",
        }

    req_obj = last.get("request")
    blocked = last.get("blocked")
    if not isinstance(req_obj, dict) or not isinstance(blocked, dict):
        raise ApprovalStoreError("corrupt approvals log")

    operator_ref = str(req_obj.get("operator_ref") or req_obj.get("skill_ref") or "").strip()
    message = str(req_obj.get("message") or "")
    workspace_id = str(req_obj.get("workspace_id") or "local")
    arguments = req_obj.get("arguments")
    if not isinstance(arguments, dict):
        legacy_input = req_obj.get("input")
        if isinstance(legacy_input, dict):
            arguments = dict(legacy_input)
        else:
            arguments = {"request": message}
    keys_dir = req_obj.get("keys_dir")
    if keys_dir is not None and not isinstance(keys_dir, str):
        keys_dir = None
    verify_asvp = bool(req_obj.get("verify_asvp", True))
    backend = str(req_obj.get("backend") or "local_mock")
    model = req_obj.get("model")
    if model is not None and not isinstance(model, str):
        model = None
    preferred_target = str(req_obj.get("preferred_target") or "auto")
    deadline_ms = int(req_obj.get("deadline_ms") or 60000)
    remote_calls_armed = bool(req_obj.get("remote_calls_armed", False))
    allow_network_egress = bool(req_obj.get("allow_network_egress", False))
    orig_idem = req_obj.get("idempotency_key")
    if orig_idem is not None and not isinstance(orig_idem, str):
        orig_idem = None

    parent_trace_id = str(blocked.get("trace_id") or "")
    parent_turn_id = str(blocked.get("turn_id") or "")

    # Rerun as a new turn to avoid idempotency cache collisions.
    trace = TraceContext(
        trace_id=_new_id("tr"),
        turn_id=_new_id("turn"),
        span_id=_new_id("span"),
        parent_span_id=None,
    )

    ex_req = ExecuteRequest(
        workspace_id=workspace_id,
        operator_ref=operator_ref,
        arguments=dict(arguments),
        idempotency_key=(orig_idem or _new_id("idem")) + f":approved:{approval_id}",
        deadline_ms=deadline_ms,
        trace=trace,
        policy_context={
            "verify_asvp": verify_asvp,
            "public_keys_dir": keys_dir,
            "backend": backend,
            "model": model,
            "remote_calls_armed": remote_calls_armed,
            "allow_network_egress": allow_network_egress,
            "approved_by_human": True,
            "approval_parent": {"trace_id": parent_trace_id, "turn_id": parent_turn_id, "approval_id": approval_id},
            "replay_mode": False,
        },
        preferred_target=preferred_target,
    )

    local_exec = LocalExecutor.for_data_dir(str(data_dir))
    orch = Orchestrator.for_data_dir(str(data_dir), local_executor=local_exec)
    res: ExecuteResult = asyncio.run(orch.execute(ex_req))

    evidence_refs = [er.ref for er in res.evidence_refs]
    reason_code, reason_msg = _extract_reason_from_evidence(data_dir, evidence_refs)
    user_msg = _extract_user_facing_message(data_dir, evidence_refs) if res.status == "accepted" else reason_code

    store.mark(
        approval_id=approval_id,
        event="approved",
        detail={
            "status": "approved",
            "rerun": {
                "trace_id": trace.trace_id,
                "turn_id": trace.turn_id,
                "span_id": trace.span_id,
                "kernel_status": res.status,
                "error_code": res.error_code,
                "evidence_refs": list(evidence_refs),
            },
        },
    )

    return {
        "schema_version": "1.0.0",
        "type": "ui1_approve_result",
        "ok": res.status == "accepted",
        "status": res.status,
        "error_code": res.error_code,
        "reason_code": reason_code,
        "reason_message": reason_msg,
        "user_facing_message": user_msg,
        "action": [{"kind": "execute", "operator_ref": operator_ref}],
        "evidence_refs": evidence_refs,
        "expires_at": last.get("expires_at"),
        "trace_id": trace.trace_id,
        "turn_id": trace.turn_id,
        "span_id": trace.span_id,
        "approval_id": approval_id,
    }
