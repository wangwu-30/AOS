from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, Mapping

MANIFEST_VERSION = "1.0.0"


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(4096), b""):
            h.update(block)
    return h.hexdigest()


def iter_content_files(skill_dir: Path) -> Iterable[Path]:
    for root, _dirs, files in os.walk(skill_dir):
        for name in files:
            if name.startswith("."):
                continue
            if name in ("manifest.json", "signature.sig"):
                continue
            yield Path(root) / name


@dataclass(frozen=True)
class Manifest:
    version: str
    signer_id: str
    timestamp: int
    files: Dict[str, str]

    def to_dict(self) -> Dict[str, object]:
        return {
            "version": self.version,
            "signer_id": self.signer_id,
            "timestamp": self.timestamp,
            "files": dict(self.files),
        }

    def canonical_bytes(self) -> bytes:
        # Canonical JSON: sort keys, no whitespace.
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":")).encode("utf-8")


def build_manifest(skill_dir: Path, *, signer_id: str, timestamp: int) -> Manifest:
    root = skill_dir.resolve()
    files: Dict[str, str] = {}
    for path in iter_content_files(root):
        rel = str(path.relative_to(root).as_posix())
        files[rel] = _sha256_file(path)
    return Manifest(version=MANIFEST_VERSION, signer_id=signer_id, timestamp=timestamp, files=files)


def load_manifest(path: Path) -> Manifest:
    data = json.loads(path.read_text(encoding="utf-8"))
    return Manifest(
        version=str(data["version"]),
        signer_id=str(data["signer_id"]),
        timestamp=int(data.get("timestamp", 0)),
        files=dict(data.get("files", {})),
    )


def assert_no_extra_files(skill_dir: Path, manifest_files: Mapping[str, str]) -> None:
    root = skill_dir.resolve()
    on_disk = {str(p.relative_to(root).as_posix()) for p in iter_content_files(root)}
    declared = set(manifest_files.keys())
    extras = sorted(on_disk - declared)
    if extras:
        raise ValueError(f"extra files not in manifest: {extras[:5]}")

