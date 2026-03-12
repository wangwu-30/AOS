from __future__ import annotations

import unittest
from pathlib import Path

import bootstrap  # noqa: F401


class TestDocsExist(unittest.TestCase):
    def test_glossary_exists(self) -> None:
        root = Path(__file__).resolve().parents[1]
        self.assertTrue((root / "docs" / "glossary.md").exists())


if __name__ == "__main__":  # pragma: no cover
    unittest.main(verbosity=2)
