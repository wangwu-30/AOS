from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from agentos_next.kernel.evidence_store import FileEvidenceStore
from agentos_next.kernel.executor import ExecuteRequest, ExecuteResult, ExecuteTiming
from agentos_next.kernel.trace_logger import FileTraceLogger
from agentos_next.kernel.types import EvidenceRef, TraceEvent


@dataclass(frozen=True)
class BuiltinDispatchResult:
    handled: bool
    result: Optional[ExecuteResult] = None


def _utc_iso(dt: datetime | None = None) -> str:
    value = dt or datetime.now(timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_utc_iso(raw: Any) -> datetime | None:
    value = str(raw or "").strip()
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _format_utc_offset(dt: datetime) -> str:
    offset = dt.utcoffset() or timedelta(0)
    total_minutes = int(offset.total_seconds() // 60)
    sign = "+" if total_minutes >= 0 else "-"
    total_minutes = abs(total_minutes)
    hours, minutes = divmod(total_minutes, 60)
    return f"{sign}{hours:02d}:{minutes:02d}"


def _local_timezone_name(local_dt: datetime) -> str:
    env_tz = str(os.getenv("TZ") or "").strip()
    if env_tz:
        return env_tz
    tzinfo = local_dt.tzinfo
    zone_key = getattr(tzinfo, "key", None)
    if isinstance(zone_key, str) and zone_key.strip():
        return zone_key.strip()
    name = str(local_dt.tzname() or "").strip()
    return name or "local"


def _time_now_payload(req: ExecuteRequest) -> dict[str, Any]:
    inp = dict(req.arguments or {})
    anchor_utc = _parse_utc_iso(inp.get("anchor_utc") or inp.get("message_received_at_utc")) or datetime.now(timezone.utc)
    local_dt = anchor_utc.astimezone()
    local_date = local_dt.date()
    return {
        "schema_version": "1.0.0",
        "ok": True,
        "operator_ref": "builtin://time.now",
        "anchor_time_utc": _utc_iso(anchor_utc),
        "anchor_time_local": local_dt.isoformat(),
        "timezone_local": _local_timezone_name(local_dt),
        "utc_offset_local": _format_utc_offset(local_dt),
        "date_local": local_date.isoformat(),
        "time_local": local_dt.strftime("%H:%M:%S"),
        "weekday_local": local_dt.strftime("%A"),
        "relative_dates": {
            "yesterday": (local_date - timedelta(days=1)).isoformat(),
            "today": local_date.isoformat(),
            "tomorrow": (local_date + timedelta(days=1)).isoformat(),
        },
    }


def maybe_execute_builtin_time(*, req: ExecuteRequest, data_dir: str) -> BuiltinDispatchResult:
    if not req.operator_ref.startswith("builtin://time."):
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
        if name != "time.now":
            raise ValueError(f"unknown builtin: {name}")
        out_ref = evidence.add_json(_time_now_payload(req), kind="tool_io")
        evidence_refs.append(out_ref)
    except Exception as exc:
        err_ref = evidence.add_json(
            {"schema_version": "1.0.0", "ok": False, "error_code": "E_EXECUTION_FAILED", "message": str(exc)},
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
