from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

import bootstrap  # noqa: F401

from agentos_next.cli import main
from agentos_next.compiler.skillc import cmd_build


class TestSpikeCR1CreatorPlan(unittest.TestCase):
    def test_creator_plan_is_deterministic_and_execute_request_shaped(self) -> None:
        root = Path(__file__).resolve().parents[1]
        contract_a = root / "examples" / "skills" / "personal_assistant_brief" / "contract.skill"
        contract_b = root / "examples" / "skills" / "expert_collab_writer" / "contract.skill"

        with tempfile.TemporaryDirectory() as td:
            registry_root = Path(td) / "registry"
            cmd_build(str(contract_a), str(registry_root))
            cmd_build(str(contract_b), str(registry_root))

            stdout1 = io.StringIO()
            with redirect_stdout(stdout1):
                rc1 = main(
                    [
                        "mvp",
                        "creator-plan",
                        "--registry-root",
                        str(registry_root),
                        "--intent",
                        "帮我写一封简短邮件",
                        "--workspace-id",
                        "ws_cr1",
                        "--deadline-ms",
                        "5000",
                        "--max-steps",
                        "2",
                        "--model",
                        "gpt-4o-mini",
                    ]
                )
            self.assertEqual(rc1, 0)
            out1 = json.loads(stdout1.getvalue().strip().splitlines()[-1])
            self.assertTrue(out1["ok"])
            self.assertIsNone(out1["error_code"])
            self.assertIsNone(out1["plan_path"])

            plan1 = out1["plan"]
            self.assertEqual(plan1["schema_version"], "1.0.0")
            self.assertEqual(plan1["mode"], "plan_only")
            self.assertEqual(plan1["intent"], "帮我写一封简短邮件")
            self.assertEqual(len(plan1["steps"]), 2)
            self.assertGreaterEqual(len(plan1["candidates"]), 2)

            for step in plan1["steps"]:
                req = step["execute_request"]
                self.assertEqual(req["workspace_id"], "ws_cr1")
                self.assertEqual(req["deadline_ms"], 5000)
                self.assertIn("skill_ref", req)
                self.assertIn("input", req)
                self.assertIn("idempotency_key", req)
                self.assertIn("trace", req)
                self.assertIn("policy_context", req)
                self.assertEqual(req["policy_context"]["model"], "gpt-4o-mini")
                self.assertEqual(req["input"]["request"], "帮我写一封简短邮件")

            stdout2 = io.StringIO()
            with redirect_stdout(stdout2):
                rc2 = main(
                    [
                        "mvp",
                        "creator-plan",
                        "--registry-root",
                        str(registry_root),
                        "--intent",
                        "帮我写一封简短邮件",
                        "--workspace-id",
                        "ws_cr1",
                        "--deadline-ms",
                        "5000",
                        "--max-steps",
                        "2",
                        "--model",
                        "gpt-4o-mini",
                    ]
                )
            self.assertEqual(rc2, 0)
            out2 = json.loads(stdout2.getvalue().strip().splitlines()[-1])
            self.assertEqual(out1["plan"], out2["plan"])

    def test_creator_plan_invalid_registry_returns_stable_error_code(self) -> None:
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            rc = main(
                [
                    "mvp",
                    "creator-plan",
                    "--registry-root",
                    "/tmp/no_such_registry_root_for_cr1",
                    "--intent",
                    "anything",
                ]
            )
        self.assertEqual(rc, 1)
        out = json.loads(stdout.getvalue().strip().splitlines()[-1])
        self.assertFalse(out["ok"])
        self.assertEqual(out["error_code"], "E_CREATOR_REGISTRY_INVALID")

    def test_creator_plan_rejects_incomplete_compiled_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            registry_root = Path(td) / "registry"
            compiled = registry_root / "broken_skill" / "compiled"
            compiled.mkdir(parents=True, exist_ok=True)
            (compiled / "intent_snapshot.json").write_text(
                json.dumps({"schema_version": "1.0.0", "name": "broken"}) + "\n",
                encoding="utf-8",
            )

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                rc = main(
                    [
                        "mvp",
                        "creator-plan",
                        "--registry-root",
                        str(registry_root),
                        "--intent",
                        "hello",
                    ]
                )

            self.assertEqual(rc, 1)
            out = json.loads(stdout.getvalue().strip().splitlines()[-1])
            self.assertFalse(out["ok"])
            self.assertEqual(out["error_code"], "E_CREATOR_SCHEMA_UNSUPPORTED")


if __name__ == "__main__":  # pragma: no cover
    unittest.main(verbosity=2)
