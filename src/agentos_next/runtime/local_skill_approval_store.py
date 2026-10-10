from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from agentos_next.kernel.local_skill_approval import (
    FileLocalSkillApprovalStore as KernelLocalSkillApprovalStore,
)


@dataclass(frozen=True)
class LocalSkillApprovalRecord:
    fingerprint: str
    skill_dir: str
    decision: str
    decided_at_utc: str
    actor: str


class LocalSkillApprovalStore:
    """Backward-compatible runtime wrapper over the kernel approval store.

    Runtime and kernel now share one fingerprint function and one remembered-approval log.
    """

    def __init__(self, *, data_dir: str | Path = "data") -> None:
        self._store = KernelLocalSkillApprovalStore(data_dir=data_dir)

    def load(self) -> dict[str, LocalSkillApprovalRecord]:
        return {}

    def is_approved(self, *, fingerprint: str) -> bool:
        return self._store.is_approved(fingerprint=fingerprint)

    def remember(self, *, fingerprint: str, skill_dir: str | Path, actor: str = "human") -> None:
        del actor
        self._store.remember(
            fingerprint=str(fingerprint or "").strip(),
            skill_dir=Path(skill_dir),
            mode="remember_by_fingerprint",
        )
