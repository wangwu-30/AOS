from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from agentos_next.kernel.evidence_manifest import (
    ManifestWriteRequest,
    ManifestWriteResult,
    write_turn_manifest_once,
)
from agentos_next.kernel.evidence_store import FileEvidenceStore
from agentos_next.kernel.executor import ExecuteRequest, ExecuteResult, ExecuteTiming, Executor
from agentos_next.kernel.idempotency_store import FileIdempotencyStore, IdempotencyStore
from agentos_next.kernel.trace_logger import FileTraceLogger
from agentos_next.kernel.types import EvidenceRef, ExecutionTarget, TraceContext, TraceEvent
from agentos_next.runtime.local_executor import LocalExecutor
from agentos_next.runtime.remote_executor import RemoteExecutor


class Orchestrator:
    """Orchestrator routes execution requests to appropriate executors.

    Responsibilities:
    - Route to LocalExecutor or RemoteExecutor based on preferred_target
    - Handle 'auto' routing logic (future: cost/availability based)
    - Provide single entry point for execution

    Spec: docs/specs/EXECUTOR_API.md
    """

    def __init__(
        self,
        *,
        local_executor: Optional[LocalExecutor] = None,
        remote_executor: Optional[RemoteExecutor] = None,
        idempotency_store: Optional[IdempotencyStore] = None,
        data_dir: str = "data",
    ) -> None:
        """Initialize Orchestrator with executors.

        Args:
            local_executor: Local execution handler. If None, created lazily.
            remote_executor: Remote execution handler. If None, created lazily.
        """
        self._local_executor = local_executor
        self._remote_executor = remote_executor
        self._idempotency_store = idempotency_store
        self._data_dir = str(data_dir)

    @classmethod
    def for_data_dir(
        cls,
        data_dir: str = "data",
        *,
        local_executor: Optional[LocalExecutor] = None,
        remote_executor: Optional[RemoteExecutor] = None,
    ) -> "Orchestrator":
        return cls(
            local_executor=local_executor,
            remote_executor=remote_executor,
            idempotency_store=FileIdempotencyStore(data_dir=data_dir),
            data_dir=str(data_dir),
        )

    @property
    def local_executor(self) -> LocalExecutor:
        if self._local_executor is None:
            self._local_executor = LocalExecutor.for_data_dir()
        return self._local_executor

    @property
    def remote_executor(self) -> RemoteExecutor:
        if self._remote_executor is None:
            self._remote_executor = RemoteExecutor(data_dir=self._data_dir)
        return self._remote_executor

    def _select_executor(self, preferred_target: Optional[str]) -> tuple[Executor, ExecutionTarget]:
        """Select appropriate executor based on preferred_target.

        Routing logic:
        - 'local': force local execution
        - 'remote': force remote execution
        - 'auto': currently defaults to local (future: cost/availability based)

        Args:
            preferred_target: User's execution target preference.

        Returns:
            Tuple of (executor, actual_target)
        """
        target = preferred_target or "auto"

        if target == "local":
            return self.local_executor, "local"
        elif target == "remote":
            return self.remote_executor, "remote"
        elif target == "auto":
            # Currently auto defaults to local for safety
            # Future: consider cost, availability, skill requirements
            return self.local_executor, "local"
        else:
            # Unknown target, fallback to local (fail-safe)
            return self.local_executor, "local"

    def finalize_turn_manifest(
        self,
        *,
        trace: TraceContext,
        workspace_id: str,
        operator_ref: str,
        idempotency_key: str,
        execute_status: str,
        execute_error_code: Optional[str],
        policy_context: Optional[dict[str, Any]] = None,
    ) -> ManifestWriteResult:
        """THREAD-028: Seal a turn by writing a signed evidence manifest (one per trace_id/turn_id).

        Important:
        - This must be invoked exactly once per turn after all spans/steps have finished.
        - replay_mode is zero-write; in replay_mode we return a stable deny without writing evidence/trace.
        """
        policy = dict(policy_context or {})
        replay_mode = bool(policy.get("replay_mode", False))
        mw = ManifestWriteRequest(
            data_dir=Path(self._data_dir),
            trace=trace,
            workspace_id=workspace_id,
            operator_ref=operator_ref,
            idempotency_key=idempotency_key,
            execute_status=execute_status,
            execute_error_code=execute_error_code,
            evidence_refs=(),
            replay_mode=replay_mode,
        )
        mres = write_turn_manifest_once(req=mw)
        if mres.ok or replay_mode:
            return mres

        # Fail-closed: record a stable error evidence + trace ERROR event.
        err_code = str(mres.error_code or "E_EVIDENCE_VERIFY_FAILED")
        reason_code = str(mres.reason_code or "evidence_manifest_failed")
        evidence = FileEvidenceStore(data_dir=self._data_dir)
        trace_log = FileTraceLogger(data_dir=self._data_dir)

        payload: dict[str, Any] = {
            "schema_version": "1.0.0",
            "type": "evidence_manifest_error",
            "ok": False,
            "error_code": err_code,
            "reason_code": reason_code,
            "trace_id": trace.trace_id,
            "turn_id": trace.turn_id,
            "manifest_path": str(mres.paths.manifest_path) if mres.paths is not None else None,
            "signature_path": str(mres.paths.signature_path) if mres.paths is not None else None,
        }
        err_ref: EvidenceRef = evidence.add_json(payload, kind="error")
        trace_log.emit(
            TraceEvent(
                schema_version="1.0.0",
                ctx=trace,
                event_type="ERROR",
                ts=_utc_iso(),
                evidence_refs=(err_ref,),
                data={
                    "component": "evidence_manifest",
                    "error_code": err_code,
                    "reason_code": reason_code,
                    "manifest_path": payload.get("manifest_path"),
                    "signature_path": payload.get("signature_path"),
                },
            )
        )
        return mres

    async def execute(self, req: ExecuteRequest) -> ExecuteResult:
        """Execute a skill via appropriate executor.

        Routes the request based on:
        1. req.preferred_target (user preference)
        2. Skill execution_targets (skill's capabilities)
        3. Runtime policies (cost, availability)

        Args:
            req: ExecuteRequest with skill, input, trace, etc.

        Returns:
            ExecuteResult from selected executor
        """
        # Hard precheck for deadlines (MVP semantics).
        if int(req.deadline_ms) <= 0:
            _, target = self._select_executor(req.preferred_target)
            return _timeout_result(target=target, error_code="E_TIMEOUT")

        store = self._idempotency_store
        if store is not None:
            cached = store.get(workspace_id=req.workspace_id, idempotency_key=req.idempotency_key)
            if cached is not None:
                return cached

        executor, target = self._select_executor(req.preferred_target)
        try:
            res = await executor.execute(req)
        except Exception as _exc:
            # Fail closed: return stable error code without leaking stack traces.
            import traceback
            print(f"[ORCH] execute exception: {_exc}")
            traceback.print_exc()
            res = _failed_result(target=target, error_code="E_EXECUTION_FAILED")

        if store is not None:
            store.put_if_absent(workspace_id=req.workspace_id, idempotency_key=req.idempotency_key, result=res)

        return res


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _timeout_result(*, target: ExecutionTarget, error_code: str) -> ExecuteResult:
    now = _utc_iso()
    return ExecuteResult(
        status="timeout",
        evidence_refs=(),
        artifact_refs=(),
        error_code=error_code,
        timing=ExecuteTiming(started_at=now, ended_at=now),
        target=target,
    )


def _failed_result(*, target: ExecutionTarget, error_code: str) -> ExecuteResult:
    now = _utc_iso()
    return ExecuteResult(
        status="failed",
        evidence_refs=(),
        artifact_refs=(),
        error_code=error_code,
        timing=ExecuteTiming(started_at=now, ended_at=now),
        target=target,
    )
