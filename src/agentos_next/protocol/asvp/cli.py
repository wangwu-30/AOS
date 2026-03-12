from __future__ import annotations

import argparse
import time
from pathlib import Path

from .crypto_ed25519 import generate_keypair
from .errors import ASVPCryptoUnavailable, ASVPVerificationFailed
from .signing import sign_skill_dir
from .verify import verify_skill_dir


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="asvp", description="ASVP signing/verification utilities")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_keygen = sub.add_parser("keygen", help="Generate Ed25519 keypair")
    p_keygen.add_argument("--out", default="keys", help="Output directory")
    p_keygen.add_argument("--name", required=True, help="Key name (also used as signer_id)")

    p_sign = sub.add_parser("sign", help="Sign a skill directory (writes manifest.json + signature.sig)")
    p_sign.add_argument("--skill-dir", required=True)
    p_sign.add_argument("--private-key", required=True)
    p_sign.add_argument("--signer-id", required=True)
    p_sign.add_argument("--timestamp", type=int, default=0)

    p_verify = sub.add_parser("verify", help="Verify a signed skill directory")
    p_verify.add_argument("--skill-dir", required=True)
    p_verify.add_argument("--keys-dir", required=True, help="Directory containing <signer_id>.pub")

    args = parser.parse_args(argv)
    try:
        if args.cmd == "keygen":
            out = Path(args.out).resolve()
            priv = out / f"{args.name}.pem"
            pub = out / f"{args.name}.pub"
            generate_keypair(private_key_path=priv, public_key_path=pub)
            print(f"private_key={priv}")
            print(f"public_key={pub}")
            return 0

        if args.cmd == "sign":
            ts = int(args.timestamp) if int(args.timestamp) > 0 else int(time.time())
            sign_skill_dir(
                skill_dir=Path(args.skill_dir),
                signer_id=args.signer_id,
                timestamp=ts,
                private_key_path=Path(args.private_key),
            )
            print("signed")
            return 0

        if args.cmd == "verify":
            verify_skill_dir(skill_dir=Path(args.skill_dir), public_keys_dir=Path(args.keys_dir))
            print("verified")
            return 0

    except ASVPCryptoUnavailable as e:
        print(f"crypto_unavailable: {e}")
        return 2
    except ASVPVerificationFailed as e:
        print(f"verification_failed: {e}")
        return 3

    raise AssertionError("unreachable")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

