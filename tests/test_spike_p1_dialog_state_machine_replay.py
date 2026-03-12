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


class TestSpikeP1DialogStateMachineReplay(unittest.TestCase):
    def test_rehydrate_is_deterministic_and_missing_evidence_blocks(self) -> None:
        root = Path(__file__).resolve().parents[1]
        keys_dir = root / "examples" / "keys"

        with tempfile.TemporaryDirectory(prefix="agentos_next_sm1_") as td:
            data_dir = Path(td)
            trace_id = "tr_sm1_test"

            stdin = io.StringIO("hello\nworld\n")
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
                        "--trace-id",
                        trace_id,
                        "--max-turns",
                        "2",
                        "--no-verify-asvp",
                        "--replay-mode",
                    ]
                )
            self.assertEqual(rc, 0)

            trace_path = data_dir / "traces" / f"{trace_id}.jsonl"
            self.assertTrue(trace_path.exists(), f"missing trace file: {trace_path}")

            events = [json.loads(ln) for ln in trace_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
            dialog_events = [ev for ev in events if ev.get("event_type") == "DIALOG_EVENT"]
            self.assertGreaterEqual(len(dialog_events), 4, msg="expected dialog events in trace")

            # Rehydrate should end in IDLE after two successful turns.
            st1 = rehydrate_dialog_state(data_dir=data_dir, trace_id=trace_id, require_evidence=True)
            self.assertEqual(st1.dialog_id, trace_id)
            self.assertEqual(st1.status, "IDLE")
            self.assertGreaterEqual(st1.turn_count, 2)
            self.assertGreaterEqual(st1.last_turn_index, 2)
            self.assertEqual(st1.last_delivery_state, "done")

            # Find last TURN_FINISHED and delete its referenced evidence meta -> must BLOCKED.
            last_turn_finished = None
            for ev in dialog_events:
                data = ev.get("data") if isinstance(ev.get("data"), dict) else None
                if not data:
                    continue
                if data.get("dialog_event_type") == "TURN_FINISHED" and data.get("turn_index") == 2:
                    last_turn_finished = data
            self.assertIsNotNone(last_turn_finished)
            assert isinstance(last_turn_finished, dict)

            final_ref = last_turn_finished.get("final_snapshot_ref")
            self.assertIsInstance(final_ref, str)
            meta_path = data_dir / "evidence" / "meta" / f"{final_ref}.json"
            self.assertTrue(meta_path.exists(), f"missing evidence meta before delete: {meta_path}")
            meta_path.unlink()

            st2 = rehydrate_dialog_state(data_dir=data_dir, trace_id=trace_id, require_evidence=True)
            self.assertEqual(st2.status, "BLOCKED")
            self.assertEqual(st2.blocked_reason, "missing_evidence")

            # Without evidence requirement, state remains deterministically IDLE.
            st3 = rehydrate_dialog_state(data_dir=data_dir, trace_id=trace_id, require_evidence=False)
            self.assertEqual(st3.status, "IDLE")
            self.assertEqual(st3.last_delivery_state, "done")


if __name__ == "__main__":  # pragma: no cover
    unittest.main(verbosity=2)
