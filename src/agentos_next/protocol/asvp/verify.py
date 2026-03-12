from __future__ import annotations

from pathlib import Path

from .crypto_ed25519 import verify as ed25519_verify
from .errors import ASVPVerificationFailed
from .manifest import assert_no_extra_files, iter_content_files, load_manifest
from .manifest import _sha256_file  # internal use in verify


def verify_skill_dir(*, skill_dir: Path, public_keys_dir: Path) -> None:
    """Verify manifest integrity and signature authenticity.

    Raises ASVPVerificationFailed on failure.
    Spec: docs/specs/SKILL_PACKAGE_ASVP.md
    """

    skill_dir = skill_dir.resolve()
    manifest_path = skill_dir / "manifest.json"
    sig_path = skill_dir / "signature.sig"
    if not manifest_path.exists():
        raise ASVPVerificationFailed("missing manifest.json")
    if not sig_path.exists():
        raise ASVPVerificationFailed("missing signature.sig")

    manifest = load_manifest(manifest_path)
    signature = bytes.fromhex(sig_path.read_text(encoding="utf-8").strip())

    pub = (public_keys_dir / f"{manifest.signer_id}.pub").resolve()
    if not pub.exists():
        raise ASVPVerificationFailed(f"unknown signer_id: {manifest.signer_id}")

    if not ed25519_verify(public_key_path=pub, message=manifest.canonical_bytes(), signature=signature):
        raise ASVPVerificationFailed("invalid signature")

    assert_no_extra_files(skill_dir, manifest.files)
    for rel, expected in manifest.files.items():
        path = (skill_dir / rel).resolve()
        if not path.exists():
            raise ASVPVerificationFailed(f"missing file: {rel}")
        actual = _sha256_file(path)
        if actual != expected:
            raise ASVPVerificationFailed(f"hash mismatch: {rel}")

    # Ensure no unlisted files exist (already checked in assert_no_extra_files).
    for _ in iter_content_files(skill_dir):
        pass

