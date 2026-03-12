from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, Optional

from agentos_next.kernel.capabilities import parse_capabilities
from agentos_next.kernel.evidence_store import FileEvidenceStore
from agentos_next.kernel.executor import ExecuteRequest
from agentos_next.kernel.trace_logger import FileTraceLogger
from agentos_next.kernel.types import EvidenceRef, TraceContext, TraceEvent
from agentos_next.llm.backend import is_remote_llm_backend

PolicyDecisionType = Literal["allow", "ask", "deny"]


@dataclass(frozen=True)
class PolicyDecision:
    decision: PolicyDecisionType
    reason_code: str
    error_code: Optional[str]
    constraints: dict[str, Any]
    evidence_payload: dict[str, Any]


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


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


def _json_default(v: Any) -> str:
    return str(v)


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=_json_default)


def _action_fingerprint(*, operator_ref: str, arguments: dict[str, Any]) -> str:
    seed = f"{operator_ref}\n{_canonical_json(arguments)}".encode("utf-8", errors="replace")
    return hashlib.sha256(seed).hexdigest()


def _trace_path(*, data_dir: str | Path, trace_id: str) -> Path:
    return Path(data_dir) / "traces" / f"{trace_id}.jsonl"


def _count_prior_policy_fingerprint_hits(
    *,
    data_dir: str | Path,
    trace_id: str,
    turn_id: str,
    fingerprint: str,
) -> int:
    path = _trace_path(data_dir=data_dir, trace_id=trace_id)
    if not path.exists():
        return 0
    count = 0
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except Exception:
            continue
        if not isinstance(obj, dict):
            continue
        if str(obj.get("event_type") or "") != "POLICY_DECIDED":
            continue
        ctx = obj.get("ctx")
        if not isinstance(ctx, dict):
            continue
        if str(ctx.get("turn_id") or "") != turn_id:
            continue
        data = obj.get("data")
        if not isinstance(data, dict):
            continue
        if str(data.get("action_fingerprint") or "") == fingerprint:
            count += 1
    return count


def _extract_policy_intent_actions(policy_context: dict[str, Any]) -> set[str]:
    intent = policy_context.get("policy_intent")
    if not isinstance(intent, dict):
        return set()
    raw_actions = intent.get("actions")
    if not isinstance(raw_actions, list):
        return set()
    out: set[str] = set()
    for item in raw_actions:
        if isinstance(item, str) and item.strip():
            out.add(item.strip().lower())
            continue
        if not isinstance(item, dict):
            continue
        for key in ("action", "name", "type", "kind"):
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                out.add(value.strip().lower())
                break
    return out


def _requires_approval(
    *,
    skill_risk_level: Optional[str],
    policy_context: dict[str, Any],
) -> bool:
    risk = str(skill_risk_level or "").strip().lower()
    if risk in {"high", "critical"}:
        return True
    high_risk_actions = {"delete", "execute_shell", "send_message", "modify_file"}
    action_names = _extract_policy_intent_actions(policy_context)
    if action_names.intersection(high_risk_actions):
        return True
    return False


def _make_payload(
    *,
    req: ExecuteRequest,
    decision: PolicyDecisionType,
    reason_code: str,
    error_code: Optional[str],
    fingerprint: str,
    count: int,
    threshold: int,
) -> dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "decision": decision,
        "policy_disposition": decision,
        "reason_code": reason_code,
        "error_code": error_code,
        "fingerprint": fingerprint,
        "count": int(count),
        "threshold": int(threshold),
        "trace_id": req.trace.trace_id,
        "turn_id": req.trace.turn_id,
        "operator_ref": req.operator_ref,
    }


def _required_capabilities_for_request(*, req: ExecuteRequest, policy: dict[str, Any]) -> list[str]:
    required: list[str] = []
    skill = str(req.operator_ref or "")

    # Builtin kernel-privileged skills only require their own specific capability.
    # They do NOT inherit network-level requirements (llm_remote, net_egress) from
    # the parent policy_context — a builtin://memory.write does not need the network.
    if skill.startswith("builtin://memory."):
        op = skill[len("builtin://memory.") :].strip().lower()
        if op == "write":
            required.append("memory_write")
        if op == "delete":
            required.append("memory_delete")
        if op == "compact":
            required.append("memory_compact")
        if op == "search":
            required.append("memory_search")
        return sorted(set(required))

    if skill.startswith("builtin://fs."):
        op = skill[len("builtin://fs.") :].strip().lower()
        if op == "read":
            required.append("fs_read")
        if op in {"write", "delete"}:
            required.append("fs_write")
        if op == "list":
            required.append("fs_read")
        return sorted(set(required))

    if skill.startswith("builtin://shell."):
        required.append("shell_exec")
        return sorted(set(required))

    if skill.startswith("builtin://web."):
        op = skill[len("builtin://web.") :].strip().lower()
        if op == "search":
            required.append("web_search")
        elif op == "browse":
            required.append("web_browse")
        return sorted(set(required))

    if skill.startswith("builtin://research."):
        op = skill[len("builtin://research.") :].strip().lower()
        if op == "run":
            required.append("research_run")
        return sorted(set(required))

    if skill.startswith("builtin://creator."):
        op = skill[len("builtin://creator.") :].strip().lower()
        if op == "plan":
            required.append("fs_read")
        if op == "write_local_skill":
            required.append("fs_write")
        return sorted(set(required))

    if skill.startswith("builtin://channel."):
        required.append("channel_send")
        return sorted(set(required))

    if skill.startswith("builtin://time."):
        required.append("time_read")
        return sorted(set(required))

    if skill.startswith("builtin://assistant."):
        op = skill[len("builtin://assistant.") :].strip().lower()
        if op == "submit":
            required.append("assistant_runtime_submit")
        return sorted(set(required))

    if skill.startswith("builtin://scheduler."):
        op = skill[len("builtin://scheduler.") :].strip().lower()
        if op in {"at", "cron"}:
            required.append("scheduler_write")
        return sorted(set(required))

    # Non-builtin skills: check network-level requirements.
    remote_calls_armed = _as_bool(policy.get("remote_calls_armed"), default=False)
    allow_network_egress = _as_bool(policy.get("allow_network_egress"), default=False)
    backend = str(policy.get("backend") or "").strip().lower()

    if allow_network_egress:
        required.append("net_egress")
    if remote_calls_armed or is_remote_llm_backend(backend):
        required.append("llm_remote")

    return sorted(set(required))


def evaluate_execute_policy(
    *,
    req: ExecuteRequest,
    data_dir: str | Path,
    skill_risk_level: Optional[str] = None,
    default_cycle_threshold: int = 2,
) -> PolicyDecision:
    policy = dict(req.policy_context or {})
    approved_by_human = _as_bool(policy.get("approved_by_human"), default=False)
    replay_mode = _as_bool(policy.get("replay_mode"), default=False)
    remote_calls_armed = _as_bool(policy.get("remote_calls_armed"), default=False)
    allow_network_egress = _as_bool(policy.get("allow_network_egress"), default=False)
    backend = str(policy.get("backend") or "").strip().lower()
    preferred_target = str(req.preferred_target or "auto").strip().lower()

    fingerprint = _action_fingerprint(operator_ref=str(req.operator_ref), arguments=dict(req.arguments or {}))

    cycle_threshold = max(2, int(default_cycle_threshold))

    # THREAD-029: Budget v1 (remote_llm_calls). Validate schema early, before any execution.
    budget_raw: Any = getattr(req, "budget_slice", None)
    budget_slice: Optional[int] = None
    if budget_raw is not None:
        if isinstance(budget_raw, bool) or not isinstance(budget_raw, int) or int(budget_raw) < 0:
            payload = _make_payload(
                req=req,
                decision="deny",
                reason_code="budget_schema_invalid",
                error_code="E_BUDGET_SCHEMA_INVALID",
                fingerprint=fingerprint,
                count=1,
                threshold=cycle_threshold,
            )
            payload.update({"budget_type": "remote_llm_calls", "budget_slice": budget_raw})
            return PolicyDecision(
                decision="deny",
                reason_code="budget_schema_invalid",
                error_code="E_BUDGET_SCHEMA_INVALID",
                constraints={},
                evidence_payload=payload,
            )
        budget_slice = int(budget_raw)
    cycle_guard_enabled = isinstance(policy.get("policy_intent"), dict)
    count = 1
    if cycle_guard_enabled:
        prior_hits = _count_prior_policy_fingerprint_hits(
            data_dir=data_dir,
            trace_id=req.trace.trace_id,
            turn_id=req.trace.turn_id,
            fingerprint=fingerprint,
        )
        count = int(prior_hits) + 1
        if count >= cycle_threshold:
            return PolicyDecision(
                decision="deny",
                reason_code="cycle_detected",
                error_code="E_CYCLE_DETECTED",
                constraints={},
                evidence_payload=_make_payload(
                    req=req,
                    decision="deny",
                    reason_code="cycle_detected",
                    error_code="E_CYCLE_DETECTED",
                    fingerprint=fingerprint,
                    count=count,
                    threshold=cycle_threshold,
                ),
            )

    remote_intent = bool(
        remote_calls_armed or allow_network_egress or preferred_target == "remote" or is_remote_llm_backend(backend)
    )
    if replay_mode and remote_intent:
        return PolicyDecision(
            decision="deny",
            reason_code="replay_remote_blocked",
            error_code="E_REPLAY_REMOTE_DISABLED",
            constraints={},
            evidence_payload=_make_payload(
                req=req,
                decision="deny",
                reason_code="replay_remote_blocked",
                error_code="E_REPLAY_REMOTE_DISABLED",
                fingerprint=fingerprint,
                count=count,
                threshold=cycle_threshold,
            ),
        )

    # THREAD-030: Capability Schema v1 (policy_context.capabilities[]).
    required_caps = _required_capabilities_for_request(req=req, policy=policy)
    parsed = parse_capabilities(policy)
    if not parsed.ok:
        payload = _make_payload(
            req=req,
            decision="deny",
            reason_code="capability_schema_invalid",
            error_code="E_CAPABILITY_SCHEMA_INVALID",
            fingerprint=fingerprint,
            count=count,
            threshold=cycle_threshold,
        )
        payload.update(
            {
                "allowed_capabilities": sorted(parsed.names),
                "required_capabilities": required_caps,
                "schema_error": parsed.error,
            }
        )
        return PolicyDecision(
            decision="deny",
            reason_code="capability_schema_invalid",
            error_code="E_CAPABILITY_SCHEMA_INVALID",
            constraints={},
            evidence_payload=payload,
        )

    if required_caps:
        missing = [c for c in required_caps if c not in parsed.names]
        if missing:
            payload = _make_payload(
                req=req,
                decision="deny",
                reason_code="capability_missing",
                error_code="E_CAPABILITY_DENY",
                fingerprint=fingerprint,
                count=count,
                threshold=cycle_threshold,
            )
            payload.update(
                {
                    "allowed_capabilities": sorted(parsed.names),
                    "required_capabilities": required_caps,
                    "missing_capabilities": missing,
                }
            )
            return PolicyDecision(
                decision="deny",
                reason_code="capability_missing",
                error_code="E_CAPABILITY_DENY",
                constraints={},
                evidence_payload=payload,
            )

    # THREAD-029: Budget v1 enforcement at allow-check time.
    # Only enforce remote LLM budget if this specific request actually requires llm_remote.
    if "llm_remote" in required_caps and budget_slice is not None and budget_slice <= 0:
        payload = _make_payload(
            req=req,
            decision="deny",
            reason_code="budget_exhausted",
            error_code="E_BUDGET_EXHAUSTED",
            fingerprint=fingerprint,
            count=count,
            threshold=cycle_threshold,
        )
        payload.update(
            {
                "budget_type": "remote_llm_calls",
                "budget_slice": int(budget_slice),
                "budget_consumed": 0,
                "budget_remaining": int(budget_slice),
            }
        )
        return PolicyDecision(
            decision="deny",
            reason_code="budget_exhausted",
            error_code="E_BUDGET_EXHAUSTED",
            constraints={},
            evidence_payload=payload,
        )

    if _requires_approval(skill_risk_level=skill_risk_level, policy_context=policy) and not approved_by_human:
        return PolicyDecision(
            decision="ask",
            reason_code="hitl_required",
            error_code="E_HITL_REQUIRED",
            constraints={},
            evidence_payload=_make_payload(
                req=req,
                decision="ask",
                reason_code="hitl_required",
                error_code="E_HITL_REQUIRED",
                fingerprint=fingerprint,
                count=count,
                threshold=cycle_threshold,
            ),
        )

    return PolicyDecision(
        decision="allow",
        reason_code="allow",
        error_code=None,
        constraints={},
        evidence_payload=_make_payload(
            req=req,
            decision="allow",
            reason_code="allow",
            error_code=None,
            fingerprint=fingerprint,
            count=count,
            threshold=cycle_threshold,
        ),
    )


def emit_policy_decision(
    *,
    data_dir: str | Path,
    trace: TraceContext,
    decision: PolicyDecision,
    write_allow_evidence: bool = False,
) -> EvidenceRef | None:
    policy_ref: EvidenceRef | None = None
    if write_allow_evidence or decision.decision != "allow":
        evidence = FileEvidenceStore(data_dir=data_dir)
        policy_ref = evidence.add_json(decision.evidence_payload, kind="policy")

    trace_logger = FileTraceLogger(data_dir=data_dir)
    trace_logger.emit(
        TraceEvent(
            schema_version="1.0.0",
            ctx=trace,
            event_type="POLICY_DECIDED",
            ts=_utc_iso(),
            evidence_refs=((policy_ref,) if policy_ref is not None else ()),
            data={
                "decision": decision.decision,
                "reason_code": decision.reason_code,
                "error_code": decision.error_code,
                "action_fingerprint": str(decision.evidence_payload.get("fingerprint") or ""),
                "count": int(decision.evidence_payload.get("count") or 0),
                "threshold": int(decision.evidence_payload.get("threshold") or 0),
            },
        )
    )
    return policy_ref
