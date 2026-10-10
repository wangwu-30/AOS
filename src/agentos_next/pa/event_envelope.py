from __future__ import annotations

import json
from dataclasses import asdict, dataclass, is_dataclass
from typing import Any, Literal, Optional, TypedDict

# NOTE: This is the shared V0 contract for THREAD-033/034/035.
# Spec: docs/specs/PA_EVENT_ENVELOPE_V0.md

SCHEMA_VERSION_V0 = "1.0.0"


@dataclass(frozen=True)
class EventEnvelopeV0:
    schema_version: Literal["1.0.0"]
    event_id: str
    idempotency_key: str
    source: str
    received_at_utc: str
    workspace_id: str
    conversation_id: str
    sender_id: str
    message_text: str
    budget_slice_remote_llm_calls: int
    message_attachments: Optional[list[dict[str, Any]]] = None

    # Reserved for forward-compatible extension (policy-only; MUST NOT drive allow/deny in-app).
    policy_context_passthrough: Optional[dict[str, Any]] = None


class EnvelopeDict(TypedDict, total=False):
    schema_version: str
    event_id: str
    idempotency_key: str
    source: str
    received_at_utc: str
    workspace_id: str
    conversation_id: str
    sender_id: str
    message_text: str
    budget_slice_remote_llm_calls: Any
    message_attachments: Any
    policy_context_passthrough: Any


def canonical_json(obj: Any) -> str:
    # Stable JSON (used across the repo for replay/determinism).
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def envelope_to_dict(env: Any) -> EnvelopeDict:
    if env is None:
        return {}
    if isinstance(env, dict):
        return dict(env)  # type: ignore[return-value]
    if is_dataclass(env):
        return asdict(env)  # type: ignore[return-value]
    # Fallback: best-effort attribute extraction.
    out: dict[str, Any] = {}
    for k in (
        "schema_version",
        "event_id",
        "idempotency_key",
        "source",
        "received_at_utc",
        "workspace_id",
        "conversation_id",
        "sender_id",
        "message_text",
        "budget_slice_remote_llm_calls",
        "message_attachments",
        "policy_context_passthrough",
    ):
        if hasattr(env, k):
            out[k] = getattr(env, k)
    return out  # type: ignore[return-value]


def validate_envelope_v0(obj: EnvelopeDict) -> tuple[bool, Optional[str]]:
    # REQUIRED (frozen):
    # - event_id: str non-empty
    # - idempotency_key: str non-empty
    # - workspace_id: str non-empty
    # - message_text: str (can be empty but usually non-empty)
    # - budget_slice_remote_llm_calls: int >= 0 (bool is invalid)
    event_id = obj.get("event_id")
    if not isinstance(event_id, str) or not event_id.strip():
        return False, "missing_or_invalid_event_id"
    idem = obj.get("idempotency_key")
    if not isinstance(idem, str) or not idem.strip():
        return False, "missing_or_invalid_idempotency_key"
    ws = obj.get("workspace_id")
    if not isinstance(ws, str) or not ws.strip():
        return False, "missing_or_invalid_workspace_id"
    msg = obj.get("message_text")
    if not isinstance(msg, str):
        return False, "missing_or_invalid_message_text"
    bud = obj.get("budget_slice_remote_llm_calls")
    if isinstance(bud, bool) or not isinstance(bud, int) or int(bud) < 0:
        return False, "missing_or_invalid_budget_slice_remote_llm_calls"
    ver = obj.get("schema_version")
    if ver is not None and str(ver).strip() != SCHEMA_VERSION_V0:
        return False, "schema_version_mismatch"
    return True, None
