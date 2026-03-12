from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from uuid import uuid4

from agentos_next.kernel.evidence_store import FileEvidenceStore
from agentos_next.kernel.local_skill_approval import resolve_local_skill_approval_context
from agentos_next.kernel.trace_logger import FileTraceLogger
from agentos_next.kernel.types import EvidenceRef, TraceContext, TraceEvent
from agentos_next.llm import (
    CodexOAuthLLMBackend,
    DoubaoArkLLMBackend,
    LLMSafetyGate,
    LocalMockLLMBackend,
    MiniMaxLLMBackend,
    OpenAICodexOAuthProvider,
    RemoteLLMCallBudget,
)
from agentos_next.skills.llm_execution import SkillExecutionError, execute_skill_via_llm
from agentos_next.skills.package_loader import SkillPackage, SkillPackageLoader
from agentos_next.skills.runtime_guard import validate_post_execution, validate_pre_execution
from agentos_next.runtime.local_skill_approval_store import LocalSkillApprovalStore


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


@dataclass(frozen=True)
class PackageRunRequest:
    skill_dir: Path
    input_obj: dict[str, Any]
    workspace_id: str
    trace: TraceContext
    verify_asvp: bool = True
    public_keys_dir: Optional[Path] = None

    backend: str = "local_mock"  # local_mock | codex_oauth | doubao_ark | minimax
    model_id_override: Optional[str] = None

    # LLM safety gate (ADR-0007 double gate)
    remote_calls_armed: bool = False
    allow_network_egress: bool = False
    approved_by_human: bool = False

    # When True, forbids any remote calls regardless of other flags.
    replay_mode: bool = False
    budget_slice: Optional[int] = None
    policy_context: Optional[dict[str, Any]] = None


@dataclass(frozen=True)
class PackageRunResult:
    ok: bool
    output: Optional[dict[str, Any]]
    error_code: Optional[str]
    evidence_refs: tuple[EvidenceRef, ...]
    trace: TraceContext


class PackageRunner:
    """MVP: load a skill package and execute it via an LLM backend with evidence+trace."""

    schema_version: str = "1.0.0"

    def __init__(self, *, evidence: FileEvidenceStore, trace: FileTraceLogger) -> None:
        self._evidence = evidence
        self._trace = trace

    @classmethod
    def for_data_dir(cls, data_dir: str | Path = "data") -> PackageRunner:
        return cls(evidence=FileEvidenceStore(data_dir=data_dir), trace=FileTraceLogger(data_dir=data_dir))

    def run(self, req: PackageRunRequest) -> PackageRunResult:
        evidence_refs: list[EvidenceRef] = []
        data_dir = Path(getattr(self._evidence, "_data_dir", Path("data")))

        pkg = self._load_package(req)
        pkg_ref = self._evidence.add_json(
            {
                "schema_version": self.schema_version,
                "skill_dir": str(req.skill_dir),
                "contract": {
                    "name": pkg.contract.name,
                    "version": pkg.contract.version,
                    "risk_level": pkg.contract.risk_level,
                },
            },
            kind="snapshot",
        )
        evidence_refs.append(pkg_ref)

        input_ref = self._evidence.add_json(
            {"schema_version": self.schema_version, "skill": pkg.contract.name, "input": req.input_obj},
            kind="tool_io",
        )
        evidence_refs.append(input_ref)

        local_skill_requires_approval = False
        local_skill_fingerprint = ""
        local_skill_ctx = resolve_local_skill_approval_context(
            operator_ref=str(req.skill_dir),
            skill_dir=req.skill_dir,
            verify_asvp=bool(req.verify_asvp),
            policy_context=req.policy_context,
        )
        if local_skill_ctx is not None:
            local_skill_fingerprint = str(local_skill_ctx.fingerprint or "").strip()
            approval_mode = (
                str(local_skill_ctx.approval_mode or "once").strip()
                or "once"
            )
            if approval_mode not in {"once", "remember_by_fingerprint"}:
                approval_mode = "once"
            approval_store = LocalSkillApprovalStore(data_dir=data_dir)
            remembered = bool(local_skill_fingerprint) and approval_store.is_approved(fingerprint=local_skill_fingerprint)
            local_skill_requires_approval = not remembered and not bool(req.approved_by_human)
            local_skill_policy = {
                "schema_version": self.schema_version,
                "type": "local_unsigned_skill_policy_v1",
                "skill": pkg.contract.name,
                "skill_dir": str(req.skill_dir),
                "fingerprint": local_skill_fingerprint or None,
                "verify_asvp": False,
                "approval_mode": approval_mode,
                "remembered": remembered,
                "approved_by_human": bool(req.approved_by_human),
                "decision": "allow" if (remembered or bool(req.approved_by_human)) else "ask",
            }
            local_skill_policy_ref = self._evidence.add_json(local_skill_policy, kind="policy")
            evidence_refs.append(local_skill_policy_ref)
            self._trace.emit(
                TraceEvent(
                    schema_version=self.schema_version,
                    ctx=req.trace,
                    event_type="POLICY_DECIDED",
                    ts=_utc_iso(),
                    evidence_refs=(local_skill_policy_ref,),
                    data={
                        "skill": pkg.contract.name,
                        "decision": local_skill_policy["decision"],
                        "policy_type": "local_unsigned_skill",
                    },
                )
            )
            if remembered or bool(req.approved_by_human):
                if approval_mode == "remember_by_fingerprint" and bool(req.approved_by_human) and local_skill_fingerprint:
                    approval_store.remember(
                        fingerprint=local_skill_fingerprint,
                        skill_dir=req.skill_dir,
                    )
            else:
                self._trace.emit(
                    TraceEvent(
                        schema_version=self.schema_version,
                        ctx=req.trace,
                        event_type="TOOL_CALL_FINISHED",
                        ts=_utc_iso(),
                        evidence_refs=(local_skill_policy_ref,),
                        data={"skill": pkg.contract.name, "ok": False},
                    )
                )
                return PackageRunResult(
                    ok=False,
                    output=None,
                    error_code="E_HITL_REQUIRED",
                    evidence_refs=tuple(evidence_refs),
                    trace=req.trace,
                )

        # Policy: MVP risk-based HITL gate.
        requires_approval = str(pkg.contract.risk_level or "").lower() in {"high", "critical"}
        policy = {
            "schema_version": self.schema_version,
            "decision": "allow" if not requires_approval else ("allow" if req.approved_by_human else "ask"),
            "policy_disposition": "allow" if not requires_approval else ("allow" if req.approved_by_human else "ask"),
            "requires_human_approval": requires_approval or local_skill_requires_approval,
            "approved_by_human": bool(req.approved_by_human),
        }
        policy_ref = self._evidence.add_json(policy, kind="policy")
        evidence_refs.append(policy_ref)
        self._trace.emit(
            TraceEvent(
                schema_version=self.schema_version,
                ctx=req.trace,
                event_type="POLICY_DECIDED",
                ts=_utc_iso(),
                evidence_refs=(policy_ref,),
                data={"skill": pkg.contract.name, "decision": policy["decision"]},
            )
        )
        if requires_approval and not req.approved_by_human:
            self._trace.emit(
                TraceEvent(
                    schema_version=self.schema_version,
                    ctx=req.trace,
                    event_type="TOOL_CALL_FINISHED",
                    ts=_utc_iso(),
                    evidence_refs=(policy_ref,),
                    data={"skill": pkg.contract.name, "ok": False},
                )
            )
            return PackageRunResult(
                ok=False,
                output=None,
                error_code="E_HITL_REQUIRED",
                evidence_refs=tuple(evidence_refs),
                trace=req.trace,
            )

        # Precheck: compile-time acceptance rules.
        pre = validate_pre_execution(req.input_obj, pkg.artifacts.acceptance_rules)
        pre_ref = self._evidence.add_json(
            {"schema_version": self.schema_version, "ok": pre.ok, "violations": list(pre.violations)},
            kind="policy",
        )
        evidence_refs.append(pre_ref)
        if not pre.ok:
            self._trace.emit(
                TraceEvent(
                    schema_version=self.schema_version,
                    ctx=req.trace,
                    event_type="ERROR",
                    ts=_utc_iso(),
                    evidence_refs=(pre_ref,),
                    data={"skill": pkg.contract.name, "error_code": "E_PRECHECK_FAIL"},
                )
            )
            return PackageRunResult(
                ok=False,
                output=None,
                error_code="E_PRECHECK_FAIL",
                evidence_refs=tuple(evidence_refs),
                trace=req.trace,
            )

        self._trace.emit(
            TraceEvent(
                schema_version=self.schema_version,
                ctx=req.trace,
                event_type="TOOL_CALL_STARTED",
                ts=_utc_iso(),
                evidence_refs=(pkg_ref, input_ref),
                data={"skill": pkg.contract.name, "skill_version": pkg.contract.version},
            )
        )

        safety = LLMSafetyGate(
            remote_calls_armed=req.remote_calls_armed,
            allow_network_egress=req.allow_network_egress,
            requires_human_approval=requires_approval,
            approved_by_human=bool(req.approved_by_human),
            replay_mode=bool(req.replay_mode),
            remote_llm_calls_budget=(
                RemoteLLMCallBudget(req.budget_slice)
                if isinstance(req.budget_slice, int) and not isinstance(req.budget_slice, bool) and req.budget_slice >= 0
                else None
            ),
        )

        backend = self._pick_backend(req)
        start = time.time()
        try:
            ex = execute_skill_via_llm(
                pkg=pkg,
                input_obj=req.input_obj,
                backend=backend,
                safety=safety,
                model_id_override=req.model_id_override,
                policy_context=req.policy_context,
                stream_callback=(
                    req.policy_context.get("llm_stream_callback")
                    if isinstance(req.policy_context, dict) and callable(req.policy_context.get("llm_stream_callback"))
                    else None
                ),
            )
        except SkillExecutionError as e:
            err_ref = self._evidence.add_json(
                {"schema_version": self.schema_version, "error_code": e.error_code, "message": str(e)},
                kind="error",
            )
            evidence_refs.append(err_ref)
            self._trace.emit(
                TraceEvent(
                    schema_version=self.schema_version,
                    ctx=req.trace,
                    event_type="ERROR",
                    ts=_utc_iso(),
                    evidence_refs=(err_ref,),
                    data={"skill": pkg.contract.name, "error_code": e.error_code},
                )
            )
            self._trace.emit(
                TraceEvent(
                    schema_version=self.schema_version,
                    ctx=req.trace,
                    event_type="TOOL_CALL_FINISHED",
                    ts=_utc_iso(),
                    evidence_refs=(err_ref,),
                    data={"skill": pkg.contract.name, "ok": False},
                )
            )
            return PackageRunResult(
                ok=False,
                output=None,
                error_code=e.error_code,
                evidence_refs=tuple(evidence_refs),
                trace=req.trace,
            )
        latency_ms = int((time.time() - start) * 1000)

        prompt_ref = self._evidence.add_text(ex.prompt, kind="llm_io")
        evidence_refs.append(prompt_ref)
        output_ref = self._evidence.add_json(
            {"schema_version": self.schema_version, "output": ex.output, "backend": ex.backend},
            kind="llm_io",
        )
        evidence_refs.append(output_ref)

        post = validate_post_execution(ex.output, {"latency_ms": latency_ms}, pkg.artifacts.acceptance_rules)
        post_ref = self._evidence.add_json(
            {"schema_version": self.schema_version, "ok": post.ok, "violations": list(post.violations), "latency_ms": latency_ms},
            kind="policy",
        )
        evidence_refs.append(post_ref)
        if not post.ok:
            self._trace.emit(
                TraceEvent(
                    schema_version=self.schema_version,
                    ctx=req.trace,
                    event_type="ERROR",
                    ts=_utc_iso(),
                    evidence_refs=(post_ref,),
                    data={"skill": pkg.contract.name, "error_code": "E_POSTCHECK_FAIL"},
                )
            )
            self._trace.emit(
                TraceEvent(
                    schema_version=self.schema_version,
                    ctx=req.trace,
                    event_type="TOOL_CALL_FINISHED",
                    ts=_utc_iso(),
                    evidence_refs=(prompt_ref, output_ref, post_ref),
                    data={"skill": pkg.contract.name, "ok": False},
                )
            )
            return PackageRunResult(
                ok=False,
                output=None,
                error_code="E_POSTCHECK_FAIL",
                evidence_refs=tuple(evidence_refs),
                trace=req.trace,
            )

        self._trace.emit(
            TraceEvent(
                schema_version=self.schema_version,
                ctx=req.trace,
                event_type="TOOL_CALL_FINISHED",
                ts=_utc_iso(),
                evidence_refs=(prompt_ref, output_ref, post_ref),
                data={"skill": pkg.contract.name, "ok": True, "latency_ms": latency_ms},
            )
        )

        return PackageRunResult(
            ok=True,
            output=ex.output,
            error_code=None,
            evidence_refs=tuple(evidence_refs),
            trace=req.trace,
        )

    def _load_package(self, req: PackageRunRequest) -> SkillPackage:
        loader = SkillPackageLoader(
            public_keys_dir=req.public_keys_dir,
            verify_asvp=req.verify_asvp,
            require_compiled_artifacts=True,
        )
        return loader.load(req.skill_dir)

    def _pick_backend(self, req: PackageRunRequest):
        backend_name = str(req.backend or "local_mock").strip().lower()
        if backend_name == "local_mock":
            return LocalMockLLMBackend()
        if backend_name == "codex_oauth":
            provider = OpenAICodexOAuthProvider(
                remote_calls_armed=req.remote_calls_armed,
                allow_network_egress=req.allow_network_egress,
            )
            return CodexOAuthLLMBackend(provider)
        if backend_name == "doubao_ark":
            return DoubaoArkLLMBackend()
        if backend_name == "minimax":
            return MiniMaxLLMBackend()
        raise ValueError(f"unknown backend: {req.backend}")
