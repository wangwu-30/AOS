from __future__ import annotations

import unittest
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory

import bootstrap  # noqa: F401

from agentos_next.kernel.evidence_store import FileEvidenceStore
from agentos_next.kernel.memory_store import (
    MEMORY_V2_SCHEMA_VERSION,
    MemoryQueryV2,
    MemoryRetrieverV2,
    MemoryScopeV2,
    MemoryStoreV2,
)
from agentos_next.kernel.runtime_snapshot_store import FileRuntimeSnapshotStore


class TestMemoryV2Store(unittest.TestCase):
    def test_retriever_prefers_conversation_scope_over_project_and_workspace(self) -> None:
        with TemporaryDirectory(prefix="agentos_next_memv2_scope_") as td:
            data_dir = Path(td)
            evidence = FileEvidenceStore(data_dir)
            store = MemoryStoreV2(data_dir)
            retriever = MemoryRetrieverV2(store)

            workspace = store.create_record(
                evidence=evidence,
                kind="note",
                summary="Workspace note",
                payload={"text": "deploy doc"},
                memory_key="note.deploy",
                scope=MemoryScopeV2(schema_version=MEMORY_V2_SCHEMA_VERSION, workspace_id="ws1"),
                source="system_consolidated",
                tags=("note",),
                ttl_seconds=0,
            )
            project = store.create_record(
                evidence=evidence,
                kind="note",
                summary="Project note",
                payload={"text": "deploy doc"},
                memory_key="note.deploy.project",
                scope=MemoryScopeV2(
                    schema_version=MEMORY_V2_SCHEMA_VERSION,
                    workspace_id="ws1",
                    project_id="proj-1",
                ),
                source="system_consolidated",
                tags=("note",),
                ttl_seconds=0,
            )
            conversation = store.create_record(
                evidence=evidence,
                kind="note",
                summary="Conversation note",
                payload={"text": "deploy doc"},
                memory_key="note.deploy.conversation",
                scope=MemoryScopeV2(
                    schema_version=MEMORY_V2_SCHEMA_VERSION,
                    workspace_id="ws1",
                    conversation_id="conv-1",
                ),
                source="system_consolidated",
                tags=("note",),
                ttl_seconds=0,
            )

            hits, conflicts = retriever.search(
                query=MemoryQueryV2(
                    schema_version=MEMORY_V2_SCHEMA_VERSION,
                    query="deploy doc",
                    intent="generic",
                    scope=MemoryScopeV2(
                        schema_version=MEMORY_V2_SCHEMA_VERSION,
                        workspace_id="ws1",
                        conversation_id="conv-1",
                        project_id="proj-1",
                    ),
                    kinds=("note",),
                    limit=3,
                )
            )
            self.assertEqual(conflicts, [])
            self.assertEqual([hit.record_id for hit in hits], [conversation.record_id, project.record_id, workspace.record_id])

    def test_retriever_prefers_relevance_before_recency(self) -> None:
        with TemporaryDirectory(prefix="agentos_next_memv2_relevance_") as td:
            data_dir = Path(td)
            evidence = FileEvidenceStore(data_dir)
            store = MemoryStoreV2(data_dir)
            retriever = MemoryRetrieverV2(store)

            relevant = store.create_record(
                evidence=evidence,
                kind="note",
                summary="Meituan stock note",
                payload={"text": "User asked about Meituan 3690.HK stock"},
                memory_key="note.stock.meituan",
                scope=MemoryScopeV2(schema_version=MEMORY_V2_SCHEMA_VERSION, workspace_id="ws1"),
                source="system_consolidated",
                tags=("stock",),
                ttl_seconds=0,
            )
            newer_irrelevant = store.create_record(
                evidence=evidence,
                kind="note",
                summary="Breakfast reminder",
                payload={"text": "Reminder at 09:00"},
                memory_key="note.reminder.breakfast",
                scope=MemoryScopeV2(schema_version=MEMORY_V2_SCHEMA_VERSION, workspace_id="ws1"),
                source="system_consolidated",
                tags=("reminder",),
                ttl_seconds=0,
            )
            store.put_record(replace(newer_irrelevant, updated_at_utc="2026-03-11T12:00:00Z"))
            store.put_record(replace(relevant, updated_at_utc="2026-03-10T12:00:00Z"))

            hits, _ = retriever.search(
                query=MemoryQueryV2(
                    schema_version=MEMORY_V2_SCHEMA_VERSION,
                    query="Meituan stock price",
                    intent="generic",
                    scope=MemoryScopeV2(schema_version=MEMORY_V2_SCHEMA_VERSION, workspace_id="ws1"),
                    kinds=("note",),
                    limit=2,
                )
            )
            self.assertEqual(hits[0].record_id, relevant.record_id)

    def test_retriever_orders_active_stale_deleted_when_requested(self) -> None:
        with TemporaryDirectory(prefix="agentos_next_memv2_freshness_") as td:
            data_dir = Path(td)
            evidence = FileEvidenceStore(data_dir)
            store = MemoryStoreV2(data_dir)
            retriever = MemoryRetrieverV2(store)

            active = store.create_record(
                evidence=evidence,
                kind="note",
                summary="Active note",
                payload={"text": "deploy checklist"},
                memory_key="note.active",
                scope=MemoryScopeV2(schema_version=MEMORY_V2_SCHEMA_VERSION, workspace_id="ws1"),
                source="system_consolidated",
                tags=("note",),
                ttl_seconds=0,
            )
            stale = store.create_record(
                evidence=evidence,
                kind="note",
                summary="Stale note",
                payload={"text": "deploy checklist"},
                memory_key="note.stale",
                scope=MemoryScopeV2(schema_version=MEMORY_V2_SCHEMA_VERSION, workspace_id="ws1"),
                source="system_consolidated",
                tags=("note",),
                ttl_seconds=0,
            )
            deleted = store.create_record(
                evidence=evidence,
                kind="note",
                summary="Deleted note",
                payload={"text": "deploy checklist"},
                memory_key="note.deleted",
                scope=MemoryScopeV2(schema_version=MEMORY_V2_SCHEMA_VERSION, workspace_id="ws1"),
                source="system_consolidated",
                tags=("note",),
                ttl_seconds=0,
            )
            store.put_record(replace(stale, expires_at_utc="2020-01-01T00:00:00Z", updated_at_utc="2020-01-01T00:00:00Z"))
            store.put_record(
                replace(
                    deleted,
                    deleted_at_utc="2020-01-02T00:00:00Z",
                    updated_at_utc="2020-01-02T00:00:00Z",
                )
            )

            hits, _ = retriever.search(
                query=MemoryQueryV2(
                    schema_version=MEMORY_V2_SCHEMA_VERSION,
                    query="deploy checklist",
                    intent="generic",
                    scope=MemoryScopeV2(schema_version=MEMORY_V2_SCHEMA_VERSION, workspace_id="ws1"),
                    kinds=("note",),
                    limit=3,
                    include_stale=True,
                    include_deleted=True,
                )
            )
            self.assertEqual([hit.freshness for hit in hits], ["active", "stale", "deleted"])
            self.assertEqual([hit.record_id for hit in hits], [active.record_id, stale.record_id, deleted.record_id])

    def test_conflict_detection_and_continuity_event_log(self) -> None:
        with TemporaryDirectory(prefix="agentos_next_memv2_conflict_") as td:
            data_dir = Path(td)
            evidence = FileEvidenceStore(data_dir)
            store = MemoryStoreV2(data_dir)
            retriever = MemoryRetrieverV2(store)
            continuity = FileRuntimeSnapshotStore(data_dir)

            for drink in ("咖啡", "茶"):
                store.create_record(
                    evidence=evidence,
                    kind="preference",
                    summary=f"饮品偏好: {drink}",
                    payload={"value": drink},
                    memory_key="preference.drink",
                    scope=MemoryScopeV2(schema_version=MEMORY_V2_SCHEMA_VERSION, workspace_id="ws1"),
                    source="user_explicit",
                    tags=("preference",),
                    ttl_seconds=0,
                )

            hits, conflicts = retriever.search(
                query=MemoryQueryV2(
                    schema_version=MEMORY_V2_SCHEMA_VERSION,
                    query="你喜欢喝什么",
                    intent="preference",
                    scope=MemoryScopeV2(schema_version=MEMORY_V2_SCHEMA_VERSION, workspace_id="ws1"),
                    kinds=("preference",),
                    limit=10,
                )
            )
            self.assertEqual(len(hits), 2)
            self.assertEqual(len(conflicts), 1)
            self.assertEqual(conflicts[0].memory_key, "preference.drink")

            continuity.put(
                workspace_id="ws1",
                conversation_id="conv-1",
                last_delivery_state="blocker",
                last_user_query="我是谁",
            )
            continuity.put(
                workspace_id="ws1",
                conversation_id="conv-1",
                last_delivery_state="done",
                last_user_query="告诉我今天的计划",
            )
            head = continuity.get(workspace_id="ws1", conversation_id="conv-1")
            events = continuity.list_events(workspace_id="ws1", conversation_id="conv-1", limit=10)
            assert head is not None
            self.assertEqual(head.last_delivery_state, "done")
            self.assertEqual(head.last_user_query, "告诉我今天的计划")
            self.assertGreaterEqual(len(events), 2)
            self.assertTrue(all(event.event_type == "head_update" for event in events))


if __name__ == "__main__":  # pragma: no cover
    unittest.main(verbosity=2)
