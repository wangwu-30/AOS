from __future__ import annotations

import json
from pathlib import Path

from .crypto_ed25519 import sign as ed25519_sign
from .manifest import build_manifest


def sign_skill_dir(*, skill_dir: Path, signer_id: str, timestamp: int, private_key_path: Path) -> None:
    """Generate manifest.json and signature.sig in a skill directory.

    Spec: docs/specs/SKILL_PACKAGE_ASVP.md
    """

    skill_dir = skill_dir.resolve()
    manifest = build_manifest(skill_dir, signer_id=signer_id, timestamp=timestamp)
    signature = ed25519_sign(private_key_path=private_key_path, message=manifest.canonical_bytes())

    (skill_dir / "manifest.json").write_text(
        json.dumps(manifest.to_dict(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (skill_dir / "signature.sig").write_text(signature.hex() + "\n", encoding="utf-8")

