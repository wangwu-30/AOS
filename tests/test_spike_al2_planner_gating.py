from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import bootstrap  # noqa: F401


class TestSpikeAL2PlannerGating(unittest.TestCase):
    def test_llm_planner_codex_is_fail_closed_without_double_gate(self) -> None:
        root = Path(__file__).resolve().parents[1]
        src = root / "src"

        with TemporaryDirectory(prefix="agentos_next_al2_") as td:
            data_dir = Path(td) / "data"

            env = dict(os.environ)
            env["PYTHONPATH"] = str(src) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")

            # planner_backend is codex_oauth, but gates are NOT armed -> must fail closed before any network/token use.
            p = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "agentos_next.cli",
                    "mvp",
                    "assistant-loop",
                    "--query",
                    "帮我决定要不要记下来：hello",
                    "--planner",
                    "llm",
                    "--planner-backend",
                    "codex_oauth",
                    "--backend",
                    "local_mock",
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

            self.assertEqual(p.returncode, 1, msg=f"stdout:\n{p.stdout}\n\nstderr:\n{p.stderr}")
            out = json.loads(p.stdout.strip().splitlines()[-1])
            self.assertFalse(out["ok"])
            self.assertEqual(out["error_code"], "E_REMOTE_CALL_NOT_ARMED")
            self.assertEqual(out["steps"], [])


if __name__ == "__main__":  # pragma: no cover
    unittest.main(verbosity=2)

