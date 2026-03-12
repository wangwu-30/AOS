from __future__ import annotations

import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import bootstrap  # noqa: F401

from agentos_next.protocol.asvp.crypto_ed25519 import generate_keypair
from agentos_next.protocol.asvp.errors import ASVPCryptoUnavailable
from agentos_next.protocol.asvp.signing import sign_skill_dir
from agentos_next.protocol.asvp.verify import verify_skill_dir


class TestASVPRoundtrip(unittest.TestCase):
    def test_sign_and_verify(self) -> None:
        with TemporaryDirectory(prefix="agentos_next_test_") as td:
            base = Path(td)

            keys_dir = base / "keys"
            priv = keys_dir / "demo.pem"
            pub = keys_dir / "demo.pub"

            try:
                generate_keypair(private_key_path=priv, public_key_path=pub)
            except ASVPCryptoUnavailable:
                self.skipTest("cryptography not installed")

            skill_dir = base / "skill_hello"
            skill_dir.mkdir()
            (skill_dir / "SKILL.md").write_text("# Hello\n", encoding="utf-8")
            (skill_dir / "impl.py").write_text("print('hello')\n", encoding="utf-8")

            sign_skill_dir(
                skill_dir=skill_dir,
                signer_id="demo",
                timestamp=int(time.time()),
                private_key_path=priv,
            )

            verify_skill_dir(skill_dir=skill_dir, public_keys_dir=keys_dir)


if __name__ == "__main__":  # pragma: no cover
    unittest.main(verbosity=2)
