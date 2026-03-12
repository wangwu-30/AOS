from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from agentos_next.kernel.evidence_store import FileEvidenceStore
from agentos_next.kernel.trace_logger import FileTraceLogger
from agentos_next.kernel.types import EvidenceRef, TraceContext, TraceEvent


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


_RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def _normalize_run_id(run_id: str) -> str:
    rid = str(run_id or "").strip()
    if not rid:
        raise ValueError("run_id must be non-empty")
    if "/" in rid or "\\" in rid or ".." in rid:
        raise ValueError("run_id must not contain path separators or '..'")
    if not _RUN_ID_RE.fullmatch(rid):
        raise ValueError("run_id must match ^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
    return rid


def _write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


@dataclass(frozen=True)
class SI1Run:
    run_id: str
    run_dir: Path
    trace_id: str

    @property
    def signals_path(self) -> Path:
        return self.run_dir / "signals.json"

    @property
    def proposal_path(self) -> Path:
        return self.run_dir / "proposal.json"

    @property
    def validation_path(self) -> Path:
        return self.run_dir / "validation.json"


def _default_run_dir(data_dir: Path, run_id: str) -> Path:
    run_root = (data_dir / "si1" / "runs").resolve()
    run_root.mkdir(parents=True, exist_ok=True)
    run_dir = (run_root / _normalize_run_id(run_id)).resolve()
    if not run_dir.is_relative_to(run_root):
        raise ValueError("run_id resolves outside si1/runs root")
    return run_dir


def _policy_blocked(*, run_id: str | None, message: str) -> dict[str, Any]:
    return {
        "ok": False,
        "error_code": "E_SI1_POLICY_VIOLATION",
        "message": message,
        "run_id": run_id,
    }


def _safe_add_json_evidence(
    *, evidence: FileEvidenceStore, value: Any, kind: str, fallback_error_code: str
) -> tuple[EvidenceRef | None, str | None]:
    try:
        ev = evidence.add_json(value, kind=kind)  # type: ignore[arg-type]
        return ev, None
    except Exception as e:
        # Keep error strings stable and non-sensitive.
        return None, f"{fallback_error_code}:{e.__class__.__name__}"


def _safe_emit_trace(
    *,
    trace_log: FileTraceLogger,
    trace_id: str,
    stage: str,
    evidence_refs: tuple[EvidenceRef, ...],
    event_type: str = "TOOL_CALL_FINISHED",
    data: dict[str, Any] | None = None,
) -> str | None:
    try:
        _emit_si1_trace_event(
            trace_log=trace_log,
            trace_id=trace_id,
            stage=stage,
            evidence_refs=evidence_refs,
            event_type=event_type,
            data=data,
        )
        return None
    except Exception as e:
        return f"E_SI1_TRACE_EMIT_FAILED:{e.__class__.__name__}"


def _emit_si1_trace_event(
    *,
    trace_log: FileTraceLogger,
    trace_id: str,
    stage: str,
    evidence_refs: tuple[EvidenceRef, ...],
    event_type: str = "TOOL_CALL_FINISHED",
    data: dict[str, Any] | None = None,
) -> None:
    ctx = TraceContext(trace_id=trace_id, turn_id="turn_si1", span_id=f"span_{stage}", parent_span_id=None)
    trace_log.emit(
        TraceEvent(
            schema_version="1.0.0",
            ctx=ctx,
            event_type=event_type,  # type: ignore[arg-type]
            ts=_utc_now_iso(),
            evidence_refs=evidence_refs,
            data={"si1_stage": stage, **(data or {})},
        )
    )


def _scan_evidence_meta(meta_dir: Path) -> dict[str, Any]:
    by_kind: dict[str, int] = {}
    total = 0
    for p in sorted(meta_dir.glob("*.json")):
        try:
            obj = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        kind = obj.get("kind")
        if isinstance(kind, str):
            by_kind[kind] = by_kind.get(kind, 0) + 1
        total += 1
    return {"count": total, "by_kind": dict(sorted(by_kind.items()))}


def _scan_traces(traces_dir: Path) -> dict[str, Any]:
    by_event_type: dict[str, int] = {}
    total = 0
    for p in sorted(traces_dir.glob("*.jsonl")):
        for raw in p.read_text(encoding="utf-8").splitlines():
            if not raw.strip():
                continue
            try:
                obj = json.loads(raw)
            except Exception:
                continue
            et = obj.get("event_type")
            if isinstance(et, str):
                by_event_type[et] = by_event_type.get(et, 0) + 1
            total += 1
    return {"count": total, "by_event_type": dict(sorted(by_event_type.items()))}


def si1_observe(*, data_dir: str | os.PathLike[str], run_id: str | None = None, replay_mode: bool = False) -> dict[str, Any]:
    """Phase-1: Observe.

    Local-only scan of evidence/trace to produce a structured signals.json + evidence snapshot.
    """
    if replay_mode:
        # replay-mode MUST produce no new persistent side effects.
        return _policy_blocked(run_id=run_id, message="replay_mode forbids SI1 persistence")

    dd = Path(data_dir)
    try:
        rid = _normalize_run_id(run_id or _new_id("si1"))
        run_dir = _default_run_dir(dd, rid)
    except ValueError as e:
        return {
            "ok": False,
            "error_code": "E_SI1_OBSERVE_FAILED",
            "message": str(e),
            "run_id": run_id,
        }
    trace_id = f"si1_{rid}"

    evidence = FileEvidenceStore(data_dir=dd)
    trace_log = FileTraceLogger(data_dir=dd)

    signals = {
        "schema_version": "1.0.0",
        "run_id": rid,
        "created_at_utc": _utc_now_iso(),
        "data_dir": str(dd),
        "evidence_meta": _scan_evidence_meta(dd / "evidence" / "meta"),
        "traces": _scan_traces(dd / "traces"),
    }
    try:
        _write_json(run_dir / "signals.json", signals)
    except Exception as e:
        # Fail-closed: try to record an error evidence/trace, but don't raise.
        err = {"schema_version": "1.0.0", "type": "si1_observe_error", "run_id": rid, "message": e.__class__.__name__}
        ev, ev_err = _safe_add_json_evidence(
            evidence=evidence,
            value=err,
            kind="error",
            fallback_error_code="E_SI1_OBSERVE_FAILED",
        )
        _safe_emit_trace(
            trace_log=trace_log,
            trace_id=trace_id,
            stage="observe",
            evidence_refs=((ev,) if ev else ()),
            event_type="ERROR",
            data={"error_code": "E_SI1_OBSERVE_FAILED", "evidence_error": ev_err},
        )
        return {
            "ok": False,
            "error_code": "E_SI1_OBSERVE_FAILED",
            "message": "failed to write signals.json",
            "run_id": rid,
            "run_dir": str(run_dir),
            "trace_id": trace_id,
            "evidence_refs": [ev.ref] if ev else [],
        }

    ev, ev_err = _safe_add_json_evidence(
        evidence=evidence,
        value={"schema_version": "1.0.0", "type": "si1_observe_signals", "run_id": rid, "signals": signals},
        kind="snapshot",
        fallback_error_code="E_SI1_OBSERVE_FAILED",
    )
    trace_err = _safe_emit_trace(
        trace_log=trace_log,
        trace_id=trace_id,
        stage="observe",
        evidence_refs=((ev,) if ev else ()),
        event_type="TOOL_CALL_FINISHED",
        data={"evidence_error": ev_err},
    )

    return {
        "ok": True,
        "error_code": None,
        "run_id": rid,
        "run_dir": str(run_dir),
        "trace_id": trace_id,
        "signals_path": str(run_dir / "signals.json"),
        "evidence_refs": [ev.ref] if ev else [],
        "warnings": [x for x in [ev_err, trace_err] if x],
    }


def si1_propose(*, data_dir: str | os.PathLike[str], run_id: str, replay_mode: bool = False) -> dict[str, Any]:
    """Phase-1: Propose (deterministic, rule-based)."""
    if replay_mode:
        return _policy_blocked(run_id=run_id, message="replay_mode forbids SI1 persistence")

    dd = Path(data_dir)
    try:
        rid = _normalize_run_id(run_id)
        run_dir = _default_run_dir(dd, rid)
    except ValueError as e:
        return {
            "ok": False,
            "error_code": "E_SI1_PROPOSAL_INVALID",
            "message": str(e),
            "run_id": run_id,
        }
    trace_id = f"si1_{rid}"

    evidence = FileEvidenceStore(data_dir=dd)
    trace_log = FileTraceLogger(data_dir=dd)

    signals_path = run_dir / "signals.json"
    try:
        signals = json.loads(signals_path.read_text(encoding="utf-8"))
    except Exception as e:
        # Fail-closed: stable error code + error evidence + trace event (no traceback leakage to caller).
        proposal_err = {
            "schema_version": "1.0.0",
            "run_id": rid,
            "created_at_utc": _utc_now_iso(),
            "ok": False,
            "error_code": "E_SI1_PROPOSAL_INVALID",
            "message": f"missing/invalid signals.json: {e.__class__.__name__}",
            "signals_path": str(signals_path),
        }
        _write_json(run_dir / "proposal.json", proposal_err)
        ev, ev_err = _safe_add_json_evidence(
            evidence=evidence,
            value={"schema_version": "1.0.0", "type": "si1_propose_error", "run_id": rid, "error": proposal_err},
            kind="error",
            fallback_error_code="E_SI1_PROPOSAL_INVALID",
        )
        trace_err = _safe_emit_trace(
            trace_log=trace_log,
            trace_id=trace_id,
            stage="propose",
            evidence_refs=((ev,) if ev else ()),
            event_type="ERROR",
            data={"error_code": "E_SI1_PROPOSAL_INVALID", "evidence_error": ev_err},
        )
        return {
            "ok": False,
            "error_code": "E_SI1_PROPOSAL_INVALID",
            "run_id": rid,
            "run_dir": str(run_dir),
            "trace_id": trace_id,
            "proposal_path": str(run_dir / "proposal.json"),
            "evidence_refs": [ev.ref] if ev else [],
            "warnings": [x for x in [ev_err, trace_err] if x],
        }

    if not isinstance(signals, dict) or signals.get("run_id") != rid:
        proposal_err = {
            "schema_version": "1.0.0",
            "run_id": rid,
            "created_at_utc": _utc_now_iso(),
            "ok": False,
            "error_code": "E_SI1_PROPOSAL_INVALID",
            "message": "signals.json schema invalid or run_id mismatch",
            "signals_path": str(signals_path),
        }
        _write_json(run_dir / "proposal.json", proposal_err)
        ev, ev_err = _safe_add_json_evidence(
            evidence=evidence,
            value={"schema_version": "1.0.0", "type": "si1_propose_error", "run_id": rid, "error": proposal_err},
            kind="error",
            fallback_error_code="E_SI1_PROPOSAL_INVALID",
        )
        trace_err = _safe_emit_trace(
            trace_log=trace_log,
            trace_id=trace_id,
            stage="propose",
            evidence_refs=((ev,) if ev else ()),
            event_type="ERROR",
            data={"error_code": "E_SI1_PROPOSAL_INVALID", "evidence_error": ev_err},
        )
        return {
            "ok": False,
            "error_code": "E_SI1_PROPOSAL_INVALID",
            "run_id": rid,
            "run_dir": str(run_dir),
            "trace_id": trace_id,
            "proposal_path": str(run_dir / "proposal.json"),
            "evidence_refs": [ev.ref] if ev else [],
            "warnings": [x for x in [ev_err, trace_err] if x],
        }

    # Deterministic heuristics: propose a no-op patch by default, but capture observed stats + next steps.
    by_kind = ((signals.get("evidence_meta") or {}) if isinstance(signals.get("evidence_meta"), dict) else {}).get("by_kind")
    by_event = ((signals.get("traces") or {}) if isinstance(signals.get("traces"), dict) else {}).get("by_event_type")
    summary = {
        "evidence_kinds": dict(by_kind) if isinstance(by_kind, dict) else {},
        "trace_event_types": dict(by_event) if isinstance(by_event, dict) else {},
    }

    proposal = {
        "schema_version": "1.0.0",
        "run_id": rid,
        "created_at_utc": _utc_now_iso(),
        "intent": "stabilize_and_audit",
        "scope": {"touched_paths": [], "notes": "Phase-1 proposes no code changes by default (no Promote)."},
        "evidence_refs": [],
        "risk": {"level": "low", "rollback": "n/a (no changes)"},
        "validation_plan": {"must_run_unittests": True, "command": "PYTHONPATH=src python3 -m unittest discover -s tests -v"},
        "summary": summary,
        "suggested_actions": [
            "If error evidence grows, add a bounded spike for the top error_code with tests and kill criteria.",
            "Keep ExecuteRequest top-level stable; use policy_context for extensions.",
        ],
    }
    _write_json(run_dir / "proposal.json", proposal)

    ev, ev_err = _safe_add_json_evidence(
        evidence=evidence,
        value={"schema_version": "1.0.0", "type": "si1_proposal", "run_id": rid, "proposal": proposal},
        kind="snapshot",
        fallback_error_code="E_SI1_PROPOSAL_INVALID",
    )
    trace_err = _safe_emit_trace(
        trace_log=trace_log,
        trace_id=trace_id,
        stage="propose",
        evidence_refs=((ev,) if ev else ()),
        event_type="TOOL_CALL_FINISHED",
        data={"evidence_error": ev_err},
    )

    return {
        "ok": True,
        "error_code": None,
        "run_id": rid,
        "run_dir": str(run_dir),
        "trace_id": trace_id,
        "proposal_path": str(run_dir / "proposal.json"),
        "evidence_refs": [ev.ref] if ev else [],
        "warnings": [x for x in [ev_err, trace_err] if x],
    }


@dataclass(frozen=True)
class _CmdRun:
    argv: list[str]
    cwd: str
    returncode: int
    stdout: str
    stderr: str


def _run(argv: list[str], cwd: Path, env: dict[str, str]) -> _CmdRun:
    p = subprocess.run(
        argv,
        cwd=str(cwd),
        env=dict(env),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    return _CmdRun(argv=list(argv), cwd=str(cwd), returncode=int(p.returncode), stdout=p.stdout or "", stderr=p.stderr or "")


def _unittest_argv() -> list[str]:
    # Phase-1 validate MUST run full unittest suite (see spec).
    return [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"]


def si1_validate(*, data_dir: str | os.PathLike[str], run_id: str, replay_mode: bool = False) -> dict[str, Any]:
    """Phase-1: Validate.

    Must run full `unittest` suite from repo root (fail-closed on any failure).
    """
    if replay_mode:
        return _policy_blocked(run_id=run_id, message="replay_mode forbids SI1 persistence")

    dd = Path(data_dir)
    try:
        rid = _normalize_run_id(run_id)
        run_dir = _default_run_dir(dd, rid)
    except ValueError as e:
        return {
            "ok": False,
            "error_code": "E_SI1_PROPOSAL_INVALID",
            "message": str(e),
            "run_id": run_id,
        }
    trace_id = f"si1_{rid}"

    evidence = FileEvidenceStore(data_dir=dd)
    trace_log = FileTraceLogger(data_dir=dd)

    proposal_path = run_dir / "proposal.json"
    try:
        proposal = json.loads(proposal_path.read_text(encoding="utf-8"))
    except Exception as e:
        validation = {
            "schema_version": "1.0.0",
            "run_id": rid,
            "created_at_utc": _utc_now_iso(),
            "ok": False,
            "error_code": "E_SI1_PROPOSAL_INVALID",
            "message": f"missing/invalid proposal.json: {e.__class__.__name__}",
            "proposal_path": str(proposal_path),
            "commands": [],
        }
        _write_json(run_dir / "validation.json", validation)
        ev, ev_err = _safe_add_json_evidence(
            evidence=evidence,
            value={"schema_version": "1.0.0", "type": "si1_validate_error", "run_id": rid, "error": validation},
            kind="error",
            fallback_error_code="E_SI1_PROPOSAL_INVALID",
        )
        trace_err = _safe_emit_trace(
            trace_log=trace_log,
            trace_id=trace_id,
            stage="validate",
            evidence_refs=((ev,) if ev else ()),
            event_type="ERROR",
            data={"error_code": "E_SI1_PROPOSAL_INVALID", "evidence_error": ev_err},
        )
        return {
            "ok": False,
            "error_code": "E_SI1_PROPOSAL_INVALID",
            "run_id": rid,
            "run_dir": str(run_dir),
            "trace_id": trace_id,
            "validation_path": str(run_dir / "validation.json"),
            "evidence_refs": [ev.ref] if ev else [],
            "warnings": [x for x in [ev_err, trace_err] if x],
        }

    if not isinstance(proposal, dict) or proposal.get("run_id") != rid:
        validation = {
            "schema_version": "1.0.0",
            "run_id": rid,
            "created_at_utc": _utc_now_iso(),
            "ok": False,
            "error_code": "E_SI1_PROPOSAL_INVALID",
            "message": "proposal.json schema invalid or run_id mismatch",
            "proposal_path": str(proposal_path),
            "commands": [],
        }
        _write_json(run_dir / "validation.json", validation)
        ev, ev_err = _safe_add_json_evidence(
            evidence=evidence,
            value={"schema_version": "1.0.0", "type": "si1_validate_error", "run_id": rid, "error": validation},
            kind="error",
            fallback_error_code="E_SI1_PROPOSAL_INVALID",
        )
        trace_err = _safe_emit_trace(
            trace_log=trace_log,
            trace_id=trace_id,
            stage="validate",
            evidence_refs=((ev,) if ev else ()),
            event_type="ERROR",
            data={"error_code": "E_SI1_PROPOSAL_INVALID", "evidence_error": ev_err},
        )
        return {
            "ok": False,
            "error_code": "E_SI1_PROPOSAL_INVALID",
            "run_id": rid,
            "run_dir": str(run_dir),
            "trace_id": trace_id,
            "validation_path": str(run_dir / "validation.json"),
            "evidence_refs": [ev.ref] if ev else [],
            "warnings": [x for x in [ev_err, trace_err] if x],
        }

    root = Path(__file__).resolve().parents[3]  # src/agentos_next/apps/si1.py -> repo root
    env = dict(os.environ)
    env["PYTHONPATH"] = str(root / "src") + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")

    # Prevent recursive self-invocation if SI1 validation is triggered from within a test run.
    if env.get("AGENTOS_NEXT_SI1_VALIDATE_RUNNING") == "1":
        validation = {
            "schema_version": "1.0.0",
            "run_id": rid,
            "created_at_utc": _utc_now_iso(),
            "ok": False,
            "error_code": "E_SI1_POLICY_VIOLATION",
            "message": "recursive si1_validate blocked (AGENTOS_NEXT_SI1_VALIDATE_RUNNING=1)",
            "commands": [],
        }
        _write_json(run_dir / "validation.json", validation)
        ev, ev_err = _safe_add_json_evidence(
            evidence=evidence,
            value={"schema_version": "1.0.0", "type": "si1_validate_error", "run_id": rid, "error": validation},
            kind="error",
            fallback_error_code="E_SI1_POLICY_VIOLATION",
        )
        trace_err = _safe_emit_trace(
            trace_log=trace_log,
            trace_id=trace_id,
            stage="validate",
            evidence_refs=((ev,) if ev else ()),
            event_type="ERROR",
            data={"error_code": "E_SI1_POLICY_VIOLATION", "evidence_error": ev_err},
        )
        return {
            "ok": False,
            "error_code": "E_SI1_POLICY_VIOLATION",
            "run_id": rid,
            "run_dir": str(run_dir),
            "trace_id": trace_id,
            "validation_path": str(run_dir / "validation.json"),
            "evidence_refs": [ev.ref] if ev else [],
            "warnings": [x for x in [ev_err, trace_err] if x],
        }

    env["AGENTOS_NEXT_SI1_VALIDATE_RUNNING"] = "1"
    cmd = _run(_unittest_argv(), cwd=root, env=env)

    validation = {
        "schema_version": "1.0.0",
        "run_id": rid,
        "created_at_utc": _utc_now_iso(),
        "ok": cmd.returncode == 0,
        "error_code": None if cmd.returncode == 0 else "E_SI1_VALIDATION_FAILED",
        "commands": [{"name": "unittest", "argv": cmd.argv, "cwd": cmd.cwd, "returncode": cmd.returncode}],
    }
    _write_json(run_dir / "validation.json", validation)

    ev_kind = "snapshot" if cmd.returncode == 0 else "error"
    ev, ev_err = _safe_add_json_evidence(
        evidence=evidence,
        value={"schema_version": "1.0.0", "type": "si1_validation", "run_id": rid, "validation": validation},
        kind=ev_kind,
        fallback_error_code="E_SI1_VALIDATION_FAILED",
    )
    trace_err = _safe_emit_trace(
        trace_log=trace_log,
        trace_id=trace_id,
        stage="validate",
        evidence_refs=((ev,) if ev else ()),
        event_type="TOOL_CALL_FINISHED" if cmd.returncode == 0 else "ERROR",
        data={"error_code": validation["error_code"], "evidence_error": ev_err},
    )

    return {
        "ok": bool(validation["ok"]),
        "error_code": validation["error_code"],
        "run_id": rid,
        "run_dir": str(run_dir),
        "trace_id": trace_id,
        "validation_path": str(run_dir / "validation.json"),
        "evidence_refs": [ev.ref] if ev else [],
        "warnings": [x for x in [ev_err, trace_err] if x],
    }
