from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _safe_segment(raw: str, *, fallback: str) -> str:
    text = "".join(ch if ch.isalnum() or ch in {"_", "-", "."} else "_" for ch in str(raw or "").strip())
    return text[:120] or fallback


def _norm(text: str) -> str:
    return " ".join(re.sub(r"[^0-9a-z_\u4e00-\u9fff]+", " ", str(text or "").lower()).split())


def _terms(text: str) -> set[str]:
    data = _norm(text)
    out = set(re.findall(r"[a-z0-9_]{2,}", data))
    out.update(re.findall(r"[\u4e00-\u9fff]{2,}", data))
    return out


@dataclass(frozen=True)
class TheoremRecord:
    schema_version: str
    theorem_id: str
    theorem_type: str
    workspace_id: str
    project_id: Optional[str]
    summary: str
    match_terms: tuple[str, ...]
    operator_hints: tuple[str, ...]
    source_ref: Optional[str]
    created_at_utc: str

    def to_json(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "theorem_id": self.theorem_id,
            "theorem_type": self.theorem_type,
            "workspace_id": self.workspace_id,
            "project_id": self.project_id,
            "summary": self.summary,
            "match_terms": list(self.match_terms),
            "operator_hints": list(self.operator_hints),
            "source_ref": self.source_ref,
            "created_at_utc": self.created_at_utc,
        }


class FileTheoremStore:
    def __init__(self, data_dir: str | os.PathLike[str] = "data") -> None:
        self._root = Path(data_dir) / "theorems"
        self._root.mkdir(parents=True, exist_ok=True)

    def _path(self, *, theorem_id: str) -> Path:
        return self._root / f"{_safe_segment(theorem_id, fallback='theorem')}.json"

    def put_if_absent(self, *, record: TheoremRecord) -> bool:
        path = self._path(theorem_id=record.theorem_id)
        if path.exists():
            return False
        path.write_text(json.dumps(record.to_json(), ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
        return True

    def search(
        self,
        *,
        workspace_id: str,
        query_text: str,
        project_id: Optional[str] = None,
        limit: int = 5,
    ) -> list[TheoremRecord]:
        query_terms = _terms(query_text)
        out: list[tuple[int, TheoremRecord]] = []
        for path in sorted(self._root.glob("*.json")):
            try:
                obj = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if not isinstance(obj, dict):
                continue
            if str(obj.get("workspace_id") or "").strip() != str(workspace_id):
                continue
            rec_project_id = str(obj.get("project_id") or "").strip() or None
            if project_id and rec_project_id not in {None, str(project_id)}:
                continue
            summary = str(obj.get("summary") or "").strip()
            match_terms = tuple(str(x).strip() for x in (obj.get("match_terms") or []) if str(x).strip())
            score = len(query_terms.intersection(set(match_terms or _terms(summary))))
            if score <= 0:
                continue
            out.append(
                (
                    score,
                    TheoremRecord(
                        schema_version=str(obj.get("schema_version") or "1.0.0"),
                        theorem_id=str(obj.get("theorem_id") or path.stem),
                        theorem_type=str(obj.get("theorem_type") or "sop"),
                        workspace_id=str(obj.get("workspace_id") or workspace_id),
                        project_id=rec_project_id,
                        summary=summary,
                        match_terms=match_terms,
                        operator_hints=tuple(str(x).strip() for x in (obj.get("operator_hints") or []) if str(x).strip()),
                        source_ref=str(obj.get("source_ref") or "").strip() or None,
                        created_at_utc=str(obj.get("created_at_utc") or ""),
                    ),
                )
            )
        out.sort(key=lambda item: (-item[0], item[1].created_at_utc), reverse=False)
        return [rec for _, rec in out[:limit]]


def build_theorem_record_v1(
    *,
    theorem_type: str,
    workspace_id: str,
    summary: str,
    project_id: Optional[str] = None,
    operator_hints: Optional[list[str]] = None,
    source_ref: Optional[str] = None,
) -> TheoremRecord:
    normalized_summary = " ".join(str(summary or "").split()).strip()
    terms = tuple(sorted(_terms(normalized_summary)))
    seed = f"{theorem_type}|{workspace_id}|{project_id or '-'}|{normalized_summary}"
    theorem_id = f"th_{abs(hash(seed))}"
    return TheoremRecord(
        schema_version="1.0.0",
        theorem_id=theorem_id,
        theorem_type=str(theorem_type or "sop"),
        workspace_id=str(workspace_id),
        project_id=str(project_id).strip() if str(project_id or "").strip() else None,
        summary=normalized_summary,
        match_terms=terms,
        operator_hints=tuple(str(x).strip() for x in (operator_hints or []) if str(x).strip()),
        source_ref=str(source_ref).strip() if str(source_ref or "").strip() else None,
        created_at_utc=_utc_iso(),
    )
