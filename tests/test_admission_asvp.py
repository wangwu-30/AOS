from __future__ import annotations

import unittest
from pathlib import Path

import bootstrap  # noqa: F401

from agentos_next.protocol.asvp.verify import verify_skill_dir


class TestAdmissionASVP(unittest.TestCase):
    def test_verify_example_skill_package_must_pass(self) -> None:
        root = Path(__file__).resolve().parents[1]
        skill_dir = root / "examples" / "skills" / "personal_assistant_brief"
        keys_dir = root / "examples" / "keys"

        self.assertTrue((skill_dir / "manifest.json").exists(), msg="missing examples manifest.json")
        self.assertTrue((skill_dir / "signature.sig").exists(), msg="missing examples signature.sig")

        # Admission requirement: ASVP verify MUST pass for the example package.
        verify_skill_dir(skill_dir=skill_dir, public_keys_dir=keys_dir)


if __name__ == "__main__":  # pragma: no cover
    unittest.main(verbosity=2)

