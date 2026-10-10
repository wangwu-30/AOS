from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

from agentos_next.kernel.evidence_store import FileEvidenceStore

MEMORY_V2_SCHEMA_VERSION = "2.0.0"
MEMORY_RECORD_KIND_SET = {
    "profile",
    "preference",
    "procedure",
    "anti_pattern",
    "delivery_summary",
    "note",
    "turn_archive",
}
MEMORY_SOURCE_SET = {
    "user_explicit",
    "assistant_inferred",
    "system_consolidated",
}
MEMORY_INTENT_SET = {
    "identity",
    "preference",
    "continuity",
    "procedure",
    "delivery",
    "generic",
}
LEGACY_L1_SCHEMA_VERSION = "1.0.0"


def _utc_iso(dt: Optional[datetime] = None) -> str:
    now = dt or datetime.now(timezone.utc)
    return now.isoformat().replace("+00:00", "Z")


def _parse_utc_iso(raw: Any) -> datetime:
    text = str(raw or "").strip()
    if not text:
        return datetime.fromtimestamp(0, tz=timezone.utc)
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except Exception:
        return datetime.fromtimestamp(0, tz=timezone.utc)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _safe_segment(raw: str, *, fallback: str) -> str:
    text = "".join(ch if ch.isalnum() or ch in {"_", "-", "."} else "_" for ch in str(raw or "").strip())
    return text[:120] or fallback


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _flatten_payload(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, dict):
        parts: list[str] = []
        for key in sorted(value.keys()):
            parts.append(str(key))
            parts.append(_flatten_payload(value.get(key)))
        return " ".join(part for part in parts if str(part).strip())
    if isinstance(value, (list, tuple, set)):
        return " ".join(_flatten_payload(item) for item in value)
    return str(value)


def _normalize_text(raw: Any) -> str:
    text = " ".join(str(raw or "").lower().split())
    text = re.sub(r"[^0-9a-z_\u4e00-\u9fff]+", " ", text)
    return " ".join(text.split())


def _extract_terms(text: str) -> tuple[str, ...]:
    if not text:
        return ()
    terms: set[str] = set(re.findall(r"[a-z0-9_]{2,}", text))
    for chunk in re.findall(r"[\u4e00-\u9fff]{2,}", text):
        terms.add(chunk)
        if len(chunk) > 4:
            terms.add(chunk[:4])
            terms.add(chunk[-4:])
    return tuple(sorted(terms, key=len, reverse=True))


def _score_relevance(*, query_text: str, candidate_text: str) -> int:
    query_norm = _normalize_text(query_text)
    candidate_norm = _normalize_text(candidate_text)
    if not query_norm or not candidate_norm:
        return 0
    score = 0
    if query_norm in candidate_norm:
        score += 64
    for term in _extract_terms(query_norm):
        if term in candidate_norm:
            score += min(len(term), 12)
    return score


def _stable_hash(prefix: str, *parts: Any) -> str:
    joined = "|".join(str(part or "") for part in parts).encode("utf-8")
    return f"{prefix}_{hashlib.sha256(joined).hexdigest()[:24]}"


def _payload_fingerprint(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _strip_nonempty_texts(values: Iterable[Any]) -> tuple[str, ...]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in values:
        text = str(raw or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return tuple(out)


def build_semantic_memory_record_input(
    *,
    workspace_id: str,
    statement: str,
    conversation_id: str | None = None,
    project_id: str | None = None,
    source: str = "user_explicit",
    tags: Iterable[str] = (),
    ttl_seconds: int | None = None,
) -> dict[str, Any]:
    normalized_statement = " ".join(str(statement or "").split()).strip(" ，,。.!！?？")
    if not normalized_statement:
        raise ValueError("statement must be non-empty")

    profile_match = re.search(r"我是(?P<value>[\w\u4e00-\u9fff_-]{1,32})", normalized_statement)
    preference_match = re.search(r"我(喜欢|偏好|爱)(?P<value>.+)", normalized_statement)
    workspace_scope = MemoryScopeV2(schema_version=MEMORY_V2_SCHEMA_VERSION, workspace_id=workspace_id).to_json()

    if profile_match is not None:
        value = str(profile_match.group("value") or "").strip()
        if value:
            return {
                "kind": "profile",
                "summary": f"用户身份: {value}",
                "payload": {
                    "statement": f"我是{value}",
                    "subject": "identity.name",
                    "value": value,
                    "name": value,
                },
                "memory_key": "profile.identity.name",
                "scope": workspace_scope,
                "source": str(source or "user_explicit").strip() or "user_explicit",
                "tags": list(_strip_nonempty_texts(("profile", "identity", *list(tags)))),
                "ttl_seconds": 0 if ttl_seconds is None else int(ttl_seconds or 0),
            }

    if preference_match is not None:
        value = str(preference_match.group("value") or "").strip(" ，,。.!！?？")
        if value:
            return {
                "kind": "preference",
                "summary": f"用户偏好: {value}",
                "payload": {
                    "statement": f"我喜欢{value}",
                    "subject": "preference",
                    "value": value,
                },
                "memory_key": _stable_hash("pref", _normalize_text(value)),
                "scope": workspace_scope,
                "source": str(source or "user_explicit").strip() or "user_explicit",
                "tags": list(_strip_nonempty_texts(("preference", *list(tags)))),
                "ttl_seconds": 0 if ttl_seconds is None else int(ttl_seconds or 0),
            }

    return {
        "kind": "note",
        "summary": normalized_statement[:160],
        "payload": {"statement": normalized_statement},
        "memory_key": _stable_hash("note", _normalize_text(normalized_statement)),
        "scope": MemoryScopeV2(
            schema_version=MEMORY_V2_SCHEMA_VERSION,
            workspace_id=workspace_id,
            conversation_id=conversation_id,
            project_id=project_id,
        ).to_json(),
        "source": str(source or "user_explicit").strip() or "user_explicit",
        "tags": list(_strip_nonempty_texts(("note", *list(tags)))),
        "ttl_seconds": 30 * 24 * 3600 if ttl_seconds is None else int(ttl_seconds or 0),
    }


@dataclass(frozen=True)
class MemoryScopeV2:
    schema_version: str
    workspace_id: str
    conversation_id: Optional[str] = None
    project_id: Optional[str] = None

    def to_json(self) -> dict[str, Any]:
        return {
            "schema_version": str(self.schema_version or MEMORY_V2_SCHEMA_VERSION),
            "workspace_id": str(self.workspace_id),
            "conversation_id": str(self.conversation_id).strip() if str(self.conversation_id or "").strip() else None,
            "project_id": str(self.project_id).strip() if str(self.project_id or "").strip() else None,
        }

    def match_rank(self, query_scope: "MemoryScopeV2") -> int:
        if str(self.workspace_id) != str(query_scope.workspace_id):
            return 0
        query_conversation = str(query_scope.conversation_id or "").strip()
        query_project = str(query_scope.project_id or "").strip()
        record_conversation = str(self.conversation_id or "").strip()
        record_project = str(self.project_id or "").strip()
        if record_conversation:
            return 3 if record_conversation == query_conversation else 0
        if record_project:
            return 2 if record_project == query_project and query_project else 0
        return 1

    @staticmethod
    def from_json(obj: Any, *, default_workspace_id: str = "") -> "MemoryScopeV2":
        data = dict(obj or {}) if isinstance(obj, dict) else {}
        workspace_id = str(data.get("workspace_id") or default_workspace_id).strip()
        if not workspace_id:
            raise ValueError("scope.workspace_id is required")
        return MemoryScopeV2(
            schema_version=str(data.get("schema_version") or MEMORY_V2_SCHEMA_VERSION),
            workspace_id=workspace_id,
            conversation_id=str(data.get("conversation_id")).strip() if data.get("conversation_id") else None,
            project_id=str(data.get("project_id")).strip() if data.get("project_id") else None,
        )


@dataclass(frozen=True)
class MemoryRecordV2:
    schema_version: str
    type: str
    record_id: str
    evidence_ref: str
    kind: str
    summary: str
    payload: Any
    memory_key: str
    scope: MemoryScopeV2
    source: str
    tags: tuple[str, ...] = ()
    ttl_seconds: int = 0
    created_at_utc: str = ""
    updated_at_utc: str = ""
    expires_at_utc: Optional[str] = None
    deleted_at_utc: Optional[str] = None
    supersedes_refs: tuple[str, ...] = ()
    superseded_by: Optional[str] = None

    @property
    def created_at(self) -> str:
        return self.created_at_utc

    @property
    def expires_at(self) -> Optional[str]:
        return self.expires_at_utc

    @property
    def tombstoned(self) -> bool:
        return self.deleted_at_utc is not None

    @property
    def tombstoned_at(self) -> Optional[str]:
        return self.deleted_at_utc

    def is_expired(self, *, now: datetime) -> bool:
        return bool(self.expires_at_utc) and _parse_utc_iso(self.expires_at_utc) <= now

    def freshness(self, *, now: datetime) -> str:
        if self.deleted_at_utc:
            return "deleted"
        if self.is_expired(now=now):
            return "stale"
        return "active"

    def payload_fingerprint(self) -> str:
        return _payload_fingerprint(self.payload)

    def search_text(self) -> str:
        parts = [self.kind, self.summary, self.memory_key, *self.tags, _flatten_payload(self.payload)]
        return " ".join(part for part in parts if str(part).strip())

    def to_json(self) -> dict[str, Any]:
        return {
            "schema_version": str(self.schema_version or MEMORY_V2_SCHEMA_VERSION),
            "type": str(self.type or "memory_record_v2"),
            "record_id": str(self.record_id),
            "evidence_ref": str(self.evidence_ref),
            "kind": str(self.kind),
            "summary": str(self.summary),
            "payload": self.payload,
            "memory_key": str(self.memory_key),
            "scope": self.scope.to_json(),
            "source": str(self.source),
            "tags": list(self.tags),
            "ttl_seconds": int(self.ttl_seconds),
            "created_at_utc": str(self.created_at_utc),
            "updated_at_utc": str(self.updated_at_utc),
            "expires_at_utc": str(self.expires_at_utc) if self.expires_at_utc is not None else None,
            "deleted_at_utc": str(self.deleted_at_utc) if self.deleted_at_utc is not None else None,
            "supersedes_refs": list(self.supersedes_refs),
            "superseded_by": str(self.superseded_by) if self.superseded_by is not None else None,
        }

    @staticmethod
    def from_json(obj: Any) -> "MemoryRecordV2":
        data = dict(obj or {}) if isinstance(obj, dict) else {}
        return MemoryRecordV2(
            schema_version=str(data.get("schema_version") or MEMORY_V2_SCHEMA_VERSION),
            type=str(data.get("type") or "memory_record_v2"),
            record_id=str(data.get("record_id") or "").strip(),
            evidence_ref=str(data.get("evidence_ref") or "").strip(),
            kind=str(data.get("kind") or "").strip(),
            summary=str(data.get("summary") or "").strip(),
            payload=data.get("payload"),
            memory_key=str(data.get("memory_key") or "").strip(),
            scope=MemoryScopeV2.from_json(data.get("scope") or {}, default_workspace_id=""),
            source=str(data.get("source") or "").strip(),
            tags=_strip_nonempty_texts(data.get("tags") or []),
            ttl_seconds=int(data.get("ttl_seconds") or 0),
            created_at_utc=str(data.get("created_at_utc") or "").strip(),
            updated_at_utc=str(data.get("updated_at_utc") or "").strip(),
            expires_at_utc=str(data.get("expires_at_utc")).strip() if data.get("expires_at_utc") else None,
            deleted_at_utc=str(data.get("deleted_at_utc")).strip() if data.get("deleted_at_utc") else None,
            supersedes_refs=_strip_nonempty_texts(data.get("supersedes_refs") or []),
            superseded_by=str(data.get("superseded_by")).strip() if data.get("superseded_by") else None,
        )


@dataclass(frozen=True)
class L1Record:
    schema_version: str
    evidence_ref: str
    created_at: str
    tags: tuple[str, ...]
    ttl_seconds: int = 0
    expires_at: Optional[str] = None
    tombstoned: bool = False
    tombstoned_at: Optional[str] = None

    def is_expired(self, *, now: datetime) -> bool:
        return bool(self.expires_at) and _parse_utc_iso(self.expires_at) <= now

    @staticmethod
    def from_json(obj: Any) -> "L1Record":
        data = dict(obj or {}) if isinstance(obj, dict) else {}
        return L1Record(
            schema_version=str(data.get("schema_version") or LEGACY_L1_SCHEMA_VERSION),
            evidence_ref=str(data.get("evidence_ref") or "").strip(),
            created_at=str(data.get("created_at") or data.get("created_at_utc") or "").strip(),
            tags=_strip_nonempty_texts(data.get("tags") or []),
            ttl_seconds=int(data.get("ttl_seconds") or 0),
            expires_at=str(data.get("expires_at")).strip() if data.get("expires_at") else None,
            tombstoned=bool(data.get("tombstoned", False)),
            tombstoned_at=str(data.get("tombstoned_at")).strip() if data.get("tombstoned_at") else None,
        )


@dataclass(frozen=True)
class MemoryQueryV2:
    schema_version: str
    query: str
    intent: str
    scope: MemoryScopeV2
    kinds: tuple[str, ...] = ()
    limit: int = 5
    include_stale: bool = False
    include_deleted: bool = False

    def to_json(self) -> dict[str, Any]:
        return {
            "schema_version": str(self.schema_version or MEMORY_V2_SCHEMA_VERSION),
            "query": str(self.query),
            "intent": str(self.intent),
            "scope": self.scope.to_json(),
            "kinds": list(self.kinds),
            "limit": int(self.limit),
            "include_stale": bool(self.include_stale),
            "include_deleted": bool(self.include_deleted),
        }


@dataclass(frozen=True)
class MemoryHitV2:
    record_id: str
    evidence_ref: str
    kind: str
    summary: str
    payload: Any
    scope: MemoryScopeV2
    source: str
    tags: tuple[str, ...]
    score: int
    freshness: str
    conflict_group: Optional[str] = None

    def to_json(self) -> dict[str, Any]:
        return {
            "record_id": str(self.record_id),
            "evidence_ref": str(self.evidence_ref),
            "kind": str(self.kind),
            "summary": str(self.summary),
            "payload": self.payload,
            "scope": self.scope.to_json(),
            "source": str(self.source),
            "tags": list(self.tags),
            "score": int(self.score),
            "freshness": str(self.freshness),
            "conflict_group": str(self.conflict_group) if self.conflict_group else None,
        }


@dataclass(frozen=True)
class MemoryConflictV2:
    memory_key: str
    record_ids: tuple[str, ...]
    summaries: tuple[str, ...]
    resolution: str = "ask_user"

    def to_json(self) -> dict[str, Any]:
        return {
            "memory_key": str(self.memory_key),
            "record_ids": list(self.record_ids),
            "summaries": list(self.summaries),
            "resolution": str(self.resolution or "ask_user"),
        }


@dataclass(frozen=True)
class MemoryContextV2:
    schema_version: str
    l0_continuity: dict[str, Any]
    l1_query: dict[str, Any]
    l2_hits: tuple[MemoryHitV2, ...]
    conflicts: tuple[MemoryConflictV2, ...]
    retrieval_ref: str

    def to_json(self) -> dict[str, Any]:
        return {
            "schema_version": str(self.schema_version or MEMORY_V2_SCHEMA_VERSION),
            "l0_continuity": dict(self.l0_continuity or {}),
            "l1_query": dict(self.l1_query or {}),
            "l2_hits": [hit.to_json() for hit in self.l2_hits],
            "conflicts": [conflict.to_json() for conflict in self.conflicts],
            "retrieval_ref": str(self.retrieval_ref),
        }


class MemoryStoreV2:
    schema_version: str = MEMORY_V2_SCHEMA_VERSION

    def __init__(self, data_dir: str | os.PathLike[str] = "data") -> None:
        self._data_dir = Path(data_dir)
        self._root = self._data_dir / "memory_v2"
        self._records_dir = self._root / "records"
        self._index_dir = self._root / "index"
        self._legacy_root = self._data_dir / "memory"
        self._legacy_l1_dir = self._legacy_root / "l1"
        self._records_dir.mkdir(parents=True, exist_ok=True)
        self._index_dir.mkdir(parents=True, exist_ok=True)

    def _record_path(self, record_id: str) -> Path:
        return self._records_dir / f"{record_id}.json"

    def _index_path(self, record_id: str) -> Path:
        return self._index_dir / f"{record_id}.json"

    def _legacy_l1_path(self, evidence_ref: str) -> Path:
        safe_ref = _safe_segment(evidence_ref, fallback="ev")
        return self._legacy_l1_dir / f"{safe_ref}.json"

    def _legacy_l1_payload(
        self,
        *,
        evidence_ref: str,
        tags: Iterable[str],
        created_at: str,
        ttl_seconds: int,
        expires_at: Optional[str],
        tombstoned: bool,
        tombstoned_at: Optional[str],
    ) -> dict[str, Any]:
        return {
            "schema_version": LEGACY_L1_SCHEMA_VERSION,
            "evidence_ref": str(evidence_ref).strip(),
            "created_at": str(created_at or "").strip(),
            "tags": list(_strip_nonempty_texts(tags)),
            "ttl_seconds": int(ttl_seconds or 0),
            "expires_at": str(expires_at).strip() if expires_at else None,
            "tombstoned": bool(tombstoned),
            "tombstoned_at": str(tombstoned_at).strip() if tombstoned_at else None,
        }

    def _load_legacy_l1_records(self) -> list[L1Record]:
        if not self._legacy_l1_dir.exists():
            return []
        out: list[L1Record] = []
        for path in sorted(self._legacy_l1_dir.glob("ev_*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if not isinstance(data, dict):
                continue
            try:
                out.append(L1Record.from_json(data))
            except Exception:
                continue
        return out

    def create_record(
        self,
        *,
        evidence: FileEvidenceStore,
        kind: str,
        summary: str,
        payload: Any,
        memory_key: str,
        scope: MemoryScopeV2,
        source: str,
        tags: Iterable[str] = (),
        ttl_seconds: int = 0,
        supersedes_refs: Iterable[str] = (),
    ) -> MemoryRecordV2:
        kind_text = str(kind or "").strip()
        source_text = str(source or "").strip()
        summary_text = str(summary or "").strip()
        memory_key_text = str(memory_key or "").strip()
        if kind_text not in MEMORY_RECORD_KIND_SET:
            raise ValueError(f"record.kind must be one of {sorted(MEMORY_RECORD_KIND_SET)}")
        if source_text not in MEMORY_SOURCE_SET:
            raise ValueError(f"record.source must be one of {sorted(MEMORY_SOURCE_SET)}")
        if not summary_text:
            raise ValueError("record.summary must be non-empty")
        if not memory_key_text:
            raise ValueError("record.memory_key must be non-empty")
        if not isinstance(payload, dict):
            raise ValueError("record.payload must be a JSON object")
        scope_obj = MemoryScopeV2.from_json(scope.to_json(), default_workspace_id=str(scope.workspace_id))
        tags_tuple = _strip_nonempty_texts([*list(tags), f"ws_{scope_obj.workspace_id}"])
        supersedes = _strip_nonempty_texts(supersedes_refs)
        now = datetime.now(timezone.utc)
        created_at_utc = _utc_iso(now)
        expires_at_utc = (
            _utc_iso(now + timedelta(seconds=int(ttl_seconds or 0)))
            if int(ttl_seconds or 0) > 0
            else None
        )
        if not supersedes:
            for existing in self.list_by_memory_key(memory_key=memory_key_text):
                if existing.kind != kind_text:
                    continue
                if existing.scope.to_json() != scope_obj.to_json():
                    continue
                if existing.payload_fingerprint() != _payload_fingerprint(payload):
                    continue
                if existing.deleted_at_utc or existing.superseded_by:
                    continue
                return existing
        record_id = _stable_hash(
            "mr",
            scope_obj.workspace_id,
            scope_obj.conversation_id or "",
            scope_obj.project_id or "",
            kind_text,
            memory_key_text,
            summary_text,
            created_at_utc,
        )
        evidence_ref = evidence.add_json(
            {
                "schema_version": MEMORY_V2_SCHEMA_VERSION,
                "type": "memory_record_v2",
                "record_id": record_id,
                "kind": kind_text,
                "summary": summary_text,
                "payload": payload,
                "memory_key": memory_key_text,
                "scope": scope_obj.to_json(),
                "source": source_text,
                "tags": list(tags_tuple),
                "ttl_seconds": int(ttl_seconds or 0),
                "created_at_utc": created_at_utc,
                "expires_at_utc": expires_at_utc,
                "supersedes_refs": list(supersedes),
            },
            kind="artifact_draft",
        ).ref
        record = MemoryRecordV2(
            schema_version=MEMORY_V2_SCHEMA_VERSION,
            type="memory_record_v2",
            record_id=record_id,
            evidence_ref=evidence_ref,
            kind=kind_text,
            summary=summary_text,
            payload=payload,
            memory_key=memory_key_text,
            scope=scope_obj,
            source=source_text,
            tags=tags_tuple,
            ttl_seconds=int(ttl_seconds or 0),
            created_at_utc=created_at_utc,
            updated_at_utc=created_at_utc,
            expires_at_utc=expires_at_utc,
            deleted_at_utc=None,
            supersedes_refs=supersedes,
            superseded_by=None,
        )
        self.put_record(record)
        for ref in supersedes:
            self.mark_superseded(record_id=ref, winner_record_id=record.record_id)
        return record

    def put_record(self, record: MemoryRecordV2) -> MemoryRecordV2:
        payload = record.to_json()
        record_path = self._record_path(record.record_id)
        index_path = self._index_path(record.record_id)
        record_path.write_text(_canonical_json(payload) + "\n", encoding="utf-8")
        index_path.write_text(
            _canonical_json(
                {
                    "schema_version": MEMORY_V2_SCHEMA_VERSION,
                    "record_id": record.record_id,
                    "evidence_ref": record.evidence_ref,
                    "kind": record.kind,
                    "memory_key": record.memory_key,
                    "scope": record.scope.to_json(),
                    "source": record.source,
                    "tags": list(record.tags),
                    "created_at_utc": record.created_at_utc,
                    "updated_at_utc": record.updated_at_utc,
                    "expires_at_utc": record.expires_at_utc,
                    "deleted_at_utc": record.deleted_at_utc,
                    "superseded_by": record.superseded_by,
                    "search_text": record.search_text(),
                }
            )
            + "\n",
            encoding="utf-8",
        )
        return record

    def get_record(self, *, record_id: str) -> Optional[MemoryRecordV2]:
        path = self._record_path(record_id)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
        if not isinstance(data, dict):
            return None
        return MemoryRecordV2.from_json(data)

    def list_records(self) -> list[MemoryRecordV2]:
        out: list[MemoryRecordV2] = []
        for path in sorted(self._records_dir.glob("mr_*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if not isinstance(data, dict):
                continue
            try:
                out.append(MemoryRecordV2.from_json(data))
            except Exception:
                continue
        return out

    def list_by_memory_key(self, *, memory_key: str) -> list[MemoryRecordV2]:
        key = str(memory_key or "").strip()
        return [record for record in self.list_records() if record.memory_key == key]

    def mark_deleted(self, *, record_id: str, deleted_at_utc: Optional[str] = None) -> MemoryRecordV2:
        record = self.get_record(record_id=record_id)
        if record is None:
            raise ValueError(f"record_id not found: {record_id}")
        ts = str(deleted_at_utc or _utc_iso()).strip() or _utc_iso()
        updated = replace(record, deleted_at_utc=ts, updated_at_utc=ts)
        return self.put_record(updated)

    def mark_superseded(self, *, record_id: str, winner_record_id: str) -> MemoryRecordV2:
        record = self.get_record(record_id=record_id)
        if record is None:
            raise ValueError(f"record_id not found: {record_id}")
        ts = _utc_iso()
        updated = replace(record, superseded_by=str(winner_record_id), updated_at_utc=ts)
        return self.put_record(updated)

    def upsert_l1(
        self,
        *,
        evidence_ref: str,
        tags: Iterable[str] = (),
        created_at: Optional[str] = None,
        ttl_seconds: int = 0,
    ) -> L1Record:
        evidence_ref_text = str(evidence_ref or "").strip()
        if not evidence_ref_text:
            raise ValueError("evidence_ref is required")
        ts = str(created_at or _utc_iso()).strip() or _utc_iso()
        ttl_value = int(ttl_seconds or 0)
        expires_at = _utc_iso(_parse_utc_iso(ts) + timedelta(seconds=ttl_value)) if ttl_value > 0 else None
        payload = self._legacy_l1_payload(
            evidence_ref=evidence_ref_text,
            tags=tags,
            created_at=ts,
            ttl_seconds=ttl_value,
            expires_at=expires_at,
            tombstoned=False,
            tombstoned_at=None,
        )
        self._legacy_l1_dir.mkdir(parents=True, exist_ok=True)
        self._legacy_l1_path(evidence_ref_text).write_text(_canonical_json(payload) + "\n", encoding="utf-8")
        return L1Record.from_json(payload)

    def tombstone_l1(self, *, evidence_ref: str, tombstoned_at: Optional[str] = None) -> L1Record:
        evidence_ref_text = str(evidence_ref or "").strip()
        if not evidence_ref_text:
            raise ValueError("evidence_ref is required")
        path = self._legacy_l1_path(evidence_ref_text)
        if not path.exists():
            raise ValueError(f"evidence_ref not found in legacy l1 index: {evidence_ref_text}")
        try:
            current = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise ValueError(f"invalid legacy l1 entry for evidence_ref: {evidence_ref_text}") from exc
        if not isinstance(current, dict):
            raise ValueError(f"invalid legacy l1 entry for evidence_ref: {evidence_ref_text}")
        payload = self._legacy_l1_payload(
            evidence_ref=evidence_ref_text,
            tags=current.get("tags") or (),
            created_at=str(current.get("created_at") or _utc_iso()).strip() or _utc_iso(),
            ttl_seconds=int(current.get("ttl_seconds") or 0),
            expires_at=str(current.get("expires_at")).strip() if current.get("expires_at") else None,
            tombstoned=True,
            tombstoned_at=str(tombstoned_at or _utc_iso()).strip() or _utc_iso(),
        )
        path.write_text(_canonical_json(payload) + "\n", encoding="utf-8")
        return L1Record.from_json(payload)

    def iter_l1(self) -> list[L1Record]:
        seen: set[str] = set()
        out: list[L1Record] = []
        for record in self._load_legacy_l1_records():
            if not record.evidence_ref or record.evidence_ref in seen:
                continue
            seen.add(record.evidence_ref)
            out.append(record)
        for record in self.list_records():
            if not record.evidence_ref or record.evidence_ref in seen:
                continue
            seen.add(record.evidence_ref)
            out.append(
                L1Record(
                    schema_version=str(record.schema_version or MEMORY_V2_SCHEMA_VERSION),
                    evidence_ref=record.evidence_ref,
                    created_at=record.created_at_utc,
                    tags=record.tags,
                    ttl_seconds=int(record.ttl_seconds or 0),
                    expires_at=record.expires_at_utc,
                    tombstoned=record.tombstoned,
                    tombstoned_at=record.tombstoned_at,
                )
            )
        return out


FileMemoryStore = MemoryStoreV2


class MemoryRetrieverV2:
    def __init__(self, store: MemoryStoreV2) -> None:
        self._store = store

    def search(self, *, query: MemoryQueryV2) -> tuple[list[MemoryHitV2], list[MemoryConflictV2]]:
        now = datetime.now(timezone.utc)
        matched: list[tuple[int, int, int, datetime, MemoryRecordV2]] = []
        conflict_map: dict[str, list[MemoryRecordV2]] = {}
        for record in self._store.list_records():
            scope_rank = record.scope.match_rank(query.scope)
            if scope_rank <= 0:
                continue
            if record.superseded_by:
                continue
            if query.kinds and record.kind not in set(query.kinds):
                continue
            freshness = record.freshness(now=now)
            if freshness == "deleted" and not query.include_deleted:
                continue
            if freshness == "stale" and not query.include_stale:
                continue
            relevance = _score_relevance(query_text=query.query, candidate_text=record.search_text())
            freshness_rank = 2 if freshness == "active" else (1 if freshness == "stale" else 0)
            matched.append(
                (
                    scope_rank,
                    relevance,
                    freshness_rank,
                    _parse_utc_iso(record.updated_at_utc or record.created_at_utc),
                    record,
                )
            )
            if not record.deleted_at_utc:
                conflict_map.setdefault(record.memory_key, []).append(record)
        conflicts: list[MemoryConflictV2] = []
        conflict_groups: set[str] = set()
        for memory_key, records in conflict_map.items():
            if len(records) <= 1:
                continue
            payloads = {record.payload_fingerprint() for record in records if not record.superseded_by}
            active_records = [record for record in records if not record.superseded_by]
            if len(active_records) <= 1 or len(payloads) <= 1:
                continue
            conflict_groups.add(memory_key)
            conflicts.append(
                MemoryConflictV2(
                    memory_key=memory_key,
                    record_ids=tuple(record.record_id for record in active_records),
                    summaries=tuple(record.summary for record in active_records),
                    )
            )
        matched.sort(key=lambda item: (item[0], item[1], item[2], item[3]), reverse=True)
        hits: list[MemoryHitV2] = []
        for scope_rank, relevance, freshness_rank, _updated_at, record in matched[: max(1, int(query.limit))]:
            freshness = "active" if freshness_rank == 2 else ("stale" if freshness_rank == 1 else "deleted")
            score = int((scope_rank * 1000) + (relevance * 10) + freshness_rank)
            hits.append(
                MemoryHitV2(
                    record_id=record.record_id,
                    evidence_ref=record.evidence_ref,
                    kind=record.kind,
                    summary=record.summary,
                    payload=record.payload,
                    scope=record.scope,
                    source=record.source,
                    tags=record.tags,
                    score=score,
                    freshness=freshness,
                    conflict_group=record.memory_key if record.memory_key in conflict_groups else None,
                )
            )
        return hits, conflicts


class MemoryConsolidatorV2:
    def __init__(self, data_dir: str | os.PathLike[str] = "data") -> None:
        self._data_dir = Path(data_dir)
        self._store = MemoryStoreV2(data_dir=data_dir)
        self._evidence = FileEvidenceStore(data_dir=data_dir)

    def consolidate_turn(
        self,
        *,
        workspace_id: str,
        conversation_id: str | None,
        project_id: str | None,
        query: str,
        reply_text: str,
        error_code: str | None,
    ) -> tuple[str, ...]:
        explicit = self._build_explicit_record(
            workspace_id=str(workspace_id),
            conversation_id=str(conversation_id or "").strip() or None,
            project_id=str(project_id or "").strip() or None,
            query=str(query or ""),
        )
        if explicit is not None:
            record = self._store.create_record(evidence=self._evidence, **explicit)
            return (record.evidence_ref,)
        if str(error_code or "").strip():
            record = self._store.create_record(
                evidence=self._evidence,
                kind="anti_pattern",
                summary=f"Failure pattern: {str(error_code).strip()}",
                payload={"query": str(query or ""), "error_code": str(error_code).strip()},
                memory_key=_stable_hash("mk", "anti_pattern", _normalize_text(query), str(error_code).strip()),
                scope=MemoryScopeV2(
                    schema_version=MEMORY_V2_SCHEMA_VERSION,
                    workspace_id=str(workspace_id),
                    project_id=str(project_id or "").strip() or None,
                ),
                source="system_consolidated",
                tags=("anti_pattern",),
                ttl_seconds=0,
            )
            return (record.evidence_ref,)
        text = str(reply_text or "").strip()
        if not text:
            return ()
        workspace_scope = MemoryScopeV2(
            schema_version=MEMORY_V2_SCHEMA_VERSION,
            workspace_id=str(workspace_id),
            conversation_id=str(conversation_id or "").strip() or None,
            project_id=str(project_id or "").strip() or None,
        )
        procedure_scope = MemoryScopeV2(
            schema_version=MEMORY_V2_SCHEMA_VERSION,
            workspace_id=str(workspace_id),
            project_id=str(project_id or "").strip() or None,
        )
        delivery_key = _stable_hash("mk", "delivery", _normalize_text(query))
        existing = [
            record
            for record in self._store.list_by_memory_key(memory_key=delivery_key)
            if not record.deleted_at_utc and not record.superseded_by
        ]
        if any(record.kind == "procedure" for record in existing):
            return ()
        if existing:
            winner = self._store.create_record(
                evidence=self._evidence,
                kind="procedure",
                summary=f"Validated procedure for: {str(query or '').strip()[:120]}",
                payload={
                    "objective": str(query or ""),
                    "latest_reply": text,
                    "successful_runs": len(existing) + 1,
                },
                memory_key=delivery_key,
                scope=procedure_scope,
                source="system_consolidated",
                tags=("procedure",),
                ttl_seconds=0,
                supersedes_refs=[record.record_id for record in existing],
            )
            return (winner.evidence_ref,)
        record = self._store.create_record(
            evidence=self._evidence,
            kind="delivery_summary",
            summary=text[:160],
            payload={"query": str(query or ""), "reply": text},
            memory_key=delivery_key,
            scope=workspace_scope,
            source="system_consolidated",
            tags=("delivery_summary",),
            ttl_seconds=30 * 24 * 3600,
        )
        return (record.evidence_ref,)

    def _build_explicit_record(
        self,
        *,
        workspace_id: str,
        conversation_id: str | None,
        project_id: str | None,
        query: str,
    ) -> Optional[dict[str, Any]]:
        raw = " ".join(str(query or "").split())
        lower = raw.lower()
        if not raw or not any(marker in raw or marker in lower for marker in ("记住", "remember", "保存")):
            return None
        remembered = raw
        remembered = re.sub(r"^(请)?(你)?(帮我)?(记住|保存)\s*", "", remembered, flags=re.IGNORECASE)
        remembered = re.sub(r"\s*(好不好|好吗|一下|这条)$", "", remembered, flags=re.IGNORECASE)
        remembered = remembered.strip(" ，,。.!！?？")
        if not remembered:
            remembered = raw
        record = build_semantic_memory_record_input(
            workspace_id=workspace_id,
            conversation_id=conversation_id,
            project_id=project_id,
            statement=remembered,
            source="user_explicit",
        )
        scope = record.get("scope")
        if isinstance(scope, dict):
            record["scope"] = MemoryScopeV2.from_json(scope, default_workspace_id=workspace_id)
        return record
