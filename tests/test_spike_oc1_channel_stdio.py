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
from agentos_next.llm.backend import LocalMockLLMBackend


class TestSpikeOC1ChannelStdio(unittest.TestCase):
    def test_channel_stdio_one_turn_writes_trace(self) -> None:
        root = Path(__file__).resolve().parents[1]
        skill_ref = root / "examples" / "skills" / "personal_assistant_brief"
        keys_dir = root / "examples" / "keys"

        with tempfile.TemporaryDirectory() as td:
            data_dir = Path(td)
            trace_id = "tr_oc1_test"

            stdin = io.StringIO("hello\n")
            stdout = io.StringIO()
            with patch("sys.stdin", stdin), redirect_stdout(stdout):
                rc = main(
                    [
                        "mvp",
                        "channel-stdio",
                        "--skill-ref",
                        str(skill_ref),
                        "--keys-dir",
                        str(keys_dir),
                        "--data-dir",
                        str(data_dir),
                        "--trace-id",
                        trace_id,
                        "--max-turns",
                        "1",
                    ]
                )

            self.assertEqual(rc, 0)

            lines = [ln for ln in stdout.getvalue().splitlines() if ln.strip()]
            self.assertEqual(len(lines), 1, f"expected exactly 1 output line, got: {lines!r}")
            obj = json.loads(lines[0])
            self.assertIsInstance(obj, dict)
            self.assertTrue(obj.get("ok"))
            self.assertEqual(obj.get("trace_id"), trace_id)

            trace_path = data_dir / "traces" / f"{trace_id}.jsonl"
            self.assertTrue(trace_path.exists(), f"missing trace file: {trace_path}")

    def test_channel_stdio_model_override_is_passed_to_backend(self) -> None:
        root = Path(__file__).resolve().parents[1]
        skill_ref = root / "examples" / "skills" / "personal_assistant_brief"
        keys_dir = root / "examples" / "keys"

        seen: dict[str, str | None] = {}
        orig = LocalMockLLMBackend.complete_json

        def wrapped(
            self: LocalMockLLMBackend,
            *,
            prompt: str,
            json_schema: dict,
            safety,
            model_id: str | None = None,
        ):
            seen["model_id"] = model_id
            return orig(self, prompt=prompt, json_schema=json_schema, safety=safety, model_id=model_id)

        with tempfile.TemporaryDirectory() as td:
            data_dir = Path(td)
            stdin = io.StringIO("hello\n")
            stdout = io.StringIO()
            with patch.object(LocalMockLLMBackend, "complete_json", wrapped), patch(
                "sys.stdin", stdin
            ), redirect_stdout(stdout):
                rc = main(
                    [
                        "mvp",
                        "channel-stdio",
                        "--skill-ref",
                        str(skill_ref),
                        "--keys-dir",
                        str(keys_dir),
                        "--data-dir",
                        str(data_dir),
                        "--model",
                        "override_model_id",
                        "--max-turns",
                        "1",
                    ]
                )

            self.assertEqual(rc, 0)
            self.assertEqual(seen.get("model_id"), "override_model_id")


if __name__ == "__main__":  # pragma: no cover
    unittest.main(verbosity=2)
