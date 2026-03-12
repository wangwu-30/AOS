from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import bootstrap  # noqa: F401

from admission_helpers import make_minimal_skill_package
from agentos_next.kernel.evidence_manifest import manifest_paths_for_turn, verify_turn_manifest
from agentos_next.kernel.executor import ExecuteRequest
from agentos_next.kernel.orchestrator import Orchestrator
from agentos_next.kernel.types import TraceContext
from agentos_next.runtime.local_executor import LocalExecutor


class TestThread028EvidenceIntegrity(unittest.IsolatedAsyncioTestCase):
    async def test_manifest_and_verify_ok(self) -> None:
        with TemporaryDirectory(prefix="agentos_next_t028_ok_") as td:
            root = Path(td)
            pkg_dir = root / "pkg"
            data_dir = root / "data"
            make_minimal_skill_package(pkg_dir)

            orch = Orchestrator.for_data_dir(str(data_dir), local_executor=LocalExecutor.for_data_dir(data_dir))
            trace = TraceContext(trace_id="tr_t028", turn_id="turn_t028", span_id="span_t028")
            req = ExecuteRequest(
                workspace_id="ws_t028",
                skill_ref=str(pkg_dir),
                input={"q": "hi"},
                idempotency_key="idem_t028_1",
                deadline_ms=3000,
                trace=trace,
                policy_context={"verify_asvp": False, "backend": "local_mock"},
                preferred_target="local",
            )
            res = await orch.execute(req)
            self.assertEqual(res.status, "accepted")
            mres = orch.finalize_turn_manifest(
                trace=trace,
                workspace_id=req.workspace_id,
                operator_ref=req.operator_ref,
                idempotency_key=req.idempotency_key,
                execute_status=str(res.status),
                execute_error_code=(str(res.error_code) if res.error_code is not None else None),
                policy_context=req.policy_context,
            )
            self.assertTrue(mres.ok, msg=f"finalize failed: {mres.error_code} {mres.reason_code}")

            paths = manifest_paths_for_turn(data_dir=data_dir, trace_id=trace.trace_id, turn_id=trace.turn_id)
            self.assertTrue(paths.manifest_path.exists(), msg=f"missing manifest: {paths.manifest_path}")
            self.assertTrue(paths.signature_path.exists(), msg=f"missing signature: {paths.signature_path}")

            ok, code, errors = verify_turn_manifest(data_dir=data_dir, trace_id=trace.trace_id, turn_id=trace.turn_id)
            self.assertTrue(ok, msg=f"verify failed: code={code} errors={errors}")

    async def test_tamper_blob_is_detected(self) -> None:
        with TemporaryDirectory(prefix="agentos_next_t028_tamper_") as td:
            root = Path(td)
            pkg_dir = root / "pkg"
            data_dir = root / "data"
            make_minimal_skill_package(pkg_dir)

            orch = Orchestrator.for_data_dir(str(data_dir), local_executor=LocalExecutor.for_data_dir(data_dir))
            trace = TraceContext(trace_id="tr_t028_t", turn_id="turn_t028_t", span_id="span_t028_t")
            req = ExecuteRequest(
                workspace_id="ws_t028",
                skill_ref=str(pkg_dir),
                input={"q": "hi"},
                idempotency_key="idem_t028_t_1",
                deadline_ms=3000,
                trace=trace,
                policy_context={"verify_asvp": False, "backend": "local_mock"},
                preferred_target="local",
            )
            res = await orch.execute(req)
            self.assertEqual(res.status, "accepted")
            self.assertTrue(res.evidence_refs)
            mres = orch.finalize_turn_manifest(
                trace=trace,
                workspace_id=req.workspace_id,
                operator_ref=req.operator_ref,
                idempotency_key=req.idempotency_key,
                execute_status=str(res.status),
                execute_error_code=(str(res.error_code) if res.error_code is not None else None),
                policy_context=req.policy_context,
            )
            self.assertTrue(mres.ok, msg=f"finalize failed: {mres.error_code} {mres.reason_code}")

            victim = res.evidence_refs[0].ref
            blob_path = data_dir / "evidence" / "blobs" / victim
            self.assertTrue(blob_path.exists(), msg=f"missing blob: {blob_path}")
            blob_path.write_bytes(blob_path.read_bytes() + b"\\nTAMPER\\n")

            ok, code, errors = verify_turn_manifest(data_dir=data_dir, trace_id=trace.trace_id, turn_id=trace.turn_id)
            self.assertFalse(ok)
            self.assertEqual(code, "E_EVIDENCE_VERIFY_FAILED")
            self.assertTrue(any("tampered" in e for e in errors), msg=f"errors: {errors}")

    async def test_missing_signature_is_fail_closed(self) -> None:
        with TemporaryDirectory(prefix="agentos_next_t028_missing_sig_") as td:
            root = Path(td)
            pkg_dir = root / "pkg"
            data_dir = root / "data"
            make_minimal_skill_package(pkg_dir)

            orch = Orchestrator.for_data_dir(str(data_dir), local_executor=LocalExecutor.for_data_dir(data_dir))
            trace = TraceContext(trace_id="tr_t028_ms", turn_id="turn_t028_ms", span_id="span_t028_ms")
            req = ExecuteRequest(
                workspace_id="ws_t028",
                skill_ref=str(pkg_dir),
                input={"q": "hi"},
                idempotency_key="idem_t028_ms_1",
                deadline_ms=3000,
                trace=trace,
                policy_context={"verify_asvp": False, "backend": "local_mock"},
                preferred_target="local",
            )
            res = await orch.execute(req)
            self.assertEqual(res.status, "accepted")
            mres = orch.finalize_turn_manifest(
                trace=trace,
                workspace_id=req.workspace_id,
                operator_ref=req.operator_ref,
                idempotency_key=req.idempotency_key,
                execute_status=str(res.status),
                execute_error_code=(str(res.error_code) if res.error_code is not None else None),
                policy_context=req.policy_context,
            )
            self.assertTrue(mres.ok, msg=f"finalize failed: {mres.error_code} {mres.reason_code}")

            paths = manifest_paths_for_turn(data_dir=data_dir, trace_id=trace.trace_id, turn_id=trace.turn_id)
            self.assertTrue(paths.signature_path.exists())
            paths.signature_path.unlink()

            ok, code, errors = verify_turn_manifest(data_dir=data_dir, trace_id=trace.trace_id, turn_id=trace.turn_id)
            self.assertFalse(ok)
            self.assertEqual(code, "E_EVIDENCE_SIGNATURE_MISSING")
            self.assertTrue(errors)

    async def test_duplicate_manifest_generation_is_fail_closed(self) -> None:
        with TemporaryDirectory(prefix="agentos_next_t028_dup_") as td:
            root = Path(td)
            pkg_dir = root / "pkg"
            data_dir = root / "data"
            make_minimal_skill_package(pkg_dir)

            orch = Orchestrator.for_data_dir(str(data_dir), local_executor=LocalExecutor.for_data_dir(data_dir))
            trace = TraceContext(trace_id="tr_t028_dup", turn_id="turn_t028_dup", span_id="span_t028_dup")
            policy = {"verify_asvp": False, "backend": "local_mock"}

            req1 = ExecuteRequest(
                workspace_id="ws_t028",
                skill_ref=str(pkg_dir),
                input={"q": "hi"},
                idempotency_key="idem_dup_1",
                deadline_ms=3000,
                trace=trace,
                policy_context=policy,
                preferred_target="local",
            )
            r1 = await orch.execute(req1)
            self.assertEqual(r1.status, "accepted")
            mres1 = orch.finalize_turn_manifest(
                trace=trace,
                workspace_id=req1.workspace_id,
                operator_ref=req1.operator_ref,
                idempotency_key=req1.idempotency_key,
                execute_status=str(r1.status),
                execute_error_code=(str(r1.error_code) if r1.error_code is not None else None),
                policy_context=req1.policy_context,
            )
            self.assertTrue(mres1.ok, msg=f"finalize failed: {mres1.error_code} {mres1.reason_code}")

            # Duplicate generation is fail-closed (one manifest per trace_id/turn_id).
            mres2 = orch.finalize_turn_manifest(
                trace=trace,
                workspace_id=req1.workspace_id,
                operator_ref=req1.operator_ref,
                idempotency_key="idem_dup_2",
                execute_status=str(r1.status),
                execute_error_code=(str(r1.error_code) if r1.error_code is not None else None),
                policy_context=req1.policy_context,
            )
            self.assertFalse(mres2.ok)
            self.assertEqual(mres2.error_code, "E_EVIDENCE_SIGNATURE_EXISTS")

            trace_path = data_dir / "traces" / f"{trace.trace_id}.jsonl"
            self.assertTrue(trace_path.exists())
            events = [json.loads(ln) for ln in trace_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
            self.assertTrue(any(ev.get("event_type") == "ERROR" for ev in events))


if __name__ == "__main__":  # pragma: no cover
    unittest.main(verbosity=2)
