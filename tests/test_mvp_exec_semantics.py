from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import bootstrap  # noqa: F401

from admission_helpers import make_minimal_skill_package
from agentos_next.kernel.executor import ExecuteResult, ExecuteTiming
from agentos_next.kernel.idempotency_store import FileIdempotencyStore


def _read_jsonl_lines(path: Path) -> list[str]:
    if not path.exists():
        return []
    return [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]


def _write_json(path: Path, obj: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=True, indent=2, sort_keys=True) + "\n", encoding="utf-8")


class TestMVPExecSemantics(unittest.TestCase):
    def test_idempotency_store_sanitizes_path_segments(self) -> None:
        with TemporaryDirectory(prefix="agentos_next_mvp_idem_sanitize_") as td:
            data_dir = Path(td) / "data"
            data_dir.mkdir(parents=True, exist_ok=True)

            store = FileIdempotencyStore(data_dir=data_dir)
            sample = ExecuteResult(
                status="accepted",
                evidence_refs=(),
                artifact_refs=(),
                error_code=None,
                timing=ExecuteTiming(started_at="2026-02-21T00:00:00Z", ended_at="2026-02-21T00:00:00Z"),
                target="local",
            )
            store.put_if_absent(workspace_id="../ws_escape", idempotency_key="../../idem_escape", result=sample)

            root = (data_dir / "idempotency").resolve()
            created = sorted(root.rglob("*.json"))
            self.assertEqual(len(created), 1)
            self.assertTrue(created[0].resolve().is_relative_to(root))

            outside = (root / ".." / ".." / "idem_escape.json").resolve()
            self.assertFalse(outside.exists(), msg=f"path traversal write detected: {outside}")

    def test_deadline_ms_zero_times_out_without_side_effects(self) -> None:
        root = Path(__file__).resolve().parents[1]
        src = root / "src"

        with TemporaryDirectory(prefix="agentos_next_mvp_exec_deadline_") as td:
            base = Path(td)
            data_dir = base / "data"
            pkg_dir = base / "pkg"
            make_minimal_skill_package(pkg_dir)

            env = dict(os.environ)
            env["PYTHONPATH"] = str(src) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")

            trace_id = "tr_deadline_0"
            p = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "agentos_next.cli",
                    "mvp",
                    "exec",
                    "--skill-ref",
                    str(pkg_dir),
                    "--no-verify-asvp",
                    "--backend",
                    "local_mock",
                    "--deadline-ms",
                    "0",
                    "--trace-id",
                    trace_id,
                    "--turn-id",
                    "turn_deadline_0",
                    "--span-id",
                    "span_deadline_0",
                    "--input",
                    '{"q":"hi"}',
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
            self.assertEqual(p.returncode, 1, msg=f"stdout:\n{p.stdout}\n\nstderr:\n{p.stderr}")
            out = json.loads(p.stdout.strip().splitlines()[-1])
            self.assertEqual(out["status"], "timeout")
            self.assertEqual(out["error_code"], "E_TIMEOUT")
            self.assertEqual(out["evidence_refs"], [])

            # Should not have executed; no trace should exist.
            trace_path = data_dir / "traces" / f"{trace_id}.jsonl"
            self.assertFalse(trace_path.exists(), msg=f"unexpected trace: {trace_path}")

    def test_idempotency_replay_returns_same_result_and_does_not_append_trace(self) -> None:
        root = Path(__file__).resolve().parents[1]
        src = root / "src"

        with TemporaryDirectory(prefix="agentos_next_mvp_exec_idem_") as td:
            base = Path(td)
            data_dir = base / "data"
            pkg_dir = base / "pkg"
            make_minimal_skill_package(pkg_dir)

            env = dict(os.environ)
            env["PYTHONPATH"] = str(src) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")

            idem = "idem_test_1"
            trace_id = "tr_idem_1"
            common = [
                sys.executable,
                "-m",
                "agentos_next.cli",
                "mvp",
                "exec",
                "--skill-ref",
                str(pkg_dir),
                "--no-verify-asvp",
                "--backend",
                "local_mock",
                "--idempotency-key",
                idem,
                "--trace-id",
                trace_id,
                "--turn-id",
                "turn_idem_1",
                "--span-id",
                "span_idem_1",
                "--data-dir",
                str(data_dir),
            ]

            p1 = subprocess.run(
                common + ["--input", '{"q":"hi"}'],
                cwd=str(root),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )
            self.assertEqual(p1.returncode, 0, msg=f"stdout:\n{p1.stdout}\n\nstderr:\n{p1.stderr}")
            out1 = json.loads(p1.stdout.strip().splitlines()[-1])

            trace_path = data_dir / "traces" / f"{trace_id}.jsonl"
            self.assertTrue(trace_path.exists(), msg=f"missing trace: {trace_path}")
            lines_before = _read_jsonl_lines(trace_path)
            self.assertGreaterEqual(len(lines_before), 1)

            # Second run: same idempotency key, different input. Should return cached result.
            p2 = subprocess.run(
                common + ["--input", '{"q":"DIFFERENT"}'],
                cwd=str(root),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )
            self.assertEqual(p2.returncode, 0, msg=f"stdout:\n{p2.stdout}\n\nstderr:\n{p2.stderr}")
            out2 = json.loads(p2.stdout.strip().splitlines()[-1])
            self.assertEqual(out1, out2)

            lines_after = _read_jsonl_lines(trace_path)
            self.assertEqual(lines_before, lines_after, msg="trace changed on idempotency replay")

            # Idempotency record should exist on disk.
            rec = data_dir / "idempotency" / "local" / f"{idem}.json"
            self.assertTrue(rec.exists(), msg=f"missing idempotency record: {rec}")

    def test_error_code_matrix_rejected_and_failed_cases(self) -> None:
        root = Path(__file__).resolve().parents[1]
        src = root / "src"

        with TemporaryDirectory(prefix="agentos_next_mvp_exec_matrix_") as td:
            base = Path(td)
            data_dir = base / "data"

            env = dict(os.environ)
            env["PYTHONPATH"] = str(src) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")

            def run_exec(pkg_dir: Path, *, input_json: str = '{"q":"hi"}') -> dict:
                p = subprocess.run(
                    [
                        sys.executable,
                        "-m",
                        "agentos_next.cli",
                        "mvp",
                        "exec",
                        "--skill-ref",
                        str(pkg_dir),
                        "--no-verify-asvp",
                        "--backend",
                        "local_mock",
                        "--trace-id",
                        "tr_matrix",
                        "--turn-id",
                        "turn_matrix",
                        "--span-id",
                        "span_matrix",
                        "--data-dir",
                        str(data_dir),
                        "--input",
                        input_json,
                        "--idempotency-key",
                        f"idem_{pkg_dir.name}",
                    ],
                    cwd=str(root),
                    env=env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    check=False,
                )
                return {"rc": p.returncode, "out": json.loads(p.stdout.strip().splitlines()[-1]), "stderr": p.stderr}

            # Case 1: HITL required -> rejected/E_HITL_REQUIRED
            pkg_hitl = base / "pkg_hitl"
            make_minimal_skill_package(pkg_hitl)
            contract_path = pkg_hitl / "contract.skill"
            cobj = json.loads(contract_path.read_text(encoding="utf-8"))
            cobj["risk_level"] = "high"
            contract_path.write_text(json.dumps(cobj, ensure_ascii=True, indent=2, sort_keys=True) + "\n", encoding="utf-8")

            r = run_exec(pkg_hitl)
            self.assertEqual(r["rc"], 1, msg=f"stderr:\n{r['stderr']}")
            self.assertEqual(r["out"]["status"], "rejected")
            self.assertEqual(r["out"]["error_code"], "E_HITL_REQUIRED")

            # Case 2: precheck fail -> rejected/E_PRECHECK_FAIL
            pkg_pre = base / "pkg_pre"
            make_minimal_skill_package(pkg_pre)
            _write_json(pkg_pre / "artifacts" / "acceptance_rules.json", {"required_input_fields": ["must"]})
            r = run_exec(pkg_pre, input_json='{"q":"hi"}')
            self.assertEqual(r["rc"], 1, msg=f"stderr:\n{r['stderr']}")
            self.assertEqual(r["out"]["status"], "rejected")
            self.assertEqual(r["out"]["error_code"], "E_PRECHECK_FAIL")

            # Case 3: postcheck fail -> rejected/E_POSTCHECK_FAIL
            pkg_post = base / "pkg_post"
            make_minimal_skill_package(pkg_post)
            _write_json(pkg_post / "artifacts" / "acceptance_rules.json", {"required_output_fields": ["missing"]})
            r = run_exec(pkg_post, input_json='{"q":"hi"}')
            self.assertEqual(r["rc"], 1, msg=f"stderr:\n{r['stderr']}")
            self.assertEqual(r["out"]["status"], "rejected")
            self.assertEqual(r["out"]["error_code"], "E_POSTCHECK_FAIL")

            # Case 4: execution failed (missing skill dir) -> failed/E_EXECUTION_FAILED
            missing = base / "no_such_pkg"
            p = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "agentos_next.cli",
                    "mvp",
                    "exec",
                    "--skill-ref",
                    str(missing),
                    "--no-verify-asvp",
                    "--backend",
                    "local_mock",
                    "--trace-id",
                    "tr_missing",
                    "--turn-id",
                    "turn_missing",
                    "--span-id",
                    "span_missing",
                    "--data-dir",
                    str(data_dir),
                    "--input",
                    '{"q":"hi"}',
                    "--idempotency-key",
                    "idem_missing",
                ],
                cwd=str(root),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )
            self.assertEqual(p.returncode, 1, msg=f"stderr:\n{p.stderr}")
            out = json.loads(p.stdout.strip().splitlines()[-1])
            self.assertEqual(out["status"], "failed")
            self.assertEqual(out["error_code"], "E_EXECUTION_FAILED")


if __name__ == "__main__":  # pragma: no cover
    unittest.main(verbosity=2)
