from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import bootstrap  # noqa: F401

from agentos_next.kernel.capabilities import capability_items_for_policy_context
from agentos_next.kernel.evidence_store import FileEvidenceStore
from agentos_next.kernel.executor import ExecuteRequest
from agentos_next.kernel.orchestrator import Orchestrator
from agentos_next.kernel.types import TraceContext
from agentos_next.runtime.local_executor import LocalExecutor


def _req(
    *,
    workspace_id: str,
    operator_ref: str,
    arguments: dict[str, object],
    idem: str,
    span_id: str,
    capability: str,
) -> ExecuteRequest:
    return ExecuteRequest(
        workspace_id=workspace_id,
        operator_ref=operator_ref,
        arguments=arguments,
        idempotency_key=idem,
        deadline_ms=2000,
        trace=TraceContext(trace_id="tr_mem_v2", turn_id="turn_mem_v2", span_id=span_id),
        policy_context={"capabilities": capability_items_for_policy_context([capability])},
        preferred_target="local",
    )


def _tool_output(evidence: FileEvidenceStore, result) -> dict[str, object]:
    tool_io = next(er for er in result.evidence_refs if er.kind == "tool_io")
    blob = evidence.get_blob(tool_io.ref)
    assert blob is not None
    obj = json.loads(blob.content.decode("utf-8"))
    assert isinstance(obj, dict)
    return obj


class TestSpikeMEMAPI1BuiltinMemory(unittest.IsolatedAsyncioTestCase):
    async def test_memory_write_search_delete_roundtrip(self) -> None:
        with TemporaryDirectory(prefix="agentos_next_memapi1_v2_") as td:
            data_dir = Path(td)
            orch = Orchestrator.for_data_dir(str(data_dir), local_executor=LocalExecutor.for_data_dir(data_dir))
            evidence = FileEvidenceStore(data_dir=data_dir)

            write_res = await orch.execute(
                _req(
                    workspace_id="ws1",
                    operator_ref="builtin://memory.write",
                    arguments={
                        "record": {
                            "kind": "note",
                            "summary": "User identity note",
                            "payload": {"statement": "我是王五"},
                            "memory_key": "profile.identity.alias",
                            "scope": {"workspace_id": "ws1", "conversation_id": "conv-1"},
                            "source": "user_explicit",
                            "tags": ["identity"],
                            "ttl_seconds": 0,
                        }
                    },
                    idem="idem_write_v2",
                    span_id="span_write_v2",
                    capability="memory_write",
                )
            )
            self.assertEqual(write_res.status, "accepted")
            write_out = _tool_output(evidence, write_res)
            record_id = str(write_out["record_id"])
            item_ref = str(write_out["evidence_ref"])
            item_blob = evidence.get_blob(item_ref)
            assert item_blob is not None
            item_obj = json.loads(item_blob.content.decode("utf-8"))
            self.assertEqual(item_obj["type"], "memory_record_v2")
            self.assertIn("identity", item_obj["tags"])
            self.assertIn("ws_ws1", item_obj["tags"])

            search_res = await orch.execute(
                _req(
                    workspace_id="ws1",
                    operator_ref="builtin://memory.search",
                    arguments={
                        "query": "我是谁",
                        "intent": "identity",
                        "scope": {"workspace_id": "ws1", "conversation_id": "conv-1"},
                        "kinds": ["note", "profile"],
                        "limit": 5,
                    },
                    idem="idem_search_v2",
                    span_id="span_search_v2",
                    capability="memory_search",
                )
            )
            self.assertEqual(search_res.status, "accepted")
            search_out = _tool_output(evidence, search_res)
            hits = list(search_out["results"])
            self.assertEqual(len(hits), 1)
            self.assertEqual(hits[0]["record_id"], record_id)
            self.assertEqual(hits[0]["evidence_ref"], item_ref)
            self.assertEqual(search_out["conflicts"], [])

            delete_res = await orch.execute(
                _req(
                    workspace_id="ws1",
                    operator_ref="builtin://memory.delete",
                    arguments={"record_ids": [record_id]},
                    idem="idem_delete_v2",
                    span_id="span_delete_v2",
                    capability="memory_delete",
                )
            )
            self.assertEqual(delete_res.status, "accepted")

            search_res_after = await orch.execute(
                _req(
                    workspace_id="ws1",
                    operator_ref="builtin://memory.search",
                    arguments={
                        "query": "我是谁",
                        "intent": "identity",
                        "scope": {"workspace_id": "ws1", "conversation_id": "conv-1"},
                        "kinds": ["note", "profile"],
                        "limit": 5,
                    },
                    idem="idem_search_v2_after",
                    span_id="span_search_v2_after",
                    capability="memory_search",
                )
            )
            self.assertEqual(search_res_after.status, "accepted")
            search_out_after = _tool_output(evidence, search_res_after)
            self.assertEqual(search_out_after["results"], [])

    async def test_memory_write_semantic_profile_and_preference_inputs_normalize_to_canonical_records(self) -> None:
        with TemporaryDirectory(prefix="agentos_next_memapi1_semantic_") as td:
            data_dir = Path(td)
            orch = Orchestrator.for_data_dir(str(data_dir), local_executor=LocalExecutor.for_data_dir(data_dir))
            evidence = FileEvidenceStore(data_dir=data_dir)

            profile_res = await orch.execute(
                _req(
                    workspace_id="ws_sem",
                    operator_ref="builtin://memory.write",
                    arguments={
                        "record": {
                            "content": "用户名叫王五",
                            "kind": "user_preference",
                            "name": "王五",
                        }
                    },
                    idem="idem_semantic_profile",
                    span_id="span_semantic_profile",
                    capability="memory_write",
                )
            )
            self.assertEqual(profile_res.status, "accepted")
            profile_out = _tool_output(evidence, profile_res)
            profile_blob = evidence.get_blob(str(profile_out["evidence_ref"]))
            assert profile_blob is not None
            profile_obj = json.loads(profile_blob.content.decode("utf-8"))
            self.assertEqual(profile_obj["kind"], "profile")
            self.assertEqual(profile_obj["summary"], "用户身份: 王五")
            self.assertEqual(profile_obj["memory_key"], "profile.identity.name")
            self.assertEqual(profile_obj["payload"]["subject"], "identity.name")
            self.assertEqual(profile_obj["payload"]["value"], "王五")

            preference_res = await orch.execute(
                _req(
                    workspace_id="ws_sem",
                    operator_ref="builtin://memory.write",
                    arguments={
                        "record": {
                            "content": "咖啡",
                            "type": "user_preference",
                            "metadata": {"field": "preference"},
                        }
                    },
                    idem="idem_semantic_preference",
                    span_id="span_semantic_preference",
                    capability="memory_write",
                )
            )
            self.assertEqual(preference_res.status, "accepted")
            preference_out = _tool_output(evidence, preference_res)
            preference_blob = evidence.get_blob(str(preference_out["evidence_ref"]))
            assert preference_blob is not None
            preference_obj = json.loads(preference_blob.content.decode("utf-8"))
            self.assertEqual(preference_obj["kind"], "preference")
            self.assertEqual(preference_obj["summary"], "用户偏好: 咖啡")
            self.assertEqual(preference_obj["payload"]["subject"], "preference")
            self.assertEqual(preference_obj["payload"]["value"], "咖啡")
            self.assertTrue(str(preference_obj["memory_key"]).startswith("pref_"))

    async def test_memory_search_reports_conflicts_and_compact_emits_winner(self) -> None:
        with TemporaryDirectory(prefix="agentos_next_memapi1_conflict_") as td:
            data_dir = Path(td)
            orch = Orchestrator.for_data_dir(str(data_dir), local_executor=LocalExecutor.for_data_dir(data_dir))
            evidence = FileEvidenceStore(data_dir=data_dir)

            for idx, value in enumerate(("咖啡", "茶"), start=1):
                res = await orch.execute(
                    _req(
                        workspace_id="ws2",
                        operator_ref="builtin://memory.write",
                        arguments={
                            "record": {
                                "kind": "preference",
                                "summary": f"User drink preference {value}",
                                "payload": {"value": value},
                                "memory_key": "preference.drink",
                                "scope": {"workspace_id": "ws2"},
                                "source": "user_explicit",
                                "tags": ["preference"],
                                "ttl_seconds": 0,
                            }
                        },
                        idem=f"idem_write_conflict_{idx}",
                        span_id=f"span_write_conflict_{idx}",
                        capability="memory_write",
                    )
                )
                self.assertEqual(res.status, "accepted")

            search_res = await orch.execute(
                _req(
                    workspace_id="ws2",
                    operator_ref="builtin://memory.search",
                    arguments={
                        "query": "你喜欢喝什么",
                        "intent": "preference",
                        "scope": {"workspace_id": "ws2"},
                        "kinds": ["preference"],
                        "limit": 10,
                    },
                    idem="idem_search_conflict",
                    span_id="span_search_conflict",
                    capability="memory_search",
                )
            )
            self.assertEqual(search_res.status, "accepted")
            search_out = _tool_output(evidence, search_res)
            self.assertEqual(len(search_out["conflicts"]), 1)
            self.assertEqual(search_out["conflicts"][0]["memory_key"], "preference.drink")

            compact_res = await orch.execute(
                _req(
                    workspace_id="ws2",
                    operator_ref="builtin://memory.compact",
                    arguments={
                        "memory_key": "preference.drink",
                        "scope": {"workspace_id": "ws2"},
                        "winner": {
                            "kind": "preference",
                            "summary": "Latest confirmed drink preference",
                            "payload": {"value": "茶"},
                            "source": "system_consolidated",
                            "tags": ["preference"],
                            "ttl_seconds": 0,
                        },
                    },
                    idem="idem_compact_conflict",
                    span_id="span_compact_conflict",
                    capability="memory_compact",
                )
            )
            self.assertEqual(compact_res.status, "accepted")
            compact_out = _tool_output(evidence, compact_res)
            winner_record_id = str(compact_out["winner_record_id"])
            self.assertTrue(winner_record_id.startswith("mr_"))

            search_res_after = await orch.execute(
                _req(
                    workspace_id="ws2",
                    operator_ref="builtin://memory.search",
                    arguments={
                        "query": "你喜欢喝什么",
                        "intent": "preference",
                        "scope": {"workspace_id": "ws2"},
                        "kinds": ["preference"],
                        "limit": 10,
                    },
                    idem="idem_search_conflict_after",
                    span_id="span_search_conflict_after",
                    capability="memory_search",
                )
            )
            self.assertEqual(search_res_after.status, "accepted")
            search_out_after = _tool_output(evidence, search_res_after)
            self.assertEqual(search_out_after["conflicts"], [])
            self.assertEqual(search_out_after["results"][0]["record_id"], winner_record_id)


if __name__ == "__main__":  # pragma: no cover
    unittest.main(verbosity=2)
