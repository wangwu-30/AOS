from __future__ import annotations

import unittest

import bootstrap  # noqa: F401

from agentos_next.skills.jsonschema_subset import (
    SchemaUnsupportedError,
    ValidationError,
    assert_supported_schema,
    validate_instance,
)


class TestJsonSchemaSubset(unittest.TestCase):
    def test_object_required_and_types(self) -> None:
        schema = {
            "type": "object",
            "properties": {"q": {"type": "string"}, "n": {"type": "integer", "minimum": 0}},
            "required": ["q", "n"],
            "additionalProperties": False,
        }
        validate_instance({"q": "hi", "n": 0}, schema)
        with self.assertRaises(ValidationError):
            validate_instance({"q": "hi"}, schema)
        with self.assertRaises(ValidationError):
            validate_instance({"q": "hi", "n": -1}, schema)
        with self.assertRaises(ValidationError):
            validate_instance({"q": "hi", "n": 1, "x": 1}, schema)

    def test_enum_and_pattern(self) -> None:
        schema = {"type": "string", "enum": ["a", "b"], "pattern": "^[ab]$"}
        validate_instance("a", schema)
        with self.assertRaises(ValidationError):
            validate_instance("c", schema)

    def test_rejects_ref(self) -> None:
        with self.assertRaises(SchemaUnsupportedError):
            assert_supported_schema({"$ref": "#/defs/x"})


if __name__ == "__main__":  # pragma: no cover
    unittest.main(verbosity=2)

