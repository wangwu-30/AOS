from __future__ import annotations

import unittest

import bootstrap  # noqa: F401

from agentos_next.runtime.local_executor import _as_bool as local_as_bool
from agentos_next.runtime.remote_executor import _as_bool as remote_as_bool


class TestPolicyBoolParsing(unittest.TestCase):
    def test_string_false_is_false(self) -> None:
        self.assertFalse(local_as_bool("false", default=True))
        self.assertFalse(remote_as_bool("false", default=True))

    def test_string_true_is_true(self) -> None:
        self.assertTrue(local_as_bool("true", default=False))
        self.assertTrue(remote_as_bool("true", default=False))

    def test_unknown_string_falls_back_default(self) -> None:
        self.assertTrue(local_as_bool("unknown", default=True))
        self.assertFalse(remote_as_bool("unknown", default=False))


if __name__ == "__main__":  # pragma: no cover
    unittest.main(verbosity=2)
