from __future__ import annotations

import json
import os
import subprocess
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


class BuiltinFsRuntimeError(RuntimeError):
    def __init__(self, error_code: str, message: str, *, payload: Optional[dict[str, Any]] = None) -> None:
        super().__init__(message)
        self.error_code = str(error_code or "E_EXECUTION_FAILED").strip() or "E_EXECUTION_FAILED"
        self.payload = dict(payload or {})


def _build_structured_error_payload(
    *,
    operator_ref: str,
    error_code: str,
    message: str,
    payload: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    out = {
        "schema_version": "1.0.0",
        "ok": False,
        "error_code": str(error_code or "E_EXECUTION_FAILED").strip() or "E_EXECUTION_FAILED",
        "message": str(message or "").strip(),
        "operator_ref": str(operator_ref or "").strip(),
    }
    if isinstance(payload, dict):
        for key, value in payload.items():
            if key in {"schema_version", "ok", "error_code", "message", "operator_ref"}:
                continue
            out[key] = value
    return out


def maybe_execute_builtin_fs(*, req: ExecuteRequest, data_dir: str) -> BuiltinDispatchResult:
    """Handle builtin://fs.* and builtin://shell.* skills."""
    if not req.operator_ref.startswith("builtin://"):
        return BuiltinDispatchResult(handled=False)

    name = req.operator_ref[len("builtin://") :].strip("/")
    if not (name.startswith("fs.") or name.startswith("shell.")):
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
        workspace_root = _workspace_root(req)

        if name == "fs.read":
            _fs_read(req=req, evidence=evidence, root=workspace_root, evidence_refs=evidence_refs)
        elif name == "fs.write":
            _fs_write(req=req, evidence=evidence, root=workspace_root, evidence_refs=evidence_refs)
        elif name == "fs.list":
            _fs_list(req=req, evidence=evidence, root=workspace_root, evidence_refs=evidence_refs)
        elif name == "shell.exec":
            _shell_exec(req=req, evidence=evidence, root=workspace_root, evidence_refs=evidence_refs)
        else:
            raise ValueError(f"unknown builtin: {name}")

    except BuiltinFsRuntimeError as e:
        err_ref = evidence.add_json(
            _build_structured_error_payload(
                operator_ref=req.operator_ref,
                error_code=e.error_code,
                message=str(e),
                payload=e.payload,
            ),
            kind="error",
        )
        evidence_refs.append(err_ref)
        _emit("ERROR", ers=(err_ref,), data={"builtin": name, "error_code": e.error_code})
        ended_at = _utc_iso()
        return BuiltinDispatchResult(
            handled=True,
            result=ExecuteResult(
                status="failed",
                evidence_refs=tuple(evidence_refs),
                artifact_refs=(),
                error_code=e.error_code,
                timing=ExecuteTiming(started_at=started_at, ended_at=ended_at),
                target="local",
            ),
        )
    except Exception as e:
        err_ref = evidence.add_json(
            _build_structured_error_payload(
                operator_ref=req.operator_ref,
                error_code="E_EXECUTION_FAILED",
                message=str(e),
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


def _require_dict(obj: Any, *, name: str) -> dict[str, Any]:
    if not isinstance(obj, dict):
        raise ValueError(f"{name} must be a JSON object")
    return obj


def _require_str(obj: Any, *, name: str, nonempty: bool = True) -> str:
    if not isinstance(obj, str):
        raise ValueError(f"{name} must be a string")
    if nonempty and not obj.strip():
        raise ValueError(f"{name} must be non-empty")
    return obj


def _workspace_root(req: ExecuteRequest) -> Path:
    policy = req.policy_context if isinstance(req.policy_context, dict) else {}
    configured = str(policy.get("workspace_root") or "").strip()
    if configured:
        return Path(os.path.expandvars(os.path.expanduser(configured))).resolve()
    return Path.cwd().resolve()


def _is_within_root(*, root: Path, path: Path) -> bool:
    root_resolved = root.resolve()
    path_resolved = path.resolve()
    return path_resolved == root_resolved or root_resolved in path_resolved.parents


def _find_subsequence(parts: tuple[str, ...], needle: tuple[str, ...]) -> int:
    if not needle or len(needle) > len(parts):
        return -1
    limit = len(parts) - len(needle) + 1
    for idx in range(limit):
        if parts[idx : idx + len(needle)] == needle:
            return idx
    return -1


def _remap_workspace_alias(root: Path, candidate: Path) -> Path | None:
    root_resolved = root.resolve()
    candidate_resolved = candidate.resolve(strict=False)
    if _is_within_root(root=root_resolved, path=candidate_resolved):
        return candidate_resolved

    root_parts = root_resolved.parts
    candidate_parts = candidate_resolved.parts
    max_anchor = min(len(root_parts), 4)
    for anchor_len in range(max_anchor, 1, -1):
        anchor = tuple(root_parts[-anchor_len:])
        idx = _find_subsequence(candidate_parts, anchor)
        if idx < 0:
            continue
        remainder = candidate_parts[idx + anchor_len :]
        remapped = (root_resolved / Path(*remainder)).resolve()
        if _is_within_root(root=root_resolved, path=remapped):
            return remapped
    return None


def _resolve_path(root: Path, raw_path: str) -> Path:
    root_resolved = root.resolve()
    path_str = str(raw_path or "").strip()
    expanded = os.path.expandvars(os.path.expanduser(path_str))
    candidate = Path(expanded) if expanded else Path(".")
    if candidate.is_absolute():
        p = _remap_workspace_alias(root_resolved, candidate)
        if p is None:
            raise ValueError(f"access denied: {raw_path} is outside workspace root")
        return p
    p = (root_resolved / candidate).resolve()
    if not _is_within_root(root=root_resolved, path=p):
        raise ValueError(f"access denied: {raw_path} is outside workspace root")
    return p


def _fs_read(*, req: ExecuteRequest, evidence: FileEvidenceStore, root: Path, evidence_refs: list[EvidenceRef]) -> None:
    inp = _require_dict(req.arguments, name="arguments")
    path_str = _require_str(inp.get("path"), name="path")
    p = _resolve_path(root, path_str)

    if not p.exists():
        raise ValueError(f"file not found: {path_str}")
    if not p.is_file():
        raise ValueError(f"not a file: {path_str}")

    content = p.read_text(encoding="utf-8")
    out = {"schema_version": "1.0.0", "ok": True, "content": content}
    out_ref = evidence.add_json(out, kind="tool_io")
    evidence_refs.append(out_ref)


def _fs_write(*, req: ExecuteRequest, evidence: FileEvidenceStore, root: Path, evidence_refs: list[EvidenceRef]) -> None:
    inp = _require_dict(req.arguments, name="arguments")
    path_str = _require_str(inp.get("path"), name="path")
    content = _require_str(inp.get("content"), name="content", nonempty=False)
    p = _resolve_path(root, path_str)

    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")

    out = {"schema_version": "1.0.0", "ok": True}
    out_ref = evidence.add_json(out, kind="tool_io")
    evidence_refs.append(out_ref)


def _fs_list(*, req: ExecuteRequest, evidence: FileEvidenceStore, root: Path, evidence_refs: list[EvidenceRef]) -> None:
    inp = _require_dict(req.arguments, name="arguments")
    path_str = _require_str(inp.get("path", "."), name="path", nonempty=False)
    p = _resolve_path(root, path_str)

    if not p.exists():
        raise ValueError(f"directory not found: {path_str}")
    if not p.is_dir():
        raise ValueError(f"not a directory: {path_str}")

    items = []
    for entry in p.iterdir():
        items.append({
            "name": entry.name,
            "is_dir": entry.is_dir(),
            "size": entry.stat().st_size if entry.is_file() else None
        })

    out = {"schema_version": "1.0.0", "ok": True, "items": items}
    out_ref = evidence.add_json(out, kind="tool_io")
    evidence_refs.append(out_ref)


def _shell_exec(*, req: ExecuteRequest, evidence: FileEvidenceStore, root: Path, evidence_refs: list[EvidenceRef]) -> None:
    inp = _require_dict(req.arguments, name="arguments")
    command = _require_str(inp.get("command"), name="command")
    cwd_str = _require_str(inp.get("cwd", "."), name="cwd", nonempty=False)
    cwd = _resolve_path(root, cwd_str)

    # Use subprocess.run for MVP. In real system, we'd want timeouts and isolation.
    try:
        res = subprocess.run(
            command,
            cwd=cwd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=30.0
        )
        out = {
            "schema_version": "1.0.0",
            "ok": True,
            "stdout": res.stdout,
            "stderr": res.stderr,
            "exit_code": res.returncode,
            "command": command,
            "cwd": cwd_str or ".",
        }
    except subprocess.TimeoutExpired as e:
        raise BuiltinFsRuntimeError(
            "E_TIMEOUT",
            "command timed out",
            payload={
                "command": command,
                "cwd": cwd_str or ".",
                "stdout": e.stdout.decode() if isinstance(e.stdout, bytes) else (e.stdout or ""),
                "stderr": e.stderr.decode() if isinstance(e.stderr, bytes) else (e.stderr or ""),
            },
        ) from e

    out_ref = evidence.add_json(out, kind="tool_io")
    evidence_refs.append(out_ref)
