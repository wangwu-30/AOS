from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import bootstrap  # noqa: F401

from agentos_next.apps.scheduler_tick import SchedulerTickRequest, run_scheduler_tick_async
from agentos_next.kernel.capabilities import capability_items_for_policy_context
from agentos_next.kernel.dialog_state_machine import rehydrate_dialog_state
from agentos_next.kernel.executor import ExecuteRequest
from agentos_next.kernel.orchestrator import Orchestrator
from agentos_next.kernel.types import TraceContext
from agentos_next.runtime.local_executor import LocalExecutor


class TestSpikeSM2SchedulerDialogLink(unittest.IsolatedAsyncioTestCase):
    async def test_scheduler_fire_emits_dialog_events_and_rehydrates(self) -> None:
        root = Path(__file__).resolve().parents[1]
        skill_dir = (root / "examples" / "skills" / "personal_assistant_brief").resolve()
        keys_dir = (root / "examples" / "keys").resolve()

        with TemporaryDirectory(prefix="agentos_next_sm2_") as td:
            data_dir = Path(td)
            dialog_trace_id = "tr_dialog_sm2"

            orch = Orchestrator.for_data_dir(str(data_dir), local_executor=LocalExecutor.for_data_dir(data_dir))

            run_at = "2026-02-20T09:00:01Z"
            req_create = ExecuteRequest(
                workspace_id="ws_sm2",
                skill_ref="builtin://scheduler.at",
                input={
                    "schema_version": "1.0.0",
                    "run_at": run_at,
                    "execute_request": {
                        "skill_ref": str(skill_dir),
                        "input": {"request": "hello"},
                        "deadline_ms": 3000,
                        "policy_context": {
                            "verify_asvp": False,
                            "public_keys_dir": str(keys_dir),
                            "backend": "local_mock",
                            "dialog_trace_id": dialog_trace_id,
                        },
                        "preferred_target": "local",
                    },
                },
                idempotency_key="idem_sm2_create_1",
                deadline_ms=2000,
                trace=TraceContext(trace_id="tr_sm2_create", turn_id="turn1", span_id="span1"),
                policy_context={"capabilities": capability_items_for_policy_context(["scheduler_write"])},
                preferred_target="local",
            )
            res_create = await orch.execute(req_create)
            self.assertEqual(res_create.status, "accepted")

            # Fire due tasks.
            tick = SchedulerTickRequest(data_dir=str(data_dir), now=run_at, max_fires=10, replay_mode=True)
            res_tick = await run_scheduler_tick_async(tick, orchestrator=orch)
            self.assertTrue(res_tick.ok)
            self.assertEqual(len(res_tick.fired), 1)

            # Dialog trace must include DIALOG_EVENT lines.
            dlg_trace_path = data_dir / "traces" / f"{dialog_trace_id}.jsonl"
            self.assertTrue(dlg_trace_path.exists(), f"missing dialog trace file: {dlg_trace_path}")
            events = [json.loads(ln) for ln in dlg_trace_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
            dialog_events = [ev for ev in events if ev.get("event_type") == "DIALOG_EVENT"]
            self.assertGreaterEqual(len(dialog_events), 2)
            self.assertTrue(
                any(ev.get("data", {}).get("dialog_event_type") == "TURN_STARTED" for ev in dialog_events),
                msg="expected TURN_STARTED",
            )
            self.assertTrue(
                any(ev.get("data", {}).get("dialog_event_type") == "TURN_FINISHED" for ev in dialog_events),
                msg="expected TURN_FINISHED",
            )

            # Rehydrate should be IDLE, and evidence requirement should pass.
            st1 = rehydrate_dialog_state(data_dir=data_dir, trace_id=dialog_trace_id, require_evidence=True)
            self.assertEqual(st1.status, "IDLE")

            # Delete the referenced evidence meta for TURN_FINISHED -> must BLOCKED.
            fin = None
            for ev in dialog_events:
                d = ev.get("data")
                if isinstance(d, dict) and d.get("dialog_event_type") == "TURN_FINISHED":
                    fin = d
            self.assertIsNotNone(fin)
            assert isinstance(fin, dict)
            final_ref = fin.get("final_snapshot_ref")
            self.assertIsInstance(final_ref, str)
            meta = data_dir / "evidence" / "meta" / f"{final_ref}.json"
            self.assertTrue(meta.exists())
            meta.unlink()

            st2 = rehydrate_dialog_state(data_dir=data_dir, trace_id=dialog_trace_id, require_evidence=True)
            self.assertEqual(st2.status, "BLOCKED")
            self.assertEqual(st2.blocked_reason, "missing_evidence")


if __name__ == "__main__":  # pragma: no cover
    unittest.main(verbosity=2)
