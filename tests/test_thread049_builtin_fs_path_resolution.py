from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agentos_next.kernel.evidence_store import FileEvidenceStore
from agentos_next.kernel.executor import ExecuteRequest
from agentos_next.kernel.types import TraceContext
from agentos_next.runtime.builtin_fs import _resolve_path, maybe_execute_builtin_fs


class TestThread049BuiltinFsPathResolution(unittest.TestCase):
    def test_resolve_path_expands_tilde_into_workspace_root(self) -> None:
        with tempfile.TemporaryDirectory(prefix="agentos_next_t049_tilde_") as td:
            root = Path(td) / "codex" / "agentos-next"
            root.mkdir(parents=True, exist_ok=True)
            target = root / "README.md"
            target.write_text("hello", encoding="utf-8")

            resolved = _resolve_path(root, "~/codex/agentos-next/README.md")

            self.assertEqual(resolved, target.resolve())

    def test_resolve_path_remaps_cross_host_workspace_alias(self) -> None:
        with tempfile.TemporaryDirectory(prefix="agentos_next_t049_alias_") as td:
            root = Path(td) / "codex" / "agentos-next"
            root.mkdir(parents=True, exist_ok=True)
            target = root / "docs" / "guides" / "README.md"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("guide", encoding="utf-8")

            resolved = _resolve_path(root, "/Users/runner/codex/agentos-next/docs/guides/README.md")

            self.assertEqual(resolved, target.resolve())

    def test_shell_exec_accepts_workspace_alias_cwd(self) -> None:
        with tempfile.TemporaryDirectory(prefix="agentos_next_t049_shell_") as td:
            root = Path(td) / "codex" / "agentos-next"
            data_dir = Path(td) / "data"
            root.mkdir(parents=True, exist_ok=True)
            (root / "README.md").write_text("workspace", encoding="utf-8")

            req = ExecuteRequest(
                workspace_id="ws1",
                skill_ref="builtin://shell.exec",
                input={"command": "pwd", "cwd": "/Users/runner/codex/agentos-next"},
                idempotency_key="idem-shell-alias",
                deadline_ms=1000,
                trace=TraceContext(trace_id="tr1", turn_id="turn1", span_id="span1"),
                policy_context={"workspace_root": str(root)},
                preferred_target="local",
            )

            dispatch = maybe_execute_builtin_fs(req=req, data_dir=str(data_dir))

            self.assertTrue(dispatch.handled)
            assert dispatch.result is not None
            self.assertEqual(dispatch.result.status, "accepted")
            evidence = FileEvidenceStore(data_dir=data_dir)
            blob = evidence.get_blob(dispatch.result.evidence_refs[0].ref)
            assert blob is not None
            payload = blob.content.decode("utf-8", errors="replace")
            self.assertIn(str(root.resolve()), payload)

    def test_shell_exec_timeout_is_reported_as_failed_result(self) -> None:
        with tempfile.TemporaryDirectory(prefix="agentos_next_t049_shell_timeout_") as td:
            root = Path(td) / "codex" / "agentos-next"
            data_dir = Path(td) / "data"
            root.mkdir(parents=True, exist_ok=True)

            req = ExecuteRequest(
                workspace_id="ws1",
                skill_ref="builtin://shell.exec",
                input={"command": "sleep 60", "cwd": "."},
                idempotency_key="idem-shell-timeout",
                deadline_ms=1000,
                trace=TraceContext(trace_id="tr2", turn_id="turn2", span_id="span2"),
                policy_context={"workspace_root": str(root)},
                preferred_target="local",
            )

            with patch(
                "agentos_next.runtime.builtin_fs.subprocess.run",
                side_effect=subprocess.TimeoutExpired(cmd="sleep 60", timeout=30.0),
            ):
                dispatch = maybe_execute_builtin_fs(req=req, data_dir=str(data_dir))

            self.assertTrue(dispatch.handled)
            assert dispatch.result is not None
            self.assertEqual(dispatch.result.status, "failed")
            self.assertEqual(dispatch.result.error_code, "E_TIMEOUT")
            evidence = FileEvidenceStore(data_dir=data_dir)
            blob = evidence.get_blob(dispatch.result.evidence_refs[0].ref)
            assert blob is not None
            payload = json.loads(blob.content.decode("utf-8", errors="replace"))
            self.assertEqual(payload["operator_ref"], "builtin://shell.exec")
            self.assertEqual(payload["command"], "sleep 60")


if __name__ == "__main__":
    unittest.main()
