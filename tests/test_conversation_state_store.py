from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import bootstrap  # noqa: F401

from agentos_next.kernel.conversation_state_store import FileConversationStateStore


class TestConversationStateStore(unittest.TestCase):
    def test_put_get_are_scoped_by_workspace_and_conversation(self) -> None:
        with tempfile.TemporaryDirectory(prefix="agentos_next_conv_state_") as td:
            store = FileConversationStateStore(data_dir=td)
            store.put(
                workspace_id="ws_a",
                conversation_id="chat_1",
                last_pending_task="分析项目",
                pending_contract={"objective": "分析项目", "intent_option": "DIRECT_TASK"},
            )
            store.put(
                workspace_id="ws_b",
                conversation_id="chat_1",
                last_pending_task="写周报",
            )

            state_a = store.get(workspace_id="ws_a", conversation_id="chat_1")
            state_b = store.get(workspace_id="ws_b", conversation_id="chat_1")

            self.assertIsNotNone(state_a)
            self.assertIsNotNone(state_b)
            self.assertEqual(state_a.last_pending_task, "分析项目")
            self.assertEqual(state_b.last_pending_task, "写周报")
            self.assertEqual((state_a.pending_contract or {}).get("objective"), "分析项目")

    def test_get_returns_none_for_corrupt_json(self) -> None:
        with tempfile.TemporaryDirectory(prefix="agentos_next_conv_state_bad_") as td:
            root = Path(td) / "conversation_state" / "ws_a"
            root.mkdir(parents=True, exist_ok=True)
            (root / "chat_1.json").write_text("{not-json", encoding="utf-8")

            store = FileConversationStateStore(data_dir=td)
            self.assertIsNone(store.get(workspace_id="ws_a", conversation_id="chat_1"))

    def test_put_trims_empty_fields_and_preserves_pending_contract(self) -> None:
        with tempfile.TemporaryDirectory(prefix="agentos_next_conv_state_trim_") as td:
            store = FileConversationStateStore(data_dir=td)
            state = store.put(
                workspace_id="ws_a",
                conversation_id="chat_1",
                last_pending_task="  ",
                expected_next_user_act="followup_or_new_task",
                pending_contract={"objective": "继续分析", "requires_workspace_observation": True},
            )
            self.assertEqual(state.last_pending_task, "继续分析")
            self.assertEqual(state.expected_next_user_act, "followup_or_new_task")
            self.assertTrue(bool(state.pending_contract))

            path = Path(td) / "memory_v2" / "continuity_heads" / "ws_a" / "chat_1.json"
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertNotIn("last_pending_task", payload)
            self.assertEqual(payload["pending_contract"]["objective"], "继续分析")
