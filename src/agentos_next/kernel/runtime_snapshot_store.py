from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

CONTINUITY_V2_SCHEMA_VERSION = "2.0.0"


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _safe_segment(raw: str, *, fallback: str) -> str:
    text = "".join(ch if ch.isalnum() or ch in {"_", "-", "."} else "_" for ch in str(raw or "").strip())
    return text[:120] or fallback


@dataclass(frozen=True)
class ContinuityHeadV2:
    schema_version: str
    workspace_id: str
    conversation_id: str
    updated_at_utc: str
    active_project_id: Optional[str] = None
    pending_contract: Optional[dict[str, Any]] = None
    expected_next_user_act: Optional[str] = None
    last_clarification_question: Optional[str] = None
    blocker: Optional[dict[str, Any]] = None
    last_delivery_state: Optional[str] = None
    last_delivery_summary: Optional[str] = None
    interaction_mode_preference: Optional[str] = None
    last_user_query: Optional[str] = None
    last_user_query_at_utc: Optional[str] = None
    active_submission_id: Optional[str] = None
    active_submission_generation: Optional[int] = None

    def to_json(self) -> dict[str, Any]:
        return {
            "schema_version": str(self.schema_version or CONTINUITY_V2_SCHEMA_VERSION),
            "workspace_id": str(self.workspace_id),
            "conversation_id": str(self.conversation_id),
            "updated_at_utc": str(self.updated_at_utc),
            "active_project_id": str(self.active_project_id).strip() if str(self.active_project_id or "").strip() else None,
            "pending_contract": dict(self.pending_contract) if isinstance(self.pending_contract, dict) else None,
            "expected_next_user_act": (
                str(self.expected_next_user_act).strip() if str(self.expected_next_user_act or "").strip() else None
            ),
            "last_clarification_question": (
                str(self.last_clarification_question).strip()
                if str(self.last_clarification_question or "").strip()
                else None
            ),
            "blocker": dict(self.blocker) if isinstance(self.blocker, dict) else None,
            "last_delivery_state": (
                str(self.last_delivery_state).strip() if str(self.last_delivery_state or "").strip() else None
            ),
            "last_delivery_summary": (
                str(self.last_delivery_summary).strip() if str(self.last_delivery_summary or "").strip() else None
            ),
            "interaction_mode_preference": (
                str(self.interaction_mode_preference).strip()
                if str(self.interaction_mode_preference or "").strip()
                else None
            ),
            "last_user_query": str(self.last_user_query).strip() if str(self.last_user_query or "").strip() else None,
            "last_user_query_at_utc": (
                str(self.last_user_query_at_utc).strip() if str(self.last_user_query_at_utc or "").strip() else None
            ),
            "active_submission_id": (
                str(self.active_submission_id).strip() if str(self.active_submission_id or "").strip() else None
            ),
            "active_submission_generation": (
                int(self.active_submission_generation)
                if self.active_submission_generation is not None
                else None
            ),
        }


@dataclass(frozen=True)
class ContinuityEventV2:
    schema_version: str
    type: str
    event_id: str
    workspace_id: str
    conversation_id: str
    created_at_utc: str
    event_type: str
    summary: Optional[str] = None
    data: Optional[dict[str, Any]] = None

    def to_json(self) -> dict[str, Any]:
        return {
            "schema_version": str(self.schema_version or CONTINUITY_V2_SCHEMA_VERSION),
            "type": str(self.type or "continuity_event_v2"),
            "event_id": str(self.event_id),
            "workspace_id": str(self.workspace_id),
            "conversation_id": str(self.conversation_id),
            "created_at_utc": str(self.created_at_utc),
            "event_type": str(self.event_type),
            "summary": str(self.summary).strip() if str(self.summary or "").strip() else None,
            "data": dict(self.data) if isinstance(self.data, dict) else None,
        }

class ContinuityStoreV2:
    schema_version: str = CONTINUITY_V2_SCHEMA_VERSION

    def __init__(self, data_dir: str | os.PathLike[str] = "data") -> None:
        self._root = Path(data_dir) / "memory_v2"
        self._heads_dir = self._root / "continuity_heads"
        self._events_dir = self._root / "continuity_events"
        self._heads_dir.mkdir(parents=True, exist_ok=True)
        self._events_dir.mkdir(parents=True, exist_ok=True)

    def _head_path(self, *, workspace_id: str, conversation_id: str) -> Path:
        ws = _safe_segment(str(workspace_id), fallback="default")
        cid = _safe_segment(str(conversation_id), fallback="conversation")
        return self._heads_dir / ws / f"{cid}.json"

    def _events_path(self, *, workspace_id: str, conversation_id: str) -> Path:
        ws = _safe_segment(str(workspace_id), fallback="default")
        cid = _safe_segment(str(conversation_id), fallback="conversation")
        return self._events_dir / ws / f"{cid}.jsonl"

    def get(self, *, workspace_id: str, conversation_id: str) -> Optional[ContinuityHeadV2]:
        path = self._head_path(workspace_id=workspace_id, conversation_id=conversation_id)
        if not path.exists():
            return None
        try:
            obj = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
        if not isinstance(obj, dict):
            return None
        return self._to_head(obj=obj)

    def put(
        self,
        *,
        workspace_id: str,
        conversation_id: str,
        active_project_id: Optional[str] = None,
        pending_contract: Optional[dict[str, Any]] = None,
        expected_next_user_act: Optional[str] = None,
        last_clarification_question: Optional[str] = None,
        blocker: Optional[dict[str, Any]] = None,
        last_delivery_state: Optional[str] = None,
        last_delivery_summary: Optional[str] = None,
        interaction_mode_preference: Optional[str] = None,
        last_user_query: Optional[str] = None,
        last_user_query_at_utc: Optional[str] = None,
        active_submission_id: Optional[str] = None,
        active_submission_generation: Optional[int] = None,
    ) -> ContinuityHeadV2:
        path = self._head_path(workspace_id=workspace_id, conversation_id=conversation_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        obj = {
            "schema_version": self.schema_version,
            "workspace_id": str(workspace_id),
            "conversation_id": str(conversation_id),
            "updated_at_utc": _utc_iso(),
            "active_project_id": str(active_project_id).strip() if str(active_project_id or "").strip() else None,
            "pending_contract": dict(pending_contract) if isinstance(pending_contract, dict) else None,
            "expected_next_user_act": (
                str(expected_next_user_act).strip() if str(expected_next_user_act or "").strip() else None
            ),
            "last_clarification_question": (
                str(last_clarification_question).strip()
                if str(last_clarification_question or "").strip()
                else None
            ),
            "blocker": dict(blocker) if isinstance(blocker, dict) else None,
            "last_delivery_state": str(last_delivery_state).strip() if str(last_delivery_state or "").strip() else None,
            "last_delivery_summary": (
                str(last_delivery_summary).strip() if str(last_delivery_summary or "").strip() else None
            ),
            "interaction_mode_preference": (
                str(interaction_mode_preference).strip()
                if str(interaction_mode_preference or "").strip()
                else None
            ),
            "last_user_query": str(last_user_query).strip() if str(last_user_query or "").strip() else None,
            "last_user_query_at_utc": (
                str(last_user_query_at_utc).strip() if str(last_user_query_at_utc or "").strip() else None
            ),
            "active_submission_id": (
                str(active_submission_id).strip() if str(active_submission_id or "").strip() else None
            ),
            "active_submission_generation": (
                int(active_submission_generation)
                if active_submission_generation is not None
                else None
            ),
        }
        path.write_text(json.dumps(obj, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
        head = self._to_head(obj=obj)
        self.append_event(
            workspace_id=workspace_id,
            conversation_id=conversation_id,
            event_type="head_update",
            summary=str(last_delivery_summary or "").strip() or str(last_delivery_state or "").strip() or None,
            data={
                "active_project_id": obj["active_project_id"],
                "pending_contract": obj["pending_contract"],
                "expected_next_user_act": obj["expected_next_user_act"],
                "blocker": obj["blocker"],
                "last_delivery_state": obj["last_delivery_state"],
                "last_delivery_summary": obj["last_delivery_summary"],
                "last_user_query": obj["last_user_query"],
                "last_user_query_at_utc": obj["last_user_query_at_utc"],
                "active_submission_id": obj["active_submission_id"],
                "active_submission_generation": obj["active_submission_generation"],
            },
        )
        return head

    def append_event(
        self,
        *,
        workspace_id: str,
        conversation_id: str,
        event_type: str,
        summary: Optional[str] = None,
        data: Optional[dict[str, Any]] = None,
    ) -> ContinuityEventV2:
        path = self._events_path(workspace_id=workspace_id, conversation_id=conversation_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        event = ContinuityEventV2(
            schema_version=self.schema_version,
            type="continuity_event_v2",
            event_id=f"ce_{_safe_segment(_utc_iso(), fallback='event')}_{_safe_segment(event_type, fallback='update')}",
            workspace_id=str(workspace_id),
            conversation_id=str(conversation_id),
            created_at_utc=_utc_iso(),
            event_type=str(event_type),
            summary=str(summary).strip() if str(summary or "").strip() else None,
            data=dict(data) if isinstance(data, dict) else None,
        )
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(event.to_json(), ensure_ascii=False, sort_keys=True) + "\n")
        return event

    def list_events(self, *, workspace_id: str, conversation_id: str, limit: int = 50) -> list[ContinuityEventV2]:
        path = self._events_path(workspace_id=workspace_id, conversation_id=conversation_id)
        if not path.exists():
            return []
        lines = path.read_text(encoding="utf-8").splitlines()
        out: list[ContinuityEventV2] = []
        for raw in lines[-max(1, int(limit)) :]:
            if not raw.strip():
                continue
            try:
                obj = json.loads(raw)
            except Exception:
                continue
            if not isinstance(obj, dict):
                continue
            out.append(
                ContinuityEventV2(
                    schema_version=str(obj.get("schema_version") or self.schema_version),
                    type=str(obj.get("type") or "continuity_event_v2"),
                    event_id=str(obj.get("event_id") or ""),
                    workspace_id=str(obj.get("workspace_id") or ""),
                    conversation_id=str(obj.get("conversation_id") or ""),
                    created_at_utc=str(obj.get("created_at_utc") or ""),
                    event_type=str(obj.get("event_type") or ""),
                    summary=str(obj.get("summary")).strip() if obj.get("summary") else None,
                    data=dict(obj.get("data")) if isinstance(obj.get("data"), dict) else None,
                )
            )
        return out

    def _to_head(self, *, obj: dict[str, Any]) -> ContinuityHeadV2:
        return ContinuityHeadV2(
            schema_version=str(obj.get("schema_version") or self.schema_version),
            workspace_id=str(obj.get("workspace_id") or ""),
            conversation_id=str(obj.get("conversation_id") or ""),
            updated_at_utc=str(obj.get("updated_at_utc") or _utc_iso()),
            active_project_id=str(obj.get("active_project_id")).strip() if obj.get("active_project_id") else None,
            pending_contract=dict(obj.get("pending_contract")) if isinstance(obj.get("pending_contract"), dict) else None,
            expected_next_user_act=(
                str(obj.get("expected_next_user_act")).strip() if obj.get("expected_next_user_act") else None
            ),
            last_clarification_question=(
                str(obj.get("last_clarification_question")).strip()
                if obj.get("last_clarification_question")
                else None
            ),
            blocker=dict(obj.get("blocker")) if isinstance(obj.get("blocker"), dict) else None,
            last_delivery_state=str(obj.get("last_delivery_state")).strip() if obj.get("last_delivery_state") else None,
            last_delivery_summary=(
                str(obj.get("last_delivery_summary")).strip() if obj.get("last_delivery_summary") else None
            ),
            interaction_mode_preference=(
                str(obj.get("interaction_mode_preference")).strip()
                if obj.get("interaction_mode_preference")
                else None
            ),
            last_user_query=str(obj.get("last_user_query")).strip() if obj.get("last_user_query") else None,
            last_user_query_at_utc=(
                str(obj.get("last_user_query_at_utc")).strip() if obj.get("last_user_query_at_utc") else None
            ),
            active_submission_id=(
                str(obj.get("active_submission_id")).strip() if obj.get("active_submission_id") else None
            ),
            active_submission_generation=(
                int(obj.get("active_submission_generation"))
                if obj.get("active_submission_generation") is not None
                else None
            ),
        )


class FileRuntimeSnapshotStore(ContinuityStoreV2):
    pass
