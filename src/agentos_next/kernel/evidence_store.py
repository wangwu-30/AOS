from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from uuid import uuid4

from .types import EvidenceKind, EvidenceRef
from .redaction import redact_json, redact_text


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _preview(content: str, limit: int = 200) -> str:
    if len(content) <= limit:
        return content
    return content[:limit] + "..."


def _default_ref(content_bytes: bytes) -> str:
    # Content-addressable by default; stable across replays.
    return "ev_" + hashlib.sha256(content_bytes).hexdigest()[:20]


@dataclass(frozen=True)
class EvidenceBlob:
    ref: str
    kind: EvidenceKind
    ts: str
    content_type: str
    content: bytes

    def to_ref(self) -> EvidenceRef:
        text_preview = None
        if self.content_type.startswith("text/") or self.content_type == "application/json":
            try:
                text_preview = _preview(self.content.decode("utf-8", errors="replace"))
            except Exception:
                text_preview = None
        return EvidenceRef(
            ref=self.ref,
            kind=self.kind,
            ts=self.ts,
            size_bytes=len(self.content),
            preview=text_preview,
        )


@dataclass(frozen=True)
class Artifact:
    id: str
    ref: str
    kind: str
    title: str
    ts: str
    visibility: str = "user"


class EvidenceStore:
    """In-memory evidence store skeleton.

    Spec: docs/specs/EVIDENCE_TRACE.md
    """

    def __init__(self) -> None:
        self._blobs: dict[str, EvidenceBlob] = {}
        self._artifacts: dict[str, Artifact] = {}

    def add_text(
        self,
        text: str,
        *,
        kind: EvidenceKind,
        ref: Optional[str] = None,
        content_type: str = "text/plain; charset=utf-8",
    ) -> EvidenceRef:
        content = redact_text(text).encode("utf-8")
        return self._add_blob(content, kind=kind, ref=ref, content_type=content_type).to_ref()

    def add_json(
        self,
        value: Any,
        *,
        kind: EvidenceKind,
        ref: Optional[str] = None,
    ) -> EvidenceRef:
        safe = redact_json(value)
        content = json.dumps(safe, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
        return self._add_blob(content, kind=kind, ref=ref, content_type="application/json").to_ref()

    def add_bytes(
        self,
        content: bytes,
        *,
        kind: EvidenceKind,
        ref: Optional[str] = None,
        content_type: str = "application/octet-stream",
    ) -> EvidenceRef:
        return self._add_blob(bytes(content), kind=kind, ref=ref, content_type=content_type).to_ref()

    def _add_blob(
        self,
        content: bytes,
        *,
        kind: EvidenceKind,
        ref: Optional[str],
        content_type: str,
    ) -> EvidenceBlob:
        blob_ref = ref or _default_ref(content)
        blob = EvidenceBlob(
            ref=blob_ref,
            kind=kind,
            ts=_utc_iso(),
            content_type=content_type,
            content=content,
        )
        self._blobs[blob_ref] = blob
        return blob

    def get_blob(self, ref: str) -> Optional[EvidenceBlob]:
        return self._blobs.get(ref)

    def commit_artifact(
        self, *, ref: str, kind: str, title: str, visibility: str = "user", artifact_id: str | None = None
    ) -> Artifact:
        # Skeleton: no single-leader enforcement here; caller must enforce.
        if ref not in self._blobs:
            raise KeyError(f"missing evidence ref: {ref}")
        aid = artifact_id or ("a_" + uuid4().hex[:12])
        art = Artifact(id=aid, ref=ref, kind=kind, title=title, ts=_utc_iso(), visibility=visibility)
        self._artifacts[aid] = art
        return art


class FileEvidenceStore:
    """File-based evidence store.

    Layout (relative to data_dir):
    - evidence/blobs/<ref>
    - evidence/meta/<ref>.json
    - evidence/artifacts/<artifact_id>.json
    """

    schema_version: str = "1.0.0"

    def __init__(self, data_dir: str | os.PathLike[str] = "data") -> None:
        self._data_dir = Path(data_dir)
        self._blobs_dir = self._data_dir / "evidence" / "blobs"
        self._meta_dir = self._data_dir / "evidence" / "meta"
        self._artifacts_dir = self._data_dir / "evidence" / "artifacts"
        self._blobs_dir.mkdir(parents=True, exist_ok=True)
        self._meta_dir.mkdir(parents=True, exist_ok=True)
        self._artifacts_dir.mkdir(parents=True, exist_ok=True)

    def add_text(
        self,
        text: str,
        *,
        kind: EvidenceKind,
        ref: Optional[str] = None,
        content_type: str = "text/plain; charset=utf-8",
    ) -> EvidenceRef:
        content = redact_text(text).encode("utf-8")
        return self._add_blob(content, kind=kind, ref=ref, content_type=content_type).to_ref()

    def add_json(self, value: Any, *, kind: EvidenceKind, ref: Optional[str] = None) -> EvidenceRef:
        safe = redact_json(value)
        content = json.dumps(safe, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
        return self._add_blob(content, kind=kind, ref=ref, content_type="application/json").to_ref()

    def add_bytes(
        self,
        content: bytes,
        *,
        kind: EvidenceKind,
        ref: Optional[str] = None,
        content_type: str = "application/octet-stream",
    ) -> EvidenceRef:
        return self._add_blob(bytes(content), kind=kind, ref=ref, content_type=content_type).to_ref()

    def _blob_path(self, ref: str) -> Path:
        return self._blobs_dir / ref

    def _meta_path(self, ref: str) -> Path:
        return self._meta_dir / f"{ref}.json"

    def _add_blob(
        self,
        content: bytes,
        *,
        kind: EvidenceKind,
        ref: Optional[str],
        content_type: str,
    ) -> EvidenceBlob:
        blob_ref = ref or _default_ref(content)
        ts = _utc_iso()
        blob = EvidenceBlob(ref=blob_ref, kind=kind, ts=ts, content_type=content_type, content=content)

        blob_path = self._blob_path(blob_ref)
        meta_path = self._meta_path(blob_ref)

        # Best-effort idempotent write: if blob/meta exists, keep existing bytes.
        # Use exclusive create to avoid TOCTOU under concurrent writers.
        try:
            with blob_path.open("xb") as f:
                f.write(content)
        except FileExistsError:
            pass

        meta = {
            "schema_version": self.schema_version,
            "ref": blob_ref,
            "kind": kind,
            "ts": ts,
            "content_type": content_type,
            "size_bytes": len(content),
            "sha256": hashlib.sha256(content).hexdigest(),
        }
        try:
            with meta_path.open("x", encoding="utf-8") as f:
                f.write(json.dumps(meta, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
        except FileExistsError:
            pass

        return blob

    def get_blob(self, ref: str) -> Optional[EvidenceBlob]:
        meta_path = self._meta_path(ref)
        blob_path = self._blob_path(ref)
        if not meta_path.exists() or not blob_path.exists():
            return None

        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        content = blob_path.read_bytes()
        return EvidenceBlob(
            ref=str(meta.get("ref", ref)),
            kind=str(meta["kind"]),  # type: ignore[arg-type]
            ts=str(meta["ts"]),
            content_type=str(meta["content_type"]),
            content=content,
        )

    def commit_artifact(
        self, *, ref: str, kind: str, title: str, visibility: str = "user", artifact_id: str | None = None
    ) -> Artifact:
        if self.get_blob(ref) is None:
            raise KeyError(f"missing evidence ref: {ref}")

        aid = artifact_id or ("a_" + uuid4().hex[:12])
        art = Artifact(id=aid, ref=ref, kind=kind, title=title, ts=_utc_iso(), visibility=visibility)
        (self._artifacts_dir / f"{aid}.json").write_text(
            json.dumps(
                {
                    "schema_version": self.schema_version,
                    "id": art.id,
                    "ref": art.ref,
                    "kind": art.kind,
                    "title": art.title,
                    "ts": art.ts,
                    "visibility": art.visibility,
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n",
            encoding="utf-8",
        )
        return art
