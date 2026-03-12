from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from agentos_next.pa.event_envelope import canonical_json


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
class OutboxItem:
    schema_version: str
    stored_at_utc: str
    workspace_id: str
    event_id: str
    idempotency_key: str
    trace_id: str
    turn_id: str
    span_id: str
    execute_status: str
    execute_error_code: Optional[str]
    evidence_refs: tuple[str, ...]
    reply_text: str
    deliveries: tuple[dict[str, Any], ...] = ()
    metering_evidence_refs: tuple[str, ...] = ()
    reply_sent_live: bool = False
    reply_delivery_mode: Optional[str] = None

    def to_json(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "stored_at_utc": self.stored_at_utc,
            "workspace_id": self.workspace_id,
            "event_id": self.event_id,
            "idempotency_key": self.idempotency_key,
            "trace": {"trace_id": self.trace_id, "turn_id": self.turn_id, "span_id": self.span_id},
            "execute": {
                "status": self.execute_status,
                "error_code": self.execute_error_code,
                "evidence_refs": list(self.evidence_refs),
            },
            "reply_text": self.reply_text,
            "deliveries": [dict(item) for item in self.deliveries],
            "metering_evidence_refs": list(self.metering_evidence_refs),
            "reply_sent_live": bool(self.reply_sent_live),
            "reply_delivery_mode": self.reply_delivery_mode,
        }

    @classmethod
    def from_json(cls, obj: Any) -> Optional["OutboxItem"]:
        if not isinstance(obj, dict):
            return None
        trace = obj.get("trace")
        exec_obj = obj.get("execute")
        if not isinstance(trace, dict) or not isinstance(exec_obj, dict):
            return None
        evs = exec_obj.get("evidence_refs") or []
        if not isinstance(evs, list):
            evs = []
        mrefs = obj.get("metering_evidence_refs") or []
        if not isinstance(mrefs, list):
            mrefs = []
        deliveries = obj.get("deliveries") or []
        if not isinstance(deliveries, list):
            deliveries = []
        return cls(
            schema_version=str(obj.get("schema_version") or ""),
            stored_at_utc=str(obj.get("stored_at_utc") or ""),
            workspace_id=str(obj.get("workspace_id") or ""),
            event_id=str(obj.get("event_id") or ""),
            idempotency_key=str(obj.get("idempotency_key") or ""),
            trace_id=str(trace.get("trace_id") or ""),
            turn_id=str(trace.get("turn_id") or ""),
            span_id=str(trace.get("span_id") or ""),
            execute_status=str(exec_obj.get("status") or ""),
            execute_error_code=str(exec_obj.get("error_code")) if exec_obj.get("error_code") is not None else None,
            evidence_refs=tuple(str(x) for x in evs),
            reply_text=str(obj.get("reply_text") or ""),
            deliveries=tuple(dict(x) for x in deliveries if isinstance(x, dict)),
            metering_evidence_refs=tuple(str(x) for x in mrefs),
            reply_sent_live=bool(obj.get("reply_sent_live", False)),
            reply_delivery_mode=(
                str(obj.get("reply_delivery_mode") or "").strip() or None
            ),
        )


class FileOutboxStore:
    """Write-once outbox store.

    Layout (relative to data_dir):
    - pa/outbox/<workspace_id>/<event_id>.json
    - pa/dedup/<workspace_id>/<event_id>.json (optional marker)
    """

    schema_version: str = "1.0.0"

    def __init__(self, data_dir: str | os.PathLike[str] = "data") -> None:
        # Normalize to a resolved root to avoid macOS /var -> /private/var symlink mismatches
        # when computing relative paths for audit markers.
        self._data_dir = Path(data_dir).resolve()
        self._outbox_root = self._data_dir / "pa" / "outbox"
        self._dedup_root = self._data_dir / "pa" / "dedup"

    def _outbox_path(self, *, workspace_id: str, event_id: str) -> Path:
        safe_ws = _safe_segment(workspace_id, fallback="default")
        safe_eid = _safe_segment(event_id, fallback="missing")
        root = self._outbox_root.resolve()
        p = (root / safe_ws / f"{safe_eid}.json").resolve()
        if not p.is_relative_to(root):
            raise ValueError("outbox path resolves outside outbox root")
        return p

    def _dedup_path(self, *, workspace_id: str, event_id: str) -> Path:
        safe_ws = _safe_segment(workspace_id, fallback="default")
        safe_eid = _safe_segment(event_id, fallback="missing")
        root = self._dedup_root.resolve()
        p = (root / safe_ws / f"{safe_eid}.json").resolve()
        if not p.is_relative_to(root):
            raise ValueError("dedup path resolves outside dedup root")
        return p

    def get(self, *, workspace_id: str, event_id: str) -> Optional[OutboxItem]:
        p = self._outbox_path(workspace_id=workspace_id, event_id=event_id)
        if not p.exists():
            return None
        try:
            obj = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return None
        return OutboxItem.from_json(obj)

    def put_if_absent(self, *, item: OutboxItem) -> None:
        p = self._outbox_path(workspace_id=item.workspace_id, event_id=item.event_id)
        p.parent.mkdir(parents=True, exist_ok=True)
        if p.exists():
            return
        # Write-once best effort: create exclusively to avoid overwrites.
        with p.open("x", encoding="utf-8") as f:
            f.write(canonical_json(item.to_json()) + "\n")

        # Optional dedup marker (write-once).
        dp = self._dedup_path(workspace_id=item.workspace_id, event_id=item.event_id)
        dp.parent.mkdir(parents=True, exist_ok=True)
        marker = {
            "schema_version": self.schema_version,
            "stored_at_utc": _utc_iso(),
            "workspace_id": item.workspace_id,
            "event_id": item.event_id,
            "outbox_relpath": str(p.resolve().relative_to(self._data_dir)),
        }
        try:
            with dp.open("x", encoding="utf-8") as f:
                f.write(canonical_json(marker) + "\n")
        except FileExistsError:
            pass
