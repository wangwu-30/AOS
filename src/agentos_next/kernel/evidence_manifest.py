from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, Sequence

from agentos_next.kernel.types import EvidenceRef, TraceContext
from agentos_next.protocol.asvp.crypto_ed25519 import ASVPCryptoUnavailable, generate_keypair, sign, verify


SCHEMA_VERSION = "1.0.0"

# v1 fixed layout (frozen by host):
#   data/evidence/manifests/<trace_id>/<turn_id>.json
#   data/evidence/manifests/<trace_id>/<turn_id>.json.sig
#
# NOTE: This is additive; it does not change EvidenceRef/TraceEvent schemas.
MANIFEST_DIR = ("evidence", "manifests")

# v1: local-only key storage under data_dir.
EVIDENCE_SIGNERS_DIR = ("keys", "evidence_signers")
DEFAULT_SIGNER_ID = "kernel_local"


@dataclass(frozen=True)
class ManifestPaths:
    manifest_path: Path
    signature_path: Path


@dataclass(frozen=True)
class ManifestWriteRequest:
    data_dir: Path
    trace: TraceContext
    workspace_id: str
    operator_ref: str
    idempotency_key: str
    execute_status: str
    execute_error_code: Optional[str]
    evidence_refs: Sequence[EvidenceRef]
    signer_id: str = DEFAULT_SIGNER_ID
    replay_mode: bool = False


@dataclass(frozen=True)
class ManifestWriteResult:
    ok: bool
    error_code: Optional[str]
    reason_code: str
    paths: Optional[ManifestPaths] = None
    manifest: Optional[dict[str, Any]] = None


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _canonical_json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode(
        "utf-8"
    )


def _read_evidence_ref_from_meta(*, data_dir: Path, ref: str) -> EvidenceRef:
    mp = _evidence_meta_path(data_dir=data_dir, ref=ref)
    if not mp.exists():
        raise FileNotFoundError(f"missing evidence meta for ref: {ref}")
    meta = json.loads(mp.read_text(encoding="utf-8"))
    if not isinstance(meta, dict):
        raise ValueError(f"evidence meta is not object for ref: {ref}")
    kind = meta.get("kind")
    ts = meta.get("ts")
    size_bytes = meta.get("size_bytes")
    if not isinstance(kind, str) or not isinstance(ts, str) or not isinstance(size_bytes, int):
        raise ValueError(f"invalid evidence meta fields for ref: {ref}")
    return EvidenceRef(ref=ref, kind=str(kind), ts=str(ts), size_bytes=int(size_bytes), preview=None)


def _collect_turn_evidence_refs_from_trace(*, data_dir: Path, trace_id: str, turn_id: str) -> list[EvidenceRef]:
    path = data_dir / "traces" / f"{trace_id}.jsonl"
    if not path.exists():
        return []

    # Deterministic order: first appearance in the trace file.
    seen: set[str] = set()
    ordered: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except Exception:
            continue
        if not isinstance(obj, dict):
            continue
        ctx = obj.get("ctx")
        if not isinstance(ctx, dict):
            continue
        if str(ctx.get("turn_id") or "") != str(turn_id):
            continue
        evs = obj.get("evidence_refs")
        if not isinstance(evs, list):
            continue
        for item in evs:
            if not isinstance(item, dict):
                continue
            ref = item.get("ref")
            if not isinstance(ref, str) or not ref.strip():
                continue
            if ref in seen:
                continue
            seen.add(ref)
            ordered.append(ref)

    out: list[EvidenceRef] = []
    for ref in ordered:
        out.append(_read_evidence_ref_from_meta(data_dir=data_dir, ref=ref))
    return out

def _evidence_meta_path(*, data_dir: Path, ref: str) -> Path:
    return data_dir / "evidence" / "meta" / f"{ref}.json"


def _read_evidence_sha256_or_none(*, data_dir: Path, ref: str) -> Optional[str]:
    mp = _evidence_meta_path(data_dir=data_dir, ref=ref)
    if not mp.exists():
        return None
    try:
        meta = json.loads(mp.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(meta, dict):
        return None
    sha = meta.get("sha256")
    return str(sha) if isinstance(sha, str) and sha.strip() else None


def _evidence_blob_path(*, data_dir: Path, ref: str) -> Path:
    return data_dir / "evidence" / "blobs" / ref


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 128), b""):
            h.update(chunk)
    return h.hexdigest()


def _compute_trace_turn_slice_sha256(*, data_dir: Path, trace_id: str, turn_id: str) -> str:
    path = data_dir / "traces" / f"{trace_id}.jsonl"
    h = hashlib.sha256()
    if not path.exists():
        return h.hexdigest()

    # Hash raw line bytes, but only for the selected turn_id.
    with path.open("rb") as f:
        for raw in f:
            if not raw.strip():
                continue
            try:
                obj = json.loads(raw.decode("utf-8", errors="strict"))
            except Exception as e:
                raise ValueError(f"trace line is not valid json: {e}") from e
            if not isinstance(obj, dict):
                continue
            ctx = obj.get("ctx")
            if not isinstance(ctx, dict):
                continue
            if str(ctx.get("turn_id") or "") != str(turn_id):
                continue
            h.update(raw)
    return h.hexdigest()


def _signer_paths(*, data_dir: Path, signer_id: str) -> tuple[Path, Path]:
    root = data_dir / Path(*EVIDENCE_SIGNERS_DIR)
    priv = root / f"{signer_id}.priv"
    pub = root / f"{signer_id}.pub"
    return priv, pub


def _ensure_signer_keypair(*, data_dir: Path, signer_id: str) -> tuple[Path, Path]:
    priv, pub = _signer_paths(data_dir=data_dir, signer_id=signer_id)
    if priv.exists() and pub.exists():
        return priv, pub
    generate_keypair(private_key_path=priv, public_key_path=pub)
    try:
        priv.chmod(0o600)
    except Exception:
        pass
    return priv, pub


def manifest_paths_for_turn(*, data_dir: Path, trace_id: str, turn_id: str) -> ManifestPaths:
    base = data_dir / Path(*MANIFEST_DIR) / str(trace_id)
    return ManifestPaths(
        manifest_path=base / f"{turn_id}.json",
        signature_path=base / f"{turn_id}.json.sig",
    )


def build_turn_manifest(*, req: ManifestWriteRequest) -> dict[str, Any]:
    trace_sha256 = _compute_trace_turn_slice_sha256(
        data_dir=req.data_dir, trace_id=req.trace.trace_id, turn_id=req.trace.turn_id
    )

    evidence_refs: Sequence[EvidenceRef] = req.evidence_refs
    if not evidence_refs:
        evidence_refs = _collect_turn_evidence_refs_from_trace(
            data_dir=req.data_dir, trace_id=req.trace.trace_id, turn_id=req.trace.turn_id
        )

    ev_items: list[dict[str, Any]] = []
    for er in evidence_refs:
        sha = _read_evidence_sha256_or_none(data_dir=req.data_dir, ref=er.ref)
        if sha is None:
            raise FileNotFoundError(f"missing evidence meta for ref: {er.ref}")
        ev_items.append(
            {
                "ref": er.ref,
                "kind": er.kind,
                "sha256": sha,
                "size_bytes": int(er.size_bytes),
            }
        )

    return {
        "schema_version": SCHEMA_VERSION,
        "type": "turn_evidence_manifest",
        "created_at": _utc_iso(),
        "trace_id": req.trace.trace_id,
        "turn_id": req.trace.turn_id,
        "workspace_id": req.workspace_id,
        "operator_ref": req.operator_ref,
        "idempotency_key": req.idempotency_key,
        "execute_status": req.execute_status,
        "execute_error_code": req.execute_error_code,
        "evidence_refs": ev_items,
        "trace_sha256": trace_sha256,
        "signer_id": req.signer_id,
        "signature_format": "ed25519_raw_base64",
    }


def write_turn_manifest_once(*, req: ManifestWriteRequest) -> ManifestWriteResult:
    if bool(req.replay_mode):
        return ManifestWriteResult(ok=False, error_code="E_POLICY_DENY", reason_code="replay_mode_no_side_effects")

    paths = manifest_paths_for_turn(data_dir=req.data_dir, trace_id=req.trace.trace_id, turn_id=req.trace.turn_id)
    paths.manifest_path.parent.mkdir(parents=True, exist_ok=True)

    if paths.manifest_path.exists() or paths.signature_path.exists():
        return ManifestWriteResult(
            ok=False, error_code="E_EVIDENCE_SIGNATURE_EXISTS", reason_code="signature_exists", paths=paths
        )

    try:
        manifest = build_turn_manifest(req=req)
    except FileNotFoundError:
        return ManifestWriteResult(ok=False, error_code="E_EVIDENCE_SIGNATURE_MISSING", reason_code="missing_evidence")
    except Exception:
        return ManifestWriteResult(ok=False, error_code="E_EVIDENCE_VERIFY_FAILED", reason_code="manifest_build_failed")

    payload = _canonical_json_bytes(manifest)

    try:
        with paths.manifest_path.open("x", encoding="utf-8") as f:
            f.write(payload.decode("utf-8"))
    except FileExistsError:
        return ManifestWriteResult(
            ok=False, error_code="E_EVIDENCE_SIGNATURE_EXISTS", reason_code="signature_exists", paths=paths
        )
    except Exception:
        return ManifestWriteResult(ok=False, error_code="E_EVIDENCE_VERIFY_FAILED", reason_code="manifest_write_failed", paths=paths)

    try:
        priv, _pub = _ensure_signer_keypair(data_dir=req.data_dir, signer_id=req.signer_id)
    except ASVPCryptoUnavailable:
        return ManifestWriteResult(ok=False, error_code="E_EVIDENCE_SIGNER_UNKNOWN", reason_code="crypto_unavailable", paths=paths)
    except Exception:
        return ManifestWriteResult(ok=False, error_code="E_EVIDENCE_SIGNER_UNKNOWN", reason_code="signer_unavailable", paths=paths)

    try:
        sig = sign(private_key_path=priv, message=payload)
        sig_b64 = base64.b64encode(sig).decode("ascii") + "\n"
        with paths.signature_path.open("x", encoding="ascii") as f:
            f.write(sig_b64)
    except FileExistsError:
        return ManifestWriteResult(
            ok=False, error_code="E_EVIDENCE_SIGNATURE_EXISTS", reason_code="signature_exists", paths=paths
        )
    except Exception:
        return ManifestWriteResult(ok=False, error_code="E_EVIDENCE_VERIFY_FAILED", reason_code="signature_write_failed", paths=paths)

    return ManifestWriteResult(ok=True, error_code=None, reason_code="ok", paths=paths, manifest=manifest)


def verify_turn_manifest(
    *,
    data_dir: Path,
    trace_id: str,
    turn_id: str,
    keys_dir: Optional[Path] = None,
) -> tuple[bool, str, list[str]]:
    """Verify a single turn manifest.

    Returns: (ok, error_code_or_empty, errors[])
    """
    paths = manifest_paths_for_turn(data_dir=data_dir, trace_id=trace_id, turn_id=turn_id)
    if not paths.manifest_path.exists() or not paths.signature_path.exists():
        return False, "E_EVIDENCE_SIGNATURE_MISSING", ["missing manifest or signature file"]

    try:
        manifest_text = paths.manifest_path.read_text(encoding="utf-8")
        manifest = json.loads(manifest_text)
    except Exception as e:
        return False, "E_EVIDENCE_VERIFY_FAILED", [f"cannot read/parse manifest: {e}"]

    if not isinstance(manifest, dict):
        return False, "E_EVIDENCE_VERIFY_FAILED", ["manifest is not a JSON object"]

    signer_id = str(manifest.get("signer_id") or "").strip()
    if not signer_id:
        return False, "E_EVIDENCE_SIGNER_UNKNOWN", ["missing signer_id"]

    keys_root = keys_dir if keys_dir is not None else (data_dir / Path(*EVIDENCE_SIGNERS_DIR))
    pub = (keys_root / f"{signer_id}.pub").resolve()
    if not pub.exists():
        return False, "E_EVIDENCE_SIGNER_UNKNOWN", [f"missing public key: {pub}"]

    # Verify trace slice hash.
    try:
        expected_trace_sha = str(manifest.get("trace_sha256") or "")
        actual_trace_sha = _compute_trace_turn_slice_sha256(data_dir=data_dir, trace_id=trace_id, turn_id=turn_id)
        if expected_trace_sha != actual_trace_sha:
            return False, "E_EVIDENCE_VERIFY_FAILED", ["trace_sha256 mismatch"]
    except Exception as e:
        return False, "E_EVIDENCE_VERIFY_FAILED", [f"trace_sha256 verify error: {e}"]

    # Verify evidence blob sha256 against meta.
    errors: list[str] = []
    evs = manifest.get("evidence_refs")
    if isinstance(evs, list):
        for item in evs:
            if not isinstance(item, dict):
                errors.append("evidence_refs item is not object")
                continue
            ref = str(item.get("ref") or "")
            expected = str(item.get("sha256") or "")
            if not ref or not expected:
                errors.append("evidence_refs missing ref/sha256")
                continue
            meta_sha = _read_evidence_sha256_or_none(data_dir=data_dir, ref=ref)
            if meta_sha is None:
                errors.append(f"missing evidence meta: {ref}")
                continue
            if meta_sha != expected:
                errors.append(f"evidence sha256 mismatch: {ref}")
                continue

            blob_path = _evidence_blob_path(data_dir=data_dir, ref=ref)
            if not blob_path.exists():
                errors.append(f"missing evidence blob: {ref}")
                continue
            try:
                blob_sha = _sha256_file(blob_path)
            except Exception as e:
                errors.append(f"cannot hash evidence blob: {ref}: {e}")
                continue
            if blob_sha != meta_sha:
                errors.append(f"evidence blob tampered: {ref}")
    else:
        errors.append("missing evidence_refs list")

    if errors:
        return False, "E_EVIDENCE_VERIFY_FAILED", errors

    # Verify signature.
    try:
        sig_text = paths.signature_path.read_text(encoding="ascii").strip()
        sig = base64.b64decode(sig_text.encode("ascii"), validate=True)
    except Exception as e:
        return False, "E_EVIDENCE_VERIFY_FAILED", [f"cannot decode signature: {e}"]

    try:
        msg = _canonical_json_bytes(manifest)
        ok = verify(public_key_path=pub, message=msg, signature=sig)
    except ASVPCryptoUnavailable as e:
        return False, "E_EVIDENCE_VERIFY_FAILED", [f"crypto unavailable: {e}"]
    except Exception as e:
        return False, "E_EVIDENCE_VERIFY_FAILED", [f"verify error: {e}"]

    if not ok:
        return False, "E_EVIDENCE_VERIFY_FAILED", ["signature invalid"]

    return True, "", []


def iter_turn_ids_for_trace(*, data_dir: Path, trace_id: str) -> list[str]:
    base = data_dir / Path(*MANIFEST_DIR) / str(trace_id)
    if not base.exists():
        return []
    out: list[str] = []
    for p in sorted(base.glob("*.json")):
        if p.name.endswith(".json") and not p.name.endswith(".json.sig"):
            out.append(p.name[:-5])
    return out
