from __future__ import annotations

import json
from pathlib import Path


def write_json(path: Path, obj: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=True, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def make_minimal_skill_package(pkg_dir: Path) -> None:
    """Create a minimal unsigned skill package accepted by SkillPackageLoader (verify_asvp=False)."""

    pkg_dir.mkdir(parents=True, exist_ok=True)

    inputs_schema = {
        "type": "object",
        "properties": {"q": {"type": "string"}},
        "required": ["q"],
        "additionalProperties": False,
    }
    outputs_schema = {
        "type": "object",
        "properties": {"ok": {"const": True}},
        "required": ["ok"],
        "additionalProperties": False,
    }
    contract = {
        "name": "admission_min_pkg",
        "version": "0.0.0",
        "description": "admission test package",
        "inputs_schema": inputs_schema,
        "outputs_schema": outputs_schema,
        "logic": "Return a JSON object with ok=true.",
        "acceptance_rules": {},
        "execution_profile": {"model_id": "local_mock"},
        "risk_level": "low",
    }

    (pkg_dir / "contract.skill").write_text(
        json.dumps(contract, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    artifacts = pkg_dir / "artifacts"
    write_json(artifacts / "inputs_schema.json", inputs_schema)
    write_json(artifacts / "outputs_schema.json", outputs_schema)
    write_json(artifacts / "acceptance_rules.json", contract["acceptance_rules"])
    write_json(artifacts / "execution_profile.json", contract["execution_profile"])

