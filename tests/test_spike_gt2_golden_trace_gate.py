from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import bootstrap  # noqa: F401

from agentos_next.apps.golden_trace_gate import GoldenTraceThresholds, evaluate_golden_trace_gate
from hybrid_gate_helpers import SCENARIOS, canonical_result_view, canonical_trace_shape, run_scenario


class TestSpikeGT2GoldenTraceGate(unittest.IsolatedAsyncioTestCase):
    async def test_golden_trace_gate_is_quantified_and_deterministic(self) -> None:
        thresholds = GoldenTraceThresholds(
            max_flake_rate=0.01,
            min_consecutive_passes=10,
            rollback_on_consecutive_failures=2,
        )

        baseline: dict[str, dict[str, object]] = {}
        run_passes: list[bool] = []

        with tempfile.TemporaryDirectory(prefix="agentos_next_gt2_") as td:
            root = Path(td)

            for run_idx in range(10):
                run_ok = True
                for spec in SCENARIOS:
                    data_dir = root / f"run_{run_idx + 1}" / spec.name.lower()
                    trace_id = f"tr_gt2_{spec.name.lower()}"
                    res = await run_scenario(
                        scenario=spec.name,
                        runtime_mode="hybrid",
                        data_dir=data_dir,
                        trace_id=trace_id,
                    )

                    current = {
                        "result": canonical_result_view(res),
                        "trace_shape": canonical_trace_shape(data_dir / "traces" / f"{trace_id}.jsonl"),
                    }

                    if spec.name not in baseline:
                        baseline[spec.name] = current
                    else:
                        if current != baseline[spec.name]:
                            run_ok = False
                run_passes.append(run_ok)

        report = evaluate_golden_trace_gate(run_passes, thresholds=thresholds)

        self.assertTrue(report.passed, msg=report.to_dict())
        self.assertFalse(report.rollback_required, msg=report.to_dict())
        self.assertLessEqual(report.flake_rate, 0.01, msg=report.to_dict())
        self.assertGreaterEqual(report.max_consecutive_passes, 10, msg=report.to_dict())


if __name__ == "__main__":  # pragma: no cover
    unittest.main(verbosity=2)
