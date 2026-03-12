from __future__ import annotations

import io
import json
import time
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory

import bootstrap  # noqa: F401

from agentos_next.cli import main
from agentos_next.kernel.scheduler_store import FileSchedulerStore, ScheduledTask


class TestSpikeDM2Daemon(unittest.TestCase):
    def _run_cli(self, argv: list[str]) -> tuple[int, dict]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            rc = main(argv)
        lines = [ln for ln in stdout.getvalue().splitlines() if ln.strip()]
        obj = json.loads(lines[-1]) if lines else {}
        return rc, obj

    def test_dm2_status_contract_is_stable(self) -> None:
        with TemporaryDirectory(prefix="agentos_next_dm2_status_") as td:
            rc, out = self._run_cli(["mvp", "daemon", "status", "--data-dir", td])
            self.assertEqual(rc, 0)
            self.assertEqual(
                set(out.keys()),
                {
                    "ok",
                    "error_code",
                    "state",
                    "last_tick_at",
                    "next_fire_at",
                    "consecutive_failures",
                    "cumulative_failures",
                    "pid",
                    "uptime_ms",
                    "evidence_refs",
                },
            )

    def test_dm2_single_writer_leader_lock_blocks_and_stale_recovers(self) -> None:
        with TemporaryDirectory(prefix="agentos_next_dm2_lock_") as td:
            data_dir = Path(td)
            lock = data_dir / "daemon" / "leader.lock"
            lock.parent.mkdir(parents=True, exist_ok=True)

            lock.write_text(json.dumps({"pid": 111, "ts": time.time()}) + "\n", encoding="utf-8")
            rc1, out1 = self._run_cli(["mvp", "daemon", "run-once", "--data-dir", td])
            self.assertEqual(rc1, 1)
            self.assertEqual(out1.get("error_code"), "E_DAEMON_LOCKED")

            lock.write_text(json.dumps({"pid": 111, "ts": time.time() - 120.0}) + "\n", encoding="utf-8")
            rc2, out2 = self._run_cli(["mvp", "daemon", "run-once", "--data-dir", td])
            self.assertEqual(rc2, 0)
            self.assertTrue(out2.get("ok"))

    def test_dm2_mutual_exclusion_with_scheduler_tick(self) -> None:
        with TemporaryDirectory(prefix="agentos_next_dm2_tick_lock_") as td:
            data_dir = Path(td)
            tick_lock = data_dir / "scheduler" / "tick.lock"
            tick_lock.parent.mkdir(parents=True, exist_ok=True)
            tick_lock.write_text(json.dumps({"pid": 222, "ts": time.time()}) + "\n", encoding="utf-8")

            rc, out = self._run_cli(["mvp", "daemon", "run-once", "--data-dir", td])
            self.assertEqual(rc, 1)
            self.assertEqual(out.get("error_code"), "E_DAEMON_LOCKED")

    def test_dm2_wal_recovery_requeues_incomplete_fire_and_is_idempotent(self) -> None:
        root = Path(__file__).resolve().parents[1]
        skill_dir = root / "examples" / "skills" / "personal_assistant_brief"

        with TemporaryDirectory(prefix="agentos_next_dm2_wal_") as td:
            data_dir = Path(td)
            store = FileSchedulerStore(data_dir=data_dir)
            run_at = "2026-02-25T09:00:01Z"
            task = store.create_at(
                workspace_id="ws_dm2",
                run_at=run_at,
                execute_request_draft={
                    "skill_ref": str(skill_dir),
                    "input": {"request": "hello"},
                    "deadline_ms": 3000,
                    "policy_context": {"verify_asvp": False, "backend": "local_mock"},
                    "preferred_target": "local",
                },
                idempotency_root="idem_dm2_wal",
            )

            store.put(ScheduledTask.from_dict({**task.to_dict(), "status": "running"}))
            wal = data_dir / "daemon" / "wal" / "events.jsonl"
            wal.parent.mkdir(parents=True, exist_ok=True)
            wal.write_text(
                json.dumps(
                    {
                        "schema_version": "1.0.0",
                        "event_type": "fire_started",
                        "ts": run_at,
                        "task_id": task.task_id,
                        "attempt": 1,
                        "idempotency_key": "idem_dm2_wal:1",
                        "trace_id": f"tr_{task.task_id}",
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n",
                encoding="utf-8",
            )

            rc1, out1 = self._run_cli(["mvp", "daemon", "run-once", "--data-dir", td, "--now", run_at])
            self.assertEqual(rc1, 0)
            self.assertTrue(out1.get("ok"))

            task_after = store.get(task_id=task.task_id)
            self.assertIsNotNone(task_after)
            self.assertEqual(task_after.status, "done")
            self.assertEqual(task_after.attempts, 1)

            trace_path = data_dir / "traces" / f"tr_{task.task_id}.jsonl"
            lines_before = trace_path.read_text(encoding="utf-8").splitlines() if trace_path.exists() else []

            rc2, out2 = self._run_cli(["mvp", "daemon", "run-once", "--data-dir", td, "--now", run_at])
            self.assertEqual(rc2, 0)
            self.assertTrue(out2.get("ok"))

            task_final = store.get(task_id=task.task_id)
            self.assertIsNotNone(task_final)
            self.assertEqual(task_final.attempts, 1)

            lines_after = trace_path.read_text(encoding="utf-8").splitlines() if trace_path.exists() else []
            self.assertEqual(lines_before, lines_after)

    def test_dm2_health_counts_internal_failures_only_and_blocks_by_threshold(self) -> None:
        with TemporaryDirectory(prefix="agentos_next_dm2_health_") as td:
            data_dir = Path(td)
            store = FileSchedulerStore(data_dir=data_dir)
            run_at = "2026-02-25T10:00:01Z"
            store.create_at(
                workspace_id="ws_dm2",
                run_at=run_at,
                execute_request_draft={
                    "skill_ref": str(data_dir / "missing_skill"),
                    "input": {"request": "hello"},
                    "deadline_ms": 3000,
                    "policy_context": {"verify_asvp": False, "backend": "local_mock"},
                    "preferred_target": "local",
                },
                idempotency_root="idem_dm2_fail",
            )

            rc1, out1 = self._run_cli(["mvp", "daemon", "run-once", "--data-dir", td, "--now", run_at])
            self.assertEqual(rc1, 0)
            self.assertTrue(out1.get("ok"))
            self.assertEqual(int(out1.get("consecutive_failures") or 0), 0)

            tick_lock = data_dir / "scheduler" / "tick.lock"
            tick_lock.parent.mkdir(parents=True, exist_ok=True)
            tick_lock.write_text(json.dumps({"pid": 222, "ts": time.time()}) + "\n", encoding="utf-8")
            rc2, out2 = self._run_cli(["mvp", "daemon", "run-once", "--data-dir", td, "--strict-mode"])
            self.assertEqual(rc2, 1)
            self.assertEqual(out2.get("error_code"), "E_DAEMON_UNHEALTHY")

        with TemporaryDirectory(prefix="agentos_next_dm2_replay_") as td2:
            data_dir2 = Path(td2)
            rc3, out3 = self._run_cli(["mvp", "daemon", "run-once", "--data-dir", td2, "--replay-mode"])
            self.assertEqual(rc3, 1)
            self.assertEqual(out3.get("error_code"), "E_DAEMON_POLICY_VIOLATION")
            self.assertFalse((data_dir2 / "daemon").exists())


if __name__ == "__main__":  # pragma: no cover
    unittest.main(verbosity=2)
