from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Literal, Optional


OutputEventType = Literal["ack", "progress", "reply_delta", "artifact", "blocker", "need_context", "done"]


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class OutputEventV1:
    schema_version: str
    trace_id: str
    turn_id: str
    event_type: OutputEventType
    ts: str
    payload: dict[str, Any]


class FileRuntimeEventLog:
    def __init__(self, data_dir: str | os.PathLike[str] = "data") -> None:
        self._root = Path(data_dir) / "runtime_events"
        self._root.mkdir(parents=True, exist_ok=True)

    def _path(self, *, trace_id: str) -> Path:
        safe = "".join(ch if ch.isalnum() or ch in {"_", "-", "."} else "_" for ch in str(trace_id or "").strip())
        return self._root / f"{safe or 'trace'}.jsonl"

    def emit(self, *, event: OutputEventV1) -> None:
        path = self._path(trace_id=event.trace_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": event.schema_version,
            "trace_id": event.trace_id,
            "turn_id": event.turn_id,
            "event_type": event.event_type,
            "ts": event.ts,
            "payload": dict(event.payload or {}),
        }
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")


def emit_output_event(
    *,
    sink: Optional[Callable[[dict[str, Any]], None]],
    event_log: FileRuntimeEventLog,
    trace_id: str,
    turn_id: str,
    event_type: OutputEventType,
    payload: Optional[dict[str, Any]] = None,
) -> None:
    event = OutputEventV1(
        schema_version="1.0.0",
        trace_id=str(trace_id),
        turn_id=str(turn_id),
        event_type=event_type,
        ts=_utc_iso(),
        payload=dict(payload or {}),
    )
    event_log.emit(event=event)
    if callable(sink):
        sink(
            {
                "schema_version": event.schema_version,
                "trace_id": event.trace_id,
                "turn_id": event.turn_id,
                "event_type": event.event_type,
                "ts": event.ts,
                "payload": dict(event.payload),
            }
        )
