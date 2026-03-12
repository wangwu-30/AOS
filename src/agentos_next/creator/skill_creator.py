from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

_REQUIRED_COMPILED_FILES = ("intent_snapshot.json", "prompt_bundle.json", "execution_ir.json")


class CreatorError(RuntimeError):
    def __init__(self, *, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class CompiledSkill:
    name: str
    version: str
    description: str
    intent: str
    schema_version: str
    constraints: dict[str, Any]
    skill_ref: str
    compiled_dir: str


def _read_json_object(path: Path) -> dict[str, Any]:
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise CreatorError(
            code="E_CREATOR_SCHEMA_UNSUPPORTED",
            message=f"compiled artifact is not valid JSON: {path}",
        ) from e
    if not isinstance(obj, dict):
        raise CreatorError(
            code="E_CREATOR_SCHEMA_UNSUPPORTED",
            message=f"compiled artifact must be a JSON object: {path}",
        )
    return obj


def _tokenize(text: str) -> list[str]:
    return [t for t in re.findall(r"\w+", text.lower()) if t]


def discover_compiled_skills(registry_root: str | Path) -> list[CompiledSkill]:
    root = Path(registry_root).resolve()
    if not root.exists() or not root.is_dir():
        raise CreatorError(
            code="E_CREATOR_REGISTRY_INVALID",
            message=f"registry root not found: {root}",
        )

    found: list[CompiledSkill] = []
    for compiled_dir in sorted((p for p in root.rglob("compiled") if p.is_dir()), key=lambda p: str(p)):
        missing = [name for name in _REQUIRED_COMPILED_FILES if not (compiled_dir / name).exists()]
        if missing:
            raise CreatorError(
                code="E_CREATOR_SCHEMA_UNSUPPORTED",
                message=f"compiled artifact set incomplete under {compiled_dir}: missing {', '.join(missing)}",
            )

        intent_snapshot = _read_json_object(compiled_dir / "intent_snapshot.json")
        schema_version = intent_snapshot.get("schema_version")
        if not isinstance(schema_version, str) or not schema_version.strip():
            raise CreatorError(
                code="E_CREATOR_SCHEMA_UNSUPPORTED",
                message=f"intent_snapshot missing non-empty schema_version: {compiled_dir}",
            )

        constraints = intent_snapshot.get("constraints") or {}
        if not isinstance(constraints, dict):
            raise CreatorError(
                code="E_CREATOR_SCHEMA_UNSUPPORTED",
                message=f"intent_snapshot.constraints must be an object: {compiled_dir}",
            )

        skill_root = compiled_dir.parent
        name = intent_snapshot.get("name")
        if not isinstance(name, str) or not name.strip():
            name = skill_root.name
        version = intent_snapshot.get("version")
        if not isinstance(version, str) or not version.strip():
            version = "0.0.0"
        description = intent_snapshot.get("description")
        if not isinstance(description, str):
            description = ""
        intent = intent_snapshot.get("intent")
        if not isinstance(intent, str) or not intent.strip():
            intent = description

        found.append(
            CompiledSkill(
                name=name.strip(),
                version=version.strip(),
                description=description,
                intent=intent,
                schema_version=schema_version.strip(),
                constraints=dict(constraints),
                skill_ref=str(skill_root),
                compiled_dir=str(compiled_dir),
            )
        )

    return sorted(found, key=lambda item: (item.name.lower(), item.version, item.skill_ref))


def compose_plan(
    *,
    intent: str,
    candidates: list[CompiledSkill],
    workspace_id: str,
    deadline_ms: int,
    max_steps: int,
    model_id_override: Optional[str],
) -> dict[str, Any]:
    q = (intent or "").strip()
    if not q:
        raise CreatorError(code="E_CREATOR_COMPOSE_INVALID", message="intent must be non-empty")
    if max_steps <= 0:
        raise CreatorError(code="E_CREATOR_COMPOSE_INVALID", message="max_steps must be > 0")
    if int(deadline_ms) <= 0:
        raise CreatorError(code="E_CREATOR_COMPOSE_INVALID", message="deadline_ms must be > 0")
    if not candidates:
        raise CreatorError(code="E_CREATOR_COMPOSE_INVALID", message="no compiled skills discovered")

    tokens = _tokenize(q)

    def _match(skill: CompiledSkill) -> tuple[int, list[str]]:
        haystack = f"{skill.name} {skill.description} {skill.intent}".lower()
        matched = [t for t in tokens if t in haystack]
        return len(matched), sorted(set(matched))

    ranked = sorted(
        candidates,
        key=lambda skill: (
            -_match(skill)[0],
            skill.name.lower(),
            skill.version,
            skill.skill_ref,
        ),
    )

    steps: list[dict[str, Any]] = []
    for idx, skill in enumerate(ranked[:max_steps], start=1):
        score, matched_tokens = _match(skill)
        policy_context: dict[str, Any] = {}
        if model_id_override is not None:
            # Align with MR1: use policy_context["model"] for model override.
            policy_context["model"] = str(model_id_override)
        steps.append(
            {
                "step_id": f"step_{idx:02d}",
                "skill_name": skill.name,
                "skill_version": skill.version,
                "reason": {"score": score, "matched_tokens": matched_tokens},
                "execute_request": {
                    "workspace_id": workspace_id,
                    "skill_ref": skill.skill_ref,
                    "input": {"request": q},
                    "idempotency_key": f"creator_step_{idx:02d}",
                    "deadline_ms": int(deadline_ms),
                    "trace": {
                        "trace_id": "REQUIRED_AT_RUNTIME",
                        "turn_id": "REQUIRED_AT_RUNTIME",
                        "span_id": f"creator_step_{idx:02d}",
                        "parent_span_id": None,
                    },
                    "policy_context": policy_context,
                },
            }
        )

    return {
        "schema_version": "1.0.0",
        "mode": "plan_only",
        "intent": q,
        "candidates": [
            {
                "name": c.name,
                "version": c.version,
                "skill_ref": c.skill_ref,
                "schema_version": c.schema_version,
                "compiled_dir": c.compiled_dir,
                "constraints": c.constraints,
            }
            for c in ranked
        ],
        "steps": steps,
    }


def build_creator_plan(
    *,
    registry_root: str | Path,
    intent: str,
    workspace_id: str = "local",
    deadline_ms: int = 60000,
    max_steps: int = 3,
    model_id_override: Optional[str] = None,
) -> dict[str, Any]:
    candidates = discover_compiled_skills(registry_root)
    return compose_plan(
        intent=intent,
        candidates=candidates,
        workspace_id=workspace_id,
        deadline_ms=int(deadline_ms),
        max_steps=int(max_steps),
        model_id_override=model_id_override,
    )
