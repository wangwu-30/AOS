from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Optional

from agentos_next.kernel.evidence_manifest import iter_turn_ids_for_trace, verify_turn_manifest

SCHEMA_VERSION = "1.0.0"


def run(argv: Optional[list[str]] = None) -> tuple[int, dict[str, Any]]:
    ap = argparse.ArgumentParser(prog="verify_evidence", add_help=True)
    ap.add_argument("--data-dir", default="data", help="Data dir containing evidence/ and traces/ (default: data)")
    ap.add_argument("--trace-id", required=True, help="Trace ID to verify")
    ap.add_argument("--turn-id", help="Only verify a single turn_id (default: all turns with manifests)")
    ap.add_argument(
        "--keys-dir",
        help="Directory containing <signer_id>.pub for evidence signer verification (default: <data_dir>/keys/evidence_signers)",
    )
    args = ap.parse_args(argv)

    data_dir = Path(args.data_dir)
    trace_id = str(args.trace_id).strip()
    if not trace_id:
        out = {"schema_version": SCHEMA_VERSION, "ok": False, "error_code": "E_INPUT_SCHEMA", "message": "empty trace_id"}
        return 3, out

    keys_dir = Path(args.keys_dir) if args.keys_dir else None

    if args.turn_id:
        turns = [str(args.turn_id).strip()]
    else:
        turns = iter_turn_ids_for_trace(data_dir=data_dir, trace_id=trace_id)
        if not turns:
            out = {
                "schema_version": SCHEMA_VERSION,
                "ok": False,
                "error_code": "E_EVIDENCE_SIGNATURE_MISSING",
                "trace_id": trace_id,
                "summary": {"turns": 0, "verified": 0, "failed": 1},
                "results": [],
                "errors": ["no manifests found for trace_id"],
            }
            return 2, out

    results: list[dict[str, Any]] = []
    failed = 0
    verified = 0
    for tid in turns:
        ok, code, errors = verify_turn_manifest(data_dir=data_dir, trace_id=trace_id, turn_id=tid, keys_dir=keys_dir)
        if ok:
            verified += 1
        else:
            failed += 1
        results.append(
            {
                "turn_id": tid,
                "ok": bool(ok),
                "error_code": (code or None),
                "errors": list(errors),
            }
        )

    ok_all = failed == 0
    out = {
        "schema_version": SCHEMA_VERSION,
        "ok": ok_all,
        "trace_id": trace_id,
        "summary": {"turns": len(turns), "verified": verified, "failed": failed},
        "results": results,
    }
    return (0 if ok_all else 2), out


def main() -> None:
    try:
        code, out = run()
    except SystemExit:
        raise
    except Exception as e:
        code = 3
        out = {"schema_version": SCHEMA_VERSION, "ok": False, "error_code": "E_TOOL_ERROR", "message": str(e)}
    sys.stdout.write(json.dumps(out, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
    raise SystemExit(code)


if __name__ == "__main__":  # pragma: no cover
    main()

