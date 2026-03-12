from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Optional


def _hash_payload(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8", errors="replace")).hexdigest()[:20]


class FileContextPlaneCache:
    schema_version = "1.0.0"

    def __init__(self, data_dir: str | os.PathLike[str] = "data") -> None:
        self._data_dir = Path(data_dir).resolve()
        self._root = self._data_dir / "context_plane_cache"

    def _path(self, *, agent_id: str, workspace_id: str) -> Path:
        key = _hash_payload({"agent_id": str(agent_id), "workspace_id": str(workspace_id)})
        return self._root / f"{key}.json"

    def _signature(
        self,
        *,
        execution_axiom_ids: list[str],
        communication_axiom_ids: list[str],
        constraint_ids: list[str],
        soul_profile_id: str | None,
        recent_failures: list[str],
        recent_success_patterns: list[str],
    ) -> str:
        return _hash_payload(
            {
                "execution_axiom_ids": list(execution_axiom_ids),
                "communication_axiom_ids": list(communication_axiom_ids),
                "constraint_ids": list(constraint_ids),
                "soul_profile_id": soul_profile_id,
                "recent_failures": list(recent_failures),
                "recent_success_patterns": list(recent_success_patterns),
            }
        )

    def get_base_pack(
        self,
        *,
        agent_id: str,
        workspace_id: str,
        execution_axiom_ids: list[str],
        communication_axiom_ids: list[str],
        constraint_ids: list[str],
        soul_profile_id: str | None,
        recent_failures: list[str],
        recent_success_patterns: list[str],
    ) -> Optional[dict[str, Any]]:
        path = self._path(agent_id=agent_id, workspace_id=workspace_id)
        if not path.exists():
            return None
        try:
            obj = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
        if not isinstance(obj, dict):
            return None
        if str(obj.get("schema_version") or "") != self.schema_version:
            return None
        expected = self._signature(
            execution_axiom_ids=execution_axiom_ids,
            communication_axiom_ids=communication_axiom_ids,
            constraint_ids=constraint_ids,
            soul_profile_id=soul_profile_id,
            recent_failures=recent_failures,
            recent_success_patterns=recent_success_patterns,
        )
        if str(obj.get("signature") or "") != expected:
            return None
        base_pack = obj.get("base_pack")
        return dict(base_pack) if isinstance(base_pack, dict) else None

    def put_base_pack(
        self,
        *,
        agent_id: str,
        workspace_id: str,
        execution_axiom_ids: list[str],
        communication_axiom_ids: list[str],
        constraint_ids: list[str],
        soul_profile_id: str | None,
        recent_failures: list[str],
        recent_success_patterns: list[str],
        base_pack: dict[str, Any],
    ) -> None:
        path = self._path(agent_id=agent_id, workspace_id=workspace_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": self.schema_version,
            "agent_id": str(agent_id),
            "workspace_id": str(workspace_id),
            "signature": self._signature(
                execution_axiom_ids=execution_axiom_ids,
                communication_axiom_ids=communication_axiom_ids,
                constraint_ids=constraint_ids,
                soul_profile_id=soul_profile_id,
                recent_failures=recent_failures,
                recent_success_patterns=recent_success_patterns,
            ),
            "base_pack": dict(base_pack),
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
