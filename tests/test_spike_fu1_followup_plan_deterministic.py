from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import bootstrap  # noqa: F401

from agentos_next.apps.assistant_loop import AssistantLoopRequest, run_assistant_loop_async
from agentos_next.kernel.evidence_store import FileEvidenceStore
from agentos_next.kernel.types import TraceContext


class TestSpikeFU1FollowupPlanDeterministic(unittest.IsolatedAsyncioTestCase):
    async def test_followup_plan_is_deterministic_across_data_dirs(self) -> None:
        root = Path(__file__).resolve().parents[1]
        skill_dir = root / "examples" / "skills" / "personal_assistant_brief"
        self.assertTrue(skill_dir.exists(), msg=f"missing example skill: {skill_dir}")

        # Avoid triggering memory.write in the assistant loop (keeps tool outputs/data_dir influence minimal).
        query = "Draft a short email asking to reschedule a meeting."

        trace = TraceContext(trace_id="tr_fu1", turn_id="turn_fu1_1", span_id="span_fu1_root")

        with TemporaryDirectory(prefix="agentos_next_fu1_a_") as td1, TemporaryDirectory(prefix="agentos_next_fu1_b_") as td2:
            data_dir1 = Path(td1) / "data"
            data_dir2 = Path(td2) / "data"

            req1 = AssistantLoopRequest(
                query=query,
                assistant_skill_dir=skill_dir,
                workspace_id="ws_fu1",
                data_dir=data_dir1,
                trace=trace,
                idempotency_key="idem_fu1",
                deadline_ms=8000,
                verify_asvp=False,
                public_keys_dir=None,
                backend="local_mock",
                model=None,
                remote_calls_armed=False,
                allow_network_egress=False,
                approved_by_human=False,
                replay_mode=True,
            )
            req2 = AssistantLoopRequest(
                query=query,
                assistant_skill_dir=skill_dir,
                workspace_id="ws_fu1",
                data_dir=data_dir2,
                trace=trace,
                idempotency_key="idem_fu1",
                deadline_ms=8000,
                verify_asvp=False,
                public_keys_dir=None,
                backend="local_mock",
                model=None,
                remote_calls_armed=False,
                allow_network_egress=False,
                approved_by_human=False,
                replay_mode=True,
            )

            res1 = await run_assistant_loop_async(req1)
            res2 = await run_assistant_loop_async(req2)

            self.assertIsInstance(res1.followup_plan_ref, str)
            self.assertTrue(res1.followup_plan_ref.startswith("ev_"))
            self.assertIsInstance(res2.followup_plan_ref, str)
            self.assertTrue(res2.followup_plan_ref.startswith("ev_"))

            if res1.followup_plan_ref != res2.followup_plan_ref:
                ev1 = FileEvidenceStore(data_dir=data_dir1).get_blob(res1.followup_plan_ref)
                ev2 = FileEvidenceStore(data_dir=data_dir2).get_blob(res2.followup_plan_ref)
                self.assertIsNotNone(ev1, msg="missing followup plan evidence blob in run1")
                self.assertIsNotNone(ev2, msg="missing followup plan evidence blob in run2")
                assert ev1 is not None
                assert ev2 is not None
                self.assertEqual(ev1.content, ev2.content, msg="followup plan blob content should be deterministic")
            else:
                # Stronger: same content-addressed ref across distinct data_dirs.
                self.assertEqual(res1.followup_plan_ref, res2.followup_plan_ref)

            # Validate schema constraints: no ts and bounded <= 5.
            evidence = FileEvidenceStore(data_dir=data_dir1)
            blob = evidence.get_blob(res1.followup_plan_ref)
            self.assertIsNotNone(blob)
            assert blob is not None
            self.assertEqual(blob.content_type, "application/json")
            obj = json.loads(blob.content.decode("utf-8"))
            self.assertIsInstance(obj, dict)
            self.assertNotIn("ts", obj)
            steps = obj.get("steps")
            self.assertIsInstance(steps, list)
            self.assertLessEqual(len(steps), 5)


if __name__ == "__main__":  # pragma: no cover
    unittest.main(verbosity=2)

