from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import bootstrap  # noqa: F401
from admission_helpers import make_minimal_skill_package

from agentos_next.kernel.evidence_store import FileEvidenceStore
from agentos_next.kernel.executor import ExecuteRequest
from agentos_next.kernel.orchestrator import Orchestrator
from agentos_next.kernel.types import TraceContext
from agentos_next.runtime.local_executor import LocalExecutor


def _set_risk_level(pkg_dir: Path, risk_level: str) -> None:
    path = pkg_dir / "contract.skill"
    obj = json.loads(path.read_text(encoding="utf-8"))
    obj["risk_level"] = risk_level
    path.write_text(json.dumps(obj, ensure_ascii=True, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _read_trace_events(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        return []
    out: list[dict[str, object]] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line:
            continue
        obj = json.loads(line)
        if isinstance(obj, dict):
            out.append(obj)
    return out


class TestThread026PolicyEngine(unittest.IsolatedAsyncioTestCase):
    async def test_cycle_gate_blocks_on_second_homomorphic_action(self) -> None:
        with TemporaryDirectory(prefix="agentos_next_thread026_cycle_") as td:
            root = Path(td)
            pkg_dir = root / "pkg"
            data_dir = root / "data"
            make_minimal_skill_package(pkg_dir)

            orch = Orchestrator.for_data_dir(str(data_dir), local_executor=LocalExecutor.for_data_dir(data_dir))
            evidence = FileEvidenceStore(data_dir=data_dir)
            trace = TraceContext(trace_id="tr_t026_cycle", turn_id="turn_cycle", span_id="span_a")
            policy = {
                "verify_asvp": False,
                "backend": "local_mock",
                "policy_intent": {"actions": ["search"]},
            }

            req1 = ExecuteRequest(
                workspace_id="ws_t026",
                skill_ref=str(pkg_dir),
                input={"q": "hello"},
                idempotency_key="idem_cycle_1",
                deadline_ms=3000,
                trace=trace,
                policy_context=policy,
                preferred_target="local",
            )
            r1 = await orch.execute(req1)
            self.assertEqual(r1.status, "accepted")
            self.assertIsNone(r1.error_code)

            req2 = ExecuteRequest(
                workspace_id="ws_t026",
                skill_ref=str(pkg_dir),
                input={"q": "hello"},
                idempotency_key="idem_cycle_2",
                deadline_ms=3000,
                trace=trace,
                policy_context=policy,
                preferred_target="local",
            )
            r2 = await orch.execute(req2)
            self.assertEqual(r2.status, "rejected")
            self.assertEqual(r2.error_code, "E_CYCLE_DETECTED")
            self.assertTrue(r2.evidence_refs)

            policy_refs = [er.ref for er in r2.evidence_refs if er.kind == "policy"]
            self.assertTrue(policy_refs, msg="missing policy evidence on cycle deny")
            payload_blob = evidence.get_blob(policy_refs[-1])
            self.assertIsNotNone(payload_blob)
            payload = json.loads(payload_blob.content.decode("utf-8"))
            self.assertEqual(payload["reason_code"], "cycle_detected")
            self.assertEqual(payload["error_code"], "E_CYCLE_DETECTED")
            self.assertEqual(int(payload["threshold"]), 2)
            self.assertEqual(int(payload["count"]), 2)
            self.assertTrue(str(payload["fingerprint"]))

            events = _read_trace_events(data_dir / "traces" / f"{trace.trace_id}.jsonl")
            policy_events = [ev for ev in events if ev.get("event_type") == "POLICY_DECIDED"]
            self.assertGreaterEqual(len(policy_events), 2)
            self.assertEqual(policy_events[-1].get("data", {}).get("error_code"), "E_CYCLE_DETECTED")

    async def test_cycle_gate_is_scoped_by_turn(self) -> None:
        with TemporaryDirectory(prefix="agentos_next_thread026_cycle_off_") as td:
            root = Path(td)
            pkg_dir = root / "pkg"
            data_dir = root / "data"
            make_minimal_skill_package(pkg_dir)
            orch = Orchestrator.for_data_dir(str(data_dir), local_executor=LocalExecutor.for_data_dir(data_dir))
            trace_1 = TraceContext(trace_id="tr_t026_cycle_scope", turn_id="turn_a", span_id="span_a")
            trace_2 = TraceContext(trace_id="tr_t026_cycle_scope", turn_id="turn_b", span_id="span_b")

            req1 = ExecuteRequest(
                workspace_id="ws_t026",
                skill_ref=str(pkg_dir),
                input={"q": "hello"},
                idempotency_key="idem_cycle_off_1",
                deadline_ms=3000,
                trace=trace_1,
                policy_context={"verify_asvp": False, "backend": "local_mock"},
                preferred_target="local",
            )
            req2 = ExecuteRequest(
                workspace_id="ws_t026",
                skill_ref=str(pkg_dir),
                input={"q": "hello"},
                idempotency_key="idem_cycle_off_2",
                deadline_ms=3000,
                trace=trace_2,
                policy_context={"verify_asvp": False, "backend": "local_mock"},
                preferred_target="local",
            )
            r1 = await orch.execute(req1)
            r2 = await orch.execute(req2)
            self.assertEqual(r1.status, "accepted")
            self.assertEqual(r2.status, "accepted")

    async def test_high_risk_skill_requires_hitl_in_kernel_policy_gate(self) -> None:
        with TemporaryDirectory(prefix="agentos_next_thread026_hitl_") as td:
            root = Path(td)
            pkg_dir = root / "pkg"
            data_dir = root / "data"
            make_minimal_skill_package(pkg_dir)
            _set_risk_level(pkg_dir, "high")

            orch = Orchestrator.for_data_dir(str(data_dir), local_executor=LocalExecutor.for_data_dir(data_dir))
            evidence = FileEvidenceStore(data_dir=data_dir)
            trace = TraceContext(trace_id="tr_t026_hitl", turn_id="turn_hitl", span_id="span_hitl")
            req = ExecuteRequest(
                workspace_id="ws_t026",
                skill_ref=str(pkg_dir),
                input={"q": "hello"},
                idempotency_key="idem_hitl_1",
                deadline_ms=3000,
                trace=trace,
                policy_context={"verify_asvp": False, "backend": "local_mock", "approved_by_human": False},
                preferred_target="local",
            )
            res = await orch.execute(req)
            self.assertEqual(res.status, "rejected")
            self.assertEqual(res.error_code, "E_HITL_REQUIRED")
            self.assertTrue(res.evidence_refs)

            policy_ref = next(er for er in res.evidence_refs if er.kind == "policy")
            payload = json.loads(evidence.get_blob(policy_ref.ref).content.decode("utf-8"))  # type: ignore[union-attr]
            self.assertEqual(payload["decision"], "ask")
            self.assertEqual(payload["policy_disposition"], "ask")
            self.assertEqual(payload["reason_code"], "hitl_required")
            self.assertEqual(payload["error_code"], "E_HITL_REQUIRED")

            events = _read_trace_events(data_dir / "traces" / f"{trace.trace_id}.jsonl")
            self.assertTrue(any(ev.get("event_type") == "POLICY_DECIDED" for ev in events))
            self.assertFalse(any(ev.get("event_type") == "TOOL_CALL_STARTED" for ev in events))

    async def test_replay_mode_blocks_remote_side_effect_intent_fail_closed(self) -> None:
        with TemporaryDirectory(prefix="agentos_next_thread026_replay_") as td:
            root = Path(td)
            pkg_dir = root / "pkg"
            data_dir = root / "data"
            make_minimal_skill_package(pkg_dir)

            orch = Orchestrator.for_data_dir(str(data_dir), local_executor=LocalExecutor.for_data_dir(data_dir))
            evidence = FileEvidenceStore(data_dir=data_dir)
            trace = TraceContext(trace_id="tr_t026_replay", turn_id="turn_replay", span_id="span_replay")
            req = ExecuteRequest(
                workspace_id="ws_t026",
                skill_ref=str(pkg_dir),
                input={"q": "hello"},
                idempotency_key="idem_replay_1",
                deadline_ms=3000,
                trace=trace,
                policy_context={
                    "verify_asvp": False,
                    "backend": "codex_oauth",
                    "remote_calls_armed": True,
                    "allow_network_egress": True,
                    "replay_mode": True,
                },
                preferred_target="local",
            )
            res = await orch.execute(req)
            self.assertEqual(res.status, "rejected")
            self.assertEqual(res.error_code, "E_REPLAY_REMOTE_DISABLED")
            self.assertFalse(any(er.kind == "llm_io" for er in res.evidence_refs))

            policy_ref = next(er for er in res.evidence_refs if er.kind == "policy")
            payload = json.loads(evidence.get_blob(policy_ref.ref).content.decode("utf-8"))  # type: ignore[union-attr]
            self.assertEqual(payload["reason_code"], "replay_remote_blocked")


if __name__ == "__main__":  # pragma: no cover
    unittest.main(verbosity=2)
