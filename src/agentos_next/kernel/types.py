from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Optional

ExecutionTarget = Literal["local", "remote"]
ExecutionLaneRef = Literal["fast_chat", "standard_task", "deep_task", "research_task", "skill_exec"]
EffectClassV1 = Literal["read_only", "workspace_write", "external_effect", "user_visible_delivery"]
ContextStrategyV1 = Literal["auto_enrich_then_clarify", "clarify_before_execution", "assumption_allowed"]
OperatorPurityV1 = EffectClassV1
IdempotencyClassV1 = Literal["idempotent", "caller_scoped", "non_idempotent"]
RetryClassV1 = Literal["safe", "idempotent_retry", "no_auto_retry"]
OperatorVisibilityV1 = Literal["canonical", "compat", "internal"]
AssumptionFallbackStrategyV1 = Literal["need_context", "leader_escalation", "abort"]


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


@dataclass(frozen=True)
class ResourceBudgetV1:
    """Canonical resource budget object.

    Spec: docs/specs/MVP_057_KERNEL_CHARTER_AND_RESOURCE_MODEL.md
    """

    compute_units: int = 0
    time_budget_ms: int = 0
    context_units: int = 8
    io_calls_max: int = 4
    side_effect_calls_max: int = 0
    delivery_ops_max: int = 1


@dataclass(frozen=True)
class ResourceCostVectorV1:
    """Canonical per-operator resource cost vector."""

    compute_cost: int = 0
    time_cost: int = 0
    context_cost: int = 0
    io_cost: int = 0
    side_effect_cost: int = 0
    delivery_cost: int = 0


@dataclass(frozen=True)
class OperatorContractV1:
    """Canonical operator contract."""

    operator_ref: str = ""
    purity: OperatorPurityV1 = "read_only"
    idempotency_class: IdempotencyClassV1 = "idempotent"
    retry_class: RetryClassV1 = "safe"
    preflight_required: bool = True
    degraded_behavior: str = "surface_to_runtime"
    resource_cost_vector: ResourceCostVectorV1 = field(default_factory=ResourceCostVectorV1)
    visibility: OperatorVisibilityV1 = "canonical"


@dataclass(frozen=True)
class MissingInputV1:
    """Structured missing input declaration."""

    input_key: str = ""
    resolution_strategy: str = ""


@dataclass(frozen=True)
class ContextSegmentV1:
    """Single context segment inside a task-scoped snapshot."""

    source_ref: str = ""
    kind: str = ""
    content_hash: str = ""
    token_estimate: int = 0


@dataclass(frozen=True)
class SelectedContextV1:
    """Selected context payload for one task-scoped snapshot."""

    memory_hits: tuple[Any, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    file_refs: tuple[str, ...] = ()
    context_segments: tuple[ContextSegmentV1, ...] = ()


@dataclass(frozen=True)
class AssumptionEvidenceV1:
    """Structured assumption evidence for assumption_continue path."""

    assumption_text: str = ""
    confidence: float = 0.5
    fallback_strategy: AssumptionFallbackStrategyV1 = "need_context"
    snapshot_id: str = ""

    def __post_init__(self) -> None:
        if not 0.0 <= float(self.confidence) <= 1.0:
            raise ValueError("confidence must be within [0.0, 1.0]")


@dataclass(frozen=True)
class OpenGapsV1:
    """Open gaps and assumptions for one task-scoped snapshot."""

    missing_inputs: tuple[MissingInputV1, ...] = ()
    assumptions: tuple[AssumptionEvidenceV1, ...] = ()


@dataclass(frozen=True)
class TaskContextSnapshotV1:
    """Canonical task-scoped context snapshot."""

    snapshot_id: str = ""
    task_id: str = ""
    submission_id: str = ""
    generation: int = 1
    frozen_at_generation: int = 1
    task_contract: dict[str, Any] = field(default_factory=dict)
    selected_context: SelectedContextV1 = field(default_factory=SelectedContextV1)
    execution_boundary: dict[str, Any] = field(default_factory=dict)
    open_gaps: OpenGapsV1 = field(default_factory=OpenGapsV1)
    provenance: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if int(self.frozen_at_generation) != int(self.generation):
            raise ValueError("frozen_at_generation must match generation")


@dataclass(frozen=True)
class ResourceEscalationRequestV1:
    """Structured escalation request raised by a worker."""

    request_id: str = ""
    task_id: str = ""
    submission_id: str = ""
    generation: int = 1
    discovered_resource_ref: str = ""
    requested_effect_class: EffectClassV1 = "workspace_write"
    reason: str = ""
    evidence_refs: tuple[str, ...] = ()
    side_effect_boundary_reached: bool = False
    escalation_count: int = 1

    def __post_init__(self) -> None:
        if int(self.escalation_count) < 1:
            raise ValueError("escalation_count must be >= 1")


@dataclass(frozen=True)
class TaskSpecV1:
    """Canonical task submission contract."""

    task_id: str = ""
    submission_id: str = ""
    generation: int = 1
    objective: str = ""
    acceptance_contract_ref: str = ""
    effect_class: EffectClassV1 = "read_only"
    execution_lane: ExecutionLaneRef = "standard_task"
    resource_budget: ResourceBudgetV1 = field(default_factory=ResourceBudgetV1)
    policy_context: dict[str, Any] = field(default_factory=dict)
    context_refs: tuple[Any, ...] = ()
    attachments: tuple[Any, ...] = ()
    missing_inputs: tuple[MissingInputV1, ...] = ()
    context_strategy: ContextStrategyV1 = "auto_enrich_then_clarify"
    max_escalation_count: int = 2
    application_context_ref: Optional[str] = None

    def __post_init__(self) -> None:
        if int(self.max_escalation_count) < 1:
            raise ValueError("max_escalation_count must be >= 1")
