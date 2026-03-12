from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional
from uuid import uuid4

from agentos_next.kernel.executor import ExecuteRequest, ExecuteResult
from agentos_next.kernel.orchestrator import Orchestrator
from agentos_next.kernel.types import TraceContext
from agentos_next.runtime.local_executor import LocalExecutor


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


class ChannelInputError(RuntimeError):
    def __init__(self, message: str) -> None:
        super().__init__(message)


@dataclass(frozen=True)
class ChannelGatewayConfig:
    data_dir: str | Path = "data"
    operator_ref: str = ""
    keys_dir: Optional[str] = None
    verify_asvp: bool = True
    target: str = "auto"
    backend: str = "local_mock"
    model: Optional[str] = None
    remote_calls_armed: bool = False
    allow_network_egress: bool = False
    approved_by_human: bool = False
    replay_mode: bool = False
    workspace_id: str = "local"
    deadline_ms: int = 60000
    budget_slice: Optional[int] = None


class ChannelGatewayService:
    def __init__(self, config: ChannelGatewayConfig) -> None:
        self._cfg = config
        local_exec = LocalExecutor.for_data_dir(config.data_dir)
        self._orchestrator = Orchestrator.for_data_dir(str(config.data_dir), local_executor=local_exec)

    async def execute(
        self,
        payload: dict[str, Any],
        *,
        trace_id_default: Optional[str] = None,
    ) -> dict[str, Any]:
        req = self._to_execute_request(payload, trace_id_default=trace_id_default)
        res: ExecuteResult = await self._orchestrator.execute(req)
        return {
            "ok": res.status == "accepted",
            "status": res.status,
            "error_code": res.error_code,
            "trace_id": req.trace.trace_id,
            "turn_id": req.trace.turn_id,
            "span_id": req.trace.span_id,
            "evidence_refs": [er.ref for er in res.evidence_refs],
            "artifact_refs": list(res.artifact_refs),
        }

    def execute_sync(
        self,
        payload: dict[str, Any],
        *,
        trace_id_default: Optional[str] = None,
    ) -> dict[str, Any]:
        return asyncio.run(self.execute(payload, trace_id_default=trace_id_default))

    def _to_execute_request(self, payload: dict[str, Any], *, trace_id_default: Optional[str]) -> ExecuteRequest:
        if not isinstance(payload, dict):
            raise ChannelInputError("request body must be a JSON object")

        arguments = self._parse_arguments(payload)
        idempotency_key = self._parse_optional_str(payload.get("idempotency_key")) or _new_id("idem")

        trace_id = self._parse_optional_str(payload.get("trace_id")) or trace_id_default or _new_id("tr")
        turn_id = self._parse_optional_str(payload.get("turn_id")) or _new_id("turn")
        span_id = self._parse_optional_str(payload.get("span_id")) or _new_id("span")
        parent_span_id = self._parse_optional_str(payload.get("parent_span_id"))
        trace = TraceContext(trace_id=trace_id, turn_id=turn_id, span_id=span_id, parent_span_id=parent_span_id)

        workspace_id = self._parse_optional_str(payload.get("workspace_id")) or str(self._cfg.workspace_id)
        operator_ref = self._parse_optional_str(payload.get("operator_ref"))
        if operator_ref is None:
            operator_ref = self._parse_optional_str(payload.get("skill_ref"))
        if operator_ref is None:
            operator_ref = str(self._cfg.operator_ref).strip() or None
        if operator_ref is None:
            raise ChannelInputError("missing operator_ref")

        preferred_target = self._parse_optional_str(payload.get("preferred_target")) or str(self._cfg.target)
        if preferred_target not in {"auto", "local", "remote"}:
            preferred_target = "auto"

        req_policy = payload.get("policy_context")
        if req_policy is None:
            req_policy_obj: dict[str, Any] = {}
        elif isinstance(req_policy, dict):
            req_policy_obj = dict(req_policy)
        else:
            raise ChannelInputError("policy_context must be a JSON object when present")

        model = str(self._cfg.model) if self._cfg.model is not None else None
        if model is None:
            req_model = self._parse_optional_str(payload.get("model"))
            if req_model is None:
                req_model = self._parse_optional_str(req_policy_obj.get("model"))
            model = req_model

        policy_context = dict(req_policy_obj)
        policy_context["verify_asvp"] = bool(self._cfg.verify_asvp)
        policy_context["public_keys_dir"] = self._cfg.keys_dir
        policy_context["backend"] = str(self._cfg.backend)
        policy_context["model"] = model
        policy_context["remote_calls_armed"] = bool(self._cfg.remote_calls_armed)
        policy_context["allow_network_egress"] = bool(self._cfg.allow_network_egress)
        policy_context["approved_by_human"] = bool(self._cfg.approved_by_human)
        policy_context["replay_mode"] = bool(self._cfg.replay_mode)

        budget_slice = self._parse_optional_int(payload.get("budget_slice"))
        if budget_slice is None:
            budget_slice = self._cfg.budget_slice

        return ExecuteRequest(
            workspace_id=workspace_id,
            operator_ref=operator_ref,
            arguments=arguments,
            idempotency_key=idempotency_key,
            deadline_ms=int(self._cfg.deadline_ms),
            trace=trace,
            policy_context=policy_context,
            preferred_target=preferred_target,
            budget_slice=budget_slice,
        )

    def _parse_arguments(self, payload: dict[str, Any]) -> dict[str, Any]:
        arguments = payload.get("arguments")
        if arguments is None:
            arguments = payload.get("input")
        if arguments is None:
            msg = payload.get("message")
            if isinstance(msg, str) and msg.strip():
                arguments = {"request": msg}
        if not isinstance(arguments, dict):
            raise ChannelInputError("arguments must be a JSON object, or provide message string")
        return dict(arguments)

    def _parse_optional_str(self, value: Any) -> Optional[str]:
        if value is None:
            return None
        if not isinstance(value, str):
            raise ChannelInputError("expected string field")
        out = value.strip()
        return out or None

    def _parse_optional_int(self, value: Any) -> Optional[int]:
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, int):
            raise ChannelInputError("expected integer field")
        return int(value)
