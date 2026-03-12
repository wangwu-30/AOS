from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional
from uuid import uuid4


class SchedulerError(RuntimeError):
    pass


def _utc_iso(dt: Optional[datetime] = None) -> str:
    d = dt or datetime.now(timezone.utc)
    return d.isoformat().replace("+00:00", "Z")


def _parse_utc_iso(s: str) -> datetime:
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s)


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:12]}"


def _require_dict(obj: Any, *, name: str) -> dict[str, Any]:
    if not isinstance(obj, dict):
        raise SchedulerError(f"{name} must be a JSON object")
    return obj


def _require_str(obj: Any, *, name: str, nonempty: bool = True, max_bytes: Optional[int] = None) -> str:
    if not isinstance(obj, str):
        raise SchedulerError(f"{name} must be a string")
    s = obj
    if nonempty and not s.strip():
        raise SchedulerError(f"{name} must be non-empty")
    if max_bytes is not None and len(s.encode("utf-8")) > max_bytes:
        raise SchedulerError(f"{name} exceeds max_bytes={max_bytes}")
    return s


def _require_int(obj: Any, *, name: str) -> int:
    try:
        return int(obj)
    except Exception as e:
        raise SchedulerError(f"{name} must be an integer") from e


def _strip_policy_escalators(policy: dict[str, Any]) -> dict[str, Any]:
    # Prevent stored tasks from smuggling escalation keys. Trigger-time overrides are authoritative.
    out = dict(policy or {})
    for k in ("remote_calls_armed", "allow_network_egress", "approved_by_human", "replay_mode"):
        out.pop(k, None)
    return out


@dataclass(frozen=True)
class ScheduledTask:
    schema_version: str
    task_id: str
    kind: str  # at|cron
    status: str  # scheduled|running|done|failed|canceled
    created_at: str
    next_run_at: str
    attempts: int
    idempotency_root: str
    cron: Optional[str] = None
    timezone: str = "UTC"
    execute_request: dict[str, Any] = None  # stored draft; see spec

    @classmethod
    def from_dict(cls, obj: dict[str, Any]) -> "ScheduledTask":
        return cls(
            schema_version=str(obj.get("schema_version") or "1.0.0"),
            task_id=str(obj.get("task_id") or ""),
            kind=str(obj.get("kind") or ""),
            status=str(obj.get("status") or "scheduled"),
            created_at=str(obj.get("created_at") or ""),
            next_run_at=str(obj.get("next_run_at") or ""),
            attempts=int(obj.get("attempts") or 0),
            idempotency_root=str(obj.get("idempotency_root") or ""),
            cron=str(obj.get("cron")) if obj.get("cron") is not None else None,
            timezone=str(obj.get("timezone") or "UTC"),
            execute_request=dict(obj.get("execute_request") or {}),
        )

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "schema_version": self.schema_version,
            "task_id": self.task_id,
            "kind": self.kind,
            "status": self.status,
            "created_at": self.created_at,
            "next_run_at": self.next_run_at,
            "attempts": self.attempts,
            "idempotency_root": self.idempotency_root,
            "execute_request": dict(self.execute_request or {}),
            "timezone": self.timezone,
        }
        if self.cron is not None:
            out["cron"] = self.cron
        return out


class FileSchedulerStore:
    """File-backed scheduler queue (MVP).

    Layout (relative to data_dir):
    - scheduler/tasks/<task_id>.json
    """

    schema_version: str = "1.0.0"

    def __init__(self, data_dir: str | os.PathLike[str] = "data") -> None:
        self._data_dir = Path(data_dir)
        self._tasks_dir = self._data_dir / "scheduler" / "tasks"
        self._tasks_dir.mkdir(parents=True, exist_ok=True)

    def _task_path(self, task_id: str) -> Path:
        return self._tasks_dir / f"{task_id}.json"

    def list_tasks(self) -> list[ScheduledTask]:
        out: list[ScheduledTask] = []
        for p in sorted(self._tasks_dir.glob("sched_*.json")):
            try:
                obj = json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                continue
            if not isinstance(obj, dict):
                continue
            out.append(ScheduledTask.from_dict(obj))
        return out

    def get(self, *, task_id: str) -> Optional[ScheduledTask]:
        p = self._task_path(task_id)
        if not p.exists():
            return None
        try:
            obj = json.loads(p.read_text(encoding="utf-8"))
        except Exception as e:  # pragma: no cover
            raise SchedulerError(f"failed to read task: {task_id}") from e
        if not isinstance(obj, dict):
            raise SchedulerError("task file must be a JSON object")
        return ScheduledTask.from_dict(obj)

    def put(self, task: ScheduledTask) -> None:
        p = self._task_path(task.task_id)
        p.write_text(
            json.dumps(task.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )

    def create_at(
        self,
        *,
        workspace_id: str,
        run_at: str,
        execute_request_draft: dict[str, Any],
        idempotency_root: Optional[str],
    ) -> ScheduledTask:
        run_at_s = _require_str(run_at, name="run_at", max_bytes=128)
        dt = _parse_utc_iso(run_at_s)
        if dt.tzinfo is None:
            raise SchedulerError("run_at must be timezone-aware UTC ISO")

        draft = _require_dict(execute_request_draft, name="execute_request")
        deadline_ms = _require_int(draft.get("deadline_ms"), name="execute_request.deadline_ms")
        if deadline_ms <= 0 or deadline_ms > 60000:
            raise SchedulerError("execute_request.deadline_ms must be in [1, 60000]")

        policy = _strip_policy_escalators(_require_dict(draft.get("policy_context") or {}, name="execute_request.policy_context"))

        task_id = _new_id("sched")
        root = (idempotency_root or f"sched:{task_id}").strip() or f"sched:{task_id}"
        task = ScheduledTask(
            schema_version=self.schema_version,
            task_id=task_id,
            kind="at",
            status="scheduled",
            created_at=_utc_iso(),
            next_run_at=_utc_iso(dt),
            attempts=0,
            idempotency_root=root,
            execute_request={
                "workspace_id": str(workspace_id),
                "operator_ref": _require_str(
                    draft.get("operator_ref") or draft.get("skill_ref"),
                    name="execute_request.operator_ref",
                ),
                "arguments": _require_dict(
                    draft.get("arguments") if isinstance(draft.get("arguments"), dict) else (draft.get("input") or {}),
                    name="execute_request.arguments",
                ),
                "deadline_ms": deadline_ms,
                "policy_context": policy,
                "preferred_target": str(draft.get("preferred_target") or "") or None,
            },
        )
        self.put(task)
        return task

    def create_cron(
        self,
        *,
        workspace_id: str,
        cron: str,
        now: datetime,
        execute_request_draft: dict[str, Any],
        idempotency_root: Optional[str],
    ) -> ScheduledTask:
        cron_s = _require_str(cron, name="cron", max_bytes=128)
        next_dt = next_cron_time(cron_s, now=now)

        draft = _require_dict(execute_request_draft, name="execute_request")
        deadline_ms = _require_int(draft.get("deadline_ms"), name="execute_request.deadline_ms")
        if deadline_ms <= 0 or deadline_ms > 60000:
            raise SchedulerError("execute_request.deadline_ms must be in [1, 60000]")

        policy = _strip_policy_escalators(_require_dict(draft.get("policy_context") or {}, name="execute_request.policy_context"))

        task_id = _new_id("sched")
        root = (idempotency_root or f"sched:{task_id}").strip() or f"sched:{task_id}"
        task = ScheduledTask(
            schema_version=self.schema_version,
            task_id=task_id,
            kind="cron",
            status="scheduled",
            created_at=_utc_iso(),
            next_run_at=_utc_iso(next_dt),
            attempts=0,
            idempotency_root=root,
            cron=cron_s,
            timezone="UTC",
            execute_request={
                "workspace_id": str(workspace_id),
                "operator_ref": _require_str(
                    draft.get("operator_ref") or draft.get("skill_ref"),
                    name="execute_request.operator_ref",
                ),
                "arguments": _require_dict(
                    draft.get("arguments") if isinstance(draft.get("arguments"), dict) else (draft.get("input") or {}),
                    name="execute_request.arguments",
                ),
                "deadline_ms": deadline_ms,
                "policy_context": policy,
                "preferred_target": str(draft.get("preferred_target") or "") or None,
            },
        )
        self.put(task)
        return task


def _parse_cron_field(field: str, *, name: str, lo: int, hi: int) -> Optional[int]:
    f = field.strip()
    if f == "*":
        return None
    try:
        v = int(f)
    except Exception as e:
        raise SchedulerError(f"cron field {name} must be '*' or integer") from e
    if v < lo or v > hi:
        raise SchedulerError(f"cron field {name} must be in [{lo}, {hi}]")
    return v


def next_cron_time(cron: str, *, now: datetime) -> datetime:
    """Compute the next matching UTC time after `now` for our MVP cron subset.

    Subset: 5 fields (minute hour day month weekday), each '*' or single integer.
    weekday uses Python datetime.weekday(): Monday=0..Sunday=6.
    """
    if now.tzinfo is None:
        raise SchedulerError("now must be timezone-aware")
    parts = [p for p in cron.split() if p.strip()]
    if len(parts) != 5:
        raise SchedulerError("cron must have 5 fields: minute hour day month weekday")
    minute = _parse_cron_field(parts[0], name="minute", lo=0, hi=59)
    hour = _parse_cron_field(parts[1], name="hour", lo=0, hi=23)
    day = _parse_cron_field(parts[2], name="day", lo=1, hi=31)
    month = _parse_cron_field(parts[3], name="month", lo=1, hi=12)
    weekday = _parse_cron_field(parts[4], name="weekday", lo=0, hi=6)

    # Search forward minute-by-minute (bounded) to keep MVP simple and deterministic.
    start = now.replace(second=0, microsecond=0) + timedelta(minutes=1)
    limit = start + timedelta(days=366)
    cur = start
    while cur <= limit:
        if minute is not None and cur.minute != minute:
            cur += timedelta(minutes=1)
            continue
        if hour is not None and cur.hour != hour:
            cur += timedelta(minutes=1)
            continue
        if day is not None and cur.day != day:
            cur += timedelta(minutes=1)
            continue
        if month is not None and cur.month != month:
            cur += timedelta(minutes=1)
            continue
        if weekday is not None and cur.weekday() != weekday:
            cur += timedelta(minutes=1)
            continue
        return cur.astimezone(timezone.utc)

    raise SchedulerError("cron did not match any time within 366 days (unsupported subset?)")
