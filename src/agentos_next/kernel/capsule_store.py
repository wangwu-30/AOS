from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional


@dataclass(frozen=True)
class GlobalCapsuleV1:
    schema_version: str
    workspace_id: str
    soul_profile_id: str
    identity_summary: str
    communication_style: tuple[str, ...]


@dataclass(frozen=True)
class ProjectCapsuleV1:
    schema_version: str
    project_id: str
    title: str
    summary: str
    evidence_refs: tuple[str, ...] = ()


def build_global_capsule_v1(
    *,
    workspace_id: str,
    soul_profile: dict[str, Any],
) -> GlobalCapsuleV1:
    defaults = dict(soul_profile.get("communication_defaults") or {})
    style = tuple(str(x).strip() for x in (defaults.get("style") or []) if str(x).strip())
    return GlobalCapsuleV1(
        schema_version="1.0.0",
        workspace_id=str(workspace_id),
        soul_profile_id=str(soul_profile.get("soul_profile_id") or "").strip(),
        identity_summary=str(soul_profile.get("identity_summary") or "").strip(),
        communication_style=style,
    )


def resolve_active_project_v1(
    *,
    query_text: str,
    runtime_snapshot: dict[str, Any] | None,
    memory_context: dict[str, Any] | None,
) -> dict[str, Any]:
    active_project_id = ""
    source = "none"
    snapshot = dict(runtime_snapshot or {})
    if str(snapshot.get("active_project_id") or "").strip():
        active_project_id = str(snapshot.get("active_project_id") or "").strip()
        source = "runtime_snapshot"
    continuity = dict((memory_context or {}).get("l0_continuity") or {})
    if not active_project_id and str(continuity.get("active_project_id") or "").strip():
        active_project_id = str(continuity.get("active_project_id") or "").strip()
        source = "memory_context"
    return {
        "schema_version": "1.0.0",
        "type": "active_project_resolver_v1",
        "active_project_id": active_project_id or None,
        "source": source,
    }


def build_project_capsule_v1(
    *,
    active_project_id: str | None,
    memory_context: dict[str, Any] | None,
) -> Optional[ProjectCapsuleV1]:
    if not str(active_project_id or "").strip():
        return None
    return ProjectCapsuleV1(
        schema_version="1.0.0",
        project_id=str(active_project_id).strip(),
        title=str(active_project_id).strip(),
        summary="",
        evidence_refs=(),
    )
