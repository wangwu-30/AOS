from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import bootstrap  # noqa: F401

from agentos_next.kernel.types import TraceContext
from agentos_next.runtime.package_runner import PackageRunRequest, PackageRunner

from admission_helpers import make_minimal_skill_package


class TestAdmissionTraceJSONL(unittest.TestCase):
    def test_trace_jsonl_lines_parse_and_have_min_fields(self) -> None:
        with TemporaryDirectory(prefix="agentos_next_admission_trace_") as td:
            base = Path(td)
            data_dir = base / "data"
            pkg_dir = base / "pkg"
            make_minimal_skill_package(pkg_dir)

            trace = TraceContext(trace_id="tr_adm_trace", turn_id="turn_adm_trace", span_id="span_adm_trace")
            runner = PackageRunner.for_data_dir(data_dir)
            res = runner.run(
                PackageRunRequest(
                    skill_dir=pkg_dir,
                    input_obj={"q": "hi"},
                    workspace_id="ws_adm_trace",
                    trace=trace,
                    verify_asvp=False,
                    backend="local_mock",
                )
            )
            self.assertTrue(res.ok, msg=f"runner failed: {res.error_code}")

            trace_path = data_dir / "traces" / f"{trace.trace_id}.jsonl"
            self.assertTrue(trace_path.exists(), msg=f"missing trace: {trace_path}")

            lines = [ln for ln in trace_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
            self.assertGreaterEqual(len(lines), 1)

            for i, ln in enumerate(lines):
                try:
                    ev = json.loads(ln)
                except Exception as e:
                    raise AssertionError(f"trace line {i} is not valid JSON: {e}\n{ln}") from e

                # Admission requirement: minimal trace event fields MUST exist.
                for k in ("schema_version", "event_type", "ts", "ctx"):
                    self.assertIn(k, ev, msg=f"missing field {k} in trace event: {ev}")

                ctx = ev["ctx"]
                self.assertIsInstance(ctx, dict)
                for k in ("trace_id", "turn_id", "span_id"):
                    self.assertIn(k, ctx, msg=f"missing ctx.{k} in trace event: {ev}")

                # Ensure correlation keys are stable and match the requested trace context.
                self.assertEqual(ctx["trace_id"], trace.trace_id)
                self.assertEqual(ctx["turn_id"], trace.turn_id)
                self.assertEqual(ctx["span_id"], trace.span_id)


if __name__ == "__main__":  # pragma: no cover
    unittest.main(verbosity=2)
