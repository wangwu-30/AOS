from __future__ import annotations

import re
from typing import Any


_REDACT = "[REDACTED]"

_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # HTTP Authorization header
    (re.compile(r"(?i)\bAuthorization:\s*Bearer\s+[A-Za-z0-9._\-~+/]+=*", re.MULTILINE), f"Authorization: Bearer {_REDACT}"),
    # Common env var like values
    (re.compile(r"(?i)OPENAI_[A-Z0-9_]*TOKEN\s*[:=]\s*\S+"), f"OPENAI_*TOKEN={_REDACT}"),
    # PEM private keys
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.DOTALL), _REDACT),
]


def redact_text(text: str) -> str:
    """Redact common sensitive patterns.

    MVP: conservative, best-effort. We prefer false positives over leaking secrets into evidence/trace.
    """

    out = text
    for pat, repl in _PATTERNS:
        out = pat.sub(repl, out)
    return out


def redact_json(value: Any) -> Any:
    """Redact sensitive patterns in JSON-like structures (dict/list/str)."""

    if value is None:
        return None
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, list):
        return [redact_json(v) for v in value]
    if isinstance(value, dict):
        return {k: redact_json(v) for k, v in value.items()}
    return value
