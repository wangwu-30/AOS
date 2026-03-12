from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import bootstrap  # noqa: F401

from agentos_next.kernel.skill_registry import FileSkillRegistry


def _write_json(path: Path, obj: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")


def _sha256_file(path: Path) -> str:
    import hashlib

    h = hashlib.sha256()
    with path.open("rb") as f:
        for blk in iter(lambda: f.read(4096), b""):
            h.update(blk)
    return h.hexdigest()


def _make_pkg(pkg_dir: Path, *, name: str, version: str) -> None:
    pkg_dir.mkdir(parents=True, exist_ok=True)
    contract = {
        "name": name,
        "version": version,
        "description": "reg2 test package",
        "inputs_schema": {"type": "object", "properties": {"q": {"type": "string"}}, "required": ["q"], "additionalProperties": False},
        "outputs_schema": {"type": "object", "properties": {"ok": {"const": True}}, "required": ["ok"], "additionalProperties": False},
        "logic": "Return ok=true.",
        "acceptance_rules": {},
        "execution_profile": {"model_id": "local_mock"},
        "risk_level": "low",
    }
    _write_json(pkg_dir / "contract.skill", contract)

    artifacts = pkg_dir / "artifacts"
    _write_json(artifacts / "inputs_schema.json", contract["inputs_schema"])
    _write_json(artifacts / "outputs_schema.json", contract["outputs_schema"])
    _write_json(artifacts / "acceptance_rules.json", contract["acceptance_rules"])
    _write_json(artifacts / "execution_profile.json", contract["execution_profile"])

    files = {
        "contract.skill": _sha256_file(pkg_dir / "contract.skill"),
        "artifacts/inputs_schema.json": _sha256_file(artifacts / "inputs_schema.json"),
        "artifacts/outputs_schema.json": _sha256_file(artifacts / "outputs_schema.json"),
        "artifacts/acceptance_rules.json": _sha256_file(artifacts / "acceptance_rules.json"),
        "artifacts/execution_profile.json": _sha256_file(artifacts / "execution_profile.json"),
    }
    manifest = {"version": "1.0.0", "signer_id": "reg2_test", "timestamp": 1, "files": files}
    _write_json(pkg_dir / "manifest.json", manifest)


class TestSpikeREG2RegistryVersionDeps(unittest.TestCase):
    def test_resolve_query_ref_picks_highest_semver(self) -> None:
        with TemporaryDirectory(prefix="agentos_next_reg2_") as td:
            base = Path(td)
            data_dir = base / "data"

            p1 = base / "pkg1"
            p2 = base / "pkg2"
            _make_pkg(p1, name="dep_pkg", version="1.0.0")
            _make_pkg(p2, name="dep_pkg", version="2.0.0")

            reg = FileSkillRegistry(data_dir=data_dir)
            e1 = reg.register(skill_dir=p1)
            e2 = reg.register(skill_dir=p2)
            self.assertNotEqual(e1.registry_id, e2.registry_id)

            rid = reg.resolve_query_ref(query_ref="registryq://dep_pkg@*")
            self.assertEqual(rid, e2.registry_id)

            rid2 = reg.resolve_query_ref(query_ref="registryq://dep_pkg@1.0.0")
            self.assertEqual(rid2, e1.registry_id)

    def test_resolve_deps_graph_is_deterministic(self) -> None:
        with TemporaryDirectory(prefix="agentos_next_reg2_deps_") as td:
            base = Path(td)
            data_dir = base / "data"

            dep = base / "dep"
            root = base / "root"
            _make_pkg(dep, name="dep_pkg", version="1.2.3")
            _make_pkg(root, name="root_pkg", version="0.1.0")

            reg = FileSkillRegistry(data_dir=data_dir)
            dep_e = reg.register(skill_dir=dep)
            root_e = reg.register(skill_dir=root, deps=["registryq://dep_pkg@1.2.3"])

            deps_map = reg.resolve_deps(root_registry_id=root_e.registry_id)
            self.assertEqual(deps_map, {"registryq://dep_pkg@1.2.3": dep_e.registry_id})

    def test_cycle_is_fail_closed(self) -> None:
        with TemporaryDirectory(prefix="agentos_next_reg2_cycle_") as td:
            base = Path(td)
            data_dir = base / "data"

            a = base / "a"
            b = base / "b"
            _make_pkg(a, name="pkg_a", version="0.1.0")
            _make_pkg(b, name="pkg_b", version="0.1.0")

            reg = FileSkillRegistry(data_dir=data_dir)
            a_e = reg.register(skill_dir=a, deps=["registryq://pkg_b@0.1.0"])
            _ = reg.register(skill_dir=b, deps=["registryq://pkg_a@0.1.0"])

            with self.assertRaises(Exception) as ctx:
                reg.resolve_deps(root_registry_id=a_e.registry_id)
            self.assertIn("cycle", str(ctx.exception).lower())


if __name__ == "__main__":  # pragma: no cover
    unittest.main(verbosity=2)
