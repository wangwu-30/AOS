from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

import bootstrap  # noqa: F401

from agentos_next.cli import main
from agentos_next.evals.memory_effect_eval import load_memory_eval_dataset, run_memory_effect_eval


def _write_dataset(path: Path) -> None:
    cases = [
        {
            "case_id": "case_pref_math",
            "seed_memory": [
                {"item_id": "i_math", "content": "用户偏好: 喜欢数学", "tags": ["profile", "math"]},
                {"item_id": "i_music", "content": "用户偏好: 喜欢音乐", "tags": ["profile", "music"]},
            ],
            "query": "喜欢数学",
            "labels": {
                "relevant_item_ids": ["i_math"],
                "conflict_item_ids": ["i_music"],
                "max_reasonable_hits": 2,
                "expect_correction": False,
            },
            "notes": "明确偏好命中",
            "strategy_hints": {"focus_tags": ["math"], "blacklist_tags": ["music"]},
        },
        {
            "case_id": "case_blacklist_game",
            "seed_memory": [
                {"item_id": "i_block", "content": "黑名单: 不推荐游戏内容", "tags": ["blacklist", "game"]},
                {"item_id": "i_goal", "content": "学习目标: 数学训练计划", "tags": ["goal", "math"]},
                {"item_id": "i_game", "content": "用户兴趣: 游戏开发", "tags": ["interest", "game"]},
            ],
            "query": "游戏",
            "labels": {
                "relevant_item_ids": ["i_game"],
                "conflict_item_ids": ["i_block"],
                "max_reasonable_hits": 1,
            },
            "notes": "冲突样本",
            "strategy_hints": {"blacklist_tags": ["blacklist"], "focus_tags": ["interest"]},
        },
    ]
    path.write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in cases) + "\n", encoding="utf-8")


class TestMemoryEffectEval(unittest.TestCase):
    def test_dataset_loader_validates_contract(self) -> None:
        with tempfile.TemporaryDirectory(prefix="agentos_next_eval_ds_") as td:
            dataset = Path(td) / "dataset.jsonl"
            _write_dataset(dataset)
            rows = load_memory_eval_dataset(dataset)
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0].case_id, "case_pref_math")
            self.assertEqual(rows[1].labels.max_reasonable_hits, 1)

    def test_run_memory_effect_eval_supports_a_b_c(self) -> None:
        with tempfile.TemporaryDirectory(prefix="agentos_next_eval_abc_") as td:
            dataset = Path(td) / "dataset.jsonl"
            _write_dataset(dataset)

            for strategy in ("A", "B", "C"):
                out = Path(td) / f"report_{strategy}.json"
                report = run_memory_effect_eval(dataset_path=dataset, strategy=strategy, out_path=out, seed=7)
                self.assertEqual(report["schema_version"], "1.0.0")
                self.assertEqual(report["strategy"], strategy)
                self.assertTrue(out.exists())
                self.assertEqual(len(report["per_case"]), 2)
                agg = report["aggregate"]
                for k in (
                    "relevant_at_1",
                    "conflict_rate",
                    "context_faithfulness",
                    "over_recall_rate",
                    "user_correction_rate",
                ):
                    self.assertIn(k, agg)
                    self.assertGreaterEqual(float(agg[k]), 0.0)
                    self.assertLessEqual(float(agg[k]), 1.0)

                for row in report["per_case"]:
                    self.assertIn("case_id", row)
                    self.assertIn("metrics", row)
                    self.assertIn("retrieval_trace_ref", row)
                    self.assertTrue(str(row["retrieval_trace_ref"]).startswith("ev_"))

    def test_cli_eval_memory_returns_stable_json(self) -> None:
        with tempfile.TemporaryDirectory(prefix="agentos_next_eval_cli_") as td:
            dataset = Path(td) / "dataset.jsonl"
            report = Path(td) / "report.json"
            _write_dataset(dataset)

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                rc = main(
                    [
                        "mvp",
                        "eval-memory",
                        "--dataset",
                        str(dataset),
                        "--strategy",
                        "A",
                        "--out",
                        str(report),
                        "--seed",
                        "123",
                    ]
                )
            self.assertEqual(rc, 0)
            out = json.loads(stdout.getvalue().strip().splitlines()[-1])
            self.assertTrue(out["ok"])
            self.assertIsNone(out["error_code"])
            self.assertEqual(out["report"]["strategy"], "A")
            self.assertTrue(report.exists())


if __name__ == "__main__":  # pragma: no cover
    unittest.main(verbosity=2)
