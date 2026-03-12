from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import bootstrap  # noqa: F401

from agentos_next.apps.assistant_runtime import AssistantRuntime, run_assistant_runtime_async
from hybrid_gate_helpers import (
    SCENARIOS,
    assert_refs_traceable,
    build_request_for_scenario,
    canonical_result_view,
    canonical_trace_shape,
    collect_traceable_refs,
    run_scenario,
)


class TestSpikeHY2HybridEquivalence(unittest.IsolatedAsyncioTestCase):
    async def test_hybrid_and_direct_are_equivalent_for_key_scenarios(self) -> None:
        with tempfile.TemporaryDirectory(prefix="agentos_next_hy2_") as td:
            root = Path(td)

            for spec in SCENARIOS:
                with self.subTest(scenario=spec.name):
                    direct_dir = root / spec.name.lower() / "direct"
                    hybrid_dir = root / spec.name.lower() / "hybrid"
                    trace_id = f"tr_hy2_{spec.name.lower()}"

                    direct = await run_scenario(
                        scenario=spec.name,
                        runtime_mode="direct",
                        data_dir=direct_dir,
                        trace_id=trace_id,
                    )
                    hybrid = await run_scenario(
                        scenario=spec.name,
                        runtime_mode="hybrid",
                        data_dir=hybrid_dir,
                        trace_id=trace_id,
                    )

                    self.assertEqual(canonical_result_view(direct), canonical_result_view(hybrid))

                    self.assertEqual(direct.error_code, spec.expected_error_code)
                    self.assertEqual(hybrid.error_code, spec.expected_error_code)
                    self.assertEqual(bool(direct.followup_task_id), spec.expect_followup_task)
                    self.assertEqual(bool(hybrid.followup_task_id), spec.expect_followup_task)

                    direct_refs = collect_traceable_refs(direct)
                    hybrid_refs = collect_traceable_refs(hybrid)
                    self.assertGreaterEqual(len(direct_refs), 1)
                    self.assertGreaterEqual(len(hybrid_refs), 1)
                    assert_refs_traceable(data_dir=direct_dir, refs=direct_refs)
                    assert_refs_traceable(data_dir=hybrid_dir, refs=hybrid_refs)

                    direct_trace = canonical_trace_shape(direct_dir / "traces" / f"{trace_id}.jsonl")
                    hybrid_trace = canonical_trace_shape(hybrid_dir / "traces" / f"{trace_id}.jsonl")
                    self.assertGreaterEqual(len(direct_trace), 1)
                    self.assertEqual(direct_trace, hybrid_trace)

    async def test_hybrid_runtime_can_fallback_to_direct_without_semantic_change(self) -> None:
        with tempfile.TemporaryDirectory(prefix="agentos_next_hy2_fb_") as td:
            base = Path(td)
            direct_dir = base / "direct"
            fallback_dir = base / "fallback"
            trace_id = "tr_hy2_fallback"

            direct = await run_scenario(
                scenario="SCHED_FOLLOWUP_SUCCESS",
                runtime_mode="direct",
                data_dir=direct_dir,
                trace_id=trace_id,
            )

            async def _boom(self: AssistantRuntime, loop_req):  # type: ignore[no-untyped-def]
                raise RuntimeError("forced_hybrid_failure")

            with patch.object(AssistantRuntime, "_run_hybrid", new=_boom):
                fallback = await run_scenario(
                    scenario="SCHED_FOLLOWUP_SUCCESS",
                    runtime_mode="hybrid",
                    data_dir=fallback_dir,
                    trace_id=trace_id,
                )

            self.assertEqual(canonical_result_view(direct), canonical_result_view(fallback))

    async def test_hybrid_without_direct_fallback_surfaces_runtime_error(self) -> None:
        with tempfile.TemporaryDirectory(prefix="agentos_next_hy2_nofb_") as td:
            data_dir = Path(td)
            trace_id = "tr_hy2_nofb"
            loop_req = build_request_for_scenario(
                scenario="TOOL_FAIL",
                data_dir=data_dir / "target",
                trace_id=trace_id,
                turn_id="turn_tool_fail",
                span_id="span_tool_fail",
            )

            async def _boom(self: AssistantRuntime, loop_req):  # type: ignore[no-untyped-def]
                raise RuntimeError("forced_hybrid_failure")

            with patch.object(AssistantRuntime, "_run_hybrid", new=_boom):
                with self.assertRaises(RuntimeError):
                    await run_assistant_runtime_async(
                        loop_req,
                        runtime_mode="hybrid",
                        direct_fallback=False,
                    )


if __name__ == "__main__":  # pragma: no cover
    unittest.main(verbosity=2)
