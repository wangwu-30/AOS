from __future__ import annotations

import contextlib
import json
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from agentos_next.apps.scheduler_tick import SchedulerTickRequest, run_scheduler_tick_async
from agentos_next.kernel.orchestrator import Orchestrator
from agentos_next.kernel.scheduler_store import FileSchedulerStore, ScheduledTask


def _utc_iso(dt: Optional[datetime] = None) -> str:
    d = dt or datetime.now(timezone.utc)
    return d.isoformat().replace("+00:00", "Z")


def _parse_utc_iso(s: str) -> datetime:
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s)


class DaemonError(RuntimeError):
    def __init__(self, error_code: str, message: str) -> None:
        super().__init__(message)
        self.error_code = str(error_code)


@dataclass(frozen=True)
class DaemonRunRequest:
    data_dir: str | Path = "data"
    tick_interval_ms: int = 1000
    max_fires_per_tick: int = 50
    replay_mode: bool = False
    remote_calls_armed: bool = False
    allow_network_egress: bool = False
    approved_by_human: bool = False
    strict_mode: bool = False
    now: Optional[str] = None
    max_loops: Optional[int] = None


@dataclass(frozen=True)
class DaemonRunResult:
    ok: bool
    error_code: Optional[str]
    state: str
    last_tick_at: Optional[str]
    next_fire_at: Optional[str]
    consecutive_failures: int
    cumulative_failures: int
    pid: int
    uptime_ms: int
    evidence_refs: tuple[str, ...]


def _default_heartbeat() -> dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "state": "idle",
        "started_at": _utc_iso(),
        "last_tick_at": None,
        "next_fire_at": None,
        "consecutive_failures": 0,
        "cumulative_failures": 0,
        "pid": 0,
        "uptime_ms": 0,
    }


def _failure_threshold(*, strict_mode: bool) -> int:
    return 1 if bool(strict_mode) else 3


def _heartbeat_path(data_dir: Path) -> Path:
    return data_dir / "daemon" / "heartbeat.json"


def _leader_lock_path(data_dir: Path) -> Path:
    return data_dir / "daemon" / "leader.lock"


def _tick_lock_path(data_dir: Path) -> Path:
    return data_dir / "scheduler" / "tick.lock"


def _wal_path(data_dir: Path) -> Path:
    return data_dir / "daemon" / "wal" / "events.jsonl"


def _load_heartbeat(*, data_dir: Path) -> dict[str, Any]:
    p = _heartbeat_path(data_dir)
    if not p.exists():
        return _default_heartbeat()
    try:
        obj = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return _default_heartbeat()
    if not isinstance(obj, dict):
        return _default_heartbeat()
    out = _default_heartbeat()
    out.update(obj)
    return out


def _save_heartbeat(*, data_dir: Path, hb: dict[str, Any]) -> None:
    p = _heartbeat_path(data_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    safe = _default_heartbeat()
    safe.update(hb or {})
    p.write_text(json.dumps(safe, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")


def _uptime_ms(started_at: Any) -> int:
    if not isinstance(started_at, str):
        return 0
    try:
        dt = _parse_utc_iso(started_at).astimezone(timezone.utc)
    except Exception:
        return 0
    now = datetime.now(timezone.utc)
    delta = now - dt
    return max(0, int(delta.total_seconds() * 1000))


def _to_result(*, hb: dict[str, Any], ok: bool, error_code: Optional[str], evidence_refs: tuple[str, ...]) -> DaemonRunResult:
    return DaemonRunResult(
        ok=bool(ok),
        error_code=error_code,
        state=str(hb.get("state") or "idle"),
        last_tick_at=(str(hb["last_tick_at"]) if hb.get("last_tick_at") else None),
        next_fire_at=(str(hb["next_fire_at"]) if hb.get("next_fire_at") else None),
        consecutive_failures=int(hb.get("consecutive_failures") or 0),
        cumulative_failures=int(hb.get("cumulative_failures") or 0),
        pid=int(hb.get("pid") or 0),
        uptime_ms=_uptime_ms(hb.get("started_at")),
        evidence_refs=tuple(evidence_refs),
    )


def _append_wal(*, data_dir: Path, event: dict[str, Any]) -> None:
    p = _wal_path(data_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")


def _list_tasks_readonly(*, data_dir: Path) -> list[ScheduledTask]:
    tasks_dir = data_dir / "scheduler" / "tasks"
    if not tasks_dir.exists():
        return []
    out: list[ScheduledTask] = []
    for p in sorted(tasks_dir.glob("sched_*.json")):
        try:
            obj = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(obj, dict):
            continue
        out.append(ScheduledTask.from_dict(obj))
    return out


def _compute_next_fire_at(*, data_dir: Path) -> Optional[str]:
    next_dt: Optional[datetime] = None
    for task in _list_tasks_readonly(data_dir=data_dir):
        if str(task.status) != "scheduled":
            continue
        try:
            dt = _parse_utc_iso(str(task.next_run_at)).astimezone(timezone.utc)
        except Exception:
            continue
        if next_dt is None or dt < next_dt:
            next_dt = dt
    return _utc_iso(next_dt) if next_dt is not None else None


def _due_tasks(*, store: FileSchedulerStore, now_dt: datetime, max_fires: int) -> list[ScheduledTask]:
    out: list[ScheduledTask] = []
    for task in store.list_tasks():
        if task.status != "scheduled":
            continue
        try:
            if _parse_utc_iso(task.next_run_at).astimezone(timezone.utc) <= now_dt:
                out.append(task)
        except Exception:
            continue
        if len(out) >= max(0, int(max_fires)):
            break
    return out


def _read_incomplete_fires(*, data_dir: Path) -> dict[tuple[str, int], dict[str, Any]]:
    p = _wal_path(data_dir)
    if not p.exists():
        return {}
    started: dict[tuple[str, int], dict[str, Any]] = {}
    for raw in p.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
        except Exception:
            continue
        if not isinstance(ev, dict):
            continue
        t = str(ev.get("event_type") or "")
        task_id = ev.get("task_id")
        attempt = ev.get("attempt")
        if not isinstance(task_id, str) or not isinstance(attempt, int):
            continue
        key = (task_id, int(attempt))
        if t == "fire_started":
            started[key] = ev
        elif t == "fire_finished":
            started.pop(key, None)
    return started


def _recover_incomplete_running_tasks(*, store: FileSchedulerStore, data_dir: Path) -> None:
    pending = _read_incomplete_fires(data_dir=data_dir)
    if not pending:
        return
    for (task_id, _attempt), _ in pending.items():
        task = store.get(task_id=task_id)
        if task is None:
            continue
        if task.status != "running":
            continue
        store.put(ScheduledTask.from_dict({**task.to_dict(), "status": "scheduled"}))


@contextlib.contextmanager
def _acquire_file_lock(*, lock_path: Path, timeout_sec: float, stale_sec: float):
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.time() + float(timeout_sec)
    while True:
        now = time.time()
        try:
            with lock_path.open("x", encoding="utf-8") as f:
                f.write(json.dumps({"pid": os.getpid(), "ts": now}) + "\n")
            break
        except FileExistsError:
            stale = False
            try:
                obj = json.loads(lock_path.read_text(encoding="utf-8"))
                ts = float(obj.get("ts"))
                stale = (now - ts) > float(stale_sec)
            except Exception:
                try:
                    stale = (now - lock_path.stat().st_mtime) > float(stale_sec)
                except Exception:
                    stale = False
            if stale:
                with contextlib.suppress(Exception):
                    lock_path.unlink()
                continue
            if now >= deadline:
                raise DaemonError("E_DAEMON_LOCKED", f"lock busy: {lock_path}") from None
            time.sleep(0.05)
    try:
        yield
    finally:
        with contextlib.suppress(Exception):
            lock_path.unlink()


def _tick_lock_available(*, data_dir: Path) -> bool:
    lock = _tick_lock_path(data_dir)
    try:
        with _acquire_file_lock(lock_path=lock, timeout_sec=0.0, stale_sec=60.0):
            return True
    except DaemonError:
        return False


def read_daemon_status(*, data_dir: str | Path = "data") -> DaemonRunResult:
    root = Path(data_dir)
    hb = _load_heartbeat(data_dir=root)
    hb["next_fire_at"] = _compute_next_fire_at(data_dir=root)
    return _to_result(hb=hb, ok=True, error_code=None, evidence_refs=())


def _apply_internal_failure(*, hb: dict[str, Any], threshold: int, base_error_code: str) -> str:
    hb["consecutive_failures"] = int(hb.get("consecutive_failures") or 0) + 1
    hb["cumulative_failures"] = int(hb.get("cumulative_failures") or 0) + 1
    hb["state"] = "running"
    if int(hb["consecutive_failures"]) >= int(threshold):
        hb["state"] = "blocked"
        return "E_DAEMON_UNHEALTHY"
    return str(base_error_code)


async def _daemon_tick_once(
    *,
    req: DaemonRunRequest,
    orchestrator: Orchestrator,
    hb: dict[str, Any],
) -> DaemonRunResult:
    root = Path(req.data_dir)
    threshold = _failure_threshold(strict_mode=bool(req.strict_mode))
    now_dt = datetime.now(timezone.utc) if req.now is None else _parse_utc_iso(str(req.now)).astimezone(timezone.utc)
    now_iso = _utc_iso(now_dt)

    hb["pid"] = int(os.getpid())
    hb["started_at"] = str(hb.get("started_at") or _utc_iso())
    hb["last_tick_at"] = now_iso

    if not _tick_lock_available(data_dir=root):
        code = _apply_internal_failure(hb=hb, threshold=threshold, base_error_code="E_DAEMON_LOCKED")
        hb["next_fire_at"] = _compute_next_fire_at(data_dir=root)
        _save_heartbeat(data_dir=root, hb=hb)
        return _to_result(hb=hb, ok=False, error_code=code, evidence_refs=())

    store = FileSchedulerStore(data_dir=str(root))
    _recover_incomplete_running_tasks(store=store, data_dir=root)
    due = _due_tasks(store=store, now_dt=now_dt, max_fires=int(req.max_fires_per_tick))

    _append_wal(
        data_dir=root,
        event={"schema_version": "1.0.0", "event_type": "tick_started", "ts": now_iso, "due_count": len(due), "pid": int(os.getpid())},
    )
    pending: dict[str, dict[str, Any]] = {}
    for task in due:
        attempt = int(task.attempts) + 1
        trace_id = f"tr_{task.task_id}"
        idem = f"{task.idempotency_root}:{attempt}"
        pending[task.task_id] = {"attempt": attempt, "trace_id": trace_id, "idempotency_key": idem}
        _append_wal(
            data_dir=root,
            event={
                "schema_version": "1.0.0",
                "event_type": "fire_started",
                "ts": now_iso,
                "task_id": task.task_id,
                "attempt": attempt,
                "idempotency_key": idem,
                "trace_id": trace_id,
            },
        )

    tick_req = SchedulerTickRequest(
        data_dir=str(root),
        now=now_iso,
        replay_mode=bool(req.replay_mode),
        remote_calls_armed=bool(req.remote_calls_armed),
        allow_network_egress=bool(req.allow_network_egress),
        approved_by_human=bool(req.approved_by_human),
        max_fires=int(req.max_fires_per_tick),
    )

    tick_res = await run_scheduler_tick_async(tick_req, orchestrator=orchestrator)
    fired_map = {ft.task_id: ft for ft in tick_res.fired}
    for task in due:
        ctx = pending.get(task.task_id) or {}
        ft = fired_map.get(task.task_id)
        execute_status = str(ft.execute_status) if ft is not None else "failed"
        error_code = ft.error_code if ft is not None else (tick_res.error_code or "E_EXECUTION_FAILED")
        target = str(ft.target) if ft is not None else "local"
        _append_wal(
            data_dir=root,
            event={
                "schema_version": "1.0.0",
                "event_type": "fire_finished",
                "ts": _utc_iso(),
                "task_id": task.task_id,
                "attempt": int(ctx.get("attempt") or 0),
                "idempotency_key": str(ctx.get("idempotency_key") or ""),
                "trace_id": str(ctx.get("trace_id") or ""),
                "execute_status": execute_status,
                "error_code": error_code,
                "target": target,
            },
        )

    _append_wal(
        data_dir=root,
        event={
            "schema_version": "1.0.0",
            "event_type": "tick_finished",
            "ts": _utc_iso(),
            "ok": bool(tick_res.ok),
            "error_code": tick_res.error_code,
            "fired_count": len(tick_res.fired),
        },
    )

    if tick_res.ok:
        hb["consecutive_failures"] = 0
        hb["state"] = "running"
        hb["next_fire_at"] = _compute_next_fire_at(data_dir=root)
        _save_heartbeat(data_dir=root, hb=hb)
        return _to_result(hb=hb, ok=True, error_code=None, evidence_refs=tuple(str(x) for x in tick_res.evidence_refs))

    code = _apply_internal_failure(hb=hb, threshold=threshold, base_error_code=str(tick_res.error_code or "E_EXECUTION_FAILED"))
    hb["next_fire_at"] = _compute_next_fire_at(data_dir=root)
    _save_heartbeat(data_dir=root, hb=hb)
    return _to_result(hb=hb, ok=False, error_code=code, evidence_refs=tuple(str(x) for x in tick_res.evidence_refs))


async def run_daemon_once_async(req: DaemonRunRequest, *, orchestrator: Optional[Orchestrator] = None) -> DaemonRunResult:
    root = Path(req.data_dir)
    if bool(req.replay_mode):
        hb = _load_heartbeat(data_dir=root)
        hb["state"] = "blocked"
        hb["next_fire_at"] = _compute_next_fire_at(data_dir=root)
        return _to_result(hb=hb, ok=False, error_code="E_DAEMON_POLICY_VIOLATION", evidence_refs=())

    orch = orchestrator or Orchestrator.for_data_dir(str(root))
    try:
        with _acquire_file_lock(lock_path=_leader_lock_path(root), timeout_sec=0.0, stale_sec=60.0):
            hb = _load_heartbeat(data_dir=root)
            return await _daemon_tick_once(req=req, orchestrator=orch, hb=hb)
    except DaemonError as e:
        hb = _load_heartbeat(data_dir=root)
        hb["state"] = "blocked" if str(e.error_code) == "E_DAEMON_UNHEALTHY" else str(hb.get("state") or "idle")
        hb["next_fire_at"] = _compute_next_fire_at(data_dir=root)
        return _to_result(hb=hb, ok=False, error_code=str(e.error_code), evidence_refs=())


async def run_daemon_async(req: DaemonRunRequest, *, orchestrator: Optional[Orchestrator] = None) -> DaemonRunResult:
    root = Path(req.data_dir)
    if bool(req.replay_mode):
        hb = _load_heartbeat(data_dir=root)
        hb["state"] = "blocked"
        hb["next_fire_at"] = _compute_next_fire_at(data_dir=root)
        return _to_result(hb=hb, ok=False, error_code="E_DAEMON_POLICY_VIOLATION", evidence_refs=())

    orch = orchestrator or Orchestrator.for_data_dir(str(root))
    interval_sec = max(0.01, float(int(req.tick_interval_ms)) / 1000.0)
    loops_limit = int(req.max_loops) if req.max_loops is not None else None
    loops = 0
    last: Optional[DaemonRunResult] = None

    try:
        with _acquire_file_lock(lock_path=_leader_lock_path(root), timeout_sec=0.0, stale_sec=60.0):
            hb = _load_heartbeat(data_dir=root)
            hb["state"] = "running"
            hb["pid"] = int(os.getpid())
            hb["started_at"] = str(hb.get("started_at") or _utc_iso())
            hb["next_fire_at"] = _compute_next_fire_at(data_dir=root)
            _save_heartbeat(data_dir=root, hb=hb)

            while True:
                loops += 1
                last = await _daemon_tick_once(req=req, orchestrator=orch, hb=hb)
                hb = _load_heartbeat(data_dir=root)

                if last.error_code == "E_DAEMON_UNHEALTHY":
                    return last
                if loops_limit is not None and loops >= loops_limit:
                    return last
                time.sleep(interval_sec)
    except DaemonError as e:
        hb = _load_heartbeat(data_dir=root)
        hb["next_fire_at"] = _compute_next_fire_at(data_dir=root)
        return _to_result(hb=hb, ok=False, error_code=str(e.error_code), evidence_refs=())
