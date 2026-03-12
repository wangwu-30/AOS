from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

import bootstrap  # noqa: F401

from agentos_next.cli import main


class TestSpikeAL3AssistantLoopStdio(unittest.TestCase):
    def test_assistant_loop_stdio_two_lines_writes_two_outputs_and_trace(self) -> None:
        root = Path(__file__).resolve().parents[1]
        keys_dir = root / "examples" / "keys"

        with tempfile.TemporaryDirectory() as td:
            data_dir = Path(td)
            trace_id = "tr_al3_test"

            stdin = io.StringIO("hello\nworld\n")
            stdout = io.StringIO()
            with patch("sys.stdin", stdin), redirect_stdout(stdout):
                rc = main(
                    [
                        "mvp",
                        "assistant-loop-stdio",
                        "--keys-dir",
                        str(keys_dir),
                        "--data-dir",
                        str(data_dir),
                        "--trace-id",
                        trace_id,
                        "--max-turns",
                        "2",
                        "--replay-mode",
                    ]
                )

            self.assertEqual(rc, 0)

            lines = [ln for ln in stdout.getvalue().splitlines() if ln.strip()]
            self.assertEqual(len(lines), 2, f"expected exactly 2 output lines, got: {lines!r}")

            objs = [json.loads(ln) for ln in lines]
            for obj in objs:
                self.assertIsInstance(obj, dict)
                self.assertEqual(obj.get("trace_id"), trace_id)
                self.assertIn("turn_id", obj)
                self.assertIn("span_id", obj)

            trace_path = data_dir / "traces" / f"{trace_id}.jsonl"
            self.assertTrue(trace_path.exists(), f"missing trace file: {trace_path}")


if __name__ == "__main__":  # pragma: no cover
    unittest.main(verbosity=2)

