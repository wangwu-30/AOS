from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from agentos_next.creator import CreatorError, build_creator_plan
from agentos_next.kernel.evidence_store import FileEvidenceStore
from agentos_next.kernel.executor import ExecuteRequest, ExecuteResult, ExecuteTiming
from agentos_next.kernel.local_skill_approval import compute_local_skill_fingerprint
from agentos_next.kernel.trace_logger import FileTraceLogger
from agentos_next.kernel.types import EvidenceRef, TraceEvent


@dataclass(frozen=True)
class BuiltinDispatchResult:
    handled: bool
    result: Optional[ExecuteResult] = None


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def maybe_execute_builtin_creator(*, req: ExecuteRequest, data_dir: str) -> BuiltinDispatchResult:
    if not req.operator_ref.startswith("builtin://creator."):
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
        if name == "creator.plan":
            output = _creator_plan(req=req)
        elif name == "creator.write_local_skill":
            output = _creator_write_local_skill(req=req)
        else:
            raise ValueError(f"unknown builtin: {name}")
        out_ref = evidence.add_json(output, kind="tool_io")
        evidence_refs.append(out_ref)
        _emit("TOOL_CALL_FINISHED", ers=(out_ref,), data={"builtin": name, "ok": True})
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
    except Exception as exc:
        error_code = getattr(exc, "code", "E_EXECUTION_FAILED")
        err_ref = evidence.add_json(
            {"schema_version": "1.0.0", "ok": False, "error_code": str(error_code), "message": str(exc)},
            kind="error",
        )
        evidence_refs.append(err_ref)
        _emit("ERROR", ers=(err_ref,), data={"builtin": name, "error_code": str(error_code)})
        ended_at = _utc_iso()
        return BuiltinDispatchResult(
            handled=True,
            result=ExecuteResult(
                status="failed",
                evidence_refs=tuple(evidence_refs),
                artifact_refs=(),
                error_code=str(error_code),
                timing=ExecuteTiming(started_at=started_at, ended_at=ended_at),
                target="local",
            ),
        )


def _creator_plan(*, req: ExecuteRequest) -> dict[str, Any]:
    inp = dict(req.arguments or {})
    intent = str(inp.get("intent") or inp.get("request") or "").strip()
    if not intent:
        raise ValueError("intent is required")
    registry_root = _resolve_registry_root(inp.get("registry_root"))
    max_steps = _coerce_int(inp.get("max_steps"), default=3, minimum=1, maximum=8)
    deadline_ms = _coerce_int(inp.get("deadline_ms"), default=max(1000, int(req.deadline_ms or 60000)), minimum=1000, maximum=300000)
    plan = build_creator_plan(
        registry_root=registry_root,
        intent=intent,
        workspace_id=str(req.workspace_id or "local"),
        deadline_ms=deadline_ms,
        max_steps=max_steps,
        model_id_override=str((req.policy_context or {}).get("model") or "").strip() or None,
    )
    return {
        "schema_version": "1.0.0",
        "ok": True,
        "registry_root": registry_root,
        "plan": plan,
    }


_DEFAULT_INPUTS_SCHEMA = {
    "type": "object",
    "required": ["request"],
    "additionalProperties": False,
    "properties": {
        "request": {"type": "string", "minLength": 1},
        "metadata": {"type": "object"},
    },
}
_DEFAULT_OUTPUTS_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "status": {
            "type": "string",
            "enum": ["continue", "done", "blocked", "need_context"],
        },
        "reasoning": {"type": "string"},
        "actions": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "action_id": {"type": "string"},
                    "operator_ref": {"type": "string"},
                    "arguments": {"type": "object"},
                    "depends_on": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["operator_ref", "arguments"],
            },
        },
    },
}
_DEFAULT_ACCEPTANCE_RULES = {
    "constraints": {
        "max_reply_words": 200,
    }
}
_DEFAULT_EXECUTION_PROFILE = {
    "model_id": "local_mock",
    "max_output_tokens": 1024,
    "temperature": 0.2,
}


def _creator_write_local_skill(*, req: ExecuteRequest) -> dict[str, Any]:
    inp = dict(req.arguments or {})
    skill_name = str(inp.get("name") or inp.get("skill_name") or "").strip()
    description = str(inp.get("description") or "").strip()
    logic = str(inp.get("logic") or inp.get("instructions") or "").strip()
    if not skill_name:
        raise CreatorError(code="E_CREATOR_SKILL_INVALID", message="skill name is required")
    if not description:
        raise CreatorError(code="E_CREATOR_SKILL_INVALID", message="skill description is required")
    if not logic:
        raise CreatorError(code="E_CREATOR_SKILL_INVALID", message="skill logic is required")
    overwrite = bool(inp.get("overwrite"))
    target_dir = _resolve_local_skill_dir(
        value=inp.get("skill_dir"),
        registry_root=inp.get("registry_root"),
        skill_name=skill_name,
    )
    if target_dir.exists() and any(target_dir.iterdir()) and not overwrite:
        raise CreatorError(code="E_CREATOR_SKILL_EXISTS", message=f"skill dir already exists: {target_dir}")
    target_dir.mkdir(parents=True, exist_ok=True)
    artifacts_dir = target_dir / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    inputs_schema = deepcopy(inp.get("inputs_schema") if isinstance(inp.get("inputs_schema"), dict) else _DEFAULT_INPUTS_SCHEMA)
    outputs_schema = deepcopy(inp.get("outputs_schema") if isinstance(inp.get("outputs_schema"), dict) else _DEFAULT_OUTPUTS_SCHEMA)
    acceptance_rules = deepcopy(
        inp.get("acceptance_rules") if isinstance(inp.get("acceptance_rules"), dict) else _DEFAULT_ACCEPTANCE_RULES
    )
    execution_profile = deepcopy(
        inp.get("execution_profile") if isinstance(inp.get("execution_profile"), dict) else _DEFAULT_EXECUTION_PROFILE
    )
    contract = {
        "name": skill_name,
        "description": description,
        "version": str(inp.get("version") or "0.1.0").strip() or "0.1.0",
        "risk_level": str(inp.get("risk_level") or "low").strip() or "low",
        "logic": logic,
        "execution_targets": list(inp.get("execution_targets") or ["auto"]),
        "requires_secrets": bool(inp.get("requires_secrets", False)),
        "network_egress": dict(inp.get("network_egress") or {"default": "deny", "allow": []}),
        "data_requirements": dict(inp.get("data_requirements") or {"pii": "avoid", "retention": "none"}),
        "inputs_schema": inputs_schema,
        "outputs_schema": outputs_schema,
        "acceptance_rules": acceptance_rules,
        "execution_profile": execution_profile,
        "type": "local_unsigned_skill_v1",
    }

    (target_dir / "contract.skill").write_text(
        json.dumps(contract, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (artifacts_dir / "inputs_schema.json").write_text(
        json.dumps(inputs_schema, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (artifacts_dir / "outputs_schema.json").write_text(
        json.dumps(outputs_schema, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (artifacts_dir / "acceptance_rules.json").write_text(
        json.dumps(acceptance_rules, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (artifacts_dir / "execution_profile.json").write_text(
        json.dumps(execution_profile, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    fingerprint = compute_local_skill_fingerprint(target_dir)
    return {
        "schema_version": "1.0.0",
        "ok": True,
        "skill_dir": str(target_dir),
        "fingerprint": fingerprint,
        "skill_ref": str(target_dir),
        "unsigned_local_skill": True,
        "skill_layer": "local_unsigned",
        "registry_eligible": False,
    }


def _resolve_registry_root(value: Any) -> str:
    if isinstance(value, str) and value.strip():
        path = Path(value.strip()).expanduser()
        if not path.is_absolute():
            path = Path.cwd() / path
        return str(path.resolve())
    for candidate in (Path.cwd() / "examples" / "skills", Path.cwd()):
        if candidate.exists() and candidate.is_dir():
            return str(candidate.resolve())
    raise CreatorError(code="E_CREATOR_REGISTRY_INVALID", message="no registry root found")


def _resolve_local_skill_dir(*, value: Any, registry_root: Any, skill_name: str) -> Path:
    if isinstance(value, str) and value.strip():
        path = Path(value.strip()).expanduser()
        if not path.is_absolute():
            path = Path.cwd() / path
        return path.resolve()
    root = _resolve_local_skill_layer_root(registry_root)
    return (root / skill_name).resolve()


def _resolve_local_skill_layer_root(registry_root: Any) -> Path:
    if isinstance(registry_root, str) and registry_root.strip():
        base = Path(registry_root.strip()).expanduser()
        if not base.is_absolute():
            base = Path.cwd() / base
        base = base.resolve()
    else:
        base = Path.cwd().resolve()
    return (base / ".agentos" / "local_skills").resolve()


def _coerce_int(value: Any, *, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except Exception:
        return default
    if parsed < minimum:
        return minimum
    if parsed > maximum:
        return maximum
    return parsed
