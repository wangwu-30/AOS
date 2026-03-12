from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import bootstrap  # noqa: F401

from agentos_next.apps.scheduler_tick import SchedulerTickRequest, run_scheduler_tick_async
from agentos_next.kernel.capabilities import capability_items_for_policy_context
from agentos_next.kernel.evidence_store import FileEvidenceStore
from agentos_next.kernel.executor import ExecuteRequest
from agentos_next.kernel.orchestrator import Orchestrator
from agentos_next.kernel.scheduler_store import FileSchedulerStore
from agentos_next.kernel.types import TraceContext
from agentos_next.runtime.local_executor import LocalExecutor


class TestSpikeSCHED1Scheduler(unittest.IsolatedAsyncioTestCase):
    async def test_scheduler_tick_invalid_now_is_fail_closed(self) -> None:
        with TemporaryDirectory(prefix="agentos_next_sched1_bad_now_") as td:
            data_dir = Path(td)
            orch = Orchestrator.for_data_dir(str(data_dir), local_executor=LocalExecutor.for_data_dir(data_dir))
            tick = SchedulerTickRequest(
                data_dir=str(data_dir),
                now="not-a-time",
                trace=TraceContext(trace_id="tr_bad_now", turn_id="turn1", span_id="span1"),
            )
            res = await run_scheduler_tick_async(tick, orchestrator=orch)
            self.assertFalse(res.ok)
            self.assertEqual(res.error_code, "E_INPUT_SCHEMA")
            self.assertGreaterEqual(len(res.evidence_refs), 1)

    async def test_scheduler_at_persistence_and_idempotent_tick(self) -> None:
        root = Path(__file__).resolve().parents[1]
        skill_dir = (root / "examples" / "skills" / "personal_assistant_brief").resolve()
        keys_dir = (root / "examples" / "keys").resolve()

        with TemporaryDirectory(prefix="agentos_next_sched1_") as td:
            data_dir = Path(td)
            evidence = FileEvidenceStore(data_dir=data_dir)

            orch1 = Orchestrator.for_data_dir(str(data_dir), local_executor=LocalExecutor.for_data_dir(data_dir))

            run_at = "2026-02-19T10:00:01Z"
            req_create = ExecuteRequest(
                workspace_id="ws1",
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
                            "remote_calls_armed": False,
                            "allow_network_egress": False,
                            "approved_by_human": False,
                            "replay_mode": False,
                        },
                        "preferred_target": "local",
                    },
                },
                idempotency_key="idem_sched_at_1",
                deadline_ms=2000,
                trace=TraceContext(trace_id="tr_sched", turn_id="turn1", span_id="span_create"),
                policy_context={"capabilities": capability_items_for_policy_context(["scheduler_write"])},
                preferred_target="local",
            )
            res_create = await orch1.execute(req_create)
            self.assertEqual(res_create.status, "accepted")

            out_er = next(er for er in res_create.evidence_refs if er.kind == "tool_io")
            out_blob = evidence.get_blob(out_er.ref)
            self.assertIsNotNone(out_blob)
            out = json.loads(out_blob.content.decode("utf-8"))
            task_id = out["task_id"]
            self.assertTrue(isinstance(task_id, str) and task_id.startswith("sched_"))

            # Simulate "restart": build new orchestrator instance and tick runner.
            orch2 = Orchestrator.for_data_dir(str(data_dir), local_executor=LocalExecutor.for_data_dir(data_dir))

            # Before run_at: nothing fires.
            tick1 = SchedulerTickRequest(data_dir=str(data_dir), now="2026-02-19T10:00:00Z", max_fires=10)
            res_tick1 = await run_scheduler_tick_async(tick1, orchestrator=orch2)
            self.assertTrue(res_tick1.ok)
            self.assertEqual(len(res_tick1.fired), 0)

            store = FileSchedulerStore(data_dir=data_dir)
            t1 = store.get(task_id=task_id)
            self.assertIsNotNone(t1)
            self.assertEqual(t1.status, "scheduled")

            # At/after run_at: fires exactly once and becomes done.
            tick2 = SchedulerTickRequest(data_dir=str(data_dir), now="2026-02-19T10:00:01Z", max_fires=10)
            res_tick2 = await run_scheduler_tick_async(tick2, orchestrator=orch2)
            self.assertTrue(res_tick2.ok)
            self.assertEqual(len(res_tick2.fired), 1)
            self.assertEqual(res_tick2.fired[0].task_id, task_id)

            t2 = store.get(task_id=task_id)
            self.assertIsNotNone(t2)
            self.assertEqual(t2.status, "done")
            self.assertEqual(t2.attempts, 1)

            # Repeat tick at same time: should not fire again.
            res_tick3 = await run_scheduler_tick_async(tick2, orchestrator=orch2)
            self.assertTrue(res_tick3.ok)
            self.assertEqual(len(res_tick3.fired), 0)

            # Executed skill trace must exist and be append-only JSONL.
            trace_path = data_dir / "traces" / f"tr_{task_id}.jsonl"
            self.assertTrue(trace_path.exists())
            self.assertIn("TOOL_CALL_STARTED", trace_path.read_text(encoding="utf-8"))

    async def test_scheduler_cron_subset_advances_next_run(self) -> None:
        root = Path(__file__).resolve().parents[1]
        skill_dir = (root / "examples" / "skills" / "personal_assistant_brief").resolve()
        keys_dir = (root / "examples" / "keys").resolve()

        with TemporaryDirectory(prefix="agentos_next_sched1_cron_") as td:
            data_dir = Path(td)
            evidence = FileEvidenceStore(data_dir=data_dir)

            orch = Orchestrator.for_data_dir(str(data_dir), local_executor=LocalExecutor.for_data_dir(data_dir))

            req_create = ExecuteRequest(
                workspace_id="ws1",
                skill_ref="builtin://scheduler.cron",
                input={
                    "schema_version": "1.0.0",
                    "cron": "* * * * *",
                    "timezone": "UTC",
                    "execute_request": {
                        "skill_ref": str(skill_dir),
                        "input": {"request": "ping"},
                        "deadline_ms": 3000,
                        "policy_context": {
                            "verify_asvp": False,
                            "public_keys_dir": str(keys_dir),
                            "backend": "local_mock",
                        },
                        "preferred_target": "local",
                    },
                },
                idempotency_key="idem_sched_cron_1",
                deadline_ms=2000,
                trace=TraceContext(trace_id="tr_sched_cron", turn_id="turn1", span_id="span_create"),
                policy_context={"capabilities": capability_items_for_policy_context(["scheduler_write"])},
                preferred_target="local",
            )
            res_create = await orch.execute(req_create)
            self.assertEqual(res_create.status, "accepted")

            out_er = next(er for er in res_create.evidence_refs if er.kind == "tool_io")
            out_blob = evidence.get_blob(out_er.ref)
            self.assertIsNotNone(out_blob)
            out = json.loads(out_blob.content.decode("utf-8"))
            task_id = out["task_id"]
            next_run_at = out["next_run_at"]

            store = FileSchedulerStore(data_dir=data_dir)
            t0 = store.get(task_id=task_id)
            self.assertIsNotNone(t0)
            self.assertEqual(t0.kind, "cron")

            # Tick at the computed time should fire once and advance next_run_at.
            tick = SchedulerTickRequest(data_dir=str(data_dir), now=str(next_run_at), max_fires=10)
            res_tick = await run_scheduler_tick_async(tick, orchestrator=orch)
            self.assertTrue(res_tick.ok)
            self.assertEqual(len(res_tick.fired), 1)

            t1 = store.get(task_id=task_id)
            self.assertIsNotNone(t1)
            self.assertEqual(t1.status, "scheduled")
            self.assertNotEqual(t1.next_run_at, next_run_at)


if __name__ == "__main__":  # pragma: no cover
    unittest.main(verbosity=2)
