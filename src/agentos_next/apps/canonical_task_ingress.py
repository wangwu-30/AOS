from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from agentos_next.apps.assistant_loop import AssistantLoopRequest
from agentos_next.kernel.evidence_store import FileEvidenceStore
from agentos_next.kernel.trace_logger import FileTraceLogger
from agentos_next.kernel.types import TraceEvent


@dataclass(frozen=True)
class IngressEnvelopeV1:
    schema_version: str
    source: str
    conversation_id: Optional[str]
    message_id: Optional[str]
    raw_text: str
    attachments: tuple[dict[str, Any], ...]
    received_at_utc: Optional[str]
    submitter_metadata: dict[str, Any]


@dataclass(frozen=True)
class CanonicalTaskIngressRequest:
    """Canonical task ingress wrapper for all assistant submitters."""

    ingress_envelope: IngressEnvelopeV1
    runtime_request: AssistantLoopRequest
    submitter: str = "runtime.direct"
    consumer: str = "runtime.result"

    @property
    def loop_request(self) -> AssistantLoopRequest:  # legacy shim
        return self.runtime_request

    @property
    def raw_input(self) -> str:  # legacy shim
        return self.ingress_envelope.raw_text


def build_ingress_envelope_v1(
    *,
    source: str,
    raw_text: str,
    conversation_id: Optional[str] = None,
    message_id: Optional[str] = None,
    attachments: Optional[list[dict[str, Any]]] = None,
    received_at_utc: Optional[str] = None,
    submitter_metadata: Optional[dict[str, Any]] = None,
) -> IngressEnvelopeV1:
    return IngressEnvelopeV1(
        schema_version="1.0.0",
        source=str(source or "runtime.direct").strip() or "runtime.direct",
        conversation_id=(str(conversation_id).strip() if str(conversation_id or "").strip() else None),
        message_id=(str(message_id).strip() if str(message_id or "").strip() else None),
        raw_text=str(raw_text or ""),
        attachments=tuple(dict(x) for x in (attachments or []) if isinstance(x, dict)),
        received_at_utc=(str(received_at_utc).strip() if str(received_at_utc or "").strip() else None),
        submitter_metadata=dict(submitter_metadata or {}),
    )


def build_canonical_task_ingress_request(
    loop_request: AssistantLoopRequest,
    *,
    submitter: str,
    consumer: str,
    raw_input: Optional[str] = None,
    metadata: Optional[dict[str, Any]] = None,
) -> CanonicalTaskIngressRequest:
    envelope = build_ingress_envelope_v1(
        source=str(submitter or "runtime.direct"),
        raw_text=str(raw_input if raw_input is not None else loop_request.query),
        conversation_id=loop_request.conversation_id,
        attachments=list(loop_request.attachments or ()),
        received_at_utc=loop_request.message_received_at_utc,
        submitter_metadata=metadata,
    )
    return CanonicalTaskIngressRequest(
        ingress_envelope=envelope,
        runtime_request=loop_request,
        submitter=str(submitter or "runtime.direct").strip() or "runtime.direct",
        consumer=str(consumer or "runtime.result").strip() or "runtime.result",
    )


def normalize_canonical_task_ingress_request(
    req: AssistantLoopRequest | CanonicalTaskIngressRequest,
    *,
    submitter: str = "runtime.direct",
    consumer: str = "runtime.result",
    metadata: Optional[dict[str, Any]] = None,
) -> CanonicalTaskIngressRequest:
    if isinstance(req, CanonicalTaskIngressRequest):
        return req
    return build_canonical_task_ingress_request(
        req,
        submitter=submitter,
        consumer=consumer,
        raw_input=req.query,
        metadata=metadata,
    )


def record_canonical_task_ingress(req: CanonicalTaskIngressRequest) -> str:
    loop_req = req.runtime_request
    data_dir = Path(loop_req.data_dir)
    evidence = FileEvidenceStore(data_dir=data_dir)
    trace_log = FileTraceLogger(data_dir=data_dir)

    payload = {
        "schema_version": "1.0.0",
        "type": "canonical_task_ingress_v1",
        "submitter": req.submitter,
        "consumer": req.consumer,
        "workspace_id": str(loop_req.workspace_id),
        "trace_id": str(loop_req.trace.trace_id),
        "turn_id": str(loop_req.trace.turn_id),
        "span_id": str(loop_req.trace.span_id),
        "ingress_envelope": {
            "schema_version": req.ingress_envelope.schema_version,
            "source": req.ingress_envelope.source,
            "conversation_id": req.ingress_envelope.conversation_id,
            "message_id": req.ingress_envelope.message_id,
            "raw_text": req.ingress_envelope.raw_text,
            "attachments": list(req.ingress_envelope.attachments),
            "received_at_utc": req.ingress_envelope.received_at_utc,
            "submitter_metadata": dict(req.ingress_envelope.submitter_metadata),
        },
    }
    ingress_ref = evidence.add_json(payload, kind="routing")
    trace_log.emit(
        TraceEvent(
            schema_version="1.0.0",
            ctx=loop_req.trace,  # type: ignore[arg-type]
            event_type="ROUTED",
            ts=ingress_ref.ts,
            evidence_refs=(ingress_ref,),
            data={
                "component": "canonical_task_ingress",
                "submitter": req.submitter,
                "consumer": req.consumer,
                "source": req.ingress_envelope.source,
            },
        )
    )
    return ingress_ref.ref
