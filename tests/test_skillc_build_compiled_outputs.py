from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import bootstrap  # noqa: F401

from agentos_next.compiler.skillc import cmd_build


class TestSkillcBuildCompiledOutputs(unittest.TestCase):
    def test_skillc_build_emits_compiled_dir(self) -> None:
        root = Path(__file__).resolve().parents[1]
        contract = root / "examples" / "skills" / "personal_assistant_brief" / "contract.skill"

        with tempfile.TemporaryDirectory() as td:
            out_dir = Path(td)
            cmd_build(str(contract), str(out_dir))

            dest = out_dir / "personal_assistant_brief"
            self.assertTrue((dest / "inputs_schema.json").exists())
            self.assertTrue((dest / "outputs_schema.json").exists())
            self.assertTrue((dest / "acceptance_rules.json").exists())
            self.assertTrue((dest / "execution_profile.json").exists())

            compiled = dest / "compiled"
            for name in ("intent_snapshot.json", "prompt_bundle.json", "execution_ir.json"):
                p = compiled / name
                self.assertTrue(p.exists(), f"missing compiled artifact: {p}")
                obj = json.loads(p.read_text(encoding="utf-8"))
                self.assertIsInstance(obj, dict)
                self.assertEqual(obj.get("schema_version"), "1.0.0")


if __name__ == "__main__":  # pragma: no cover
    unittest.main(verbosity=2)

