from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from agentos_next.kernel.evidence_store import FileEvidenceStore
from agentos_next.kernel.types import EvidenceRef


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class MeteringEventV0:
    schema_version: str
    type: str
    ts: str
    workspace_id: str
    event_id: str
    trace_id: str
    turn_id: str
    op: str
    ok: bool
    error_code: Optional[str]
    budget_slice_remote_llm_calls: int

    def to_json(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "type": self.type,
            "ts": self.ts,
            "workspace_id": self.workspace_id,
            "event_id": self.event_id,
            "trace_id": self.trace_id,
            "turn_id": self.turn_id,
            "op": self.op,
            "ok": bool(self.ok),
            "error_code": self.error_code,
            "budget_slice_remote_llm_calls": int(self.budget_slice_remote_llm_calls),
        }


def write_metering_evidence_v0(
    *,
    evidence: FileEvidenceStore,
    workspace_id: str,
    event_id: str,
    trace_id: str,
    turn_id: str,
    op: str,
    ok: bool,
    error_code: Optional[str],
    budget_slice_remote_llm_calls: int,
) -> EvidenceRef:
    payload = MeteringEventV0(
        schema_version="1.0.0",
        type="metering_v0",
        ts=_utc_iso(),
        workspace_id=workspace_id,
        event_id=event_id,
        trace_id=trace_id,
        turn_id=turn_id,
        op=op,
        ok=bool(ok),
        error_code=error_code,
        budget_slice_remote_llm_calls=int(budget_slice_remote_llm_calls),
    )
    return evidence.add_json(payload.to_json(), kind="snapshot")

