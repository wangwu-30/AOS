from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping, Sequence


class SchemaError(ValueError):
    pass


class SchemaUnsupportedError(SchemaError):
    pass


@dataclass(frozen=True)
class ValidationError(ValueError):
    message: str
    path: str = "$"

    def __str__(self) -> str:  # pragma: no cover (tiny)
        return f"{self.path}: {self.message}"


_UNSUPPORTED_KEYS = {
    "$ref",
    "$defs",
    "definitions",
    "oneOf",
    "anyOf",
    "allOf",
    "not",
    "if",
    "then",
    "else",
    "dependentRequired",
    "dependentSchemas",
    "patternProperties",
    "propertyNames",
    "unevaluatedProperties",
    "contains",
    "contentMediaType",
    "contentEncoding",
}

_IGNORE_KEYS = {
    "title",
    "description",
    "default",
    "examples",
}


def assert_supported_schema(schema: Any, *, path: str = "$") -> None:
    """Reject JSON Schema features outside a small supported subset.

    This is NOT a full meta-schema validator. It's a guardrail to keep runtime validation
    predictable and stdlib-only.
    """

    if schema is True or schema is False:
        raise SchemaUnsupportedError(f"{path}: boolean schemas are not supported")
    if schema is None or not isinstance(schema, dict):
        raise SchemaError(f"{path}: schema must be an object")

    for k in schema.keys():
        if k in _IGNORE_KEYS:
            continue
        if k in _UNSUPPORTED_KEYS:
            raise SchemaUnsupportedError(f"{path}: unsupported keyword: {k}")

    t = schema.get("type")
    if t is not None:
        if isinstance(t, str):
            _assert_supported_type(t, path=path)
        elif isinstance(t, list) and all(isinstance(x, str) for x in t):
            for x in t:
                _assert_supported_type(x, path=path)
        else:
            raise SchemaError(f"{path}: `type` must be a string or list of strings")

    props = schema.get("properties")
    if props is not None:
        if not isinstance(props, dict):
            raise SchemaError(f"{path}: `properties` must be an object")
        for name, sub in props.items():
            if not isinstance(name, str):
                raise SchemaError(f"{path}: `properties` keys must be strings")
            assert_supported_schema(sub, path=f"{path}.properties.{name}")

    req = schema.get("required")
    if req is not None:
        if not (isinstance(req, list) and all(isinstance(x, str) for x in req)):
            raise SchemaError(f"{path}: `required` must be a list of strings")

    ap = schema.get("additionalProperties")
    if ap is not None and not isinstance(ap, (bool, dict)):
        raise SchemaError(f"{path}: `additionalProperties` must be a boolean or schema object")
    if isinstance(ap, dict):
        assert_supported_schema(ap, path=f"{path}.additionalProperties")

    items = schema.get("items")
    if items is not None:
        if not isinstance(items, dict):
            raise SchemaError(f"{path}: `items` must be a schema object")
        assert_supported_schema(items, path=f"{path}.items")

    enum = schema.get("enum")
    if enum is not None and not isinstance(enum, list):
        raise SchemaError(f"{path}: `enum` must be a list")

    # Simple scalar constraints. We only validate types here; semantics are enforced in validate_instance.
    for k in ("minimum", "maximum"):
        v = schema.get(k)
        if v is not None and not isinstance(v, (int, float)):
            raise SchemaError(f"{path}: `{k}` must be a number")

    for k in ("minLength", "maxLength", "minItems", "maxItems"):
        v = schema.get(k)
        if v is not None and not (isinstance(v, int) and v >= 0):
            raise SchemaError(f"{path}: `{k}` must be a non-negative integer")

    pat = schema.get("pattern")
    if pat is not None and not isinstance(pat, str):
        raise SchemaError(f"{path}: `pattern` must be a string")
    if isinstance(pat, str):
        try:
            re.compile(pat)
        except re.error as e:
            raise SchemaError(f"{path}: invalid regex pattern") from e


def validate_instance(instance: Any, schema: Mapping[str, Any], *, path: str = "$") -> None:
    """Validate an instance against a small JSON Schema subset.

    Raises ValidationError on mismatch.
    """

    assert_supported_schema(dict(schema), path=path)

    # Empty schema: accept anything.
    if not schema:
        return

    if "const" in schema and instance != schema["const"]:
        raise ValidationError("must equal const", path=path)

    if "enum" in schema:
        enum = schema["enum"]
        if isinstance(enum, list) and instance not in enum:
            raise ValidationError("must be one of enum values", path=path)

    typ = schema.get("type")
    if typ is not None:
        if isinstance(typ, str):
            _validate_type(instance, typ, schema, path=path)
        else:
            # list union type
            ok = False
            last_err: ValidationError | None = None
            for t in typ:
                try:
                    _validate_type(instance, t, schema, path=path)
                except ValidationError as e:
                    last_err = e
                else:
                    ok = True
                    break
            if not ok:
                raise last_err or ValidationError("type mismatch", path=path)
        return

    # If no `type`, validate nested keywords when present.
    if "properties" in schema or "required" in schema or "additionalProperties" in schema:
        _validate_type(instance, "object", schema, path=path)
    if "items" in schema or "minItems" in schema or "maxItems" in schema:
        _validate_type(instance, "array", schema, path=path)
    if any(k in schema for k in ("minLength", "maxLength", "pattern")):
        _validate_type(instance, "string", schema, path=path)
    if any(k in schema for k in ("minimum", "maximum")):
        _validate_type(instance, "number", schema, path=path)


def _assert_supported_type(t: str, *, path: str) -> None:
    if t not in {"object", "array", "string", "number", "integer", "boolean", "null"}:
        raise SchemaUnsupportedError(f"{path}: unsupported type: {t}")


def _validate_type(instance: Any, t: str, schema: Mapping[str, Any], *, path: str) -> None:
    if t == "null":
        if instance is not None:
            raise ValidationError("must be null", path=path)
        return
    if t == "boolean":
        if not isinstance(instance, bool):
            raise ValidationError("must be boolean", path=path)
        return
    if t == "integer":
        if not (isinstance(instance, int) and not isinstance(instance, bool)):
            raise ValidationError("must be integer", path=path)
        _validate_number_bounds(float(instance), schema, path=path)
        return
    if t == "number":
        if not (isinstance(instance, (int, float)) and not isinstance(instance, bool)):
            raise ValidationError("must be number", path=path)
        _validate_number_bounds(float(instance), schema, path=path)
        return
    if t == "string":
        if not isinstance(instance, str):
            raise ValidationError("must be string", path=path)
        mn = schema.get("minLength")
        mx = schema.get("maxLength")
        if isinstance(mn, int) and len(instance) < mn:
            raise ValidationError("string shorter than minLength", path=path)
        if isinstance(mx, int) and len(instance) > mx:
            raise ValidationError("string longer than maxLength", path=path)
        pat = schema.get("pattern")
        if isinstance(pat, str) and re.search(pat, instance) is None:
            raise ValidationError("string does not match pattern", path=path)
        return
    if t == "array":
        if not isinstance(instance, list):
            raise ValidationError("must be array", path=path)
        mn = schema.get("minItems")
        mx = schema.get("maxItems")
        if isinstance(mn, int) and len(instance) < mn:
            raise ValidationError("array shorter than minItems", path=path)
        if isinstance(mx, int) and len(instance) > mx:
            raise ValidationError("array longer than maxItems", path=path)
        items = schema.get("items")
        if isinstance(items, dict):
            for i, v in enumerate(instance):
                validate_instance(v, items, path=f"{path}[{i}]")
        return
    if t == "object":
        if not isinstance(instance, dict):
            raise ValidationError("must be object", path=path)
        props = schema.get("properties") or {}
        req = schema.get("required") or []
        if isinstance(req, Sequence):
            for k in req:
                if isinstance(k, str) and k not in instance:
                    raise ValidationError(f"missing required property: {k}", path=path)
        if isinstance(props, dict):
            for k, sub in props.items():
                if k in instance:
                    validate_instance(instance[k], sub, path=f"{path}.{k}")

        ap = schema.get("additionalProperties", True)
        for k in instance.keys():
            if isinstance(props, dict) and k in props:
                continue
            if ap is False:
                raise ValidationError(f"additionalProperties not allowed: {k}", path=path)
            if isinstance(ap, dict):
                validate_instance(instance[k], ap, path=f"{path}.{k}")
        return
    raise ValidationError(f"unsupported type: {t}", path=path)


def _validate_number_bounds(v: float, schema: Mapping[str, Any], *, path: str) -> None:
    mn = schema.get("minimum")
    mx = schema.get("maximum")
    if isinstance(mn, (int, float)) and v < float(mn):
        raise ValidationError("number less than minimum", path=path)
    if isinstance(mx, (int, float)) and v > float(mx):
        raise ValidationError("number greater than maximum", path=path)


def synthesize_instance(schema: Mapping[str, Any]) -> Any:
    """Create a minimal instance that should satisfy the schema subset.

    This is used by the local mock LLM backend to produce deterministic outputs.
    """

    assert_supported_schema(dict(schema))

    if not schema:
        return None

    if "const" in schema:
        return schema["const"]
    if "enum" in schema and isinstance(schema["enum"], list) and schema["enum"]:
        return schema["enum"][0]

    typ = schema.get("type")
    if isinstance(typ, list) and typ:
        # Prefer a non-null type when present to produce more useful instances.
        chosen = next((t for t in typ if t != "null"), typ[0])
        return synthesize_instance({**dict(schema), "type": chosen})

    if typ == "null":
        return None
    if typ == "boolean":
        return False
    if typ == "integer":
        mn = schema.get("minimum")
        return int(mn) if isinstance(mn, (int, float)) else 0
    if typ == "number":
        mn = schema.get("minimum")
        return float(mn) if isinstance(mn, (int, float)) else 0.0
    if typ == "string":
        mn = schema.get("minLength")
        if isinstance(mn, int) and mn > 0:
            return "x" * mn
        return ""
    if typ == "array":
        mn = schema.get("minItems")
        n = int(mn) if isinstance(mn, int) else 0
        items = schema.get("items")
        if isinstance(items, dict):
            return [synthesize_instance(items) for _ in range(n)]
        return []
    if typ == "object" or typ is None:
        props = schema.get("properties") or {}
        req = schema.get("required") or []
        out: dict[str, Any] = {}
        if isinstance(props, dict) and isinstance(req, list):
            for k in req:
                if isinstance(k, str) and k in props and isinstance(props[k], dict):
                    out[k] = synthesize_instance(props[k])
                elif isinstance(k, str):
                    out[k] = None
        return out

    # Unknown type; fail closed.
    raise SchemaUnsupportedError(f"unsupported type for synthesis: {typ}")

