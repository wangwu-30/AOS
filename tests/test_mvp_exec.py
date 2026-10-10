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


class TestMVPExec(unittest.TestCase):
    def test_cli_exec_runs_orchestrator_executor_chain(self) -> None:
        root = Path(__file__).resolve().parents[1]
        src = root / "src"

        with TemporaryDirectory(prefix="agentos_next_mvp_exec_") as td:
            base = Path(td)
            data_dir = base / "data"
            pkg_dir = base / "pkg"
            make_minimal_skill_package(pkg_dir)

            env = dict(os.environ)
            env["PYTHONPATH"] = str(src) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")

            p = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "agentos_next.cli",
                    "mvp",
                    "exec",
                    "--skill-ref",
                    str(pkg_dir),
                    "--no-verify-asvp",
                    "--backend",
                    "local_mock",
                    "--input",
                    '{"q":"hi"}',
                    "--workspace-id",
                    "ws_exec_1",
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
            self.assertEqual(p.returncode, 0, msg=f"stderr:\n{p.stderr}")

            out = json.loads(p.stdout.strip().splitlines()[-1])
            self.assertEqual(out["status"], "accepted")
            self.assertEqual(out["target"], "local")
            self.assertIsNone(out["error_code"])
            self.assertEqual(out["artifact_refs"], [])
            self.assertGreaterEqual(len(out["evidence_refs"]), 1)
            self.assertIn("started_at", out["timing"])
            self.assertIn("ended_at", out["timing"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main(verbosity=2)
