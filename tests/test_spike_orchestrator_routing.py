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


class TestSpike005BOrchestratorRouting(unittest.TestCase):
    """Spike-005B: Minimal Orchestrator routing and RemoteExecutor placeholder."""

    def _run_exec(self, root: Path, src: Path, data_dir: Path, pkg_dir: Path, *, target: str) -> subprocess.CompletedProcess[str]:
        env = dict(os.environ)
        env["PYTHONPATH"] = str(src) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
        return subprocess.run(
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
                "--target",
                target,
                "--input",
                '{"q":"hi"}',
                "--workspace-id",
                "ws_spike_005b",
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

    def test_routing_to_local(self) -> None:
        """Test --target local executes successfully."""
        root = Path(__file__).resolve().parents[1]
        src = root / "src"
        with TemporaryDirectory(prefix="agentos_next_spike_005b_local_") as td:
            base = Path(td)
            pkg_dir = base / "pkg"
            data_dir = base / "data"
            make_minimal_skill_package(pkg_dir)

            cli = self._run_exec(root, src, data_dir, pkg_dir, target="local")
            self.assertEqual(cli.returncode, 0, msg=f"stderr:\n{cli.stderr}")
            out = json.loads(cli.stdout.strip().splitlines()[-1])

            self.assertEqual(out["status"], "accepted")
            self.assertEqual(out["target"], "local")
            self.assertIsNone(out["error_code"])

    def test_routing_to_remote_returns_placeholder(self) -> None:
        """Test --target remote returns E_REMOTE_NOT_IMPLEMENTED placeholder."""
        root = Path(__file__).resolve().parents[1]
        src = root / "src"
        with TemporaryDirectory(prefix="agentos_next_spike_005b_remote_") as td:
            base = Path(td)
            pkg_dir = base / "pkg"
            data_dir = base / "data"
            make_minimal_skill_package(pkg_dir)

            cli = self._run_exec(root, src, data_dir, pkg_dir, target="remote")
            # Should return non-zero because remote is not implemented
            self.assertNotEqual(cli.returncode, 0, msg=f"Expected failure for remote, got: {cli.stdout}")
            out = json.loads(cli.stdout.strip().splitlines()[-1])

            self.assertEqual(out["status"], "rejected")
            self.assertEqual(out["target"], "remote")
            self.assertEqual(out["error_code"], "E_REMOTE_NOT_IMPLEMENTED")

    def test_routing_auto_defaults_to_local(self) -> None:
        """Test --target auto defaults to local execution."""
        root = Path(__file__).resolve().parents[1]
        src = root / "src"
        with TemporaryDirectory(prefix="agentos_next_spike_005b_auto_") as td:
            base = Path(td)
            pkg_dir = base / "pkg"
            data_dir = base / "data"
            make_minimal_skill_package(pkg_dir)

            cli = self._run_exec(root, src, data_dir, pkg_dir, target="auto")
            self.assertEqual(cli.returncode, 0, msg=f"stderr:\n{cli.stderr}")
            out = json.loads(cli.stdout.strip().splitlines()[-1])

            # Auto should default to local for safety
            self.assertEqual(out["status"], "accepted")
            self.assertEqual(out["target"], "local")
            self.assertIsNone(out["error_code"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
