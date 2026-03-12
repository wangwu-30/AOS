from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from .skill_contract import load_contract


def _write_json(path: Path, obj: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")


def _sha256_text(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def cmd_build(skill_path: str, out_dir: str) -> None:
    contract = load_contract(skill_path)
    dest = Path(out_dir).resolve() / contract.name
    dest.mkdir(parents=True, exist_ok=True)

    _write_json(dest / "inputs_schema.json", contract.inputs_schema)
    _write_json(dest / "outputs_schema.json", contract.outputs_schema)
    _write_json(dest / "acceptance_rules.json", contract.acceptance_rules)
    _write_json(dest / "execution_profile.json", contract.execution_profile)

    # Spike-SC1: emit additional compiled artifacts (audit materials).
    # These are intentionally NOT consumed by runtime paths yet.
    compiled_dir = dest / "compiled"
    contract_text = Path(skill_path).read_text(encoding="utf-8")
    _write_json(
        compiled_dir / "intent_snapshot.json",
        {
            "schema_version": "1.0.0",
            "name": contract.name,
            "version": contract.version,
            "description": contract.description,
            "intent": contract.description,
            "success_criteria": dict(contract.acceptance_rules),
            "constraints": dict(contract.execution_profile),
            "contract_sha256": _sha256_text(contract_text),
        },
    )
    _write_json(
        compiled_dir / "prompt_bundle.json",
        {
            "schema_version": "1.0.0",
            "prompt_kind": "llm_json_contract_v1",
            "static_parts": {
                "header": [
                    "You are executing a skill contract. Follow the contract logic strictly.",
                    f"Skill: {contract.name} v{contract.version}",
                    f"Description: {contract.description}",
                    "Logic:",
                ],
                "logic": contract.logic,
            },
            "notes": "Dynamic Input/Output schema are injected by runtime; this bundle is audit-only in v1.",
        },
    )
    _write_json(
        compiled_dir / "execution_ir.json",
        {
            "schema_version": "1.0.0",
            "executor_kind": "local_llm_json",
            "streaming_capable": False,
            "required_capabilities": [],
            "policy_hints": {},
        },
    )


def cmd_test(skill_path: str) -> None:
    # Skeleton: load-only. Real runner comes later.
    _ = load_contract(skill_path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="skillc", description="Skill compiler (skeleton)")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_build = sub.add_parser("build", help="Compile a .skill contract into artifacts")
    p_build.add_argument("skill_path")
    p_build.add_argument("--out", default="dist")

    p_test = sub.add_parser("test", help="Run compile-time checks/tests (skeleton)")
    p_test.add_argument("skill_path")

    args = parser.parse_args(argv)
    if args.cmd == "build":
        cmd_build(args.skill_path, args.out)
        return 0
    if args.cmd == "test":
        cmd_test(args.skill_path)
        return 0
    raise AssertionError("unreachable")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
