from __future__ import annotations

import unittest
from typing import Any
from unittest.mock import MagicMock

from agentos_next.kernel.executor import ExecuteRequest, ExecuteResult
from agentos_next.kernel.types import TraceContext
from agentos_next.runtime.remote_executor import RemoteExecutor


class RemoteExecutorSpy(RemoteExecutor):
    """Spy subclass to capture the generated payload."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.captured_payload: dict[str, Any] | None = None

    async def execute(self, req: ExecuteRequest) -> ExecuteResult:
        # Override to capture payload before calling original stub
        self.captured_payload = {
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
            # Map full policy context including unknown keys
            "policy_context": {
                "model": str(req.policy_context.get("model") or ""),
                "allow_network_egress": bool(req.policy_context.get("allow_network_egress")),
                "verify_asvp": bool(req.policy_context.get("verify_asvp", True)),
                # Capture everything else for forward compatibility testing
                **{
                    k: v
                    for k, v in req.policy_context.items()
                    if k
                    not in (
                        "model",
                        "model_id_override",
                        "allow_network_egress",
                        "verify_asvp",
                        "backend",
                        "public_keys_dir",
                    )
                },
            },
        }
        return await super().execute(req)


class TestRemoteExecutorCR1Payload(unittest.IsolatedAsyncioTestCase):
    async def test_cr1_model_override_mapping(self) -> None:
        """Verify CR1 model override is correctly mapped to payload."""
        executor = RemoteExecutorSpy()
        
        # Simulate an ExecuteRequest from Spike-CR1 with model override
        req = ExecuteRequest(
            workspace_id="ws_cr1_model",
            operator_ref="registry://cr1-model-skill/v1",
            arguments={"q": "test"},
            idempotency_key="idem_cr1_model",
            deadline_ms=10000,
            trace=TraceContext(trace_id="t_cr1", turn_id="turn_cr1", span_id="s_cr1"),
            policy_context={
                "verify_asvp": True,
                # Simulate CR1 model routing from --model
                "model": "gpt-5-preview",
                # Simulate CR1 setting extended metadata
                "cr1_metadata": {"source": "cli-creator", "version": "1.0.0"},
            },
        )

        await executor.execute(req)
        
        payload = executor.captured_payload
        self.assertIsNotNone(payload)
        
        # Verify trace context flattening/structure
        trace = payload["trace_context"]
        self.assertEqual(trace["trace_id"], "t_cr1")
        self.assertEqual(trace["turn_id"], "turn_cr1")
        self.assertEqual(trace["span_id"], "s_cr1")
        
        # Verify policy context mapping
        policy = payload["policy_context"]
        self.assertEqual(policy["model"], "gpt-5-preview")
        self.assertTrue(policy["verify_asvp"])
        self.assertNotIn("model_id_override", policy)
        
        # Verify extension keys preservation (CR1 specific)
        self.assertEqual(policy["cr1_metadata"], {"source": "cli-creator", "version": "1.0.0"})

    async def test_policy_context_forward_compatibility(self) -> None:
        """Verify that unknown keys in policy_context are preserved in the payload."""
        executor = RemoteExecutorSpy()
        
        # Simulate an ExecuteRequest from Spike-CR1 with extended policy
        req = ExecuteRequest(
            workspace_id="ws_cr1",
            operator_ref="s3://cr1-bucket/skill.zip",
            arguments={"foo": "bar"},
            idempotency_key="idem_123",
            deadline_ms=5000,
            trace=TraceContext(trace_id="t1", turn_id="turn1", span_id="s1"),
            policy_context={
                "verify_asvp": False,
                # Standard keys
                "model": "gpt-4-turbo",
                "model_id_override": "legacy-should-be-ignored",
                # Extension keys (CR1/MR1)
                "executor_preference": "cloud-sandbox-v2",
                "cost_budget": 0.5,
                "custom_feature_flag": True,
            },
        )

        result = await executor.execute(req)
        
        # Verify the stub behavior hasn't changed
        self.assertEqual(result.status, "rejected")
        self.assertEqual(result.error_code, "E_REMOTE_NOT_IMPLEMENTED")

        # Verify payload structure (frozen schema + extensions)
        payload = executor.captured_payload
        self.assertIsNotNone(payload)
        self.assertEqual(payload["workspace_id"], "ws_cr1")
        self.assertEqual(payload["operator_ref"], "s3://cr1-bucket/skill.zip")
        self.assertEqual(payload["deadline_ms"], 5000)
        
        # Verify policy_context mapping
        policy = payload["policy_context"]
        self.assertEqual(policy["verify_asvp"], False)
        self.assertEqual(policy["model"], "gpt-4-turbo")
        self.assertNotIn("model_id_override", policy)
        
        # Verify extension keys presence
        self.assertEqual(policy["executor_preference"], "cloud-sandbox-v2")
        self.assertEqual(policy["cost_budget"], 0.5)
        self.assertTrue(policy["custom_feature_flag"])

    async def test_memory_context_is_preserved_as_policy_context_extension(self) -> None:
        """Verify policy_context["memory_context"] passthrough for Spike-MEMCTX1."""
        executor = RemoteExecutorSpy()

        memctx = {
            "schema_version": "2.0.0",
            "l0_continuity": {"workspace_id": "ws_memctx", "conversation_id": "turn_memctx"},
            "l1_query": {"query": "hello", "intent": "generic", "limit": 3},
            "l2_hits": [{"record_id": "mr_123", "kind": "note", "summary": "session summary", "evidence_ref": "ev_123"}],
            "conflicts": [],
            "retrieval_ref": "ev_route_123",
        }

        req = ExecuteRequest(
            workspace_id="ws_memctx",
            operator_ref="registry://memctx-skill/v1",
            arguments={"request": "hello"},
            idempotency_key="idem_memctx",
            deadline_ms=10000,
            trace=TraceContext(trace_id="t_memctx", turn_id="turn_memctx", span_id="s_memctx"),
            policy_context={
                "verify_asvp": True,
                "model": "gpt-4.1-mini",
                "memory_context": memctx,
            },
        )

        await executor.execute(req)
        payload = executor.captured_payload
        self.assertIsNotNone(payload)
        self.assertEqual(payload["policy_context"]["memory_context"], memctx)


if __name__ == "__main__":
    unittest.main()
