from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from agentos_next.kernel.runtime_snapshot_store import ContinuityHeadV2, FileRuntimeSnapshotStore


@dataclass(frozen=True)
class ConversationState:
    schema_version: str
    workspace_id: str
    conversation_id: str
    updated_at_utc: str
    active_project_id: Optional[str] = None
    last_pending_task: Optional[str] = None
    expected_next_user_act: Optional[str] = None
    last_clarification_question: Optional[str] = None
    last_delivery_state: Optional[str] = None
    last_delivery_summary: Optional[str] = None
    interaction_mode_preference: Optional[str] = None
    pending_contract: Optional[dict[str, Any]] = None
    last_user_query: Optional[str] = None
    last_user_query_at_utc: Optional[str] = None
    active_submission_id: Optional[str] = None
    active_submission_generation: Optional[int] = None


class FileConversationStateStore:
    """Conversation-state facade over continuity head storage."""

    def __init__(self, data_dir: str = "data") -> None:
        self._delegate = FileRuntimeSnapshotStore(data_dir=data_dir)

    def get(self, *, workspace_id: str, conversation_id: str) -> Optional[ConversationState]:
        snap = self._delegate.get(workspace_id=workspace_id, conversation_id=conversation_id)
        if snap is None:
            return None
        return self._from_snapshot(snap)

    def put(
        self,
        *,
        workspace_id: str,
        conversation_id: str,
        active_project_id: Optional[str] = None,
        last_pending_task: Optional[str] = None,
        expected_next_user_act: Optional[str] = None,
        last_clarification_question: Optional[str] = None,
        last_delivery_state: Optional[str] = None,
        last_delivery_summary: Optional[str] = None,
        interaction_mode_preference: Optional[str] = None,
        pending_contract: Optional[dict[str, Any]] = None,
        active_submission_id: Optional[str] = None,
        active_submission_generation: Optional[int] = None,
    ) -> ConversationState:
        contract = dict(pending_contract) if isinstance(pending_contract, dict) else None
        if contract is None and str(last_pending_task or "").strip():
            contract = {"objective": str(last_pending_task).strip()}
        snap = self._delegate.put(
            workspace_id=workspace_id,
            conversation_id=conversation_id,
            active_project_id=active_project_id,
            pending_contract=contract,
            expected_next_user_act=expected_next_user_act,
            last_clarification_question=last_clarification_question,
            last_delivery_state=last_delivery_state,
            last_delivery_summary=last_delivery_summary,
            interaction_mode_preference=interaction_mode_preference,
            active_submission_id=active_submission_id,
            active_submission_generation=active_submission_generation,
        )
        return self._from_snapshot(snap)

    @staticmethod
    def _from_snapshot(snap: ContinuityHeadV2) -> ConversationState:
        pending_contract = dict(snap.pending_contract) if isinstance(snap.pending_contract, dict) else None
        last_pending_task = None
        if pending_contract is not None:
            objective = str(pending_contract.get("objective") or "").strip()
            if objective:
                last_pending_task = objective
        return ConversationState(
            schema_version=snap.schema_version,
            workspace_id=snap.workspace_id,
            conversation_id=snap.conversation_id,
            updated_at_utc=snap.updated_at_utc,
            active_project_id=snap.active_project_id,
            last_pending_task=last_pending_task,
            expected_next_user_act=snap.expected_next_user_act,
            last_clarification_question=snap.last_clarification_question,
            last_delivery_state=snap.last_delivery_state,
            last_delivery_summary=snap.last_delivery_summary,
            interaction_mode_preference=snap.interaction_mode_preference,
            pending_contract=pending_contract,
            last_user_query=snap.last_user_query,
            last_user_query_at_utc=snap.last_user_query_at_utc,
            active_submission_id=snap.active_submission_id,
            active_submission_generation=snap.active_submission_generation,
        )
