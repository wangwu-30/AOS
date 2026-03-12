from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Optional


HypothesisResult = Literal["confirmed", "rejected", "partial"]


def _safe_segment(value: str, *, fallback: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return fallback
    if re.fullmatch(r"[A-Za-z0-9._-]{1,200}", raw):
        return raw
    return fallback


@dataclass(frozen=True)
class HypothesisRecord:
    schema_version: str
    turn_id: str
    iteration: int
    hypothesis: str
    verification_action: str
    verification_evidence_refs: tuple[str, ...]
    result: HypothesisResult
    revision: str

    def to_json(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "turn_id": self.turn_id,
            "iteration": int(self.iteration),
            "hypothesis": self.hypothesis,
            "verification_action": self.verification_action,
            "verification_evidence_refs": list(self.verification_evidence_refs),
            "result": self.result,
            "revision": self.revision,
        }

    @classmethod
    def from_json(cls, obj: Any) -> Optional["HypothesisRecord"]:
        if not isinstance(obj, dict):
            return None
        refs = obj.get("verification_evidence_refs") or []
        if not isinstance(refs, list):
            refs = []
        result = str(obj.get("result") or "").strip()
        if result not in {"confirmed", "rejected", "partial"}:
            return None
        try:
            iteration = int(obj.get("iteration") or 0)
        except Exception:
            return None
        if iteration <= 0:
            return None
        hypothesis = str(obj.get("hypothesis") or "").strip()
        verification_action = str(obj.get("verification_action") or "").strip()
        if not hypothesis or not verification_action:
            return None
        return cls(
            schema_version=str(obj.get("schema_version") or ""),
            turn_id=str(obj.get("turn_id") or ""),
            iteration=iteration,
            hypothesis=hypothesis,
            verification_action=verification_action,
            verification_evidence_refs=tuple(str(x) for x in refs if str(x).strip()),
            result=result,  # type: ignore[arg-type]
            revision=str(obj.get("revision") or ""),
        )


class FileHypothesisStore:
    schema_version: str = "1.0.0"

    def __init__(self, data_dir: str | os.PathLike[str] = "data") -> None:
        self._data_dir = Path(data_dir).resolve()
        self._root = self._data_dir / "hypotheses"

    def _workspace_dir(self, *, workspace_id: str) -> Path:
        return self._root / _safe_segment(workspace_id, fallback="default")

    def _record_path(self, *, workspace_id: str, turn_id: str, iteration: int) -> Path:
        ws_dir = self._workspace_dir(workspace_id=workspace_id)
        safe_turn = _safe_segment(turn_id, fallback="turn")
        return ws_dir / f"{safe_turn}_{int(iteration):04d}.json"

    def put_if_absent(self, *, workspace_id: str, record: HypothesisRecord) -> None:
        path = self._record_path(
            workspace_id=workspace_id,
            turn_id=record.turn_id,
            iteration=record.iteration,
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            return
        with path.open("x", encoding="utf-8") as f:
            f.write(json.dumps(record.to_json(), ensure_ascii=False, sort_keys=True) + "\n")

    def list_recent(
        self,
        *,
        workspace_id: str,
        limit: int = 5,
        result: HypothesisResult | None = None,
    ) -> list[HypothesisRecord]:
        ws_dir = self._workspace_dir(workspace_id=workspace_id)
        if not ws_dir.exists():
            return []
        out: list[tuple[float, HypothesisRecord]] = []
        for path in ws_dir.glob("*.json"):
            try:
                obj = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            rec = HypothesisRecord.from_json(obj)
            if rec is None:
                continue
            if result is not None and rec.result != result:
                continue
            try:
                score = float(path.stat().st_mtime)
            except Exception:
                score = 0.0
            out.append((score, rec))
        out.sort(key=lambda item: item[0], reverse=True)
        return [rec for _, rec in out[: max(0, int(limit))]]
