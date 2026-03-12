from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import bootstrap  # noqa: F401


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _run_cli(args: list[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(_repo_root() / "src")
    return subprocess.run(
        ["python3", "-m", "agentos_next.cli", *args],
        cwd=str(cwd),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )


def _set_risk_level(pkg_dir: Path, risk_level: str) -> None:
    cpath = pkg_dir / "contract.skill"
    obj = json.loads(cpath.read_text(encoding="utf-8"))
    obj["risk_level"] = risk_level
    cpath.write_text(json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


class TestThread021UI1(unittest.TestCase):
    def test_ui_run_once_success(self) -> None:
        root = _repo_root()
        skill = root / "examples" / "skills" / "personal_assistant_brief"
        keys = root / "examples" / "keys"

        with tempfile.TemporaryDirectory() as td:
            data_dir = Path(td) / "data"
            p = _run_cli(
                [
                    "mvp",
                    "ui-run-once",
                    "--message",
                    "Draft a short email asking to reschedule a meeting.",
                    "--operator-ref",
                    str(skill),
                    "--keys-dir",
                    str(keys),
                    "--data-dir",
                    str(data_dir),
                ],
                cwd=root,
            )
            self.assertEqual(p.returncode, 0, p.stderr)
            out = json.loads(p.stdout)
            self.assertTrue(out["ok"])
            self.assertEqual(out["status"], "accepted")
            self.assertIsNone(out["error_code"])
            self.assertIsInstance(out.get("evidence_refs"), list)
            self.assertTrue(out.get("trace_id"))
            self.assertTrue(str(out.get("user_facing_message") or "").strip())

    def test_ui_hitl_creates_pending_and_approve_reruns(self) -> None:
        root = _repo_root()
        src_skill = root / "examples" / "skills" / "personal_assistant_brief"

        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            data_dir = td_path / "data"
            hi_skill = td_path / "hi_skill"
            shutil.copytree(src_skill, hi_skill)
            _set_risk_level(hi_skill, "high")  # triggers HITL gate in policy engine

            p1 = _run_cli(
                [
                    "mvp",
                    "ui-run-once",
                    "--message",
                    "Draft a short email asking to reschedule a meeting.",
                    "--operator-ref",
                    str(hi_skill),
                    "--no-verify-asvp",
                    "--data-dir",
                    str(data_dir),
                ],
                cwd=root,
            )
            self.assertEqual(p1.returncode, 1, p1.stderr)
            out1 = json.loads(p1.stdout)
            self.assertFalse(out1["ok"])
            self.assertEqual(out1["status"], "pending_approval")
            self.assertEqual(out1["error_code"], "E_HITL_REQUIRED")
            approval_id = out1.get("approval_id")
            self.assertTrue(isinstance(approval_id, str) and approval_id)

            approvals_path = data_dir / "ui" / "approvals.jsonl"
            self.assertTrue(approvals_path.exists())
            log = approvals_path.read_text(encoding="utf-8")
            self.assertIn(approval_id, log)

            p2 = _run_cli(
                [
                    "mvp",
                    "ui-approvals",
                    "approve",
                    "--approval-id",
                    approval_id,
                    "--data-dir",
                    str(data_dir),
                ],
                cwd=root,
            )
            self.assertEqual(p2.returncode, 0, p2.stderr)
            out2 = json.loads(p2.stdout)
            self.assertTrue(out2["ok"], out2)
            self.assertEqual(out2["status"], "accepted")
            self.assertEqual(out2["approval_id"], approval_id)

    def test_ui_replay_mode_is_zero_write(self) -> None:
        root = _repo_root()
        skill = root / "examples" / "skills" / "personal_assistant_brief"

        with tempfile.TemporaryDirectory() as td:
            data_dir = Path(td) / "data"
            p = _run_cli(
                [
                    "mvp",
                    "ui-run-once",
                    "--message",
                    "hello",
                    "--operator-ref",
                    str(skill),
                    "--replay-mode",
                    "--data-dir",
                    str(data_dir),
                    "--no-verify-asvp",
                ],
                cwd=root,
            )
            self.assertEqual(p.returncode, 1, p.stderr)
            out = json.loads(p.stdout)
            self.assertFalse(out["ok"])
            self.assertEqual(out["error_code"], "E_POLICY_DENY")
            self.assertEqual(out["reason_code"], "replay_mode_no_side_effects")
            # zero-write: data_dir should not be created by the command
            self.assertFalse(data_dir.exists())
