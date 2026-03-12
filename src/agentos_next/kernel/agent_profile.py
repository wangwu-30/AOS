from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any


def _safe_segment(value: str, *, fallback: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return fallback
    if re.fullmatch(r"[A-Za-z0-9._-]{1,200}", raw):
        return raw
    return fallback


def _normalize_axiom_items(items: Any, *, field: str) -> tuple[list[dict[str, Any]] | None, str | None]:
    if not isinstance(items, list) or not items:
        return None, f"{field} must be a non-empty array"
    normalized: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            return None, f"{field} items must be objects"
        ax_id = str(item.get("id") or "").strip()
        statement = str(item.get("statement") or "").strip()
        try:
            priority = int(item.get("priority"))
        except Exception:
            return None, f"{field}.priority must be int"
        if not ax_id or not statement:
            return None, f"{field}.id and {field}.statement are required"
        normalized.append({"id": ax_id, "statement": statement, "priority": priority})
    normalized.sort(key=lambda x: int(x["priority"]))
    return normalized, None


def _normalize_constraints(items: Any) -> tuple[list[dict[str, Any]] | None, str | None]:
    if items is None:
        return [], None
    if not isinstance(items, list) or len(items) > 64:
        return None, "reality_constraints length must be within [0, 64]"
    normalized: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            return None, "reality_constraints items must be objects"
        rc_id = str(item.get("id") or "").strip()
        statement = str(item.get("statement") or "").strip()
        source_ref = str(item.get("source_ref") or "").strip()
        effective_at = str(item.get("effective_at_utc") or "").strip()
        if not rc_id or not statement or not source_ref or not effective_at:
            return None, "reality_constraints.* required fields missing"
        normalized.append(
            {
                "id": rc_id,
                "statement": statement,
                "source_ref": source_ref,
                "effective_at_utc": effective_at,
            }
        )
    return normalized, None


def validate_agent_profile_v2(raw: dict[str, Any] | None) -> tuple[dict[str, Any] | None, str | None]:
    profile = dict(raw or {})
    if str(profile.get("schema_version") or "").strip() != "2.0.0":
        return None, "schema_version must be 2.0.0"
    agent_id = str(profile.get("agent_id") or "").strip()
    soul_profile_id = str(profile.get("soul_profile_id") or "").strip()
    if not agent_id:
        return None, "agent_id is required"
    if not soul_profile_id:
        return None, "soul_profile_id is required"
    execution_axioms, err = _normalize_axiom_items(profile.get("execution_axioms"), field="execution_axioms")
    if execution_axioms is None:
        return None, err
    communication_axioms, err = _normalize_axiom_items(
        profile.get("communication_axioms"), field="communication_axioms"
    )
    if communication_axioms is None:
        return None, err
    constraints, err = _normalize_constraints(profile.get("reality_constraints"))
    if constraints is None:
        return None, err
    resolution = profile.get("operator_resolution") or {}
    if not isinstance(resolution, dict):
        return None, "operator_resolution must be an object"
    policy_defaults = profile.get("policy_defaults") or {}
    if not isinstance(policy_defaults, dict):
        return None, "policy_defaults must be an object"
    normalized = {
        "schema_version": "2.0.0",
        "agent_id": agent_id,
        "soul_profile_id": soul_profile_id,
        "execution_axioms": execution_axioms,
        "communication_axioms": communication_axioms,
        "reality_constraints": constraints,
        "operator_resolution": {
            "policy": str(resolution.get("policy") or "skill_first").strip() or "skill_first",
            "allow_tool_composition": bool(resolution.get("allow_tool_composition", True)),
        },
        "policy_defaults": {
            "interaction_mode_default": (
                str(policy_defaults.get("interaction_mode_default") or "task").strip() or "task"
            ),
            "planner_strategy_default": (
                str(policy_defaults.get("planner_strategy_default") or "model_owned").strip() or "model_owned"
            ),
            "user_override_allowed": bool(policy_defaults.get("user_override_allowed", True)),
        },
    }
    # Thin derived aliases for subsystems not yet migrated.
    normalized["axioms"] = list(execution_axioms)
    normalized["communication_axiom_ids"] = [str(x["id"]) for x in communication_axioms]
    normalized["execution_axiom_ids"] = [str(x["id"]) for x in execution_axioms]
    normalized["active_constraint_ids"] = [str(x["id"]) for x in constraints]
    return normalized, None


def _convert_legacy_profile_v1(raw: dict[str, Any]) -> dict[str, Any]:
    axioms = raw.get("axioms") or []
    communication_axioms = []
    execution_axioms = []
    for item in axioms:
        if not isinstance(item, dict):
            continue
        ax_id = str(item.get("id") or "").strip()
        if ax_id == "AX_COMMUNICATION_SEPARATE":
            communication_axioms.append(item)
        else:
            execution_axioms.append(item)
    if not communication_axioms:
        communication_axioms = [
            {
                "id": "AX_GENUINELY_HELPFUL",
                "statement": "Be genuinely helpful rather than performatively helpful.",
                "priority": 0,
            }
        ]
    return {
        "schema_version": "2.0.0",
        "agent_id": str(raw.get("agent_id") or "assistant_loop").strip() or "assistant_loop",
        "soul_profile_id": str(raw.get("soul_profile_id") or "default_assistant").strip() or "default_assistant",
        "execution_axioms": execution_axioms or communication_axioms,
        "communication_axioms": communication_axioms,
        "reality_constraints": list(raw.get("reality_constraints") or []),
        "operator_resolution": dict(raw.get("operator_resolution") or raw.get("capability_resolution") or {}),
        "policy_defaults": {
            "interaction_mode_default": "task",
            "planner_strategy_default": "model_owned",
            "user_override_allowed": True,
        },
    }


def validate_agent_profile_v1(raw: dict[str, Any] | None) -> tuple[dict[str, Any] | None, str | None]:
    profile = dict(raw or {})
    schema_version = str(profile.get("schema_version") or "").strip()
    if schema_version == "1.0.0":
        profile = _convert_legacy_profile_v1(profile)
    return validate_agent_profile_v2(profile)


def build_default_agent_profile_v1(*, agent_id: str) -> dict[str, Any]:
    store = FileAgentProfileStore(data_dir="data")
    return store.get_or_default(agent_id=agent_id)


class FileAgentProfileStore:
    def __init__(self, data_dir: str | os.PathLike[str] = "data") -> None:
        self._data_dir = Path(data_dir).resolve()
        self._repo_root = Path(__file__).resolve().parents[3]
        self._config_root = self._repo_root / "configs" / "agent_profiles"
        self._override_root = self._data_dir / "agent_profiles"

    def _config_path(self, *, agent_id: str) -> Path:
        return self._config_root / f"{_safe_segment(agent_id, fallback='agent')}.json"

    def _override_path(self, *, agent_id: str) -> Path:
        return self._override_root / f"{_safe_segment(agent_id, fallback='agent')}.json"

    def _read(self, path: Path) -> dict[str, Any] | None:
        if not path.exists():
            return None
        try:
            obj = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
        normalized, err = validate_agent_profile_v1(obj if isinstance(obj, dict) else None)
        if err:
            return None
        return normalized

    def get(self, *, agent_id: str) -> dict[str, Any] | None:
        override = self._read(self._override_path(agent_id=agent_id))
        if override is not None:
            return override
        return self._read(self._config_path(agent_id=agent_id))

    def get_or_default(self, *, agent_id: str) -> dict[str, Any]:
        existing = self.get(agent_id=agent_id)
        if existing is not None:
            return existing
        fallback = self.get(agent_id="assistant_loop")
        if fallback is not None:
            return fallback
        raise ValueError("missing repo default agent profile: assistant_loop")

    def put(self, *, profile: dict[str, Any]) -> None:
        normalized, err = validate_agent_profile_v1(profile)
        if normalized is None:
            raise ValueError(err or "invalid agent profile")
        path = self._override_path(agent_id=str(normalized["agent_id"]))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(normalized, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")


def make_axiom_review_candidate(
    *,
    agent_profile: dict[str, Any],
    context_planes: dict[str, Any],
    threshold_constraints: int = 8,
    threshold_recent_failures: int = 3,
) -> dict[str, Any] | None:
    constraints = agent_profile.get("reality_constraints") or []
    execution_axioms = agent_profile.get("execution_axioms") or agent_profile.get("axioms") or []
    communication_axioms = agent_profile.get("communication_axioms") or []
    retrospective = (context_planes or {}).get("retrospective_plane") or {}
    recent_failures = retrospective.get("recent_failures") or []
    if not isinstance(constraints, list) or not isinstance(recent_failures, list):
        return None
    if not isinstance(execution_axioms, list) or not isinstance(communication_axioms, list):
        return None
    constraint_count = len(constraints)
    recent_failure_count = len(recent_failures)
    if constraint_count < int(threshold_constraints) and recent_failure_count < int(threshold_recent_failures):
        return None
    all_axioms = [*execution_axioms, *communication_axioms]
    axiom_statements = {
        str(item.get("statement") or "").strip().lower()
        for item in all_axioms
        if isinstance(item, dict) and str(item.get("statement") or "").strip()
    }
    constraint_statements = [
        str(item.get("statement") or "").strip().lower()
        for item in constraints
        if isinstance(item, dict) and str(item.get("statement") or "").strip()
    ]
    conflict_count = sum(1 for statement in constraint_statements if statement in axiom_statements)
    pressure_reasons: list[str] = []
    if constraint_count >= int(threshold_constraints):
        pressure_reasons.append("constraint_pressure")
    if recent_failure_count >= int(threshold_recent_failures):
        pressure_reasons.append("failure_pressure")
    if conflict_count > 0:
        pressure_reasons.append("conflict_pressure")
    cost_score = round(
        (
            max(0, constraint_count - int(threshold_constraints))
            + recent_failure_count
            + conflict_count
        )
        / max(1, int(threshold_constraints)),
        3,
    )
    if cost_score >= 1.0:
        pressure_reasons.append("maintenance_cost_pressure")
    if constraint_count >= int(threshold_constraints) and recent_failure_count >= int(threshold_recent_failures):
        pressure_reasons.append("axiom_revision_threshold_reached")
    pressure_score = max(
        float(constraint_count) / max(1, int(threshold_constraints)),
        float(recent_failure_count) / max(1, int(threshold_recent_failures)),
        float(conflict_count),
        float(cost_score),
    )
    return {
        "schema_version": "1.0.0",
        "type": "axiom_review_candidate_v1",
        "agent_id": str(agent_profile.get("agent_id") or ""),
        "meta_axioms": [
            "MAX1_EVERYTHING_IS_REVISABLE",
            "MAX2_CONSTRAINT_PRESSURE_PRECEDES_AXIOM_REVISION",
            "MAX3_PRESERVE_COHERENCE_DURING_REVISION",
        ],
        "pressure": {
            "constraint_count": constraint_count,
            "recent_failure_count": recent_failure_count,
            "conflict_count": conflict_count,
            "threshold_constraints": int(threshold_constraints),
            "threshold_recent_failures": int(threshold_recent_failures),
            "cost_score": cost_score,
            "pressure_score": round(pressure_score, 3),
            "reason_codes": pressure_reasons,
        },
        "reason": "constraint/failure pressure may require axiom revision",
        "active_execution_axiom_ids": [
            str(x.get("id") or "") for x in execution_axioms if isinstance(x, dict)
        ],
        "active_communication_axiom_ids": [
            str(x.get("id") or "") for x in communication_axioms if isinstance(x, dict)
        ],
        "active_constraint_ids": [str(x.get("id") or "") for x in constraints if isinstance(x, dict)],
        "recommended_action": "review axioms against active constraints and repeated failures before adding more runtime patches",
    }
