from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

DialogStatus = str  # OPEN|RUNNING|BLOCKED|IDLE|CLOSED|FAILED


@dataclass(frozen=True)
class DialogState:
    dialog_id: str
    status: DialogStatus
    turn_count: int
    last_turn_index: int
    last_error_code: Optional[str]
    blocked_reason: Optional[str]
    last_delivery_state: Optional[str] = None
    last_delivery_summary: Optional[str] = None


def _sha256_hex(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _evidence_meta_path(data_dir: Path, ref: str) -> Path:
    return data_dir / "evidence" / "meta" / f"{ref}.json"


def _trace_path(data_dir: Path, trace_id: str) -> Path:
    return data_dir / "traces" / f"{trace_id}.jsonl"


def rehydrate_dialog_state(
    *,
    data_dir: str | os.PathLike[str] = "data",
    trace_id: str,
    require_evidence: bool = True,
) -> DialogState:
    """Rehydrate dialog state from append-only trace JSONL.

    Spec: docs/specs/MVP_014_DIALOG_STATE_MACHINE.md
    """
    dd = Path(data_dir)
    tp = _trace_path(dd, trace_id)
    if not tp.exists():
        # Fail-closed: missing trace => blocked for missing evidence.
        return DialogState(
            dialog_id=str(trace_id),
            status="BLOCKED",
            turn_count=0,
            last_turn_index=0,
            last_error_code=None,
            blocked_reason="missing_trace",
            last_delivery_state=None,
            last_delivery_summary=None,
        )

    status: DialogStatus = "OPEN"
    turn_count = 0
    last_turn_index = 0
    last_error: Optional[str] = None
    blocked_reason: Optional[str] = None
    last_delivery_state: Optional[str] = None
    last_delivery_summary: Optional[str] = None

    lines = [ln for ln in tp.read_text(encoding="utf-8").splitlines() if ln.strip()]
    for ln in lines:
        try:
            ev = json.loads(ln)
        except Exception:
            continue
        if not isinstance(ev, dict):
            continue
        if ev.get("event_type") != "DIALOG_EVENT":
            continue
        data = ev.get("data")
        if not isinstance(data, dict):
            continue
        et = data.get("dialog_event_type")
        if not isinstance(et, str) or not et.strip():
            continue

        # Evidence presence checking: fail-closed into BLOCKED if referenced evidence is missing.
        if require_evidence:
            refs = []
            for er in ev.get("evidence_refs") or []:
                if isinstance(er, dict) and isinstance(er.get("ref"), str):
                    refs.append(er["ref"])
            final_ref = data.get("final_snapshot_ref")
            if isinstance(final_ref, str) and final_ref.strip():
                refs.append(final_ref)
            for ref in refs:
                if not _evidence_meta_path(dd, ref).exists():
                    return DialogState(
                        dialog_id=str(trace_id),
                        status="BLOCKED",
                        turn_count=turn_count,
                        last_turn_index=last_turn_index,
                        last_error_code=last_error,
                        blocked_reason="missing_evidence",
                        last_delivery_state=last_delivery_state,
                        last_delivery_summary=last_delivery_summary,
                    )

        if et == "DIALOG_OPENED":
            status = "OPEN"
            blocked_reason = None
            continue

        if et == "USER_MESSAGE_RECEIVED":
            idx = data.get("turn_index")
            if isinstance(idx, int) and idx > 0:
                last_turn_index = max(last_turn_index, idx)
            continue

        if et == "DELIVERY_STATE":
            state = str(data.get("state") or "").strip().lower()
            summary = str(data.get("summary") or "").strip() or None
            err = data.get("error_code")
            if isinstance(err, str) and err.strip():
                last_error = err.strip()
            last_delivery_state = state or last_delivery_state
            last_delivery_summary = summary or last_delivery_summary
            if state in {"ack", "progress"}:
                status = "RUNNING"
                blocked_reason = None
            elif state == "blocker":
                status = "BLOCKED"
                blocked_reason = summary or (str(err).strip() if isinstance(err, str) and err.strip() else "blocked")
            elif state == "done":
                status = "IDLE"
                blocked_reason = None
            continue

        if et == "TURN_STARTED":
            status = "RUNNING"
            blocked_reason = None
            idx = data.get("turn_index")
            if isinstance(idx, int) and idx > 0:
                last_turn_index = max(last_turn_index, idx)
            continue

        if et == "TURN_FINISHED":
            ok = bool(data.get("ok"))
            err = data.get("error_code")
            last_error = str(err) if isinstance(err, str) and err.strip() else None

            idx = data.get("turn_index")
            if isinstance(idx, int) and idx > 0:
                last_turn_index = max(last_turn_index, idx)
                turn_count = max(turn_count, last_turn_index)

            if ok:
                status = "IDLE"
                blocked_reason = None
                continue

            # Map common governance/policy failures into BLOCKED; others are FAILED.
            blocked_codes = {
                "E_HITL_REQUIRED",
                "E_REMOTE_CALL_NOT_ARMED",
                "E_NETWORK_EGRESS_DENY",
                "E_REPLAY_REMOTE_DISABLED",
                "E_PRECHECK_FAIL",
                "E_POSTCHECK_FAIL",
            }
            if last_error in blocked_codes:
                status = "BLOCKED"
                blocked_reason = "policy_or_approval"
            else:
                status = "FAILED"
                blocked_reason = None
            continue

        if et == "DIALOG_BLOCKED":
            status = "BLOCKED"
            r = data.get("reason")
            blocked_reason = str(r) if isinstance(r, str) and r.strip() else "blocked"
            continue

        if et == "DIALOG_CLOSED":
            status = "CLOSED"
            blocked_reason = None
            continue

        if et == "DIALOG_FAILED":
            status = "FAILED"
            blocked_reason = None
            continue

    # If we never observed a finish event but did see message received, keep RUNNING->BLOCKED.
    if status == "RUNNING":
        status = "BLOCKED"
        blocked_reason = blocked_reason or "incomplete_turn"

    return DialogState(
        dialog_id=str(trace_id),
        status=status,
        turn_count=turn_count,
        last_turn_index=last_turn_index,
        last_error_code=last_error,
        blocked_reason=blocked_reason,
        last_delivery_state=last_delivery_state,
        last_delivery_summary=last_delivery_summary,
    )


def build_user_message_digest(*, message: str) -> str:
    # Deterministic digest to avoid storing raw text in trace.
    return _sha256_hex(message.strip())
