from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import bootstrap  # noqa: F401

from admission_helpers import make_minimal_skill_package
from agentos_next.kernel.capabilities import capability_items_for_policy_context
from agentos_next.kernel.executor import ExecuteRequest
from agentos_next.kernel.orchestrator import Orchestrator
from agentos_next.kernel.types import TraceContext
from agentos_next.llm.backend import CodexOAuthLLMBackend, LLMSafetyGate, LLMCallError, RemoteLLMCallBudget
from agentos_next.llm.openai_codex_oauth import OpenAICodexOAuthProvider
from agentos_next.runtime.local_executor import LocalExecutor

from test_openai_codex_oauth_provider import FakeTransport


class TestThread029BudgetV1(unittest.IsolatedAsyncioTestCase):
    async def test_budget_schema_invalid_is_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory(prefix="agentos_next_t029_schema_") as td:
            root = Path(td)
            pkg_dir = root / "pkg"
            data_dir = root / "data"
            make_minimal_skill_package(pkg_dir)

            orch = Orchestrator.for_data_dir(str(data_dir), local_executor=LocalExecutor.for_data_dir(data_dir))
            trace = TraceContext(trace_id="tr_t029_schema", turn_id="turn_t029_schema", span_id="span_t029_schema")
            # Intentionally wrong type; ExecuteRequest is a dataclass (no runtime type enforcement).
            req = ExecuteRequest(  # type: ignore[arg-type]
                workspace_id="ws_t029",
                skill_ref=str(pkg_dir),
                input={"q": "hi"},
                idempotency_key="idem_t029_schema_1",
                deadline_ms=3000,
                trace=trace,
                policy_context={"verify_asvp": False, "backend": "local_mock"},
                preferred_target="local",
                budget_slice="not-an-int",
            )
            res = await orch.execute(req)
            self.assertEqual(res.status, "rejected")
            self.assertEqual(res.error_code, "E_BUDGET_SCHEMA_INVALID")

    async def test_remote_llm_budget_zero_denies_at_allow_check(self) -> None:
        with tempfile.TemporaryDirectory(prefix="agentos_next_t029_exhausted_") as td:
            root = Path(td)
            pkg_dir = root / "pkg"
            data_dir = root / "data"
            make_minimal_skill_package(pkg_dir)

            orch = Orchestrator.for_data_dir(str(data_dir), local_executor=LocalExecutor.for_data_dir(data_dir))
            trace = TraceContext(trace_id="tr_t029_exh", turn_id="turn_t029_exh", span_id="span_t029_exh")
            req = ExecuteRequest(
                workspace_id="ws_t029",
                skill_ref=str(pkg_dir),
                input={"q": "hi"},
                idempotency_key="idem_t029_exh_1",
                deadline_ms=3000,
                trace=trace,
                policy_context={
                    "verify_asvp": False,
                    "backend": "codex_oauth",
                    "remote_calls_armed": True,
                    "allow_network_egress": True,
                    "capabilities": capability_items_for_policy_context(["net_egress", "llm_remote"]),
                },
                preferred_target="local",
                budget_slice=0,
            )
            res = await orch.execute(req)
            self.assertEqual(res.status, "rejected")
            self.assertEqual(res.error_code, "E_BUDGET_EXHAUSTED")

    def test_budget_decrement_blocks_second_remote_call(self) -> None:
        codex_url = "https://chatgpt.com/backend-api/codex/responses"
        with tempfile.TemporaryDirectory(prefix="agentos_next_t029_remote_") as td:
            token_path = Path(td) / "openai_oauth_token.json"
            token_path.write_text(json.dumps({"access_token": "x", "expires_at": 9999999999}), encoding="utf-8")

            ft = FakeTransport()
            ft.add_response(method="POST", url=codex_url, status=200, json_body={"output": {"ok": True}})

            provider = OpenAICodexOAuthProvider(
                remote_calls_armed=True,
                allow_network_egress=True,
                token_path=token_path,
                codex_endpoint=codex_url,
                transport=ft,
            )
            backend = CodexOAuthLLMBackend(provider)

            budget = RemoteLLMCallBudget(1)
            safety = LLMSafetyGate(
                remote_calls_armed=True,
                allow_network_egress=True,
                replay_mode=False,
                remote_llm_calls_budget=budget,
            )
            schema = {
                "type": "object",
                "additionalProperties": False,
                "required": ["ok"],
                "properties": {"ok": {"const": True}},
            }

            out1 = backend.complete_json(prompt="p1", json_schema=schema, safety=safety, model_id="m1")
            self.assertEqual(out1, {"ok": True})
            self.assertEqual(len(ft.requests), 1)

            with self.assertRaises(LLMCallError) as ctx:
                backend.complete_json(prompt="p2", json_schema=schema, safety=safety, model_id="m1")
            self.assertEqual(ctx.exception.error_code, "E_BUDGET_EXHAUSTED")
            self.assertEqual(len(ft.requests), 1, msg="second call must not reach transport when budget is exhausted")

    def test_provider_bad_response_exposes_status_and_body_preview(self) -> None:
        codex_url = "https://chatgpt.com/backend-api/codex/responses"
        with tempfile.TemporaryDirectory(prefix="agentos_next_t029_bad_resp_") as td:
            token_path = Path(td) / "openai_oauth_token.json"
            token_path.write_text(json.dumps({"access_token": "x", "expires_at": 9999999999}), encoding="utf-8")

            ft = FakeTransport()
            ft.add_response(
                method="POST",
                url=codex_url,
                status=403,
                json_body={"error": {"message": "forbidden", "type": "access_denied"}},
            )

            provider = OpenAICodexOAuthProvider(
                remote_calls_armed=True,
                allow_network_egress=True,
                token_path=token_path,
                codex_endpoint=codex_url,
                transport=ft,
            )
            backend = CodexOAuthLLMBackend(provider)
            safety = LLMSafetyGate(remote_calls_armed=True, allow_network_egress=True, replay_mode=False)
            schema = {
                "type": "object",
                "additionalProperties": False,
                "required": ["ok"],
                "properties": {"ok": {"const": True}},
            }

            with self.assertRaises(LLMCallError) as ctx:
                backend.complete_json(prompt="p", json_schema=schema, safety=safety, model_id="m1")

            self.assertEqual(ctx.exception.error_code, "E_PROVIDER_BAD_RESPONSE")
            self.assertIn("status=403", str(ctx.exception))
            self.assertIn("forbidden", str(ctx.exception))


if __name__ == "__main__":  # pragma: no cover
    unittest.main(verbosity=2)
