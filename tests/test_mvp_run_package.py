from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import bootstrap  # noqa: F401


def _write_json(path: Path, obj: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=True, indent=2, sort_keys=True) + "\n", encoding="utf-8")


class TestMVPRunPackage(unittest.TestCase):
    def test_cli_run_package_local_mock_writes_evidence_and_trace(self) -> None:
        root = Path(__file__).resolve().parents[1]
        src = root / "src"

        with TemporaryDirectory(prefix="agentos_next_mvp_pkg_") as td:
            base = Path(td)
            data_dir = base / "data"

            # Minimal skill package directory accepted by SkillPackageLoader:
            # - contract.skill
            # - artifacts/{inputs_schema,outputs_schema,acceptance_rules,execution_profile}.json
            pkg_dir = base / "pkg"
            pkg_dir.mkdir(parents=True, exist_ok=True)

            inputs_schema = {
                "type": "object",
                "properties": {"q": {"type": "string"}},
                "required": ["q"],
                "additionalProperties": False,
            }
            outputs_schema = {
                "type": "object",
                "properties": {"ok": {"const": True}},
                "required": ["ok"],
                "additionalProperties": False,
            }

            contract = {
                "name": "demo_pkg_skill",
                "version": "0.0.1",
                "description": "demo pkg skill",
                "inputs_schema": inputs_schema,
                "outputs_schema": outputs_schema,
                "logic": "Return a JSON object with ok=true.",
                "acceptance_rules": {},
                "execution_profile": {"model_id": "local_mock"},
                "risk_level": "low",
            }
            (pkg_dir / "contract.skill").write_text(
                json.dumps(contract, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )

            artifacts = pkg_dir / "artifacts"
            _write_json(artifacts / "inputs_schema.json", inputs_schema)
            _write_json(artifacts / "outputs_schema.json", outputs_schema)
            _write_json(artifacts / "acceptance_rules.json", contract["acceptance_rules"])
            _write_json(artifacts / "execution_profile.json", contract["execution_profile"])

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
                    str(pkg_dir),
                    "--no-verify-asvp",
                    "--backend",
                    "local_mock",
                    "--input",
                    '{"q":"hi"}',
                    "--workspace-id",
                    "ws_pkg_1",
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
            self.assertEqual(out["output"], {"ok": True})
            self.assertIsNone(out["error"])
            self.assertGreaterEqual(len(out["evidence_refs"]), 1)

            trace_path = data_dir / "traces" / f"{out['trace_id']}.jsonl"
            self.assertTrue(trace_path.exists(), msg=f"missing trace: {trace_path}")
            trace_lines = [ln for ln in trace_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
            self.assertGreaterEqual(len(trace_lines), 2)
            trace_events = [json.loads(ln) for ln in trace_lines]
            self.assertTrue(
                any(ev.get("event_type") == "TOOL_CALL_FINISHED" and ev.get("data", {}).get("ok") is True for ev in trace_events)
            )

            # Evidence should be written to disk for each emitted ref.
            blobs_dir = data_dir / "evidence" / "blobs"
            meta_dir = data_dir / "evidence" / "meta"
            self.assertTrue(blobs_dir.exists())
            self.assertTrue(meta_dir.exists())
            for ref in out["evidence_refs"]:
                self.assertTrue((blobs_dir / ref).exists(), msg=f"missing evidence blob: {ref}")
                self.assertTrue((meta_dir / f"{ref}.json").exists(), msg=f"missing evidence meta: {ref}")


if __name__ == "__main__":  # pragma: no cover
    unittest.main(verbosity=2)
