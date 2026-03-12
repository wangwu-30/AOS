from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from agentos_next.pa.event_envelope import EnvelopeDict, canonical_json


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _safe_segment(value: str, *, fallback: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return fallback
    if re.fullmatch(r"[A-Za-z0-9._-]{1,200}", raw):
        return raw
    return "h_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


@dataclass(frozen=True)
class EventLogItem:
    schema_version: str
    stored_at_utc: str
    workspace_id: str
    event_id: str
    envelope: EnvelopeDict


class FileEventLog:
    """Append-only event log (write-once per event_id).

    Layout (relative to data_dir):
    - pa/events/<workspace_id>/<event_id>.json
    """

    schema_version: str = "1.0.0"

    def __init__(self, data_dir: str | os.PathLike[str] = "data") -> None:
        self._data_dir = Path(data_dir)
        self._root = self._data_dir / "pa" / "events"

    def _path(self, *, workspace_id: str, event_id: str) -> Path:
        safe_ws = _safe_segment(workspace_id, fallback="default")
        safe_eid = _safe_segment(event_id, fallback="missing")
        root = self._root.resolve()
        p = (root / safe_ws / f"{safe_eid}.json").resolve()
        if not p.is_relative_to(root):
            raise ValueError("event path resolves outside events root")
        return p

    def exists(self, *, workspace_id: str, event_id: str) -> bool:
        p = self._path(workspace_id=workspace_id, event_id=event_id)
        return p.exists()

    def write_once(self, *, workspace_id: str, event_id: str, envelope: EnvelopeDict) -> None:
        p = self._path(workspace_id=workspace_id, event_id=event_id)
        p.parent.mkdir(parents=True, exist_ok=True)
        item: dict[str, Any] = {
            "schema_version": self.schema_version,
            "stored_at_utc": _utc_iso(),
            "workspace_id": workspace_id,
            "event_id": event_id,
            "envelope": envelope,
        }
        # Write-once: fail-closed to caller via FileExistsError handling.
        with p.open("x", encoding="utf-8") as f:
            f.write(canonical_json(item) + "\n")

    def read(self, *, workspace_id: str, event_id: str) -> Optional[EventLogItem]:
        p = self._path(workspace_id=workspace_id, event_id=event_id)
        if not p.exists():
            return None
        obj = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(obj, dict):
            return None
        env = obj.get("envelope") if isinstance(obj.get("envelope"), dict) else {}
        return EventLogItem(
            schema_version=str(obj.get("schema_version") or ""),
            stored_at_utc=str(obj.get("stored_at_utc") or ""),
            workspace_id=str(obj.get("workspace_id") or ""),
            event_id=str(obj.get("event_id") or ""),
            envelope=dict(env),
        )

