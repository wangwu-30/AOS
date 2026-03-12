from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import bootstrap  # noqa: F401


class TestMVPRCPack(unittest.TestCase):
    def test_cli_rc_pack_emits_demo_trace_and_collab_refs(self) -> None:
        root = Path(__file__).resolve().parents[1]
        src = root / "src"

        with TemporaryDirectory(prefix="agentos_next_mvp_rc_pack_") as td:
            base = Path(td)
            out_dir = base / "out"
            data_dir = base / "data"

            env = dict(os.environ)
            env["PYTHONPATH"] = str(src) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")

            p = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "agentos_next.cli",
                    "mvp",
                    "rc-pack",
                    "--out-dir",
                    str(out_dir),
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
            self.assertEqual(p.returncode, 0, msg=f"stdout:\n{p.stdout}\n\nstderr:\n{p.stderr}")

            manifest_path = out_dir / "manifest.json"
            unittest_path = out_dir / "unittest.txt"
            demo_path = out_dir / "demo.json"
            trace_path = out_dir / "trace.jsonl"
            execute_result_path = out_dir / "execute_result.json"

            self.assertTrue(manifest_path.exists(), msg=f"missing: {manifest_path}")
            self.assertTrue(unittest_path.exists(), msg=f"missing: {unittest_path}")
            self.assertTrue(demo_path.exists(), msg=f"missing: {demo_path}")
            self.assertTrue(trace_path.exists(), msg=f"missing: {trace_path}")
            self.assertTrue(execute_result_path.exists(), msg=f"missing: {execute_result_path}")

            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            results = manifest["results"]
            self.assertTrue(results.get("admission_ok"), msg=f"admission_ok not true: {results}")
            self.assertTrue(results.get("demo_ok"), msg=f"demo_ok not true: {results}")
            self.assertTrue(results.get("trace_copied"), msg=f"trace_copied not true: {results}")
            self.assertTrue(results.get("exec_ok"), msg=f"exec_ok not true: {results}")

            # Lock down execute_result.json contract (CLI ExecuteResult-shaped JSON).
            exec_obj = json.loads(execute_result_path.read_text(encoding="utf-8"))
            self.assertIsInstance(exec_obj, dict, msg=f"execute_result.json must be a JSON object: {exec_obj}")
            for k in ["artifact_refs", "error_code", "evidence_refs", "status", "target", "timing"]:
                self.assertIn(k, exec_obj, msg=f"missing key in execute_result.json: {k}")
            self.assertEqual(exec_obj.get("status"), "accepted")
            self.assertEqual(exec_obj.get("target"), "local")
            self.assertIsNone(exec_obj.get("error_code"))
            self.assertIsInstance(exec_obj.get("artifact_refs"), list)
            self.assertIsInstance(exec_obj.get("evidence_refs"), list)
            self.assertGreaterEqual(len(exec_obj.get("evidence_refs") or []), 1)

            timing = exec_obj.get("timing")
            self.assertIsInstance(timing, dict)
            self.assertIsInstance(timing.get("started_at"), str)
            self.assertIsInstance(timing.get("ended_at"), str)

            collab_refs = manifest.get("collab_refs")
            self.assertIsInstance(collab_refs, dict, msg=f"collab_refs missing/invalid: {collab_refs}")
            self.assertEqual(collab_refs.get("thread_id"), "20260214-EXT-COLLAB-001")

            paths = collab_refs.get("paths")
            self.assertIsInstance(paths, list, msg=f"collab_refs.paths must be a list: {paths}")
            self.assertGreaterEqual(len(paths), 4, msg=f"collab_refs.paths too small: {paths}")

            for item in paths:
                self.assertIsInstance(item, dict)
                path = item.get("path")
                digest = item.get("sha256")
                self.assertIsInstance(path, str)
                self.assertIsInstance(digest, str)
                self.assertRegex(digest, re.compile(r"^[0-9a-f]{64}$"), msg=f"bad sha256: {digest}")
                self.assertTrue((root / path).exists(), msg=f"collab_refs path missing: {path}")

            # Additive: rc-pack now includes full thread audit trail without breaking collab_refs.
            collab_threads = manifest.get("collab_threads")
            self.assertIsInstance(collab_threads, list, msg=f"collab_threads missing/invalid: {collab_threads}")
            self.assertGreaterEqual(len(collab_threads), 1, msg=f"collab_threads too small: {collab_threads}")

            thread_ids = [x.get("thread_id") for x in collab_threads if isinstance(x, dict)]
            self.assertIn("20260214-EXT-COLLAB-001", thread_ids, msg=f"missing thread_id 20260214-EXT-COLLAB-001 in {thread_ids}")

            for entry in collab_threads:
                self.assertIsInstance(entry, dict)
                self.assertIsInstance(entry.get("thread_id"), str)
                self.assertIsInstance(entry.get("paths"), list)
                if entry.get("ok") is True:
                    for item in entry.get("paths") or []:
                        self.assertIsInstance(item, dict)
                        path = item.get("path")
                        digest = item.get("sha256")
                        self.assertIsInstance(path, str)
                        self.assertIsInstance(digest, str)
                        self.assertRegex(digest, re.compile(r"^[0-9a-f]{64}$"), msg=f"bad sha256: {digest}")
                        self.assertTrue((root / path).exists(), msg=f"collab_threads path missing: {path}")


if __name__ == "__main__":  # pragma: no cover
    unittest.main(verbosity=2)
