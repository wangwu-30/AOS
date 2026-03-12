from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agentos_next.compiler.skill_contract import load_contract
from agentos_next.kernel.executor import ExecuteRequest, ExecuteResult, Executor, ExecuteTiming
from agentos_next.kernel.local_skill_approval import (
    FileLocalSkillApprovalStore,
    resolve_local_skill_approval_context,
)
from agentos_next.kernel.policy_engine import emit_policy_decision, evaluate_execute_policy
from agentos_next.runtime.execute_mapping import package_run_result_to_execute_result
from agentos_next.runtime.package_runner import PackageRunRequest, PackageRunner
from agentos_next.runtime.builtin_memory import maybe_execute_builtin_memory
from agentos_next.runtime.builtin_scheduler import maybe_execute_builtin_scheduler
from agentos_next.runtime.builtin_fs import maybe_execute_builtin_fs
from agentos_next.runtime.builtin_channel import maybe_execute_builtin_channel
from agentos_next.runtime.builtin_time import maybe_execute_builtin_time
from agentos_next.runtime.builtin_web import maybe_execute_builtin_web
from agentos_next.runtime.builtin_research import maybe_execute_builtin_research
from agentos_next.runtime.builtin_operator import maybe_execute_builtin_operator
from agentos_next.runtime.builtin_creator import maybe_execute_builtin_creator
from agentos_next.runtime.builtin_assistant import maybe_execute_builtin_assistant
from agentos_next.kernel.evidence_store import FileEvidenceStore
from agentos_next.kernel.trace_logger import FileTraceLogger
from agentos_next.kernel.types import EvidenceRef, TraceEvent
from agentos_next.kernel.skill_registry import FileSkillRegistry, SkillRegistryError, try_resolve_registry_ref


class LocalExecutor(Executor):
    target = "local"

    def __init__(self, runner: PackageRunner, *, data_dir: str | Path = "data") -> None:
        self._runner = runner
        self._data_dir = Path(data_dir)

    @classmethod
    def for_data_dir(cls, data_dir: str | Path = "data") -> "LocalExecutor":
        return cls(runner=PackageRunner.for_data_dir(data_dir), data_dir=data_dir)

    async def execute(self, req: ExecuteRequest) -> ExecuteResult:
        policy = dict(req.policy_context or {})

        registry = FileSkillRegistry(data_dir=str(self._data_dir))
        resolved_skill_dir = None
        registry_id = None
        resolution_ref: EvidenceRef | None = None
        if not req.operator_ref.startswith("builtin://"):
            try:
                resolved_skill_dir, registry_id = try_resolve_registry_ref(skill_ref=req.operator_ref, registry=registry)
                if registry_id is not None and resolved_skill_dir is not None:
                    # Resolution evidence is part of the replayable chain (ref -> path).
                    evidence = FileEvidenceStore(data_dir=str(self._data_dir))
                    resolution_ref = evidence.add_json(
                        {
                            "schema_version": "1.0.0",
                            "type": "skill_ref_resolution",
                            "operator_ref": req.operator_ref,
                            "registry_id": registry_id,
                            "skill_dir": str(resolved_skill_dir),
                        },
                        kind="routing",
                    )
            except SkillRegistryError:
                resolved_skill_dir, registry_id = None, None

        skill_dir_for_policy: Path | None = None
        if not req.operator_ref.startswith("builtin://"):
            skill_dir_for_policy = resolved_skill_dir if resolved_skill_dir is not None else Path(req.operator_ref)

        effective_policy = dict(policy)
        verify_asvp = _as_bool(effective_policy.get("verify_asvp"), default=True)
        local_skill_ctx = resolve_local_skill_approval_context(
            operator_ref=req.operator_ref,
            skill_dir=skill_dir_for_policy,
            verify_asvp=verify_asvp,
            policy_context=effective_policy,
        )
        local_skill_store = FileLocalSkillApprovalStore(data_dir=str(self._data_dir))
        remembered_local_skill_approval = (
            local_skill_store.is_approved(fingerprint=local_skill_ctx.fingerprint)
            if local_skill_ctx is not None
            else False
        )
        if local_skill_ctx is not None and remembered_local_skill_approval:
            effective_policy["approved_by_human"] = True
            effective_policy["local_skill_approval_mode"] = "remember_by_fingerprint"
        effective_req = ExecuteRequest(
            workspace_id=req.workspace_id,
            operator_ref=req.operator_ref,
            arguments=dict(req.arguments),
            idempotency_key=req.idempotency_key,
            deadline_ms=req.deadline_ms,
            trace=req.trace,
            policy_context=effective_policy,
            preferred_target=req.preferred_target,
            priority=req.priority,
            budget_slice=req.budget_slice,
        )

        policy_decision = evaluate_execute_policy(
            req=effective_req,
            data_dir=self._data_dir,
            skill_risk_level=("critical" if local_skill_ctx is not None else _load_skill_risk_level(skill_dir_for_policy)),
        )
        policy_ref = emit_policy_decision(
            data_dir=self._data_dir,
            trace=req.trace,
            decision=policy_decision,
        )
        if policy_decision.decision != "allow":
            now = _utc_iso()
            ers: list[EvidenceRef] = []
            if resolution_ref is not None:
                ers.append(resolution_ref)
            if policy_ref is not None:
                ers.append(policy_ref)
            return ExecuteResult(
                status="rejected",
                evidence_refs=tuple(ers),
                artifact_refs=(),
                error_code=str(policy_decision.error_code or "E_POLICY_DENY"),
                timing=ExecuteTiming(started_at=now, ended_at=now),
                target="local",
            )

        if local_skill_ctx is not None and _as_bool(effective_policy.get("approved_by_human"), default=False):
            if str(local_skill_ctx.approval_mode or "").strip() == "remember_by_fingerprint":
                local_skill_store.remember(
                    fingerprint=local_skill_ctx.fingerprint,
                    skill_dir=local_skill_ctx.skill_dir,
                    mode=local_skill_ctx.approval_mode,
                )

        package_req = PackageRunRequest(
            skill_dir=(resolved_skill_dir if resolved_skill_dir is not None else Path(req.operator_ref)),
            input_obj=dict(req.arguments),
            workspace_id=req.workspace_id,
            trace=req.trace,
            verify_asvp=_as_bool(effective_policy.get("verify_asvp"), default=True),
            public_keys_dir=_optional_path(effective_policy.get("public_keys_dir")),
            backend=str(effective_policy.get("backend") or "local_mock"),
            model_id_override=effective_policy.get("model"),  # Model ID override from CLI
            remote_calls_armed=_as_bool(effective_policy.get("remote_calls_armed"), default=False),
            allow_network_egress=_as_bool(effective_policy.get("allow_network_egress"), default=False),
            approved_by_human=_as_bool(effective_policy.get("approved_by_human"), default=False),
            replay_mode=_as_bool(effective_policy.get("replay_mode"), default=False),
            budget_slice=req.budget_slice,
            policy_context=effective_policy,
        )

        loop = asyncio.get_running_loop()
        timeout_sec = req.deadline_ms / 1000.0 if req.deadline_ms > 0 else None

        # Builtin privileged skills bypass package loading and are implemented in-kernel.
        # Still enforce deadline semantics consistently.
        if req.operator_ref.startswith("builtin://"):
            def _run_builtin() -> ExecuteResult:
                disp = maybe_execute_builtin_memory(req=req, data_dir=str(self._data_dir))
                if not disp.handled:
                    disp = maybe_execute_builtin_scheduler(req=req, data_dir=str(self._data_dir))
                if not disp.handled:
                    disp = maybe_execute_builtin_fs(req=req, data_dir=str(self._data_dir))
                if not disp.handled:
                    disp = maybe_execute_builtin_channel(req=req, data_dir=str(self._data_dir))
                if not disp.handled:
                    disp = maybe_execute_builtin_time(req=req, data_dir=str(self._data_dir))
                if not disp.handled:
                    disp = maybe_execute_builtin_web(req=req, data_dir=str(self._data_dir))
                if not disp.handled:
                    disp = maybe_execute_builtin_research(req=req, data_dir=str(self._data_dir))
                if not disp.handled:
                    disp = maybe_execute_builtin_operator(req=req, data_dir=str(self._data_dir))
                if not disp.handled:
                    disp = maybe_execute_builtin_creator(req=req, data_dir=str(self._data_dir))
                if not disp.handled:
                    disp = maybe_execute_builtin_assistant(req=req, data_dir=str(self._data_dir))

                if not disp.handled or disp.result is None:
                    now = _utc_iso()
                    return ExecuteResult(
                        status="rejected",
                        evidence_refs=(),
                        artifact_refs=(),
                        error_code="E_EXECUTION_FAILED",
                        timing=ExecuteTiming(started_at=now, ended_at=now),
                        target="local",
                    )
                return disp.result

            try:
                if timeout_sec:
                    return await asyncio.wait_for(loop.run_in_executor(None, _run_builtin), timeout=timeout_sec)
                return await loop.run_in_executor(None, _run_builtin)
            except asyncio.TimeoutError:
                now = _utc_iso()
                return ExecuteResult(
                    status="timeout",
                    evidence_refs=(),
                    artifact_refs=(),
                    error_code="E_TIMEOUT",
                    timing=ExecuteTiming(started_at=now, ended_at=now),
                    target="local",
                )

        # Fail-closed on registry refs that cannot be resolved.
        if registry_id is None and req.operator_ref.startswith("registry://"):
            evidence = FileEvidenceStore(data_dir=str(self._data_dir))
            trace = FileTraceLogger(data_dir=str(self._data_dir))
            started_at = _utc_iso()
            err_ref = evidence.add_json(
                {
                    "schema_version": "1.0.0",
                    "ok": False,
                    "error_code": "E_EXECUTION_FAILED",
                    "message": f"registry operator_ref not resolvable: {req.operator_ref}",
                },
                kind="error",
            )
            trace.emit(
                TraceEvent(
                    schema_version="1.0.0",
                    ctx=req.trace,
                    event_type="ERROR",
                    ts=_utc_iso(),
                    evidence_refs=(err_ref,),
                    data={"operator_ref": req.operator_ref, "error_code": "E_EXECUTION_FAILED"},
                )
            )
            ended_at = _utc_iso()
            return ExecuteResult(
                status="rejected",
                evidence_refs=(err_ref,),
                artifact_refs=(),
                error_code="E_EXECUTION_FAILED",
                timing=ExecuteTiming(started_at=started_at, ended_at=ended_at),
                target="local",
            )

        try:
            if timeout_sec:
                run_result = await asyncio.wait_for(
                    loop.run_in_executor(None, self._runner.run, package_req),
                    timeout=timeout_sec,
                )
            else:
                run_result = await loop.run_in_executor(None, self._runner.run, package_req)
            res = package_run_result_to_execute_result(run_result)
            if resolution_ref is None:
                return res
            # Prepend resolution evidence to preserve replayability.
            return ExecuteResult(
                status=res.status,
                evidence_refs=(resolution_ref, *tuple(res.evidence_refs)),
                artifact_refs=tuple(res.artifact_refs),
                error_code=res.error_code,
                timing=res.timing,
                target=res.target,
            )
        except asyncio.TimeoutError:
            now = _utc_iso()
            return ExecuteResult(
                status="timeout",
                evidence_refs=(),
                artifact_refs=(),
                error_code="E_TIMEOUT",
                timing=ExecuteTiming(started_at=now, ended_at=now),
                target="local",
            )
        except Exception as _exc:
            evidence = FileEvidenceStore(data_dir=str(self._data_dir))
            trace = FileTraceLogger(data_dir=str(self._data_dir))
            now = _utc_iso()
            err_ref = evidence.add_json(
                {
                    "schema_version": "1.0.0",
                    "ok": False,
                    "error_code": "E_EXECUTION_FAILED",
                    "message": str(_exc),
                    "operator_ref": req.operator_ref,
                },
                kind="error",
            )
            ers = ((resolution_ref,) if resolution_ref is not None else ()) + (err_ref,)
            trace.emit(
                TraceEvent(
                    schema_version="1.0.0",
                    ctx=req.trace,
                    event_type="ERROR",
                    ts=now,
                    evidence_refs=ers,
                    data={"operator_ref": req.operator_ref, "error_code": "E_EXECUTION_FAILED"},
                )
            )
            return ExecuteResult(
                status="failed",
                evidence_refs=ers,
                artifact_refs=(),
                error_code="E_EXECUTION_FAILED",
                timing=ExecuteTiming(started_at=now, ended_at=now),
                target="local",
            )


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


def _optional_path(value: Any) -> Path | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return Path(text)


def _load_skill_risk_level(skill_dir: Path | None) -> str | None:
    if skill_dir is None:
        return None
    try:
        root = skill_dir.resolve()
    except Exception:
        return None
    if not root.exists() or not root.is_dir():
        return None
    contract_path = root / "contract.skill"
    if not contract_path.exists():
        return None
    try:
        return str(load_contract(str(contract_path)).risk_level or "").strip().lower() or None
    except Exception:
        return None
