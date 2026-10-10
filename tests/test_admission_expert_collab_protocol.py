from __future__ import annotations

import re
import unittest
from pathlib import Path

import bootstrap  # noqa: F401

REQUIRED_MESSAGE_CONTRACT_FIELDS = {
    "id",
    "author",
    "topic",
    "position",
    "evidence",
    "tradeoffs",
    "open_questions",
    "proposal",
    "acceptance",
    "confidence",
}


def _parse_top_level_fields(md_text: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for raw_line in md_text.splitlines():
        line = raw_line.rstrip("\n")
        m = re.match(r"^([a-z_]+):\s*(.*)$", line)
        if not m:
            continue
        key = m.group(1)
        value = m.group(2).strip()
        fields[key] = value
    return fields


def _unwrap_md_value(value: str) -> str:
    # Most journal inputs encode scalars as `value` in backticks.
    s = value.strip()
    if len(s) >= 2 and s[0] == "`" and s[-1] == "`":
        s = s[1:-1].strip()
    if len(s) >= 2 and s[0] == '"' and s[-1] == '"':
        s = s[1:-1].strip()
    return s


class TestAdmissionExpertCollabProtocol(unittest.TestCase):
    def test_expert_collab_protocol_admission(self) -> None:
        root = Path(__file__).resolve().parents[1]

        protocol = root / "docs" / "specs" / "EXPERT_COLLAB_PROTOCOL.md"
        self.assertTrue(protocol.exists(), f"missing protocol doc: {protocol}")

        journal_dir = root / "docs" / "journal"
        self.assertTrue(journal_dir.exists(), f"missing journal dir: {journal_dir}")

        thread_files = sorted(journal_dir.glob("*-expert-collab-thread-*.md"))
        self.assertTrue(thread_files, "missing expert-collab thread file(s)")

        # Validate each thread file has required metadata keys, and has corresponding SYNTHESIS/DECISIONS files.
        for tf in thread_files:
            thread_text = tf.read_text(encoding="utf-8")
            for k in ("thread_id", "status", "updated_at", "owner"):
                self.assertRegex(
                    thread_text,
                    rf"(?m)^\s*-\s*`{re.escape(k)}`\s*:\s*`[^`]+`\s*$",
                    f"thread file missing `{k}`: {tf}",
                )

            m_thread_id = re.search(r"^\s*-\s*`thread_id`\s*:\s*`([^`]+)`\s*$", thread_text, re.M)
            self.assertIsNotNone(m_thread_id, f"thread_id not found in: {tf}")
            thread_id = m_thread_id.group(1)

            synthesis = journal_dir / f"SYNTHESIS_{thread_id}.md"
            decisions = journal_dir / f"DECISIONS_{thread_id}.md"
            self.assertTrue(synthesis.exists(), f"missing synthesis file: {synthesis}")
            self.assertTrue(decisions.exists(), f"missing decisions file: {decisions}")

        inputs_dir = journal_dir / "inputs"
        self.assertTrue(inputs_dir.exists(), f"missing inputs dir: {inputs_dir}")

        input_files = sorted(inputs_dir.glob("INPUT_*.md"))
        self.assertTrue(input_files, "missing input file(s): docs/journal/inputs/INPUT_*.md")

        # Admission requirement: at least one expert input satisfies Message Contract + confidence domain.
        any_valid = False
        violations: list[str] = []
        for p in input_files:
            text = p.read_text(encoding="utf-8")
            fields = _parse_top_level_fields(text)
            missing = sorted(REQUIRED_MESSAGE_CONTRACT_FIELDS - set(fields.keys()))
            if missing:
                violations.append(f"{p}: missing fields: {missing}")
                continue

            conf = _unwrap_md_value(fields.get("confidence", ""))
            if conf not in {"low", "medium", "high"}:
                violations.append(f"{p}: invalid confidence: {conf!r}")
                continue

            any_valid = True
            break

        self.assertTrue(any_valid, "no valid INPUT_*.md found; violations:\n- " + "\n- ".join(violations))


if __name__ == "__main__":  # pragma: no cover
    unittest.main(verbosity=2)
