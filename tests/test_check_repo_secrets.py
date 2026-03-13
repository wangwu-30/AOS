from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import bootstrap  # noqa: F401

from agentos_next.tools.check_repo_secrets import scan_repo


class TestCheckRepoSecrets(unittest.TestCase):
    def test_detects_tracked_env_file(self) -> None:
        with TemporaryDirectory(prefix="agentos_next_secret_scan_") as td:
            root = Path(td)
            (root / ".env").write_text("HELLO=world\n", encoding="utf-8")

            findings = scan_repo(repo_root=root, tracked_files=[".env"])

            self.assertEqual(len(findings), 1)
            self.assertEqual(findings[0].rule_id, "tracked_env_file")
            self.assertEqual(findings[0].path, ".env")

    def test_detects_github_token_without_echoing_secret(self) -> None:
        with TemporaryDirectory(prefix="agentos_next_secret_scan_") as td:
            root = Path(td)
            token = "gho_" + ("A" * 36)
            path = root / "notes.txt"
            path.write_text(f"token={token}\n", encoding="utf-8")

            findings = scan_repo(repo_root=root, tracked_files=["notes.txt"])

            self.assertEqual(len(findings), 1)
            self.assertEqual(findings[0].rule_id, "github_token")
            self.assertEqual(findings[0].line, 1)
            self.assertIsNotNone(findings[0].excerpt)
            self.assertNotIn(token, str(findings[0].excerpt))
            self.assertIn("[REDACTED]", str(findings[0].excerpt))

    def test_allows_redaction_fixture_private_key_sample(self) -> None:
        with TemporaryDirectory(prefix="agentos_next_secret_scan_") as td:
            root = Path(td)
            path = root / "tests" / "test_admission_redaction.py"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("q = '-----BEGIN PRIVATE KEY-----\\nxyz'\n", encoding="utf-8")

            findings = scan_repo(repo_root=root, tracked_files=["tests/test_admission_redaction.py"])

            self.assertEqual(findings, [])


if __name__ == "__main__":  # pragma: no cover
    unittest.main(verbosity=2)
