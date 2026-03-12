from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from agentos_next.apps.assistant_loop import AssistantLoopRequest, AssistantLoopResult, run_assistant_loop_async
from agentos_next.apps.canonical_task_ingress import (
    CanonicalTaskIngressRequest,
    normalize_canonical_task_ingress_request,
    record_canonical_task_ingress,
)


AssistantRuntimeMode = Literal["direct", "hybrid"]


@dataclass(frozen=True)
class AssistantRuntimeRequest:
    """Canonical runtime facade request for assistant loop execution."""

    ingress_request: CanonicalTaskIngressRequest
    runtime_mode: AssistantRuntimeMode = "hybrid"
    direct_fallback: bool = True


class AssistantRuntime:
    """Canonical runtime facade with internal fast-path selection.

    runtime_mode only selects an internal shell strategy; it does not
    represent a second active runtime surface.
    """

    async def run(self, req: AssistantRuntimeRequest) -> AssistantLoopResult:
        ingress_ref = record_canonical_task_ingress(req.ingress_request)
        mode = str(req.runtime_mode or "hybrid").strip().lower()
        if mode not in {"direct", "hybrid"}:
            mode = "hybrid"

        if mode == "direct":
            res = await self._run_direct(req.ingress_request)
            return _attach_ingress_ref(res, ingress_ref)

        try:
            res = await self._run_hybrid(req.ingress_request)
        except Exception:
            if not bool(req.direct_fallback):
                raise
            res = await self._run_direct(req.ingress_request)
        return _attach_ingress_ref(res, ingress_ref)

    async def _run_direct(self, ingress_req: CanonicalTaskIngressRequest) -> AssistantLoopResult:
        return await run_assistant_loop_async(ingress_req.runtime_request)

    async def _run_hybrid(self, ingress_req: CanonicalTaskIngressRequest) -> AssistantLoopResult:
        # Spike-RT1 minimal event-dispatch shell (single-writer sequential queue).
        queue: list[tuple[str, CanonicalTaskIngressRequest]] = [("USER_INPUT", ingress_req)]
        while queue:
            event_type, payload = queue.pop(0)
            if event_type == "USER_INPUT":
                return await run_assistant_loop_async(payload.runtime_request)
        raise RuntimeError("E_EXECUTION_FAILED")


async def run_assistant_runtime_async(
    loop_req: AssistantLoopRequest | CanonicalTaskIngressRequest,
    *,
    runtime_mode: AssistantRuntimeMode = "hybrid",
    direct_fallback: bool = True,
    submitter: str = "runtime.direct",
    consumer: str = "runtime.result",
    ingress_metadata: dict[str, Any] | None = None,
) -> AssistantLoopResult:
    runtime = AssistantRuntime()
    ingress_request = normalize_canonical_task_ingress_request(
        loop_req,
        submitter=submitter,
        consumer=consumer,
        metadata=ingress_metadata,
    )
    return await runtime.run(
        AssistantRuntimeRequest(
            ingress_request=ingress_request,
            runtime_mode=runtime_mode,
            direct_fallback=bool(direct_fallback),
        )
    )


def _attach_ingress_ref(res: AssistantLoopResult, ingress_ref: str) -> AssistantLoopResult:
    merged_refs = list(dict.fromkeys([ingress_ref, *list(res.evidence_refs)]))
    if merged_refs == list(res.evidence_refs):
        return res
    return AssistantLoopResult(
        ok=res.ok,
        final_output=res.final_output,
        error_code=res.error_code,
        steps=res.steps,
        trace=res.trace,
        evidence_refs=merged_refs,
        followup_plan_ref=res.followup_plan_ref,
        followup_task_id=res.followup_task_id,
        delivery_state=res.delivery_state,
        graph_id=res.graph_id,
    )
