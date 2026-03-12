from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class SkillContract:
    """Skill contract skeleton.

    This is intentionally minimal. The spec is the source of truth:
    - docs/specs/SKILL_CONTRACT.md
    """

    name: str
    version: str
    description: str
    inputs_schema: Dict[str, Any]
    outputs_schema: Dict[str, Any]
    logic: str
    execution_targets: List[str] = field(default_factory=lambda: ["auto"])
    data_requirements: Dict[str, Any] = field(default_factory=dict)
    network_egress: Dict[str, Any] = field(default_factory=dict)
    requires_secrets: bool = False
    risk_level: str = "medium"
    tests: List[Dict[str, Any]] = field(default_factory=list)
    acceptance_rules: Dict[str, Any] = field(default_factory=dict)
    execution_profile: Dict[str, Any] = field(default_factory=dict)


def load_contract_from_dict(data: Dict[str, Any]) -> SkillContract:
    required = ["name", "version", "description", "inputs_schema", "outputs_schema", "logic"]
    missing = [k for k in required if k not in data]
    if missing:
        raise ValueError(f"missing required fields: {missing}")
    return SkillContract(
        name=str(data["name"]),
        version=str(data["version"]),
        description=str(data["description"]),
        inputs_schema=dict(data["inputs_schema"]),
        outputs_schema=dict(data["outputs_schema"]),
        logic=str(data["logic"]),
        execution_targets=list(data.get("execution_targets", ["auto"])),
        data_requirements=dict(data.get("data_requirements", {})),
        network_egress=dict(data.get("network_egress", {})),
        requires_secrets=bool(data.get("requires_secrets", False)),
        risk_level=str(data.get("risk_level", "medium")),
        tests=list(data.get("tests", [])),
        acceptance_rules=dict(data.get("acceptance_rules", {})),
        execution_profile=dict(data.get("execution_profile", {})),
    )


def load_contract(path: str) -> SkillContract:
    # YAML is an optional dependency to keep the skeleton lightweight.
    #
    # For tests and early prototypes, we allow `.skill` files to be JSON (YAML 1.2 is a superset of JSON),
    # so a JSON-only contract can be loaded without PyYAML installed.
    text = Path(path).read_text(encoding="utf-8")
    data: Any
    try:
        import yaml  # type: ignore
    except Exception:
        try:
            data = json.loads(text)
        except Exception as e:  # pragma: no cover
            raise RuntimeError(
                "PyYAML is required to load YAML .skill files (or use JSON-only .skill). "
                "Install extra: agentos-next[yaml]"
            ) from e
    else:
        data = yaml.safe_load(text)
    if not isinstance(data, dict):
        raise ValueError("skill contract must parse to an object")
    return load_contract_from_dict(data)
