from __future__ import annotations

import unittest

import bootstrap  # noqa: F401

from agentos_next.kernel.types import (
    AssumptionEvidenceV1,
    OperatorContractV1,
    ResourceBudgetV1,
    ResourceEscalationRequestV1,
    TaskContextSnapshotV1,
    TaskSpecV1,
)


class TestKernelTypesV1(unittest.TestCase):
    def test_task_spec_v1_defaults(self) -> None:
        spec = TaskSpecV1(task_id="task_1", submission_id="sub_1")
        self.assertEqual(spec.generation, 1)
        self.assertEqual(spec.execution_lane, "standard_task")
        self.assertEqual(spec.context_strategy, "auto_enrich_then_clarify")
        self.assertEqual(spec.max_escalation_count, 2)
        self.assertIsInstance(spec.resource_budget, ResourceBudgetV1)

    def test_task_context_snapshot_requires_matching_generation(self) -> None:
        snapshot = TaskContextSnapshotV1(
            snapshot_id="ctx_1",
            task_id="task_1",
            submission_id="sub_1",
            generation=3,
            frozen_at_generation=3,
        )
        self.assertEqual(snapshot.generation, snapshot.frozen_at_generation)

        with self.assertRaises(ValueError):
            TaskContextSnapshotV1(
                snapshot_id="ctx_2",
                task_id="task_1",
                submission_id="sub_1",
                generation=3,
                frozen_at_generation=2,
            )

    def test_assumption_evidence_validates_confidence(self) -> None:
        evidence = AssumptionEvidenceV1(assumption_text="x", confidence=0.75)
        self.assertEqual(evidence.confidence, 0.75)

        with self.assertRaises(ValueError):
            AssumptionEvidenceV1(assumption_text="x", confidence=1.5)

    def test_resource_escalation_request_validates_count(self) -> None:
        req = ResourceEscalationRequestV1(request_id="req_1", escalation_count=1)
        self.assertEqual(req.escalation_count, 1)

        with self.assertRaises(ValueError):
            ResourceEscalationRequestV1(request_id="req_2", escalation_count=0)

    def test_operator_contract_defaults(self) -> None:
        contract = OperatorContractV1(operator_ref="builtin://memory.search")
        self.assertEqual(contract.purity, "read_only")
        self.assertEqual(contract.retry_class, "safe")
        self.assertEqual(contract.visibility, "canonical")


if __name__ == "__main__":
    unittest.main()
