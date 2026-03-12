from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import bootstrap  # noqa: F401


class TestReplayModeBlocksRemoteBackend(unittest.TestCase):
    def test_run_package_replay_mode_blocks_codex_backend_without_network(self) -> None:
        root = Path(__file__).resolve().parents[1]
        src = root / "src"

        with TemporaryDirectory(prefix="agentos_next_replay_mode_") as td:
            base = Path(td)
            data_dir = base / "data"

            env = dict(os.environ)
            env["PYTHONPATH"] = str(src) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")

            p = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "agentos_next.cli",
                    "mvp",
                    "run-package",
                    "--skill-dir",
                    str(root / "examples" / "skills" / "personal_assistant_brief"),
                    "--keys-dir",
                    str(root / "examples" / "keys"),
                    "--no-verify-asvp",
                    "--backend",
                    "codex_oauth",
                    "--remote-calls-armed",
                    "--allow-network-egress",
                    "--replay-mode",
                    "--data-dir",
                    str(data_dir),
                    "--input",
                    json.dumps({"request": "hello"}, ensure_ascii=False),
                ],
                cwd=str(root),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )
            # Must fail closed before any network/token dependency.
            self.assertNotEqual(p.returncode, 0, msg=f"stdout:\n{p.stdout}\n\nstderr:\n{p.stderr}")

            last = (p.stdout or "").strip().splitlines()[-1]
            obj = json.loads(last)
            self.assertIsInstance(obj, dict)
            self.assertEqual(obj.get("error"), "E_REPLAY_REMOTE_DISABLED", msg=f"unexpected output: {obj}")

    def test_run_package_replay_mode_blocks_minimax_backend_without_network(self) -> None:
        root = Path(__file__).resolve().parents[1]
        src = root / "src"

        with TemporaryDirectory(prefix="agentos_next_replay_mode_minimax_") as td:
            base = Path(td)
            data_dir = base / "data"

            env = dict(os.environ)
            env["PYTHONPATH"] = str(src) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")

            p = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "agentos_next.cli",
                    "mvp",
                    "run-package",
                    "--skill-dir",
                    str(root / "examples" / "skills" / "personal_assistant_brief"),
                    "--keys-dir",
                    str(root / "examples" / "keys"),
                    "--no-verify-asvp",
                    "--backend",
                    "minimax",
                    "--remote-calls-armed",
                    "--allow-network-egress",
                    "--replay-mode",
                    "--data-dir",
                    str(data_dir),
                    "--input",
                    json.dumps({"request": "hello"}, ensure_ascii=False),
                ],
                cwd=str(root),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )
            self.assertNotEqual(p.returncode, 0, msg=f"stdout:\n{p.stdout}\n\nstderr:\n{p.stderr}")

            last = (p.stdout or "").strip().splitlines()[-1]
            obj = json.loads(last)
            self.assertIsInstance(obj, dict)
            self.assertEqual(obj.get("error"), "E_REPLAY_REMOTE_DISABLED", msg=f"unexpected output: {obj}")


if __name__ == "__main__":  # pragma: no cover
    unittest.main(verbosity=2)
