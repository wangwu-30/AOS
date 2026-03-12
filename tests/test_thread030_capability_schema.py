from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import bootstrap  # noqa: F401

from admission_helpers import make_minimal_skill_package
from agentos_next.kernel.capabilities import capability_items_for_policy_context, parse_capabilities
from agentos_next.kernel.executor import ExecuteRequest
from agentos_next.kernel.orchestrator import Orchestrator
from agentos_next.kernel.types import TraceContext
from agentos_next.runtime.local_executor import LocalExecutor


class TestThread030CapabilitySchema(unittest.IsolatedAsyncioTestCase):
    async def test_missing_net_egress_capability_denies(self) -> None:
        with TemporaryDirectory(prefix="agentos_next_t030_net_") as td:
            root = Path(td)
            pkg_dir = root / "pkg"
            data_dir = root / "data"
            make_minimal_skill_package(pkg_dir)

            orch = Orchestrator.for_data_dir(str(data_dir), local_executor=LocalExecutor.for_data_dir(data_dir))
            trace = TraceContext(trace_id="tr_t030_net", turn_id="turn_t030_net", span_id="span_t030_net")
            req = ExecuteRequest(
                workspace_id="ws_t030",
                skill_ref=str(pkg_dir),
                input={"q": "hi"},
                idempotency_key="idem_t030_net_1",
                deadline_ms=3000,
                trace=trace,
                policy_context={
                    "verify_asvp": False,
                    "backend": "local_mock",
                    "allow_network_egress": True,
                },
                preferred_target="local",
            )
            res = await orch.execute(req)
            self.assertEqual(res.status, "rejected")
            self.assertEqual(res.error_code, "E_CAPABILITY_DENY")

    async def test_missing_llm_remote_capability_denies_doubao_backend(self) -> None:
        with TemporaryDirectory(prefix="agentos_next_t030_doubao_") as td:
            root = Path(td)
            pkg_dir = root / "pkg"
            data_dir = root / "data"
            make_minimal_skill_package(pkg_dir)

            orch = Orchestrator.for_data_dir(str(data_dir), local_executor=LocalExecutor.for_data_dir(data_dir))
            trace = TraceContext(trace_id="tr_t030_doubao", turn_id="turn_t030_doubao", span_id="span_t030_doubao")
            req = ExecuteRequest(
                workspace_id="ws_t030",
                skill_ref=str(pkg_dir),
                input={"q": "hi"},
                idempotency_key="idem_t030_doubao_1",
                deadline_ms=3000,
                trace=trace,
                policy_context={
                    "verify_asvp": False,
                    "backend": "doubao_ark",
                },
                preferred_target="local",
            )
            res = await orch.execute(req)
            self.assertEqual(res.status, "rejected")
            self.assertEqual(res.error_code, "E_CAPABILITY_DENY")

    async def test_invalid_capabilities_schema_is_fail_closed(self) -> None:
        with TemporaryDirectory(prefix="agentos_next_t030_schema_") as td:
            root = Path(td)
            pkg_dir = root / "pkg"
            data_dir = root / "data"
            make_minimal_skill_package(pkg_dir)

            orch = Orchestrator.for_data_dir(str(data_dir), local_executor=LocalExecutor.for_data_dir(data_dir))
            trace = TraceContext(trace_id="tr_t030_schema", turn_id="turn_t030_schema", span_id="span_t030_schema")
            req = ExecuteRequest(
                workspace_id="ws_t030",
                skill_ref=str(pkg_dir),
                input={"q": "hi"},
                idempotency_key="idem_t030_schema_1",
                deadline_ms=3000,
                trace=trace,
                policy_context={
                    "verify_asvp": False,
                    "backend": "local_mock",
                    "capabilities": "not-a-list",
                },
                preferred_target="local",
            )
            res = await orch.execute(req)
            self.assertEqual(res.status, "rejected")
            self.assertEqual(res.error_code, "E_CAPABILITY_SCHEMA_INVALID")

    async def test_builtin_memory_write_requires_memory_write_capability(self) -> None:
        with TemporaryDirectory(prefix="agentos_next_t030_mem_") as td:
            root = Path(td)
            data_dir = root / "data"

            orch = Orchestrator.for_data_dir(str(data_dir), local_executor=LocalExecutor.for_data_dir(data_dir))
            trace = TraceContext(trace_id="tr_t030_mem", turn_id="turn_t030_mem", span_id="span_t030_mem")
            req = ExecuteRequest(
                workspace_id="ws_t030",
                skill_ref="builtin://memory.write",
                input={"content": "hello"},
                idempotency_key="idem_t030_mem_1",
                deadline_ms=3000,
                trace=trace,
                policy_context={"verify_asvp": True, "backend": "local_mock"},
                preferred_target="local",
            )
            res = await orch.execute(req)
            self.assertEqual(res.status, "rejected")
            self.assertEqual(res.error_code, "E_CAPABILITY_DENY")

            # Now allow with memory_write capability.
            req2 = ExecuteRequest(
                workspace_id="ws_t030",
                skill_ref="builtin://memory.write",
                input={"content": "hello"},
                idempotency_key="idem_t030_mem_2",
                deadline_ms=3000,
                trace=TraceContext(trace_id="tr_t030_mem2", turn_id="turn_t030_mem2", span_id="span_t030_mem2"),
                policy_context={
                    "verify_asvp": True,
                    "backend": "local_mock",
                    "capabilities": capability_items_for_policy_context(["memory_write"]),
                },
                preferred_target="local",
            )
            res2 = await orch.execute(req2)
            self.assertEqual(res2.status, "accepted", msg=f"error_code={res2.error_code}")

    async def test_web_browse_capability_implies_web_search(self) -> None:
        parsed = parse_capabilities({"capabilities": capability_items_for_policy_context(["web_browse"])})
        self.assertTrue(parsed.ok)
        self.assertIn("web_browse", parsed.names)
        self.assertIn("web_search", parsed.names)

    async def test_builtin_research_run_requires_research_run_capability(self) -> None:
        with TemporaryDirectory(prefix="agentos_next_t030_research_") as td:
            root = Path(td)
            data_dir = root / "data"

            orch = Orchestrator.for_data_dir(str(data_dir), local_executor=LocalExecutor.for_data_dir(data_dir))
            trace = TraceContext(trace_id="tr_t030_research", turn_id="turn_t030_research", span_id="span_t030_research")
            req = ExecuteRequest(
                workspace_id="ws_t030",
                skill_ref="builtin://research.run",
                input={"objective": "深入调研北京天气并给我带引用的报告"},
                idempotency_key="idem_t030_research_1",
                deadline_ms=3000,
                trace=trace,
                policy_context={"verify_asvp": False, "backend": "local_mock"},
                preferred_target="local",
            )
            res = await orch.execute(req)
            self.assertEqual(res.status, "rejected")
            self.assertEqual(res.error_code, "E_CAPABILITY_DENY")

            req2 = ExecuteRequest(
                workspace_id="ws_t030",
                skill_ref="builtin://research.run",
                input={"objective": "深入调研北京天气并给我带引用的报告", "min_sources": 1},
                idempotency_key="idem_t030_research_2",
                deadline_ms=3000,
                trace=TraceContext(trace_id="tr_t030_research2", turn_id="turn_t030_research2", span_id="span_t030_research2"),
                policy_context={
                    "verify_asvp": False,
                    "backend": "local_mock",
                    "capabilities": capability_items_for_policy_context(["research_run"]),
                },
                preferred_target="local",
            )
            with patch(
                "agentos_next.runtime.builtin_research._run_search_provider",
                return_value={
                    "provider_used": "duckduckgo_html",
                    "results": [{"title": "Source", "snippet": "Fact", "url": "https://example.com/source"}],
                    "attempts": [{"provider": "duckduckgo_html", "status": "ok"}],
                },
            ), patch(
                "agentos_next.runtime.builtin_research.playwright_browse",
                return_value={
                    "provider_used": "playwright",
                    "url": "https://example.com/source",
                    "final_url": "https://example.com/source",
                    "title": "Source",
                    "text": "Verified fact from the source.",
                },
            ):
                res2 = await orch.execute(req2)
            self.assertEqual(res2.status, "accepted", msg=f"error_code={res2.error_code}")

    async def test_builtin_assistant_submit_requires_assistant_runtime_submit_capability(self) -> None:
        with TemporaryDirectory(prefix="agentos_next_t030_assistant_") as td:
            root = Path(td)
            data_dir = root / "data"

            orch = Orchestrator.for_data_dir(str(data_dir), local_executor=LocalExecutor.for_data_dir(data_dir))
            trace = TraceContext(trace_id="tr_t030_assistant", turn_id="turn_t030_assistant", span_id="span_t030_assistant")
            req = ExecuteRequest(
                workspace_id="ws_t030",
                skill_ref="builtin://assistant.submit",
                input={"query": "hello"},
                idempotency_key="idem_t030_assistant_1",
                deadline_ms=3000,
                trace=trace,
                policy_context={"verify_asvp": False, "backend": "local_mock"},
                preferred_target="local",
            )
            res = await orch.execute(req)
            self.assertEqual(res.status, "rejected")
            self.assertEqual(res.error_code, "E_CAPABILITY_DENY")

            req2 = ExecuteRequest(
                workspace_id="ws_t030",
                skill_ref="builtin://assistant.submit",
                input={"query": "hello", "submitter": "test.scheduler", "consumer": "test.result"},
                idempotency_key="idem_t030_assistant_2",
                deadline_ms=6000,
                trace=TraceContext(
                    trace_id="tr_t030_assistant2",
                    turn_id="turn_t030_assistant2",
                    span_id="span_t030_assistant2",
                ),
                policy_context={
                    "verify_asvp": False,
                    "backend": "local_mock",
                    "capabilities": capability_items_for_policy_context(["assistant_runtime_submit"]),
                },
                preferred_target="local",
            )
            res2 = await orch.execute(req2)
            self.assertEqual(res2.status, "accepted", msg=f"error_code={res2.error_code}")

    async def test_builtin_channel_send_requires_channel_send_capability(self) -> None:
        with TemporaryDirectory(prefix="agentos_next_t030_channel_") as td:
            root = Path(td)
            data_dir = root / "data"

            orch = Orchestrator.for_data_dir(str(data_dir), local_executor=LocalExecutor.for_data_dir(data_dir))
            trace = TraceContext(trace_id="tr_t030_channel", turn_id="turn_t030_channel", span_id="span_t030_channel")
            req = ExecuteRequest(
                workspace_id="ws_t030",
                skill_ref="builtin://channel.send_message",
                input={"text": "hello"},
                idempotency_key="idem_t030_channel_1",
                deadline_ms=3000,
                trace=trace,
                policy_context={"verify_asvp": False, "backend": "local_mock"},
                preferred_target="local",
            )
            res = await orch.execute(req)
            self.assertEqual(res.status, "rejected")
            self.assertEqual(res.error_code, "E_CAPABILITY_DENY")

            req2 = ExecuteRequest(
                workspace_id="ws_t030",
                skill_ref="builtin://channel.send_message",
                input={"text": "hello"},
                idempotency_key="idem_t030_channel_2",
                deadline_ms=3000,
                trace=TraceContext(trace_id="tr_t030_channel2", turn_id="turn_t030_channel2", span_id="span_t030_channel2"),
                policy_context={
                    "verify_asvp": False,
                    "backend": "local_mock",
                    "capabilities": capability_items_for_policy_context(["channel_send"]),
                },
                preferred_target="local",
            )
            res2 = await orch.execute(req2)
            self.assertEqual(res2.status, "accepted", msg=f"error_code={res2.error_code}")
            self.assertGreaterEqual(len(res2.evidence_refs), 1)

    async def test_builtin_time_now_requires_time_read_capability(self) -> None:
        with TemporaryDirectory(prefix="agentos_next_t030_time_") as td:
            root = Path(td)
            data_dir = root / "data"

            orch = Orchestrator.for_data_dir(str(data_dir), local_executor=LocalExecutor.for_data_dir(data_dir))
            trace = TraceContext(trace_id="tr_t030_time", turn_id="turn_t030_time", span_id="span_t030_time")
            req = ExecuteRequest(
                workspace_id="ws_t030",
                skill_ref="builtin://time.now",
                input={},
                idempotency_key="idem_t030_time_1",
                deadline_ms=3000,
                trace=trace,
                policy_context={"verify_asvp": False, "backend": "local_mock"},
                preferred_target="local",
            )
            res = await orch.execute(req)
            self.assertEqual(res.status, "rejected")
            self.assertEqual(res.error_code, "E_CAPABILITY_DENY")

            req2 = ExecuteRequest(
                workspace_id="ws_t030",
                skill_ref="builtin://time.now",
                input={},
                idempotency_key="idem_t030_time_2",
                deadline_ms=3000,
                trace=TraceContext(trace_id="tr_t030_time2", turn_id="turn_t030_time2", span_id="span_t030_time2"),
                policy_context={
                    "verify_asvp": False,
                    "backend": "local_mock",
                    "capabilities": capability_items_for_policy_context(["time_read"]),
                },
                preferred_target="local",
            )
            res2 = await orch.execute(req2)
            self.assertEqual(res2.status, "accepted", msg=f"error_code={res2.error_code}")


if __name__ == "__main__":  # pragma: no cover
    unittest.main(verbosity=2)
