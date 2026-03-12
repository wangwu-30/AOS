from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

import bootstrap  # noqa: F401

from agentos_next.apps.si1 import si1_validate
from agentos_next.kernel.evidence_store import FileEvidenceStore
from agentos_next.kernel.trace_logger import FileTraceLogger
from agentos_next.kernel.types import TraceContext, TraceEvent


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class TestSpikeSI1Phase1Autoevolve(unittest.TestCase):
    def test_si1_observe_and_propose_cli_emits_files(self) -> None:
        root = Path(__file__).resolve().parents[1]
        src = root / "src"

        with TemporaryDirectory(prefix="agentos_next_si1_") as td:
            data_dir = Path(td) / "data"
            data_dir.mkdir(parents=True, exist_ok=True)

            # Seed a bit of local evidence/trace for observe() to find.
            evidence = FileEvidenceStore(data_dir=data_dir)
            evidence.add_json({"schema_version": "1.0.0", "type": "seed", "x": 1}, kind="routing")

            trace_log = FileTraceLogger(data_dir=data_dir)
            trace_log.emit(
                TraceEvent(
                    schema_version="1.0.0",
                    ctx=TraceContext(trace_id="tr_seed", turn_id="turn_seed", span_id="span_seed"),
                    event_type="ROUTED",  # type: ignore[arg-type]
                    ts=_utc_iso(),
                    evidence_refs=(),
                    data={"seed": True},
                )
            )

            env = dict(os.environ)
            env["PYTHONPATH"] = str(src) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")

            run_id = "si1_test_run"

            p_obs = subprocess.run(
                [sys.executable, "-m", "agentos_next.cli", "mvp", "si1-observe", "--data-dir", str(data_dir), "--run-id", run_id],
                cwd=str(root),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )
            self.assertEqual(p_obs.returncode, 0, msg=f"stdout:\n{p_obs.stdout}\n\nstderr:\n{p_obs.stderr}")
            obs = json.loads(p_obs.stdout.strip().splitlines()[-1])
            self.assertTrue(obs.get("ok"))
            self.assertEqual(obs.get("run_id"), run_id)

            signals_path = Path(obs["signals_path"])
            self.assertTrue(signals_path.exists(), msg=f"missing signals.json: {signals_path}")
            signals = json.loads(signals_path.read_text(encoding="utf-8"))
            self.assertIsInstance(signals.get("evidence_meta"), dict)
            self.assertGreaterEqual(int(signals["evidence_meta"]["count"]), 1)
            self.assertIsInstance(signals.get("traces"), dict)
            self.assertGreaterEqual(int(signals["traces"]["count"]), 1)

            p_prop = subprocess.run(
                [sys.executable, "-m", "agentos_next.cli", "mvp", "si1-propose", "--data-dir", str(data_dir), "--run-id", run_id],
                cwd=str(root),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )
            self.assertEqual(p_prop.returncode, 0, msg=f"stdout:\n{p_prop.stdout}\n\nstderr:\n{p_prop.stderr}")
            prop = json.loads(p_prop.stdout.strip().splitlines()[-1])
            self.assertTrue(prop.get("ok"))
            proposal_path = Path(prop["proposal_path"])
            self.assertTrue(proposal_path.exists(), msg=f"missing proposal.json: {proposal_path}")
            proposal = json.loads(proposal_path.read_text(encoding="utf-8"))
            self.assertEqual(proposal.get("run_id"), run_id)
            self.assertTrue(proposal.get("validation_plan", {}).get("must_run_unittests"))

    def test_si1_validate_is_fail_closed_and_records_error_code(self) -> None:
        with TemporaryDirectory(prefix="agentos_next_si1_val_") as td:
            data_dir = Path(td) / "data"
            data_dir.mkdir(parents=True, exist_ok=True)

            # Missing proposal.json => fail-closed with stable error code; MUST NOT run unittest.
            with patch("agentos_next.apps.si1.subprocess.run") as p_run:
                res = si1_validate(data_dir=data_dir, run_id="r_missing")
            self.assertFalse(res.get("ok"))
            self.assertEqual(res.get("error_code"), "E_SI1_PROPOSAL_INVALID")
            p_run.assert_not_called()

            # Patch subprocess.run so we do not recursively run the test suite inside tests.
            fake_proc = SimpleNamespace(returncode=1, stdout="FAIL", stderr="boom")
            with patch("agentos_next.apps.si1.subprocess.run", return_value=fake_proc) as p_run:
                # Seed a minimal proposal.json for this run_id.
                run_dir = data_dir / "si1" / "runs" / "r1"
                run_dir.mkdir(parents=True, exist_ok=True)
                (run_dir / "proposal.json").write_text(
                    json.dumps({"schema_version": "1.0.0", "run_id": "r1"}, ensure_ascii=False, sort_keys=True) + "\n",
                    encoding="utf-8",
                )
                res = si1_validate(data_dir=data_dir, run_id="r1")

            self.assertFalse(res.get("ok"))
            self.assertEqual(res.get("error_code"), "E_SI1_VALIDATION_FAILED")
            p_run.assert_called()

            validation_path = Path(res["validation_path"])
            self.assertTrue(validation_path.exists(), msg=f"missing validation.json: {validation_path}")
            val = json.loads(validation_path.read_text(encoding="utf-8"))
            self.assertFalse(val.get("ok"))
            self.assertEqual(val.get("error_code"), "E_SI1_VALIDATION_FAILED")

    def test_si1_propose_missing_signals_is_fail_closed(self) -> None:
        root = Path(__file__).resolve().parents[1]
        src = root / "src"

        with TemporaryDirectory(prefix="agentos_next_si1_prop_missing_") as td:
            data_dir = Path(td) / "data"
            data_dir.mkdir(parents=True, exist_ok=True)

            env = dict(os.environ)
            env["PYTHONPATH"] = str(src) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")

            p = subprocess.run(
                [sys.executable, "-m", "agentos_next.cli", "mvp", "si1-propose", "--data-dir", str(data_dir), "--run-id", "no_such_run"],
                cwd=str(root),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )
            # Stable: no traceback, return code indicates failure, JSON has stable error_code.
            self.assertEqual(p.returncode, 1, msg=f"stdout:\n{p.stdout}\n\nstderr:\n{p.stderr}")
            last = p.stdout.strip().splitlines()[-1]
            obj = json.loads(last)
            self.assertFalse(obj.get("ok"))
            self.assertEqual(obj.get("error_code"), "E_SI1_PROPOSAL_INVALID")

    def test_si1_replay_mode_produces_no_writes(self) -> None:
        root = Path(__file__).resolve().parents[1]
        src = root / "src"

        with TemporaryDirectory(prefix="agentos_next_si1_replay_") as td:
            data_dir = Path(td) / "data"
            data_dir.mkdir(parents=True, exist_ok=True)

            env = dict(os.environ)
            env["PYTHONPATH"] = str(src) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")

            p = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "agentos_next.cli",
                    "mvp",
                    "si1-observe",
                    "--data-dir",
                    str(data_dir),
                    "--run-id",
                    "r_replay",
                    "--replay-mode",
                ],
                cwd=str(root),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )
            self.assertEqual(p.returncode, 1, msg=f"stdout:\n{p.stdout}\n\nstderr:\n{p.stderr}")
            obj = json.loads(p.stdout.strip().splitlines()[-1])
            self.assertFalse(obj.get("ok"))
            self.assertEqual(obj.get("error_code"), "E_SI1_POLICY_VIOLATION")

            # MUST NOT write SI1 run outputs.
            self.assertFalse((data_dir / "si1").exists(), msg="SI1 wrote files in replay-mode")

    def test_si1_rejects_invalid_run_id(self) -> None:
        root = Path(__file__).resolve().parents[1]
        src = root / "src"

        with TemporaryDirectory(prefix="agentos_next_si1_bad_run_id_") as td:
            data_dir = Path(td) / "data"
            data_dir.mkdir(parents=True, exist_ok=True)

            env = dict(os.environ)
            env["PYTHONPATH"] = str(src) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")

            p = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "agentos_next.cli",
                    "mvp",
                    "si1-observe",
                    "--data-dir",
                    str(data_dir),
                    "--run-id",
                    "../escape",
                ],
                cwd=str(root),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )
            self.assertEqual(p.returncode, 1, msg=f"stdout:\n{p.stdout}\n\nstderr:\n{p.stderr}")
            obj = json.loads(p.stdout.strip().splitlines()[-1])
            self.assertFalse(obj.get("ok"))
            self.assertEqual(obj.get("error_code"), "E_SI1_OBSERVE_FAILED")
            self.assertFalse((data_dir / "si1").exists(), msg="SI1 should not write run files for invalid run_id")


if __name__ == "__main__":  # pragma: no cover
    unittest.main(verbosity=2)
