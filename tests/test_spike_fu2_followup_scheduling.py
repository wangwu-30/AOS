from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

import bootstrap  # noqa: F401

from agentos_next.cli import main
from agentos_next.kernel.dialog_state_machine import rehydrate_dialog_state


class TestSpikeFU2FollowupScheduling(unittest.TestCase):
    def test_assistant_loop_stdio_can_schedule_followup_and_tick_emits_dialog_events(self) -> None:
        root = Path(__file__).resolve().parents[1]
        keys_dir = root / "examples" / "keys"

        with tempfile.TemporaryDirectory(prefix="agentos_next_fu2_") as td:
            data_dir = Path(td)
            dialog_trace_id = "tr_fu2_dialog"

            # 1) Run assistant-loop-stdio once with explicit followup-at (not replay-mode).
            stdin = io.StringIO("hello\n")
            stdout = io.StringIO()
            with patch("sys.stdin", stdin), redirect_stdout(stdout):
                rc = main(
                    [
                        "mvp",
                        "assistant-loop-stdio",
                        "--keys-dir",
                        str(keys_dir),
                        "--data-dir",
                        str(data_dir),
                        "--no-verify-asvp",
                        "--trace-id",
                        dialog_trace_id,
                        "--max-turns",
                        "1",
                        "--followup-at",
                        "2026-02-20T09:00:01Z",
                    ]
                )
            self.assertEqual(rc, 0)

            out_line = stdout.getvalue().strip().splitlines()[-1]
            out = json.loads(out_line)
            self.assertTrue(out.get("ok"))
            ev_refs = out.get("evidence_refs")
            self.assertIsInstance(ev_refs, list)
            self.assertGreaterEqual(len(ev_refs), 1)

            # 2) Tick at followup time: should fire at least 1 task and write dialog events (SM2).
            stdout2 = io.StringIO()
            with redirect_stdout(stdout2):
                rc2 = main(
                    [
                        "mvp",
                        "scheduler-tick",
                        "--data-dir",
                        str(data_dir),
                        "--now",
                        "2026-02-20T09:00:01Z",
                        "--max-fires",
                        "10",
                        "--replay-mode",
                    ]
                )
            self.assertEqual(rc2, 0)
            tick_out = json.loads(stdout2.getvalue().strip().splitlines()[-1])
            fired = tick_out.get("fired")
            self.assertIsInstance(fired, list)
            self.assertGreaterEqual(len(fired), 1)

            # 3) Rehydrate dialog: should be IDLE when evidence present.
            st1 = rehydrate_dialog_state(data_dir=data_dir, trace_id=dialog_trace_id, require_evidence=True)
            self.assertIn(st1.status, {"IDLE", "BLOCKED"})

            # Ensure we have at least one TURN_FINISHED with final_snapshot_ref, and missing it blocks.
            dlg_trace_path = data_dir / "traces" / f"{dialog_trace_id}.jsonl"
            self.assertTrue(dlg_trace_path.exists())
            events = [json.loads(ln) for ln in dlg_trace_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
            fins = [
                ev.get("data")
                for ev in events
                if ev.get("event_type") == "DIALOG_EVENT"
                and isinstance(ev.get("data"), dict)
                and ev["data"].get("dialog_event_type") == "TURN_FINISHED"
                and isinstance(ev["data"].get("final_snapshot_ref"), str)
            ]
            self.assertTrue(fins)
            final_ref = fins[-1]["final_snapshot_ref"]
            meta = data_dir / "evidence" / "meta" / f"{final_ref}.json"
            self.assertTrue(meta.exists())
            meta.unlink()

            st2 = rehydrate_dialog_state(data_dir=data_dir, trace_id=dialog_trace_id, require_evidence=True)
            self.assertEqual(st2.status, "BLOCKED")
            self.assertEqual(st2.blocked_reason, "missing_evidence")

    def test_replay_mode_skips_followup_side_effects(self) -> None:
        root = Path(__file__).resolve().parents[1]
        keys_dir = root / "examples" / "keys"

        with tempfile.TemporaryDirectory(prefix="agentos_next_fu2_replay_") as td:
            data_dir = Path(td)
            trace_id = "tr_fu2_replay"

            stdin = io.StringIO("hello\n")
            stdout = io.StringIO()
            with patch("sys.stdin", stdin), redirect_stdout(stdout):
                rc = main(
                    [
                        "mvp",
                        "assistant-loop-stdio",
                        "--keys-dir",
                        str(keys_dir),
                        "--data-dir",
                        str(data_dir),
                        "--no-verify-asvp",
                        "--trace-id",
                        trace_id,
                        "--max-turns",
                        "1",
                        "--replay-mode",
                        "--followup-at",
                        "2026-02-20T09:00:01Z",
                    ]
                )
            self.assertEqual(rc, 0)

            # No scheduler tasks should be created.
            tasks_dir = data_dir / "scheduler" / "tasks"
            if tasks_dir.exists():
                tasks = list(tasks_dir.glob("sched_*.json"))
                self.assertEqual(tasks, [])


if __name__ == "__main__":  # pragma: no cover
    unittest.main(verbosity=2)
