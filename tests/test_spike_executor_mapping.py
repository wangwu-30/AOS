from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import bootstrap  # noqa: F401

from agentos_next.kernel.types import TraceContext
from agentos_next.runtime.execute_mapping import package_run_result_to_execute_result
from agentos_next.runtime.package_runner import PackageRunRequest, PackageRunner

from admission_helpers import make_minimal_skill_package


def _set_risk_level(pkg_dir: Path, risk_level: str) -> None:
    contract_path = pkg_dir / "contract.skill"
    obj = json.loads(contract_path.read_text(encoding="utf-8"))
    obj["risk_level"] = risk_level
    contract_path.write_text(json.dumps(obj, ensure_ascii=True, indent=2, sort_keys=True) + "\n", encoding="utf-8")


class TestSpikeExecutorMapping(unittest.TestCase):
    def test_mapping_success_fields_and_status(self) -> None:
        with TemporaryDirectory(prefix="agentos_next_spike_mapping_ok_") as td:
            base = Path(td)
            data_dir = base / "data"
            pkg_dir = base / "pkg"
            make_minimal_skill_package(pkg_dir)

            trace = TraceContext(trace_id="tr_map_ok", turn_id="turn_map_ok", span_id="span_map_ok")
            runner = PackageRunner.for_data_dir(data_dir)
            res = runner.run(
                PackageRunRequest(
                    skill_dir=pkg_dir,
                    input_obj={"q": "hi"},
                    workspace_id="ws_map_ok",
                    trace=trace,
                    verify_asvp=False,
                    backend="local_mock",
                )
            )
            self.assertTrue(res.ok, msg=f"runner failed: {res.error_code}")

            ex = package_run_result_to_execute_result(res)
            self.assertEqual(ex.status, "accepted")
            self.assertEqual(ex.target, "local")
            self.assertIsNone(ex.error_code)
            self.assertEqual(tuple(ex.evidence_refs), tuple(res.evidence_refs))

            self.assertTrue(ex.timing.started_at.endswith("Z"), msg=f"started_at not UTC ISO: {ex.timing.started_at}")
            self.assertTrue(ex.timing.ended_at.endswith("Z"), msg=f"ended_at not UTC ISO: {ex.timing.ended_at}")

    def test_mapping_rejected_preserves_error_code(self) -> None:
        with TemporaryDirectory(prefix="agentos_next_spike_mapping_reject_") as td:
            base = Path(td)
            data_dir = base / "data"
            pkg_dir = base / "pkg"
            make_minimal_skill_package(pkg_dir)
            _set_risk_level(pkg_dir, "high")  # triggers HITL gate

            trace = TraceContext(trace_id="tr_map_rej", turn_id="turn_map_rej", span_id="span_map_rej")
            runner = PackageRunner.for_data_dir(data_dir)
            res = runner.run(
                PackageRunRequest(
                    skill_dir=pkg_dir,
                    input_obj={"q": "hi"},
                    workspace_id="ws_map_rej",
                    trace=trace,
                    verify_asvp=False,
                    backend="local_mock",
                    approved_by_human=False,
                )
            )
            self.assertFalse(res.ok)
            self.assertEqual(res.error_code, "E_HITL_REQUIRED")

            ex = package_run_result_to_execute_result(res)
            self.assertEqual(ex.status, "rejected")
            self.assertEqual(ex.target, "local")
            self.assertEqual(ex.error_code, "E_HITL_REQUIRED")
            self.assertEqual(tuple(ex.evidence_refs), tuple(res.evidence_refs))


if __name__ == "__main__":  # pragma: no cover
    unittest.main(verbosity=2)

