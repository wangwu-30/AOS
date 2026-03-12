from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, Protocol

from agentos_next.kernel.executor import ExecuteResult, ExecuteTiming
from agentos_next.kernel.types import EvidenceRef


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class IdempotencyStore(Protocol):
    def get(self, *, workspace_id: str, idempotency_key: str) -> Optional[ExecuteResult]:  # pragma: no cover
        raise NotImplementedError

    def put_if_absent(self, *, workspace_id: str, idempotency_key: str, result: ExecuteResult) -> None:  # pragma: no cover
        raise NotImplementedError


class FileIdempotencyStore:
    """File-backed idempotency store (MVP).

    Layout (relative to data_dir):
    - idempotency/<workspace_id>/<idempotency_key>.json
    """

    schema_version: str = "1.0.0"

    def __init__(self, data_dir: str | os.PathLike[str] = "data") -> None:
        self._data_dir = Path(data_dir)
        self._root = self._data_dir / "idempotency"
        self._root.mkdir(parents=True, exist_ok=True)

    def _safe_segment(self, value: str, *, fallback: str) -> str:
        raw = str(value or "").strip()
        if not raw:
            return fallback
        if re.fullmatch(r"[A-Za-z0-9._-]{1,200}", raw):
            return raw
        return "h_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]

    def _path(self, *, workspace_id: str, idempotency_key: str) -> Path:
        safe_ws = self._safe_segment(workspace_id, fallback="default")
        safe_key = self._safe_segment(idempotency_key, fallback="missing")
        root = self._root.resolve()
        p = (root / safe_ws / f"{safe_key}.json").resolve()
        if not p.is_relative_to(root):
            raise ValueError("idempotency key resolves outside store root")
        return p

    def get(self, *, workspace_id: str, idempotency_key: str) -> Optional[ExecuteResult]:
        p = self._path(workspace_id=workspace_id, idempotency_key=idempotency_key)
        if not p.exists():
            return None
        obj = json.loads(p.read_text(encoding="utf-8"))
        return _execute_result_from_json(obj.get("result") if isinstance(obj, dict) else None)

    def put_if_absent(self, *, workspace_id: str, idempotency_key: str, result: ExecuteResult) -> None:
        p = self._path(workspace_id=workspace_id, idempotency_key=idempotency_key)
        p.parent.mkdir(parents=True, exist_ok=True)
        if p.exists():
            return

        payload = {
            "schema_version": self.schema_version,
            "workspace_id": workspace_id,
            "idempotency_key": idempotency_key,
            "stored_at_utc": _utc_iso(),
            "result": _execute_result_to_json(result),
        }

        tmp = p.with_suffix(p.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
        tmp.replace(p)


def _execute_result_to_json(res: ExecuteResult) -> dict[str, Any]:
    d = asdict(res)
    d["timing"] = {"started_at": res.timing.started_at, "ended_at": res.timing.ended_at}
    d["evidence_refs"] = [asdict(er) for er in res.evidence_refs]
    d["artifact_refs"] = list(res.artifact_refs)
    return d


def _execute_result_from_json(obj: Any) -> Optional[ExecuteResult]:
    if not isinstance(obj, dict):
        return None
    timing = obj.get("timing")
    if not isinstance(timing, dict):
        return None
    started_at = timing.get("started_at")
    ended_at = timing.get("ended_at")
    if not isinstance(started_at, str) or not isinstance(ended_at, str):
        return None

    evs: list[EvidenceRef] = []
    raw_evs = obj.get("evidence_refs") or []
    if isinstance(raw_evs, list):
        for it in raw_evs:
            if not isinstance(it, dict):
                continue
            ref = it.get("ref")
            kind = it.get("kind")
            ts = it.get("ts")
            size_bytes = it.get("size_bytes")
            preview = it.get("preview")
            if not isinstance(ref, str) or not isinstance(kind, str) or not isinstance(ts, str) or not isinstance(size_bytes, int):
                continue
            evs.append(EvidenceRef(ref=ref, kind=kind, ts=ts, size_bytes=size_bytes, preview=preview if isinstance(preview, str) else None))

    arts = obj.get("artifact_refs") or []
    art_refs: list[str] = []
    if isinstance(arts, list):
        art_refs = [str(x) for x in arts]

    status = obj.get("status")
    target = obj.get("target")
    if not isinstance(status, str) or not isinstance(target, str):
        return None
    error_code = obj.get("error_code")
    if error_code is not None and not isinstance(error_code, str):
        error_code = str(error_code)

    return ExecuteResult(
        status=status,  # type: ignore[arg-type]
        evidence_refs=tuple(evs),
        artifact_refs=tuple(art_refs),
        error_code=error_code,
        timing=ExecuteTiming(started_at=started_at, ended_at=ended_at),
        target=target,  # type: ignore[arg-type]
    )
