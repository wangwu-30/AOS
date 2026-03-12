from __future__ import annotations

import json
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import bootstrap  # noqa: F401

from agentos_next.protocol.asvp.crypto_ed25519 import generate_keypair
from agentos_next.protocol.asvp.errors import ASVPCryptoUnavailable
from agentos_next.protocol.asvp.signing import sign_skill_dir
from agentos_next.skills.package_loader import SkillPackageLoadError, SkillPackageLoader


def _write_json(path: Path, obj: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=True, indent=2, sort_keys=True) + "\n", encoding="utf-8")


class TestSkillPackageLoader(unittest.TestCase):
    def _make_pkg(self, root: Path) -> None:
        contract = {
            "name": "demo_skill",
            "version": "0.1.0",
            "description": "demo",
            "inputs_schema": {
                "type": "object",
                "properties": {"q": {"type": "string"}},
                "required": ["q"],
                "additionalProperties": False,
            },
            "outputs_schema": {
                "type": "object",
                "properties": {"answer": {"type": "string"}},
                "required": ["answer"],
                "additionalProperties": False,
            },
            "logic": "Return an answer string.",
            "acceptance_rules": {},
            "execution_profile": {"model_id": "local_mock"},
        }

        (root / "contract.skill").write_text(
            json.dumps(contract, ensure_ascii=True, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )

        artifacts = root / "artifacts"
        _write_json(artifacts / "inputs_schema.json", contract["inputs_schema"])
        _write_json(artifacts / "outputs_schema.json", contract["outputs_schema"])
        _write_json(artifacts / "acceptance_rules.json", contract["acceptance_rules"])
        _write_json(artifacts / "execution_profile.json", contract["execution_profile"])

    def test_load_without_asvp(self) -> None:
        with TemporaryDirectory(prefix="agentos_next_test_") as td:
            root = Path(td) / "pkg"
            root.mkdir(parents=True)
            self._make_pkg(root)

            loader = SkillPackageLoader(verify_asvp=False)
            pkg = loader.load(root)
            self.assertEqual(pkg.contract.name, "demo_skill")
            self.assertIn("q", pkg.artifacts.inputs_schema.get("properties", {}))

    def test_missing_artifacts_fails(self) -> None:
        with TemporaryDirectory(prefix="agentos_next_test_") as td:
            root = Path(td) / "pkg"
            root.mkdir(parents=True)
            self._make_pkg(root)
            # Remove one required artifact.
            (root / "artifacts" / "outputs_schema.json").unlink()

            loader = SkillPackageLoader(verify_asvp=False)
            with self.assertRaises(SkillPackageLoadError):
                loader.load(root)

    def test_load_with_asvp_verify(self) -> None:
        with TemporaryDirectory(prefix="agentos_next_test_") as td:
            base = Path(td)
            root = base / "pkg"
            root.mkdir(parents=True)
            self._make_pkg(root)

            keys_dir = base / "keys"
            priv = keys_dir / "demo.pem"
            pub = keys_dir / "demo.pub"
            try:
                generate_keypair(private_key_path=priv, public_key_path=pub)
            except ASVPCryptoUnavailable:
                self.skipTest("cryptography not installed")

            sign_skill_dir(
                skill_dir=root,
                signer_id="demo",
                timestamp=int(time.time()),
                private_key_path=priv,
            )

            loader = SkillPackageLoader(public_keys_dir=keys_dir, verify_asvp=True)
            pkg = loader.load(root)
            self.assertEqual(pkg.contract.name, "demo_skill")


if __name__ == "__main__":  # pragma: no cover
    unittest.main(verbosity=2)

