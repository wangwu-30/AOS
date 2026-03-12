from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Optional

ExecutionTarget = Literal["local", "remote"]


@dataclass(frozen=True)
class TraceContext:
    """Correlation keys for Evidence/Trace.

    Spec: docs/specs/EVIDENCE_TRACE.md
    """

    trace_id: str
    turn_id: str
    span_id: str
    parent_span_id: Optional[str] = None


EvidenceKind = Literal[
    "tool_io",
    "llm_io",
    "policy",
    "routing",
    "snapshot",
    "artifact_draft",
    "error",
    "context_routing",
]


@dataclass(frozen=True)
class EvidenceRef:
    """Minimal metadata for an evidence blob.

    Spec: docs/specs/EVIDENCE_TRACE.md
    """

    ref: str
    kind: EvidenceKind
    ts: str
    size_bytes: int
    preview: Optional[str] = None


TraceEventType = Literal[
    "TOOL_CALL_STARTED",
    "TOOL_CALL_FINISHED",
    "POLICY_DECIDED",
    "ROUTED",
    "RETRIEVAL_CHAIN",
    "ARTIFACT_COMMITTED",
    "DIALOG_EVENT",
    "ERROR",
    "CONTEXT_COMPILED",
]


@dataclass(frozen=True)
class TraceEvent:
    """A single trace event with evidence references.

    Spec: docs/specs/EVIDENCE_TRACE.md
    """

    schema_version: str
    ctx: TraceContext
    event_type: TraceEventType
    ts: str
    evidence_refs: tuple[EvidenceRef, ...] = ()
    data: Optional[dict[str, Any]] = None
