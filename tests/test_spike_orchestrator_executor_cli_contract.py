from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import bootstrap  # noqa: F401
from admission_helpers import make_minimal_skill_package

from agentos_next.kernel.types import TraceContext
from agentos_next.runtime.execute_mapping import package_run_result_to_execute_result
from agentos_next.runtime.package_runner import PackageRunner, PackageRunRequest


def _set_risk_level(pkg_dir: Path, risk_level: str) -> None:
    contract_path = pkg_dir / "contract.skill"
    obj = json.loads(contract_path.read_text(encoding="utf-8"))
    obj["risk_level"] = risk_level
    contract_path.write_text(json.dumps(obj, ensure_ascii=True, indent=2, sort_keys=True) + "\n", encoding="utf-8")


class TestSpikeOrchestratorExecutorCLIContract(unittest.TestCase):
    def _run_cli(self, root: Path, src: Path, data_dir: Path, pkg_dir: Path, *, trace: TraceContext) -> subprocess.CompletedProcess[str]:
        env = dict(os.environ)
        env["PYTHONPATH"] = str(src) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
        return subprocess.run(
            [
                sys.executable,
                "-m",
                "agentos_next.cli",
                "mvp",
                "run-package",
                "--skill-dir",
                str(pkg_dir),
                "--no-verify-asvp",
                "--backend",
                "local_mock",
                "--input",
                '{"q":"hi"}',
                "--workspace-id",
                "ws_spike_005a",
                "--trace-id",
                trace.trace_id,
                "--turn-id",
                trace.turn_id,
                "--span-id",
                trace.span_id,
                "--data-dir",
                str(data_dir),
            ],
            cwd=str(root),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )

    def test_run_package_output_contract_is_stable_when_execute_result_path_exists(self) -> None:
        root = Path(__file__).resolve().parents[1]
        src = root / "src"
        with TemporaryDirectory(prefix="agentos_next_spike_005a_ok_") as td:
            base = Path(td)
            pkg_dir = base / "pkg"
            data_dir = base / "data"
            make_minimal_skill_package(pkg_dir)

            trace = TraceContext(trace_id="tr_spike_005a_ok", turn_id="turn_spike_005a_ok", span_id="span_spike_005a_ok")
            runner = PackageRunner.for_data_dir(data_dir)
            pkg_res = runner.run(
                PackageRunRequest(
                    skill_dir=pkg_dir,
                    input_obj={"q": "hi"},
                    workspace_id="ws_spike_005a",
                    trace=trace,
                    verify_asvp=False,
                    backend="local_mock",
                )
            )
            ex_res = package_run_result_to_execute_result(pkg_res)
            self.assertEqual(ex_res.status, "accepted")
            self.assertIsNone(ex_res.error_code)

            cli = self._run_cli(root, src, data_dir, pkg_dir, trace=trace)
            self.assertEqual(cli.returncode, 0, msg=f"stderr:\n{cli.stderr}")
            out = json.loads(cli.stdout.strip().splitlines()[-1])

            self.assertEqual(
                set(out),
                {"ok", "output", "error", "trace_id", "turn_id", "span_id", "evidence_refs"},
            )
            self.assertNotIn("status", out)
            self.assertNotIn("target", out)
            self.assertNotIn("timing", out)
            self.assertNotIn("artifact_refs", out)
            self.assertTrue(out["ok"])
            self.assertEqual(out["output"], {"ok": True})
            self.assertIsNone(out["error"])

    def test_error_contract_is_stable_for_hitl_rejection(self) -> None:
        root = Path(__file__).resolve().parents[1]
        src = root / "src"
        with TemporaryDirectory(prefix="agentos_next_spike_005a_reject_") as td:
            base = Path(td)
            pkg_dir = base / "pkg"
            data_dir = base / "data"
            make_minimal_skill_package(pkg_dir)
            _set_risk_level(pkg_dir, "high")

            trace = TraceContext(trace_id="tr_spike_005a_rej", turn_id="turn_spike_005a_rej", span_id="span_spike_005a_rej")
            runner = PackageRunner.for_data_dir(data_dir)
            pkg_res = runner.run(
                PackageRunRequest(
                    skill_dir=pkg_dir,
                    input_obj={"q": "hi"},
                    workspace_id="ws_spike_005a",
                    trace=trace,
                    verify_asvp=False,
                    backend="local_mock",
                )
            )
            ex_res = package_run_result_to_execute_result(pkg_res)
            self.assertEqual(ex_res.status, "rejected")
            self.assertEqual(ex_res.error_code, "E_HITL_REQUIRED")

            cli = self._run_cli(root, src, data_dir, pkg_dir, trace=trace)
            self.assertEqual(cli.returncode, 1, msg=f"stderr:\n{cli.stderr}")
            out = json.loads(cli.stdout.strip().splitlines()[-1])

            self.assertEqual(
                set(out),
                {"ok", "output", "error", "trace_id", "turn_id", "span_id", "evidence_refs"},
            )
            self.assertFalse(out["ok"])
            self.assertIsNone(out["output"])
            self.assertEqual(out["error"], "E_HITL_REQUIRED")


if __name__ == "__main__":  # pragma: no cover
    unittest.main(verbosity=2)
