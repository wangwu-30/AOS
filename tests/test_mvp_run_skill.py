from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import bootstrap  # noqa: F401


class TestMVPRunSkill(unittest.TestCase):
    def test_cli_run_skill_writes_evidence_and_trace(self) -> None:
        root = Path(__file__).resolve().parents[1]
        src = root / "src"

        with TemporaryDirectory(prefix="agentos_next_mvp_") as td:
            base = Path(td)
            data_dir = base / "data"

            impl = base / "impl.py"
            impl.write_text(
                "def run(input, ctx=None, workspace_id=None):\n"
                "    return {'ok': True, 'input': input, 'trace_id': getattr(ctx, 'trace_id', None), 'workspace_id': workspace_id}\n",
                encoding="utf-8",
            )

            contract = base / "echo.skill.json"
            contract.write_text(
                json.dumps(
                    {
                        "name": "echo",
                        "version": "0.0.1",
                        "description": "echo",
                        "inputs_schema": {},
                        "outputs_schema": {},
                        "logic": "python:impl.py:run",
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            env = dict(os.environ)
            env["PYTHONPATH"] = str(src) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")

            p = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "agentos_next.cli",
                    "mvp",
                    "run-skill",
                    "--contract",
                    str(contract),
                    "--input",
                    '{"x":1}',
                    "--workspace-id",
                    "ws1",
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
            self.assertEqual(out["output"]["input"], {"x": 1})
            self.assertEqual(out["output"]["workspace_id"], "ws1")

            trace_path = data_dir / "traces" / f"{out['trace_id']}.jsonl"
            self.assertTrue(trace_path.exists(), msg=f"missing trace: {trace_path}")
            lines = [ln for ln in trace_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
            self.assertGreaterEqual(len(lines), 2)

            # At least one evidence blob should have been written.
            blobs_dir = data_dir / "evidence" / "blobs"
            meta_dir = data_dir / "evidence" / "meta"
            self.assertTrue(blobs_dir.exists())
            self.assertTrue(meta_dir.exists())
            self.assertGreaterEqual(len(list(blobs_dir.iterdir())), 1)
            self.assertGreaterEqual(len(list(meta_dir.iterdir())), 1)


if __name__ == "__main__":  # pragma: no cover
    unittest.main(verbosity=2)

