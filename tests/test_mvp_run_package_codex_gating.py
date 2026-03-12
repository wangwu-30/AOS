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


class TestMVPRunPackageCodexGating(unittest.TestCase):
    def test_codex_backend_is_fail_closed_without_double_gate(self) -> None:
        root = Path(__file__).resolve().parents[1]
        src = root / "src"

        with TemporaryDirectory(prefix="agentos_next_mvp_pkg_codex_") as td:
            base = Path(td)
            data_dir = base / "data"
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
                    "codex_oauth",
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

            # Fail-closed: no remote calls unless double gate is explicitly opened.
            self.assertEqual(p.returncode, 1, msg=f"stdout:\n{p.stdout}\nstderr:\n{p.stderr}")
            out = json.loads(p.stdout.strip().splitlines()[-1])
            self.assertFalse(out["ok"])
            self.assertEqual(out["error"], "E_REMOTE_CALL_NOT_ARMED")

