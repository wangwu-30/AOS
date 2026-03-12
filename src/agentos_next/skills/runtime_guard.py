from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Mapping, Sequence


def _safe_stringify(obj: Any) -> str:
    try:
        return json.dumps(obj if obj is not None else {}, ensure_ascii=False, sort_keys=True)
    except Exception:
        return ""


def _check_required_fields(data: Any, required: Sequence[str]) -> list[str]:
    violations: list[str] = []
    if data is None or not isinstance(data, dict):
        for field in required:
            violations.append(f"missing_required_field:{field}")
        return violations
    for field in required:
        if field not in data:
            violations.append(f"missing_required_field:{field}")
    return violations


def _check_patterns(content: str, patterns: Sequence[str], prefix: str) -> list[str]:
    violations: list[str] = []
    for pattern in patterns:
        try:
            # Support the JS-style inline case-insensitive marker `(?i)` by stripping it and always using IGNORECASE.
            normalized = str(pattern).replace("(?i)", "")
            rx = re.compile(normalized, re.IGNORECASE)
            if rx.search(content) is not None:
                violations.append(f"{prefix}:{pattern}")
        except re.error:
            violations.append(f"invalid_pattern:{pattern}")
    return violations


@dataclass(frozen=True)
class PrecheckResult:
    ok: bool
    violations: tuple[str, ...]


@dataclass(frozen=True)
class PostcheckResult:
    ok: bool
    violations: tuple[str, ...]


def validate_pre_execution(params: Any, rules: Mapping[str, Any] | None = None) -> PrecheckResult:
    r = dict(rules or {})
    required = r.get("required_input_fields") or []
    forbidden = r.get("forbidden_input_patterns") or []

    violations: list[str] = []
    if isinstance(required, list):
        violations.extend(_check_required_fields(params, [str(x) for x in required if isinstance(x, str)]))
    if isinstance(forbidden, list):
        violations.extend(_check_patterns(_safe_stringify(params), [str(x) for x in forbidden], "forbidden_input_pattern"))

    return PrecheckResult(ok=len(violations) == 0, violations=tuple(violations))


def validate_post_execution(
    output: Any,
    runtime_meta: Mapping[str, Any] | None,
    rules: Mapping[str, Any] | None = None,
) -> PostcheckResult:
    r = dict(rules or {})
    required = r.get("required_output_fields") or []
    forbidden = r.get("forbidden_output_patterns") or []

    violations: list[str] = []
    text = _safe_stringify(output)

    if isinstance(required, list):
        violations.extend(_check_required_fields(output, [str(x) for x in required if isinstance(x, str)]))
    if isinstance(forbidden, list):
        violations.extend(_check_patterns(text, [str(x) for x in forbidden], "forbidden_output_pattern"))

    max_latency_ms = r.get("max_latency_ms")
    latency_ms = None
    if runtime_meta and isinstance(runtime_meta, dict):
        latency_ms = runtime_meta.get("latency_ms")
    if isinstance(max_latency_ms, (int, float)) and isinstance(latency_ms, (int, float)):
        if float(latency_ms) > float(max_latency_ms):
            violations.append(f"latency_exceeded:{int(latency_ms)}ms>{int(max_latency_ms)}ms")

    max_output_chars = r.get("max_output_chars")
    if isinstance(max_output_chars, (int, float)):
        if len(text) > int(max_output_chars):
            violations.append(f"output_too_large:{len(text)}>{int(max_output_chars)}")

    if r.get("adversarial_checks") is True:
        adversarial_patterns = [
            "(?i)system\\s*prompt",
            "(?i)ignore\\s+previous\\s+instructions",
            "(?i)developer\\s+message",
            "(?i)BEGIN\\s+PRIVATE\\s+KEY",
            "(?i)sk-[a-z0-9]{10,}",
        ]
        violations.extend(_check_patterns(text, adversarial_patterns, "adversarial_signal"))

    return PostcheckResult(ok=len(violations) == 0, violations=tuple(violations))

