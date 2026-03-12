from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agentos_next.kernel.executor import ExecuteRequest, ExecuteResult, Executor, ExecuteTiming
from agentos_next.kernel.policy_engine import emit_policy_decision, evaluate_execute_policy


class RemoteExecutor(Executor):
    """Remote sandbox executor placeholder.

    This is a stub implementation that does NOT connect to any real remote service.
    It exists to validate the routing architecture and can be replaced with real
    remote execution (e.g., cloud sandbox) in the future.

    Spec: docs/specs/EXECUTOR_API.md
    Spec: docs/specs/SANDBOXING.md
    """

    target = "remote"

    def __init__(self, *, sandbox_endpoint: str = "https://sandbox.agentos.dev", data_dir: str | Path = "data") -> None:
        """Initialize RemoteExecutor.

        Args:
            sandbox_endpoint: Placeholder for future sandbox service URL.
        """
        self._sandbox_endpoint = sandbox_endpoint
        self._data_dir = Path(data_dir)

    async def execute(self, req: ExecuteRequest) -> ExecuteResult:
        """Execute a skill in remote sandbox (placeholder).

        This stub prepares the payload according to REMOTE_SANDBOX_API.md but
        returns a 'rejected' status because the actual network call is not implemented.

        Args:
            req: ExecuteRequest with skill_ref, input, trace, etc.

        Returns:
            ExecuteResult with status='rejected' and error_code='E_REMOTE_NOT_IMPLEMENTED'
        """
        policy_decision = evaluate_execute_policy(req=req, data_dir=self._data_dir)
        policy_ref = emit_policy_decision(
            data_dir=self._data_dir,
            trace=req.trace,
            decision=policy_decision,
        )
        if policy_decision.decision != "allow":
            now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            return ExecuteResult(
                status="rejected",
                evidence_refs=((policy_ref,) if policy_ref is not None else ()),
                artifact_refs=(),
                error_code=str(policy_decision.error_code or "E_POLICY_DENY"),
                timing=ExecuteTiming(started_at=now, ended_at=now),
                target="remote",
            )

        # 1. Prepare payload according to REMOTE_SANDBOX_API.md
        #
        # NOTE: This is a placeholder executor (no network). Still, we keep the payload mapping
        # aligned with the spec so tests and future integration don't drift.
        policy = dict(req.policy_context or {})
        model = policy.get("model")
        model_id = str(model or "")

        # Forward-compatible policy_context mapping: preserve unknown keys (including memory_context)
        # except values that are local-only implementation details.
        local_only_keys = {"public_keys_dir", "backend"}
        ext = {k: v for k, v in policy.items() if k not in local_only_keys and k not in ("model", "model_id_override")}

        payload = {
            "workspace_id": req.workspace_id,
            "operator_ref": req.operator_ref,
            "arguments": req.arguments,
            "idempotency_key": req.idempotency_key,
            "deadline_ms": req.deadline_ms,
            "trace_context": {
                "trace_id": req.trace.trace_id,
                "turn_id": req.trace.turn_id,
                "span_id": req.trace.span_id,
            },
            "policy_context": {
                # MR1: preferred key for model routing is "model".
                "model": model_id,
                "allow_network_egress": _as_bool(policy.get("allow_network_egress"), default=False),
                "verify_asvp": _as_bool(policy.get("verify_asvp"), default=True),
                **ext,
            },
        }

        # TODO: Implement actual HTTP/JSON call to self._sandbox_endpoint + "/v1/execute"
        # For now, just logging the payload (in a real scenario) or inspecting it in tests would be enough.
        # We simulate a "Network Call Not Implemented" error.

        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        return ExecuteResult(
            status="rejected",
            evidence_refs=(),
            artifact_refs=(),
            error_code="E_REMOTE_NOT_IMPLEMENTED",
            timing=ExecuteTiming(started_at=now, ended_at=now),
            target="remote",
        )


def remote_executor_placeholder() -> RemoteExecutor:
    """Factory function for creating RemoteExecutor instance."""
    return RemoteExecutor()


def _as_bool(value: Any, *, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        s = value.strip().lower()
        if s in {"1", "true", "yes", "on"}:
            return True
        if s in {"0", "false", "no", "off", ""}:
            return False
        return default
    return bool(value)
