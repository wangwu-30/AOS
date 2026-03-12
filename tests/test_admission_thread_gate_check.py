from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import bootstrap  # noqa: F401

from agentos_next.tools.thread_gate_check import run


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _minimal_input_md(*, ok: bool, name: str = "x", confidence: str = "high") -> str:
    if ok:
        return "\n".join(
            [
                "id: `t-001`",
                "author: `tester`",
                "topic: `t`",
                "position:",
                f"- {name}",
                "evidence:",
                "- `docs/specs/EXPERT_COLLAB_PROTOCOL.md`",
                "tradeoffs:",
                "- ok",
                "open_questions:",
                "- none",
                "proposal:",
                "- do",
                "acceptance:",
                "- pass",
                f"confidence: `{confidence}`",
                "",
            ]
        )
    # Missing fields and invalid confidence.
    return "id: `t-001`\nconfidence: `nope`\n"


def _minimal_thread_md(*, thread_id: str, status: str, input_paths: list[str]) -> str:
    links = "\n".join([f"- `{p}`" for p in input_paths])
    return "\n".join(
        [
            f"# Thread {thread_id}",
            "",
            f"- `thread_id`: `{thread_id}`",
            f"- `status`: `{status}`",
            "- `updated_at`: `2026-02-25`",
            "- `owner`: `human + codex`",
            "",
            "## Evidence (Links)",
            "",
            links,
            "",
        ]
    )


def _minimal_decisions_md(*, thread_id: str, tokens: bool = True, needs_decision: bool = False, gate_ok: bool = True) -> str:
    parts = [
        f"# DECISIONS {thread_id}",
        "",
        f"- `thread_id`: `{thread_id}`",
        "- `status`: `accepted`",
        "",
    ]
    if needs_decision:
        parts.append("needs_decision")
        parts.append("")
    if gate_ok and needs_decision:
        parts.append("bounded spike")
        parts.append("kill criteria")
        parts.append("PYTHONPATH=src python3 -m unittest discover -s tests -v")
        parts.append("")
    if tokens:
        parts.append("top_level_api_stable")
        parts.append("fail_closed")
        parts.append("replay_mode_no_side_effects")
        parts.append("")
    return "\n".join(parts)


class TestAdmissionThreadGateCheck(unittest.TestCase):
    def test_thread_gate_check_outputs_stable_json_schema(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            journal = root / "docs" / "journal"

            _write(root / "docs" / "specs" / "EXPERT_COLLAB_PROTOCOL.md", "# proto\n")
            _write(root / "docs" / "journal" / "inputs" / "INPUT_demo_round2_cross_review.md", _minimal_input_md(ok=True))

            thread_id = "20260225-DEMO-001"
            tfile = journal / "2026-02-25-expert-collab-thread-001.md"
            _write(
                tfile,
                _minimal_thread_md(
                    thread_id=thread_id,
                    status="round_4_completed",
                    input_paths=["docs/journal/inputs/INPUT_demo_round2_cross_review.md"],
                ),
            )
            _write(journal / f"SYNTHESIS_{thread_id}.md", "# synth\n")
            _write(journal / f"DECISIONS_{thread_id}.md", _minimal_decisions_md(thread_id=thread_id))

            code, out = run(["--journal-dir", str(journal)])
            self.assertEqual(code, 0, json.dumps(out, ensure_ascii=False, sort_keys=True))
            self.assertEqual(out.get("schema_version"), "1.0.0")
            self.assertIn("ok", out)
            self.assertIn("summary", out)
            self.assertIn("results", out)
            self.assertIsInstance(out["results"], list)

    def test_thread_gate_cross_review_naming_must(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            journal = root / "docs" / "journal"

            _write(root / "docs" / "specs" / "EXPERT_COLLAB_PROTOCOL.md", "# proto\n")
            _write(root / "docs" / "journal" / "inputs" / "INPUT_demo.md", _minimal_input_md(ok=True))

            thread_id = "20260225-DEMO-002"
            _write(
                journal / "2026-02-25-expert-collab-thread-001.md",
                _minimal_thread_md(
                    thread_id=thread_id,
                    status="round_4_completed",
                    input_paths=["docs/journal/inputs/INPUT_demo.md"],
                ),
            )
            _write(journal / f"SYNTHESIS_{thread_id}.md", "# synth\n")
            _write(journal / f"DECISIONS_{thread_id}.md", _minimal_decisions_md(thread_id=thread_id))

            code, out = run(["--journal-dir", str(journal)])
            self.assertEqual(code, 2)
            self.assertFalse(out.get("ok"))
            # Ensure the error code is surfaced somewhere in per-thread errors.
            errors = json.dumps(out, ensure_ascii=False, sort_keys=True)
            self.assertIn("E_CROSS_REVIEW_MISSING", errors)

    def test_thread_gate_needs_decision_triggers_evidence_gate(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            journal = root / "docs" / "journal"

            _write(root / "docs" / "specs" / "EXPERT_COLLAB_PROTOCOL.md", "# proto\n")
            _write(root / "docs" / "journal" / "inputs" / "INPUT_demo_round2_cross_review.md", _minimal_input_md(ok=True))

            thread_id = "20260225-DEMO-003"
            _write(
                journal / "2026-02-25-expert-collab-thread-001.md",
                _minimal_thread_md(
                    thread_id=thread_id,
                    status="round_4_completed",
                    input_paths=["docs/journal/inputs/INPUT_demo_round2_cross_review.md"],
                ),
            )
            _write(journal / f"SYNTHESIS_{thread_id}.md", "# synth\n")
            # needs_decision but missing bounded spike / kill criteria / command.
            _write(journal / f"DECISIONS_{thread_id}.md", _minimal_decisions_md(thread_id=thread_id, needs_decision=True, gate_ok=False))

            code, out = run(["--journal-dir", str(journal)])
            self.assertEqual(code, 2)
            self.assertIn("E_BOUNDED_SPIKE_REQUIRED", json.dumps(out, ensure_ascii=False, sort_keys=True))

    def test_thread_gate_tokens_required(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            journal = root / "docs" / "journal"

            _write(root / "docs" / "specs" / "EXPERT_COLLAB_PROTOCOL.md", "# proto\n")
            _write(root / "docs" / "journal" / "inputs" / "INPUT_demo_round2_cross_review.md", _minimal_input_md(ok=True))

            thread_id = "20260225-DEMO-004"
            _write(
                journal / "2026-02-25-expert-collab-thread-001.md",
                _minimal_thread_md(
                    thread_id=thread_id,
                    status="round_4_completed",
                    input_paths=["docs/journal/inputs/INPUT_demo_round2_cross_review.md"],
                ),
            )
            _write(journal / f"SYNTHESIS_{thread_id}.md", "# synth\n")
            _write(journal / f"DECISIONS_{thread_id}.md", _minimal_decisions_md(thread_id=thread_id, tokens=False))

            code, out = run(["--journal-dir", str(journal)])
            self.assertEqual(code, 2)
            self.assertIn("E_NONNEGOTIABLES_MISSING", json.dumps(out, ensure_ascii=False, sort_keys=True))

    def test_thread_gate_tool_error_exit_code_3(self) -> None:
        code, out = run(["--journal-dir", "does-not-exist"])
        self.assertEqual(code, 3)
        self.assertIn("E_TOOL_ERROR", json.dumps(out, ensure_ascii=False, sort_keys=True))

    def test_repo_docs_journal_passes_thread_gate_check(self) -> None:
        root = Path(__file__).resolve().parents[1]
        journal = root / "docs" / "journal"
        code, out = run(["--journal-dir", str(journal)])
        self.assertEqual(code, 0, json.dumps(out, ensure_ascii=False, sort_keys=True))
        self.assertTrue(out.get("ok"))
