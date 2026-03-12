from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Optional

from agentos_next.compiler.skill_contract import SkillContract, load_contract
from agentos_next.protocol.asvp.verify import verify_skill_dir

from .jsonschema_subset import SchemaError, assert_supported_schema


class SkillPackageLoadError(RuntimeError):
    pass


@dataclass(frozen=True)
class SkillArtifacts:
    inputs_schema: Mapping[str, Any]
    outputs_schema: Mapping[str, Any]
    acceptance_rules: Mapping[str, Any]
    execution_profile: Mapping[str, Any]

    artifacts_dir: Path


@dataclass(frozen=True)
class SkillPackage:
    root: Path
    contract: SkillContract
    artifacts: SkillArtifacts


def _read_json_object(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as e:
        raise SkillPackageLoadError(f"missing required artifact: {path.name}") from e
    except json.JSONDecodeError as e:
        raise SkillPackageLoadError(f"invalid JSON in {path.name}") from e
    if not isinstance(data, dict):
        raise SkillPackageLoadError(f"{path.name} must be a JSON object")
    return data


class SkillPackageLoader:
    """Load a skill package directory.

    Enforces:
    - ASVP verification (integrity/authenticity), unless disabled
    - presence of `contract.skill`
    - presence of compiled artifacts (schemas + rules/profile)
    - supported JSON Schema subset for inputs/outputs
    """

    def __init__(
        self,
        *,
        public_keys_dir: Path | None = None,
        verify_asvp: bool = True,
        require_compiled_artifacts: bool = True,
    ) -> None:
        self.public_keys_dir = public_keys_dir
        self.verify_asvp = bool(verify_asvp)
        self.require_compiled_artifacts = bool(require_compiled_artifacts)

    def load(self, skill_dir: str | Path) -> SkillPackage:
        root = Path(skill_dir).resolve()
        if not root.exists() or not root.is_dir():
            raise SkillPackageLoadError(f"skill package dir not found: {root}")

        if self.verify_asvp:
            if self.public_keys_dir is None:
                raise SkillPackageLoadError("public_keys_dir is required when verify_asvp=True")
            try:
                verify_skill_dir(skill_dir=root, public_keys_dir=self.public_keys_dir.resolve())
            except Exception as e:
                raise SkillPackageLoadError(f"ASVP verification failed: {e}") from e

        contract_path = root / "contract.skill"
        if not contract_path.exists():
            raise SkillPackageLoadError("missing contract.skill")
        try:
            contract = load_contract(str(contract_path))
        except Exception as e:
            raise SkillPackageLoadError(f"failed to load contract.skill: {e}") from e

        artifacts = self._load_artifacts(root=root, contract=contract)
        return SkillPackage(root=root, contract=contract, artifacts=artifacts)

    def _load_artifacts(self, *, root: Path, contract: SkillContract) -> SkillArtifacts:
        artifacts_dir = self._pick_artifacts_dir(root=root, contract=contract)
        if artifacts_dir is None:
            if self.require_compiled_artifacts:
                raise SkillPackageLoadError("missing compiled artifacts (expected artifacts/ or dist/<name>/)")
            # Compile artifacts are optional in some early workflows; fall back to contract schemas.
            inputs = dict(contract.inputs_schema)
            outputs = dict(contract.outputs_schema)
            try:
                assert_supported_schema(inputs, path="$.inputs_schema")
                assert_supported_schema(outputs, path="$.outputs_schema")
            except SchemaError as e:
                raise SkillPackageLoadError(f"unsupported schema: {e}") from e
            return SkillArtifacts(
                inputs_schema=inputs,
                outputs_schema=outputs,
                acceptance_rules=dict(contract.acceptance_rules),
                execution_profile=dict(contract.execution_profile),
                artifacts_dir=root,
            )

        inputs = _read_json_object(artifacts_dir / "inputs_schema.json")
        outputs = _read_json_object(artifacts_dir / "outputs_schema.json")
        acceptance = _read_json_object(artifacts_dir / "acceptance_rules.json")
        profile = _read_json_object(artifacts_dir / "execution_profile.json")

        # Enforce that compiled schemas match the contract to avoid TOCTOU drift.
        if dict(contract.inputs_schema) != inputs:
            raise SkillPackageLoadError("inputs_schema.json does not match contract.inputs_schema")
        if dict(contract.outputs_schema) != outputs:
            raise SkillPackageLoadError("outputs_schema.json does not match contract.outputs_schema")

        try:
            assert_supported_schema(inputs, path="$.inputs_schema")
            assert_supported_schema(outputs, path="$.outputs_schema")
        except SchemaError as e:
            raise SkillPackageLoadError(f"unsupported schema: {e}") from e

        return SkillArtifacts(
            inputs_schema=inputs,
            outputs_schema=outputs,
            acceptance_rules=acceptance,
            execution_profile=profile,
            artifacts_dir=artifacts_dir,
        )

    def _pick_artifacts_dir(self, *, root: Path, contract: SkillContract) -> Optional[Path]:
        p1 = root / "artifacts"
        if p1.exists() and p1.is_dir():
            return p1

        # Back-compat with `skillc build ... --out dist` outputs.
        p2 = root / "dist" / contract.name
        if p2.exists() and p2.is_dir():
            return p2
        return None

