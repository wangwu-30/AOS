from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import bootstrap  # noqa: F401

from agentos_next.kernel.capabilities import capability_items_for_policy_context
from agentos_next.kernel.evidence_store import FileEvidenceStore
from agentos_next.kernel.executor import ExecuteRequest
from agentos_next.kernel.orchestrator import Orchestrator
from agentos_next.kernel.types import TraceContext
from agentos_next.runtime.local_executor import LocalExecutor


class TestSpikeAL1AssistantLoop(unittest.IsolatedAsyncioTestCase):
    async def test_assistant_loop_runs_memory_tool_and_personal_assistant_skill_and_persists_trace_evidence(self) -> None:
        root = Path(__file__).resolve().parents[1]
        skill_dir = root / "examples" / "skills" / "personal_assistant_brief"
        self.assertTrue(skill_dir.exists(), msg=f"missing example skill: {skill_dir}")

        with TemporaryDirectory(prefix="agentos_next_al1_") as td:
            data_dir = Path(td) / "data"

            orch = Orchestrator.for_data_dir(str(data_dir), local_executor=LocalExecutor.for_data_dir(data_dir))
            evidence = FileEvidenceStore(data_dir=data_dir)

            trace_id = "tr_al1"
            turn_id = "turn_al1_1"
            parent_span_id = "span_root"

            # Step 1: Tool call (builtin://memory.*)
            req_mem_write = ExecuteRequest(
                workspace_id="ws_al1",
                skill_ref="builtin://memory.write",
                input={"content": "remember this: draft a reschedule email", "tags": ["al1"], "ttl_seconds": 0},
                idempotency_key="idem_al1_mem_write_1",
                deadline_ms=2000,
                trace=TraceContext(
                    trace_id=trace_id,
                    turn_id=turn_id,
                    span_id="span_mem_write_1",
                    parent_span_id=parent_span_id,
                ),
                policy_context={"capabilities": capability_items_for_policy_context(["memory_write"])},
                preferred_target="local",
            )
            res_mem_write = await orch.execute(req_mem_write)
            self.assertEqual(res_mem_write.status, "accepted")
            self.assertGreaterEqual(len(res_mem_write.evidence_refs), 1)

            # Step 2: Skill execution (personal_assistant_brief)
            req_skill = ExecuteRequest(
                workspace_id="ws_al1",
                skill_ref=str(skill_dir),
                input={"request": "Draft a short email asking to reschedule a meeting.", "tone": "formal"},
                idempotency_key="idem_al1_skill_1",
                deadline_ms=5000,
                trace=TraceContext(
                    trace_id=trace_id,
                    turn_id=turn_id,
                    span_id="span_skill_1",
                    parent_span_id=parent_span_id,
                ),
                policy_context={
                    "verify_asvp": False,
                    "public_keys_dir": None,
                    "backend": "local_mock",
                    "remote_calls_armed": False,
                    "allow_network_egress": False,
                    "approved_by_human": False,
                    "replay_mode": True,
                },
                preferred_target="local",
            )
            res_skill = await orch.execute(req_skill)
            self.assertEqual(res_skill.status, "accepted")
            self.assertGreaterEqual(len(res_skill.evidence_refs), 1)

            # Confirm we can read the assistant output (llm_io JSON evidence, not the prompt text blob).
            out_skill = None
            for er in res_skill.evidence_refs:
                if er.kind != "llm_io":
                    continue
                blob = evidence.get_blob(er.ref)
                if blob is None or blob.content_type != "application/json":
                    continue
                try:
                    candidate = json.loads(blob.content.decode("utf-8"))
                except Exception:
                    continue
                if isinstance(candidate, dict) and isinstance(candidate.get("output"), dict):
                    out_skill = candidate
                    break
            self.assertIsNotNone(out_skill, msg="missing llm_io JSON evidence with output object")
            assert isinstance(out_skill, dict)  # for type checkers
            self.assertIsInstance(out_skill["output"].get("reply"), str)
            self.assertGreater(len(out_skill["output"]["reply"].strip()), 0)

            # Evidence must be on disk for both steps.
            blobs_dir = data_dir / "evidence" / "blobs"
            meta_dir = data_dir / "evidence" / "meta"
            self.assertTrue(blobs_dir.exists())
            self.assertTrue(meta_dir.exists())
            for er in list(res_mem_write.evidence_refs) + list(res_skill.evidence_refs):
                self.assertTrue((blobs_dir / er.ref).exists(), msg=f"missing evidence blob: {er.ref}")
                self.assertTrue((meta_dir / f"{er.ref}.json").exists(), msg=f"missing evidence meta: {er.ref}")

            # Trace must be on disk and include both the memory tool call and the skill call.
            trace_path = data_dir / "traces" / f"{trace_id}.jsonl"
            self.assertTrue(trace_path.exists(), msg=f"missing trace: {trace_path}")

            events = [json.loads(ln) for ln in trace_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
            self.assertGreaterEqual(len(events), 4)

            self.assertTrue(
                any(
                    ev.get("event_type") == "TOOL_CALL_FINISHED" and ev.get("data", {}).get("builtin") == "memory.write"
                    for ev in events
                ),
                msg="expected memory.write TOOL_CALL_FINISHED in trace",
            )
            self.assertTrue(
                any(
                    ev.get("event_type") == "TOOL_CALL_FINISHED"
                    and ev.get("data", {}).get("skill") == "personal_assistant_brief"
                    and ev.get("data", {}).get("ok") is True
                    for ev in events
                ),
                msg="expected personal_assistant_brief TOOL_CALL_FINISHED ok=true in trace",
            )


if __name__ == "__main__":  # pragma: no cover
    unittest.main(verbosity=2)
