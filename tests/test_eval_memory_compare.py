from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

import bootstrap  # noqa: F401

from agentos_next.cli import main
from agentos_next.evals.memory_effect_compare import compare_memory_effect_reports


def _write_report(
    path: Path,
    *,
    strategy: str,
    aggregate: dict[str, float],
    per_case: list[dict[str, object]],
) -> None:
    obj = {
        "schema_version": "1.0.0",
        "strategy": strategy,
        "dataset_path": "dummy.jsonl",
        "generated_at": "2026-02-25T00:00:00Z",
        "aggregate": aggregate,
        "per_case": per_case,
    }
    path.write_text(json.dumps(obj, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


class TestMemoryEffectCompare(unittest.TestCase):
    def test_compare_prefers_guard_eligible_strategy(self) -> None:
        with tempfile.TemporaryDirectory(prefix="agentos_next_eval_cmp_") as td:
            root = Path(td)
            path_a = root / "report_a.json"
            path_b = root / "report_b.json"
            path_c = root / "report_c.json"

            per_case_a = [
                {
                    "case_id": "c1",
                    "metrics": {
                        "relevant_at_1": True,
                        "conflict": False,
                        "context_faithfulness": True,
                        "over_recall": False,
                        "need_correction": True,
                    },
                },
                {
                    "case_id": "c2",
                    "metrics": {
                        "relevant_at_1": True,
                        "conflict": False,
                        "context_faithfulness": True,
                        "over_recall": False,
                        "need_correction": False,
                    },
                },
            ]
            per_case_b = [
                {
                    "case_id": "c1",
                    "metrics": {
                        "relevant_at_1": True,
                        "conflict": False,
                        "context_faithfulness": True,
                        "over_recall": False,
                        "need_correction": False,
                    },
                },
                {
                    "case_id": "c2",
                    "metrics": {
                        "relevant_at_1": True,
                        "conflict": False,
                        "context_faithfulness": True,
                        "over_recall": False,
                        "need_correction": False,
                    },
                },
            ]
            per_case_c = [
                {
                    "case_id": "c1",
                    "metrics": {
                        "relevant_at_1": True,
                        "conflict": True,
                        "context_faithfulness": True,
                        "over_recall": False,
                        "need_correction": True,
                    },
                },
                {
                    "case_id": "c2",
                    "metrics": {
                        "relevant_at_1": True,
                        "conflict": False,
                        "context_faithfulness": True,
                        "over_recall": False,
                        "need_correction": False,
                    },
                },
            ]

            _write_report(
                path_a,
                strategy="A",
                aggregate={
                    "relevant_at_1": 0.7,
                    "conflict_rate": 0.1,
                    "context_faithfulness": 0.9,
                    "over_recall_rate": 0.2,
                    "user_correction_rate": 0.5,
                },
                per_case=per_case_a,
            )
            _write_report(
                path_b,
                strategy="B",
                aggregate={
                    "relevant_at_1": 0.8,
                    "conflict_rate": 0.1,
                    "context_faithfulness": 0.9,
                    "over_recall_rate": 0.2,
                    "user_correction_rate": 0.2,
                },
                per_case=per_case_b,
            )
            _write_report(
                path_c,
                strategy="C",
                aggregate={
                    "relevant_at_1": 0.9,
                    "conflict_rate": 0.3,
                    "context_faithfulness": 0.9,
                    "over_recall_rate": 0.2,
                    "user_correction_rate": 0.1,
                },
                per_case=per_case_c,
            )

            comparison = compare_memory_effect_reports(
                report_a_path=path_a,
                report_b_path=path_b,
                report_c_path=path_c,
                baseline_strategy="A",
            )
            self.assertEqual(comparison["winner_strategy"], "B")
            violations = {row["strategy"]: row["violations"] for row in comparison["guard_violations"]}
            self.assertIn("C", violations)
            self.assertIn("conflict_rate_increase", violations["C"])

    def test_cli_eval_memory_compare_outputs_stable_json(self) -> None:
        with tempfile.TemporaryDirectory(prefix="agentos_next_eval_cmp_cli_") as td:
            root = Path(td)
            path_a = root / "report_a.json"
            path_b = root / "report_b.json"
            path_c = root / "report_c.json"
            out = root / "comparison.json"

            common_per_case = [
                {
                    "case_id": "c1",
                    "metrics": {
                        "relevant_at_1": True,
                        "conflict": False,
                        "context_faithfulness": True,
                        "over_recall": False,
                        "need_correction": False,
                    },
                }
            ]
            _write_report(
                path_a,
                strategy="A",
                aggregate={
                    "relevant_at_1": 0.7,
                    "conflict_rate": 0.1,
                    "context_faithfulness": 0.8,
                    "over_recall_rate": 0.2,
                    "user_correction_rate": 0.4,
                },
                per_case=common_per_case,
            )
            _write_report(
                path_b,
                strategy="B",
                aggregate={
                    "relevant_at_1": 0.8,
                    "conflict_rate": 0.1,
                    "context_faithfulness": 0.8,
                    "over_recall_rate": 0.2,
                    "user_correction_rate": 0.3,
                },
                per_case=common_per_case,
            )
            _write_report(
                path_c,
                strategy="C",
                aggregate={
                    "relevant_at_1": 0.75,
                    "conflict_rate": 0.1,
                    "context_faithfulness": 0.8,
                    "over_recall_rate": 0.2,
                    "user_correction_rate": 0.35,
                },
                per_case=common_per_case,
            )

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                rc = main(
                    [
                        "mvp",
                        "eval-memory-compare",
                        "--report-a",
                        str(path_a),
                        "--report-b",
                        str(path_b),
                        "--report-c",
                        str(path_c),
                        "--baseline-strategy",
                        "A",
                        "--out",
                        str(out),
                    ]
                )
            self.assertEqual(rc, 0)
            out_obj = json.loads(stdout.getvalue().strip().splitlines()[-1])
            self.assertTrue(out_obj["ok"])
            self.assertIsNone(out_obj["error_code"])
            self.assertEqual(out_obj["comparison"]["winner_strategy"], "B")
            self.assertTrue(out.exists())


if __name__ == "__main__":  # pragma: no cover
    unittest.main(verbosity=2)
