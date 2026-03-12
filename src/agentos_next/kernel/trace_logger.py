from __future__ import annotations

import json
import os
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from .types import EvidenceRef, TraceEvent


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class TraceLogger:
    """Trace logger interface.

    Spec: docs/specs/EVIDENCE_TRACE.md
    """

    def emit(self, event: TraceEvent) -> None:  # pragma: no cover (interface)
        raise NotImplementedError


class FileTraceLogger(TraceLogger):
    """Append-only JSONL trace logger.

    Layout (relative to data_dir):
    - traces/<trace_id>.jsonl
    """

    def __init__(self, data_dir: str | os.PathLike[str] = "data", *, schema_version: str = "1.0.0") -> None:
        self._data_dir = Path(data_dir)
        self._traces_dir = self._data_dir / "traces"
        self._traces_dir.mkdir(parents=True, exist_ok=True)
        self._schema_version = schema_version

    def _trace_path(self, trace_id: str) -> Path:
        return self._traces_dir / f"{trace_id}.jsonl"

    def emit(self, event: TraceEvent) -> None:
        payload = _trace_event_to_dict(event)
        payload.setdefault("schema_version", self._schema_version)
        payload.setdefault("ts", _utc_iso())
        path = self._trace_path(event.ctx.trace_id)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")


def _trace_event_to_dict(event: TraceEvent) -> dict[str, Any]:
    d = asdict(event)
    # asdict() turns tuples into lists; keep this stable for JSON.
    d["ctx"] = dict(d["ctx"])
    d["evidence_refs"] = [_evidence_ref_to_dict(er) for er in event.evidence_refs]
    _strip_none(d["ctx"])
    _strip_none(d)
    return d


def _evidence_ref_to_dict(er: EvidenceRef) -> dict[str, Any]:
    d = asdict(er)
    _strip_none(d)
    return d


def _strip_none(d: dict[str, Any]) -> None:
    for k in list(d.keys()):
        v = d[k]
        if v is None:
            del d[k]
        elif isinstance(v, dict):
            _strip_none(v)
