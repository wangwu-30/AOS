from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import bootstrap  # noqa: F401

from agentos_next.kernel.evidence_store import FileEvidenceStore
from agentos_next.kernel.executor import ExecuteRequest
from agentos_next.kernel.orchestrator import Orchestrator
from agentos_next.kernel.skill_registry import FileSkillRegistry
from agentos_next.kernel.types import TraceContext
from agentos_next.runtime.local_executor import LocalExecutor


class TestSpikeREG1SkillRegistry(unittest.IsolatedAsyncioTestCase):
    async def test_registry_ref_exec_is_semantically_equivalent_to_path(self) -> None:
        root = Path(__file__).resolve().parents[1]
        skill_dir = (root / "examples" / "skills" / "personal_assistant_brief").resolve()
        keys_dir = (root / "examples" / "keys").resolve()

        with TemporaryDirectory(prefix="agentos_next_reg1_") as td:
            data_dir = Path(td)
            reg = FileSkillRegistry(data_dir=data_dir)
            entry = reg.register(skill_dir=skill_dir)

            orch = Orchestrator.for_data_dir(str(data_dir), local_executor=LocalExecutor.for_data_dir(data_dir))

            base_policy = {
                "verify_asvp": True,
                "public_keys_dir": str(keys_dir),
                "backend": "local_mock",
                "remote_calls_armed": False,
                "allow_network_egress": False,
                "approved_by_human": False,
                "replay_mode": False,
            }

            req_path = ExecuteRequest(
                workspace_id="ws1",
                skill_ref=str(skill_dir),
                input={"request": "hello"},
                idempotency_key="idem_path_1",
                deadline_ms=3000,
                trace=TraceContext(trace_id="tr_reg", turn_id="turn1", span_id="span_path"),
                policy_context=dict(base_policy),
                preferred_target="local",
            )
            res_path = await orch.execute(req_path)
            self.assertEqual(res_path.status, "accepted")

            req_reg = ExecuteRequest(
                workspace_id="ws1",
                skill_ref=f"registry://{entry.registry_id}",
                input={"request": "hello"},
                idempotency_key="idem_reg_1",
                deadline_ms=3000,
                trace=TraceContext(trace_id="tr_reg", turn_id="turn1", span_id="span_reg"),
                policy_context=dict(base_policy),
                preferred_target="local",
            )
            res_reg = await orch.execute(req_reg)
            self.assertEqual(res_reg.status, "accepted")
            self.assertEqual(res_reg.error_code, res_path.error_code)

            # Resolution evidence must be present and replayable.
            self.assertTrue(len(res_reg.evidence_refs) >= len(res_path.evidence_refs))
            self.assertEqual(res_reg.evidence_refs[0].kind, "routing")

            evidence = FileEvidenceStore(data_dir=data_dir)
            self.assertIsNotNone(evidence.get_blob(res_reg.evidence_refs[0].ref))

    async def test_registry_ref_missing_is_fail_closed(self) -> None:
        root = Path(__file__).resolve().parents[1]
        keys_dir = (root / "examples" / "keys").resolve()

        with TemporaryDirectory(prefix="agentos_next_reg1_missing_") as td:
            data_dir = Path(td)
            orch = Orchestrator.for_data_dir(str(data_dir), local_executor=LocalExecutor.for_data_dir(data_dir))

            req = ExecuteRequest(
                workspace_id="ws1",
                skill_ref="registry://rg_does_not_exist",
                input={"request": "hello"},
                idempotency_key="idem_missing_1",
                deadline_ms=3000,
                trace=TraceContext(trace_id="tr_reg_missing", turn_id="turn1", span_id="span_missing"),
                policy_context={
                    "verify_asvp": True,
                    "public_keys_dir": str(keys_dir),
                    "backend": "local_mock",
                },
                preferred_target="local",
            )
            res = await orch.execute(req)
            self.assertEqual(res.status, "rejected")
            self.assertEqual(res.error_code, "E_EXECUTION_FAILED")
            self.assertTrue(len(res.evidence_refs) >= 1)
            self.assertEqual(res.evidence_refs[0].kind, "error")


if __name__ == "__main__":  # pragma: no cover
    unittest.main(verbosity=2)

