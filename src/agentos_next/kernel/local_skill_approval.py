from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


LOCAL_SKILL_LAYER_MARKERS = (
    "local_skills",
    ".agentos/local_skills",
)


@dataclass(frozen=True)
class LocalSkillApprovalContext:
    required: bool
    skill_dir: Path
    fingerprint: str
    approval_mode: str


class FileLocalSkillApprovalStore:
    def __init__(self, *, data_dir: str | Path = "data") -> None:
        self._path = Path(data_dir) / "kernel" / "local_skill_approvals.jsonl"

    def is_approved(self, *, fingerprint: str) -> bool:
        target = str(fingerprint or "").strip()
        if not target or not self._path.exists():
            return False
        approved = False
        for raw in self._path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except Exception:
                continue
            if not isinstance(obj, dict):
                continue
            if str(obj.get("fingerprint") or "").strip() != target:
                continue
            status = str(obj.get("status") or "").strip().lower()
            if status == "approved":
                approved = True
            elif status == "revoked":
                approved = False
        return approved

    def remember(
        self,
        *,
        fingerprint: str,
        skill_dir: Path,
        mode: str = "remember_by_fingerprint",
    ) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        event = {
            "schema_version": "1.0.0",
            "type": "local_skill_approval_event",
            "status": "approved",
            "approval_mode": str(mode or "remember_by_fingerprint").strip() or "remember_by_fingerprint",
            "fingerprint": str(fingerprint or "").strip(),
            "skill_dir": str(skill_dir),
        }
        with self._path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")


def resolve_local_skill_approval_context(
    *,
    operator_ref: str,
    skill_dir: Path | None,
    verify_asvp: bool,
    policy_context: dict[str, Any] | None = None,
) -> LocalSkillApprovalContext | None:
    root = skill_dir.resolve() if skill_dir is not None else None
    if root is None or not root.exists() or not root.is_dir():
        return None
    policy = dict(policy_context or {})
    explicit_origin = str(policy.get("skill_origin") or "").strip().lower()
    if explicit_origin not in {"", "local_unsigned"}:
        return None
    if explicit_origin != "local_unsigned":
        marker_hit = any(marker in str(root).replace("\\", "/") for marker in LOCAL_SKILL_LAYER_MARKERS)
        if not marker_hit:
            return None
    if verify_asvp:
        return None
    if str(operator_ref or "").strip().startswith("registry://"):
        return None
    fingerprint = compute_local_skill_fingerprint(root)
    approval_mode = str(policy.get("local_skill_approval_mode") or "once").strip().lower() or "once"
    if approval_mode not in {"once", "remember_by_fingerprint"}:
        approval_mode = "once"
    return LocalSkillApprovalContext(
        required=True,
        skill_dir=root,
        fingerprint=fingerprint,
        approval_mode=approval_mode,
    )


def compute_local_skill_fingerprint(skill_dir: Path) -> str:
    root = skill_dir.resolve()
    digest = hashlib.sha256()
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        rel = path.relative_to(root).as_posix()
        if rel.startswith(".git/") or rel.endswith(".pyc"):
            continue
        digest.update(rel.encode("utf-8", errors="replace"))
        digest.update(b"\n")
        digest.update(path.read_bytes())
        digest.update(b"\n")
    return digest.hexdigest()
