from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from .errors import ASVPCryptoUnavailable

try:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ed25519
except Exception as e:  # pragma: no cover
    serialization = None
    ed25519 = None
    _CRYPTO_IMPORT_ERROR = e
else:  # pragma: no cover
    _CRYPTO_IMPORT_ERROR = None


def _crypto_available() -> bool:
    return serialization is not None and ed25519 is not None


def _openssl_exe() -> str | None:
    return shutil.which("openssl")


def _require_any_backend() -> None:
    if _crypto_available():
        return
    if _openssl_exe() is not None:
        return
    raise ASVPCryptoUnavailable(
        "Ed25519 operations require either 'cryptography' (agentos-next[crypto]) or system 'openssl' on PATH"
    ) from _CRYPTO_IMPORT_ERROR


def _openssl_run(*args: str, input_bytes: bytes | None = None, check: bool = True) -> subprocess.CompletedProcess[bytes]:
    exe = _openssl_exe()
    if exe is None:
        raise ASVPCryptoUnavailable("system 'openssl' not found on PATH")
    try:
        return subprocess.run(
            [exe, *args],
            input=input_bytes,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=check,
        )
    except subprocess.CalledProcessError as e:
        stderr = (e.stderr or b"").decode("utf-8", errors="replace").strip()
        cmd = " ".join([exe, *args])
        raise ASVPCryptoUnavailable(f"openssl failed: {cmd}: {stderr}") from e


def _generate_keypair_openssl(*, private_key_path: Path, public_key_path: Path) -> None:
    private_key_path.parent.mkdir(parents=True, exist_ok=True)
    public_key_path.parent.mkdir(parents=True, exist_ok=True)

    # OpenSSL writes PKCS#8 PEM (BEGIN PRIVATE KEY) for Ed25519 keys.
    _openssl_run("genpkey", "-algorithm", "Ed25519", "-out", str(private_key_path))
    # Derive public key in SubjectPublicKeyInfo PEM (BEGIN PUBLIC KEY).
    _openssl_run("pkey", "-in", str(private_key_path), "-pubout", "-out", str(public_key_path))

    try:
        private_key_path.chmod(0o600)
    except Exception:
        # Best-effort: chmod may fail on some filesystems.
        pass


def _sign_openssl(*, private_key_path: Path, message: bytes) -> bytes:
    with tempfile.TemporaryDirectory(prefix="agentos_asvp_") as td:
        msg_path = Path(td) / "msg.bin"
        sig_path = Path(td) / "sig.bin"
        msg_path.write_bytes(message)

        _openssl_run(
            "pkeyutl",
            "-sign",
            "-inkey",
            str(private_key_path),
            "-rawin",
            "-in",
            str(msg_path),
            "-out",
            str(sig_path),
        )
        return sig_path.read_bytes()


def _verify_openssl(*, public_key_path: Path, message: bytes, signature: bytes) -> bool:
    with tempfile.TemporaryDirectory(prefix="agentos_asvp_") as td:
        msg_path = Path(td) / "msg.bin"
        sig_path = Path(td) / "sig.bin"
        msg_path.write_bytes(message)
        sig_path.write_bytes(signature)

        # OpenSSL uses exit code 1 for "signature invalid" and other failures; treat the
        # known verification-failure messages as False and escalate other errors.
        p = _openssl_run(
            "pkeyutl",
            "-verify",
            "-pubin",
            "-inkey",
            str(public_key_path),
            "-rawin",
            "-in",
            str(msg_path),
            "-sigfile",
            str(sig_path),
            check=False,
        )
        if p.returncode == 0:
            return True

        out = (p.stdout or b"") + b"\n" + (p.stderr or b"")
        text = out.decode("utf-8", errors="replace")
        if "Signature Verification Failure" in text:
            return False

        cmd = " ".join([_openssl_exe() or "openssl", "pkeyutl", "-verify", "..."])
        raise ASVPCryptoUnavailable(f"openssl failed: {cmd}: {text.strip()}")


def generate_keypair(*, private_key_path: Path, public_key_path: Path) -> None:
    _require_any_backend()
    if _crypto_available():
        private_key = ed25519.Ed25519PrivateKey.generate()
        public_key = private_key.public_key()

        private_pem = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
        public_pem = public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )

        private_key_path.parent.mkdir(parents=True, exist_ok=True)
        public_key_path.parent.mkdir(parents=True, exist_ok=True)
        private_key_path.write_bytes(private_pem)
        public_key_path.write_bytes(public_pem)
        return

    _generate_keypair_openssl(private_key_path=private_key_path, public_key_path=public_key_path)


def sign(*, private_key_path: Path, message: bytes) -> bytes:
    _require_any_backend()
    if _crypto_available():
        private_key = serialization.load_pem_private_key(private_key_path.read_bytes(), password=None)
        return private_key.sign(message)
    return _sign_openssl(private_key_path=private_key_path, message=message)


def verify(*, public_key_path: Path, message: bytes, signature: bytes) -> bool:
    _require_any_backend()
    if _crypto_available():
        public_key = serialization.load_pem_public_key(public_key_path.read_bytes())
        try:
            public_key.verify(signature, message)
            return True
        except Exception:
            return False

    return _verify_openssl(public_key_path=public_key_path, message=message, signature=signature)
