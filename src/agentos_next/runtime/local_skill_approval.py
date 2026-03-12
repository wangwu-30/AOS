from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _fingerprint_skill_dir(skill_dir: Path) -> str:
    root = skill_dir.resolve()
    digest = hashlib.sha256()
    for path in sorted((p for p in root.rglob("*") if p.is_file()), key=lambda item: str(item.relative_to(root))):
        rel = str(path.relative_to(root))
        if rel in {"signature.sig", "manifest.json"}:
            continue
        digest.update(rel.encode("utf-8", errors="replace"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


@dataclass(frozen=True)
class LocalSkillApproval:
    fingerprint: str
    skill_dir: str
    approval_mode: str
    approved_at_utc: str


class FileLocalSkillApprovalStore:
    def __init__(self, *, data_dir: str | Path = "data") -> None:
        self._path = Path(data_dir) / "skills" / "local_unsigned_approvals.jsonl"

    def remember(self, *, skill_dir: Path, approval_mode: str) -> LocalSkillApproval:
        fingerprint = _fingerprint_skill_dir(skill_dir)
        record = LocalSkillApproval(
            fingerprint=fingerprint,
            skill_dir=str(skill_dir.resolve()),
            approval_mode=str(approval_mode or "remember_by_fingerprint").strip() or "remember_by_fingerprint",
            approved_at_utc=_utc_iso(),
        )
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as handle:
            handle.write(
                json.dumps(
                    {
                        "schema_version": "1.0.0",
                        "type": "local_unsigned_skill_approval",
                        "fingerprint": record.fingerprint,
                        "skill_dir": record.skill_dir,
                        "approval_mode": record.approval_mode,
                        "approved_at_utc": record.approved_at_utc,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n"
            )
        return record

    def is_remembered(self, *, skill_dir: Path) -> bool:
        fingerprint = _fingerprint_skill_dir(skill_dir)
        if not self._path.exists():
            return False
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
            if str(obj.get("fingerprint") or "").strip() == fingerprint:
                return True
        return False


def is_local_unsigned_skill(
    *,
    skill_dir: Path | None,
    operator_ref: str,
    verify_asvp: bool,
    registry_id: str | None,
    policy_context: dict[str, Any] | None,
) -> bool:
    if verify_asvp:
        return False
    if skill_dir is None:
        return False
    if registry_id is not None or str(operator_ref or "").strip().startswith("registry://"):
        return False
    policy = dict(policy_context or {})
    explicit_layer = str(policy.get("skill_layer") or "").strip().lower()
    if explicit_layer == "local_unsigned":
        return True
    parts = {part.lower() for part in skill_dir.resolve().parts}
    return "local_skills" in parts or ".agentos_local_skills" in parts


def local_skill_approval_mode(policy_context: dict[str, Any] | None) -> str:
    raw = str((policy_context or {}).get("local_skill_approval_mode") or "once").strip().lower()
    if raw in {"once", "remember_by_fingerprint"}:
        return raw
    return "once"


def local_skill_fingerprint(skill_dir: Path) -> str:
    return _fingerprint_skill_dir(skill_dir)
