from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import bootstrap  # noqa: F401


class TestMVPReleasePack(unittest.TestCase):
    def test_cli_release_pack_default_emits_no_demo_or_trace(self) -> None:
        root = Path(__file__).resolve().parents[1]
        src = root / "src"

        with TemporaryDirectory(prefix="agentos_next_mvp_release_pack_") as td:
            base = Path(td)
            out_dir = base / "out"

            env = dict(os.environ)
            env["PYTHONPATH"] = str(src) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")

            p = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "agentos_next.cli",
                    "mvp",
                    "release-pack",
                    "--out-dir",
                    str(out_dir),
                ],
                cwd=str(root),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )
            self.assertEqual(p.returncode, 0, msg=f"stdout:\n{p.stdout}\n\nstderr:\n{p.stderr}")

            manifest_path = out_dir / "manifest.json"
            unittest_path = out_dir / "unittest.txt"
            demo_path = out_dir / "demo.json"
            trace_path = out_dir / "trace.jsonl"

            self.assertTrue(manifest_path.exists(), msg=f"missing: {manifest_path}")
            self.assertTrue(unittest_path.exists(), msg=f"missing: {unittest_path}")
            self.assertFalse(demo_path.exists(), msg=f"unexpected: {demo_path}")
            self.assertFalse(trace_path.exists(), msg=f"unexpected: {trace_path}")

            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            for k in (
                "schema_version",
                "pack_kind",
                "release_id",
                "created_at_utc",
                "git_commit",
                "python_version",
                "platform",
                "commands",
                "results",
                "waivers",
            ):
                self.assertIn(k, manifest, msg=f"missing manifest field: {k}")

            results = manifest["results"]
            self.assertIsInstance(results, dict)
            self.assertTrue(results.get("admission_ok"), msg=f"admission_ok not true: {results}")
            self.assertNotIn("collab_refs", manifest, msg="release-pack should not include collab_refs")


if __name__ == "__main__":  # pragma: no cover
    unittest.main(verbosity=2)
