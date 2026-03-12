from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Optional, Sequence

from .types import EvidenceRef, ExecutionTarget, TraceContext

ExecuteStatus = Literal["accepted", "rejected", "failed", "canceled", "timeout"]


@dataclass(frozen=True, init=False)
class ExecuteRequest:
    """Spec: docs/specs/EXECUTOR_API.md"""

    workspace_id: str
    operator_ref: str
    arguments: dict[str, Any]
    idempotency_key: str
    deadline_ms: int
    trace: TraceContext
    policy_context: dict[str, Any]
    preferred_target: Optional[Literal["auto", "local", "remote"]] = None
    priority: Optional[int] = None
    budget_slice: Optional[int] = None

    def __init__(
        self,
        *,
        workspace_id: str,
        operator_ref: Optional[str] = None,
        arguments: Optional[dict[str, Any]] = None,
        idempotency_key: str,
        deadline_ms: int,
        trace: TraceContext,
        policy_context: dict[str, Any],
        preferred_target: Optional[Literal["auto", "local", "remote"]] = None,
        priority: Optional[int] = None,
        budget_slice: Optional[int] = None,
        skill_ref: Optional[str] = None,
        input: Optional[dict[str, Any]] = None,
    ) -> None:
        object.__setattr__(self, "workspace_id", str(workspace_id))
        resolved_operator_ref = str(operator_ref or skill_ref or "").strip()
        if not resolved_operator_ref:
            raise ValueError("operator_ref is required")
        object.__setattr__(self, "operator_ref", resolved_operator_ref)
        object.__setattr__(self, "arguments", dict(arguments if isinstance(arguments, dict) else (input or {})))
        object.__setattr__(self, "idempotency_key", str(idempotency_key))
        object.__setattr__(self, "deadline_ms", int(deadline_ms))
        object.__setattr__(self, "trace", trace)
        object.__setattr__(self, "policy_context", dict(policy_context or {}))
        object.__setattr__(self, "preferred_target", preferred_target)
        object.__setattr__(self, "priority", priority)
        object.__setattr__(self, "budget_slice", budget_slice)

    @property
    def skill_ref(self) -> str:  # legacy shim
        return self.operator_ref

    @property
    def input(self) -> dict[str, Any]:  # legacy shim
        return self.arguments


@dataclass(frozen=True)
class ExecuteTiming:
    started_at: str
    ended_at: str


@dataclass(frozen=True)
class ExecuteResult:
    """Spec: docs/specs/EXECUTOR_API.md"""

    status: ExecuteStatus
    evidence_refs: Sequence[EvidenceRef]
    artifact_refs: Sequence[str]
    error_code: Optional[str]
    timing: ExecuteTiming
    target: ExecutionTarget


class Executor:
    """Executor interface.

    Implementations: LocalExecutor, RemoteExecutor, ProxyExecutor.
    """

    target: ExecutionTarget

    async def execute(self, req: ExecuteRequest) -> ExecuteResult:  # pragma: no cover (interface)
        raise NotImplementedError
