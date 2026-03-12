from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import bootstrap  # noqa: F401


class TestMVPAssistantDemo(unittest.TestCase):
    def test_cli_assistant_demo_default_example(self) -> None:
        root = Path(__file__).resolve().parents[1]
        src = root / "src"

        with TemporaryDirectory(prefix="agentos_next_demo_") as td:
            data_dir = Path(td) / "data"

            env = dict(os.environ)
            env["PYTHONPATH"] = str(src) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")

            p = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "agentos_next.cli",
                    "mvp",
                    "assistant-demo",
                    "--query",
                    "写一封简短邮件申请改期",
                    "--no-verify-asvp",
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
            self.assertTrue(out["ok"])
            self.assertIsNone(out["error"])
            self.assertIsInstance(out["output"], dict)
            self.assertIsInstance(out["output"].get("reply"), str)
            self.assertGreater(len(out["output"]["reply"].strip()), 0)

            trace_path = data_dir / "traces" / f"{out['trace_id']}.jsonl"
            self.assertTrue(trace_path.exists(), msg=f"missing trace: {trace_path}")
