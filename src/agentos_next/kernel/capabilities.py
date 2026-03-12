from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional, Sequence


ALLOWED_CAPABILITY_NAMES = {
    "fs_read",
    "fs_write",
    "net_egress",
    "llm_remote",
    "scheduler_write",
    "memory_write",
    "memory_search",
    "memory_compact",
    "memory_delete",
    "registry_write",
    "channel_send",
    "time_read",
    "shell_exec",
    "web_search",
    "web_browse",
    "research_run",
    "assistant_runtime_submit",
}

ALLOWED_SCOPES = {"workspace", "skill", "turn"}


@dataclass(frozen=True)
class CapabilityParseResult:
    ok: bool
    error: Optional[str]
    names: set[str]


def parse_capabilities(policy_context: dict[str, Any]) -> CapabilityParseResult:
    effective_runtime_capabilities = policy_context.get("effective_runtime_capabilities")
    if effective_runtime_capabilities is not None:
        if not isinstance(effective_runtime_capabilities, dict):
            return CapabilityParseResult(
                ok=False,
                error="effective_runtime_capabilities must be an object",
                names=set(),
            )
        effective = effective_runtime_capabilities.get("effective_capabilities")
        if not isinstance(effective, list):
            return CapabilityParseResult(
                ok=False,
                error="effective_runtime_capabilities.effective_capabilities must be a list",
                names=set(),
            )
        names = {str(name).strip() for name in effective if str(name).strip()}
        if "web_browse" in names:
            names.add("web_search")
        return CapabilityParseResult(ok=True, error=None, names=names)

    raw = policy_context.get("capabilities")
    if raw is None:
        return CapabilityParseResult(ok=True, error=None, names=set())
    if not isinstance(raw, list):
        return CapabilityParseResult(ok=False, error="capabilities must be a list", names=set())

    names: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            return CapabilityParseResult(ok=False, error="capabilities items must be objects", names=set())
        name = item.get("name")
        scope = item.get("scope")
        if not isinstance(name, str) or not name.strip():
            return CapabilityParseResult(ok=False, error="capability.name must be non-empty string", names=set())
        if name.strip() not in ALLOWED_CAPABILITY_NAMES:
            return CapabilityParseResult(ok=False, error=f"unknown capability name: {name!r}", names=set())
        if not isinstance(scope, str) or scope.strip() not in ALLOWED_SCOPES:
            return CapabilityParseResult(ok=False, error=f"invalid capability.scope: {scope!r}", names=set())
        constraints = item.get("constraints")
        if constraints is not None and not isinstance(constraints, dict):
            return CapabilityParseResult(ok=False, error="capability.constraints must be object when present", names=set())
        names.add(name.strip())

    # Compatibility: browse privilege subsumes search privilege.
    if "web_browse" in names:
        names.add("web_search")

    return CapabilityParseResult(ok=True, error=None, names=names)


def capability_items_for_policy_context(names: Sequence[str]) -> list[dict[str, Any]]:
    # Convenience helper for callers/tests.
    return [{"name": str(n), "scope": "workspace"} for n in names]
