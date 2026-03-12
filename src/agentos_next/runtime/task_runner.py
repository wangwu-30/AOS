from __future__ import annotations

import asyncio
import importlib
import importlib.util
import inspect
import json
import os
import traceback
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional
from uuid import uuid4

from agentos_next.compiler.skill_contract import SkillContract, load_contract_from_dict
from agentos_next.kernel.evidence_store import FileEvidenceStore
from agentos_next.kernel.trace_logger import FileTraceLogger
from agentos_next.kernel.types import EvidenceRef, TraceContext, TraceEvent


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


class SkillLoadError(RuntimeError):
    pass


class SkillExecutionError(RuntimeError):
    pass


@dataclass(frozen=True)
class SkillInvocation:
    contract: SkillContract
    contract_path: Optional[Path]
    input: dict[str, Any]
    workspace_id: str
    trace: TraceContext


@dataclass(frozen=True)
class SkillInvocationResult:
    ok: bool
    output: Optional[Any]
    error: Optional[str]
    evidence_refs: tuple[EvidenceRef, ...]
    trace: TraceContext


class TaskRunner:
    """Minimal local runner for a single skill invocation."""

    def __init__(
        self,
        *,
        evidence: FileEvidenceStore,
        trace: FileTraceLogger,
    ) -> None:
        self._evidence = evidence
        self._trace = trace

    @classmethod
    def for_data_dir(cls, data_dir: str | os.PathLike[str] = "data") -> TaskRunner:
        return cls(evidence=FileEvidenceStore(data_dir=data_dir), trace=FileTraceLogger(data_dir=data_dir))

    def run(self, inv: SkillInvocation) -> SkillInvocationResult:
        evidence_refs: list[EvidenceRef] = []

        contract_ref = self._evidence.add_json(
            {
                "name": inv.contract.name,
                "version": inv.contract.version,
                "description": inv.contract.description,
                "inputs_schema": inv.contract.inputs_schema,
                "outputs_schema": inv.contract.outputs_schema,
                "logic": inv.contract.logic,
            },
            kind="snapshot",
        )
        evidence_refs.append(contract_ref)

        input_ref = self._evidence.add_json(
            {"skill": inv.contract.name, "input": inv.input, "workspace_id": inv.workspace_id},
            kind="tool_io",
        )
        evidence_refs.append(input_ref)

        self._trace.emit(
            TraceEvent(
                schema_version="1.0.0",
                ctx=inv.trace,
                event_type="TOOL_CALL_STARTED",
                ts=_utc_iso(),
                evidence_refs=(contract_ref, input_ref),
                data={"skill": inv.contract.name, "skill_version": inv.contract.version},
            )
        )

        try:
            fn = _load_python_entrypoint(inv.contract.logic, base_dir=_base_dir_for(inv.contract_path))
            output = _invoke_entrypoint(fn, inv.input, inv)
        except Exception:
            tb = traceback.format_exc()
            err_ref = self._evidence.add_text(tb, kind="error")
            evidence_refs.append(err_ref)

            self._trace.emit(
                TraceEvent(
                    schema_version="1.0.0",
                    ctx=inv.trace,
                    event_type="ERROR",
                    ts=_utc_iso(),
                    evidence_refs=(err_ref,),
                    data={"skill": inv.contract.name},
                )
            )
            self._trace.emit(
                TraceEvent(
                    schema_version="1.0.0",
                    ctx=inv.trace,
                    event_type="TOOL_CALL_FINISHED",
                    ts=_utc_iso(),
                    evidence_refs=(err_ref,),
                    data={"skill": inv.contract.name, "ok": False},
                )
            )
            return SkillInvocationResult(
                ok=False,
                output=None,
                error="E_EXECUTION_FAILED",
                evidence_refs=tuple(evidence_refs),
                trace=inv.trace,
            )

        out_ref = self._evidence.add_json({"skill": inv.contract.name, "output": output}, kind="tool_io")
        evidence_refs.append(out_ref)

        self._trace.emit(
            TraceEvent(
                schema_version="1.0.0",
                ctx=inv.trace,
                event_type="TOOL_CALL_FINISHED",
                ts=_utc_iso(),
                evidence_refs=(out_ref,),
                data={"skill": inv.contract.name, "ok": True},
            )
        )

        return SkillInvocationResult(
            ok=True,
            output=output,
            error=None,
            evidence_refs=tuple(evidence_refs),
            trace=inv.trace,
        )


def load_skill_contract(path: str | os.PathLike[str]) -> tuple[SkillContract, Path]:
    p = Path(path)
    if not p.exists():
        raise SkillLoadError(f"skill contract not found: {p}")

    if p.suffix.lower() == ".json":
        data = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise SkillLoadError("contract JSON must be an object")
        return load_contract_from_dict(data), p

    if p.suffix.lower() in {".skill", ".yaml", ".yml"}:
        # YAML is an optional dependency; keep MVP runnable without it.
        try:
            from agentos_next.compiler.skill_contract import load_contract
        except Exception as e:  # pragma: no cover
            raise SkillLoadError("PyYAML is required to load .skill/.yaml contracts") from e
        return load_contract(str(p)), p

    # Fallback: try JSON first (no optional deps).
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        raise SkillLoadError(f"unsupported contract extension: {p.suffix}") from e
    if not isinstance(data, dict):
        raise SkillLoadError("contract JSON must be an object")
    return load_contract_from_dict(data), p


def _base_dir_for(contract_path: Optional[Path]) -> Path:
    return contract_path.parent if contract_path is not None else Path.cwd()


def _load_python_entrypoint(logic: str, *, base_dir: Path) -> Callable[..., Any]:
    # MVP convention: "python:<module_or_file>:<callable>"
    if not logic.startswith("python:"):
        raise SkillExecutionError(f"unsupported logic: {logic!r} (expected 'python:...')")
    rest = logic[len("python:") :]
    parts = rest.split(":", 1)
    if len(parts) != 2:
        raise SkillExecutionError(f"invalid logic: {logic!r} (expected 'python:<module_or_file>:<callable>')")

    mod_or_file, attr = parts[0].strip(), parts[1].strip()
    if not mod_or_file or not attr:
        raise SkillExecutionError(f"invalid logic: {logic!r}")

    module = None
    if mod_or_file.endswith(".py") or "/" in mod_or_file or "\\" in mod_or_file:
        file_path = (base_dir / mod_or_file).resolve()
        if not file_path.exists():
            raise SkillExecutionError(f"python file not found: {file_path}")
        module_name = f"_agentos_skill_{uuid4().hex}"
        spec = importlib.util.spec_from_file_location(module_name, file_path)
        if spec is None or spec.loader is None:
            raise SkillExecutionError(f"failed to load python file: {file_path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    else:
        module = importlib.import_module(mod_or_file)

    obj: Any = module
    for part in attr.split("."):
        obj = getattr(obj, part)

    if not callable(obj):
        raise SkillExecutionError(f"entrypoint not callable: {logic!r}")
    return obj  # type: ignore[return-value]


def _invoke_entrypoint(fn: Callable[..., Any], input_value: dict[str, Any], inv: SkillInvocation) -> Any:
    # Try to be friendly with different signatures while staying minimal.
    try:
        sig = inspect.signature(fn)
    except Exception:
        sig = None

    if sig is None:
        return _maybe_await(fn(input_value))

    params = sig.parameters
    has_var_kw = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values())

    pos_args: list[Any] = []
    call_kwargs: dict[str, Any] = {}

    if "input" in params:
        call_kwargs["input"] = input_value
    elif "inputs" in params:
        call_kwargs["inputs"] = input_value
    elif "payload" in params:
        call_kwargs["payload"] = input_value
    else:
        positional = [
            p
            for p in params.values()
            if p.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
        ]
        if positional:
            pos_args.append(input_value)

    extras = {"ctx": inv.trace, "workspace_id": inv.workspace_id}
    for name, value in extras.items():
        if name in params or has_var_kw:
            call_kwargs[name] = value

    return _maybe_await(fn(*pos_args, **call_kwargs))


def _maybe_await(v: Any) -> Any:
    if inspect.isawaitable(v):
        return asyncio.run(v)
    return v
