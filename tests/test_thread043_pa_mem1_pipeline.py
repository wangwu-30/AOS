from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import bootstrap  # noqa: F401

from agentos_next.apps.telegram_connector import TelegramChannelAdapter
from agentos_next.kernel.evidence_store import FileEvidenceStore
from agentos_next.kernel.executor import ExecuteResult, ExecuteTiming
from agentos_next.kernel.memory_store import (
    MEMORY_V2_SCHEMA_VERSION,
    FileMemoryStore,
    MemoryScopeV2,
)
from agentos_next.kernel.runtime_snapshot_store import FileRuntimeSnapshotStore
from agentos_next.pa.ev1_runtime import PA_EV_ERROR_CONTEXT_FAILED, EV1Config, EV1Runtime
from agentos_next.pa.memory_pipeline import (
    PA_MEM_ERROR_SCHEMA_INVALID,
    PAMemoryPipelineConfig,
    build_memory_context_for_event,
)
from tests.admission_helpers import make_minimal_skill_package
from tests.fixtures.telegram_webhook_fixtures import (
    generate_secret_token_fixture,
    generate_telegram_webhook_fixture,
)


class _CaptureDispatcher:
    def __init__(self) -> None:
        self.last_envelope = None

    def dispatch(self, envelope, idempotency_key: str) -> None:  # noqa: ANN001
        self.last_envelope = envelope


class _FakeOrchestrator:
    def __init__(self) -> None:
        self.last_req = None

    async def execute(self, req):  # noqa: ANN001
        self.last_req = req
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        return ExecuteResult(
            status="accepted",
            evidence_refs=(),
            artifact_refs=(),
            error_code=None,
            timing=ExecuteTiming(started_at=now, ended_at=now),
            target="local",
        )


def _make_envelope(*, update_id: int = 7001, workspace_id: str = "ws_mem1", text: str = "我是谁") -> object:
    secret = generate_secret_token_fixture()
    cap = _CaptureDispatcher()
    adapter = TelegramChannelAdapter(expected_secret_token=secret, kernel_dispatcher=cap)
    payload = generate_telegram_webhook_fixture(update_id=update_id, text=text)
    code, _body = adapter.handle_webhook(
        payload_str=payload,
        secret_token=secret,
        workspace_id=workspace_id,
        replay_mode=False,
    )
    assert code == 200
    assert cap.last_envelope is not None
    return cap.last_envelope


class TestThread043PAMEM1Pipeline(unittest.TestCase):
    def test_build_memory_context_for_event_success(self) -> None:
        with tempfile.TemporaryDirectory(prefix="agentos_next_t043_ctx_ok_") as td:
            data_dir = Path(td)
            evidence = FileEvidenceStore(data_dir)
            memory = FileMemoryStore(data_dir)
            continuity = FileRuntimeSnapshotStore(data_dir)
            record = memory.create_record(
                evidence=evidence,
                kind="profile",
                summary="用户身份: 王五",
                payload={"name": "王五", "statement": "我是王五"},
                memory_key="profile.identity.name",
                scope=MemoryScopeV2(
                    schema_version=MEMORY_V2_SCHEMA_VERSION,
                    workspace_id="ws_mem1",
                    conversation_id="conv-1",
                ),
                source="user_explicit",
                tags=("profile", "identity"),
                ttl_seconds=0,
            )
            continuity.put(
                workspace_id="ws_mem1",
                conversation_id="conv-1",
                active_project_id="proj-1",
                pending_contract={"objective": "回答身份问题"},
                blocker={"summary": "等待用户确认昵称"},
                last_delivery_state="blocker",
                last_delivery_summary="上轮需要澄清",
                last_user_query="记住我是王五",
                last_user_query_at_utc="2026-03-11T08:00:00Z",
            )

            out = build_memory_context_for_event(
                config=PAMemoryPipelineConfig(enabled=True, retrieval_limit=5, include_stale=False),
                data_dir=data_dir,
                workspace_id="ws_mem1",
                conversation_id="conv-1",
                trace_id="tr_mem1",
                turn_id="turn_mem1",
                user_message="我是谁",
            )

            self.assertTrue(out.ok)
            mc = out.memory_context or {}
            self.assertEqual(mc.get("schema_version"), MEMORY_V2_SCHEMA_VERSION)
            self.assertEqual(mc.get("l0_continuity", {}).get("conversation_id"), "conv-1")
            self.assertEqual(mc.get("l0_continuity", {}).get("active_project_id"), "proj-1")
            self.assertEqual(mc.get("l1_query", {}).get("intent"), "identity")
            self.assertEqual(mc.get("l1_query", {}).get("scope", {}).get("conversation_id"), "conv-1")
            self.assertEqual(mc.get("retrieval_ref", "")[:3], "ev_")
            hits = list(mc.get("l2_hits") or [])
            self.assertEqual(len(hits), 1)
            self.assertEqual(hits[0]["record_id"], record.record_id)
            self.assertEqual(hits[0]["kind"], "profile")
            self.assertEqual(mc.get("conflicts"), [])

    def test_build_memory_context_for_event_invalid_limit_is_schema_invalid(self) -> None:
        with tempfile.TemporaryDirectory(prefix="agentos_next_t043_ctx_bad_") as td:
            out = build_memory_context_for_event(
                config=PAMemoryPipelineConfig(enabled=True, retrieval_limit=0),
                data_dir=Path(td),
                workspace_id="ws_mem1",
                conversation_id="conv-1",
                trace_id="tr_mem1",
                turn_id="turn_mem1",
                user_message="hi",
            )
            self.assertFalse(out.ok)
            self.assertEqual(out.error_code, PA_MEM_ERROR_SCHEMA_INVALID)

    def test_build_memory_context_hides_historical_failure_for_unrelated_query(self) -> None:
        with tempfile.TemporaryDirectory(prefix="agentos_next_t043_ctx_hist_fail_") as td:
            data_dir = Path(td)
            evidence = FileEvidenceStore(data_dir)
            memory = FileMemoryStore(data_dir)
            continuity = FileRuntimeSnapshotStore(data_dir)
            memory.create_record(
                evidence=evidence,
                kind="anti_pattern",
                summary="Failure pattern: E_PROVIDER_BAD_RESPONSE",
                payload={"query": "今天北京天气怎么样", "error_code": "E_PROVIDER_BAD_RESPONSE"},
                memory_key="anti_pattern.weather.bad_response",
                scope=MemoryScopeV2(
                    schema_version=MEMORY_V2_SCHEMA_VERSION,
                    workspace_id="ws_mem1",
                    conversation_id="conv-1",
                ),
                source="system_consolidated",
                tags=("anti_pattern",),
                ttl_seconds=0,
            )
            continuity.put(
                workspace_id="ws_mem1",
                conversation_id="conv-1",
                blocker={"summary": "上轮 provider 故障"},
                last_delivery_state="blocker",
                last_delivery_summary="上轮 provider 故障",
                last_user_query="今天北京天气怎么样",
                last_user_query_at_utc="2026-03-11T08:00:00Z",
            )

            out = build_memory_context_for_event(
                config=PAMemoryPipelineConfig(enabled=True, retrieval_limit=5, include_stale=False),
                data_dir=data_dir,
                workspace_id="ws_mem1",
                conversation_id="conv-1",
                trace_id="tr_mem1",
                turn_id="turn_mem1",
                user_message="hello",
            )

            self.assertTrue(out.ok)
            continuity_payload = (out.memory_context or {}).get("l0_continuity", {})
            self.assertIsNone(continuity_payload.get("blocker"))
            self.assertIsNone(continuity_payload.get("last_delivery_state"))
            self.assertIsNone(continuity_payload.get("last_delivery_summary"))
            self.assertIsNone(continuity_payload.get("last_user_query"))
            self.assertEqual((out.memory_context or {}).get("l2_hits"), [])

    def test_build_memory_context_keeps_historical_failure_for_same_task_retry(self) -> None:
        with tempfile.TemporaryDirectory(prefix="agentos_next_t043_ctx_retry_") as td:
            data_dir = Path(td)
            evidence = FileEvidenceStore(data_dir)
            memory = FileMemoryStore(data_dir)
            continuity = FileRuntimeSnapshotStore(data_dir)
            failure = memory.create_record(
                evidence=evidence,
                kind="anti_pattern",
                summary="Failure pattern: E_PROVIDER_BAD_RESPONSE",
                payload={"query": "今天北京天气怎么样", "error_code": "E_PROVIDER_BAD_RESPONSE"},
                memory_key="anti_pattern.weather.bad_response",
                scope=MemoryScopeV2(
                    schema_version=MEMORY_V2_SCHEMA_VERSION,
                    workspace_id="ws_mem1",
                    conversation_id="conv-1",
                ),
                source="system_consolidated",
                tags=("anti_pattern",),
                ttl_seconds=0,
            )
            continuity.put(
                workspace_id="ws_mem1",
                conversation_id="conv-1",
                blocker={"summary": "上轮 provider 故障"},
                last_delivery_state="blocker",
                last_delivery_summary="上轮 provider 故障",
                last_user_query="今天北京天气怎么样",
                last_user_query_at_utc="2026-03-11T08:00:00Z",
            )

            out = build_memory_context_for_event(
                config=PAMemoryPipelineConfig(enabled=True, retrieval_limit=5, include_stale=False),
                data_dir=data_dir,
                workspace_id="ws_mem1",
                conversation_id="conv-1",
                trace_id="tr_mem1",
                turn_id="turn_mem1",
                user_message="今天北京天气怎么样",
            )

            self.assertTrue(out.ok)
            continuity_payload = (out.memory_context or {}).get("l0_continuity", {})
            self.assertEqual(continuity_payload.get("last_delivery_state"), "blocker")
            self.assertEqual(continuity_payload.get("last_delivery_summary"), "上轮 provider 故障")
            self.assertEqual(continuity_payload.get("last_user_query"), "今天北京天气怎么样")
            hits = list((out.memory_context or {}).get("l2_hits") or [])
            self.assertEqual(len(hits), 1)
            self.assertEqual(hits[0]["record_id"], failure.record_id)
            self.assertEqual(hits[0]["kind"], "anti_pattern")

    def test_ev1_injects_memory_context_into_policy_context(self) -> None:
        with tempfile.TemporaryDirectory(prefix="agentos_next_t043_ev1_ctx_") as td:
            root = Path(td)
            pkg_dir = root / "pkg"
            data_dir = root / "data"
            make_minimal_skill_package(pkg_dir)

            evidence = FileEvidenceStore(data_dir)
            memory = FileMemoryStore(data_dir)
            memory.create_record(
                evidence=evidence,
                kind="profile",
                summary="用户身份: 王五",
                payload={"name": "王五"},
                memory_key="profile.identity.name",
                scope=MemoryScopeV2(
                    schema_version=MEMORY_V2_SCHEMA_VERSION,
                    workspace_id="ws_mem1",
                    conversation_id="12345",
                ),
                source="user_explicit",
                tags=("profile", "identity"),
                ttl_seconds=0,
            )

            env = _make_envelope(update_id=7100, workspace_id="ws_mem1", text="我是谁")
            fake_orch = _FakeOrchestrator()
            with patch("agentos_next.pa.ev1_runtime.Orchestrator.for_data_dir", return_value=fake_orch):
                rt = EV1Runtime(
                    EV1Config(
                        data_dir=data_dir,
                        skill_ref=str(pkg_dir),
                        message_input_key="q",
                        memory_context_enabled=True,
                        memory_context_retrieval_limit=4,
                    )
                )
                out = rt.handle_envelope(env, replay_mode=False)
            self.assertTrue(out.get("ok"))
            self.assertIsNotNone(fake_orch.last_req)
            policy = dict(fake_orch.last_req.policy_context)  # type: ignore[union-attr]
            self.assertIn("memory_context", policy)
            self.assertEqual(policy["memory_context"]["schema_version"], MEMORY_V2_SCHEMA_VERSION)
            self.assertEqual(policy["memory_context"]["l1_query"]["intent"], "identity")
            self.assertEqual(policy["memory_context"]["l2_hits"][0]["summary"], "用户身份: 王五")

    def test_ev1_memory_context_compile_failure_is_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory(prefix="agentos_next_t043_ev1_fail_") as td:
            root = Path(td)
            pkg_dir = root / "pkg"
            data_dir = root / "data"
            make_minimal_skill_package(pkg_dir)
            env_bad = _make_envelope(update_id=7200, workspace_id="ws_mem1", text="我是谁")
            rt = EV1Runtime(
                EV1Config(
                    data_dir=data_dir,
                    skill_ref=str(pkg_dir),
                    message_input_key="q",
                    memory_context_enabled=True,
                    memory_context_retrieval_limit=0,
                )
            )
            out = rt.handle_envelope(env_bad, replay_mode=False)
            self.assertFalse(out.get("ok"))
            self.assertEqual(out.get("error_code"), PA_EV_ERROR_CONTEXT_FAILED)
            self.assertEqual(out.get("context_error_code"), PA_MEM_ERROR_SCHEMA_INVALID)

    def test_ev1_consolidates_explicit_memory_request(self) -> None:
        with tempfile.TemporaryDirectory(prefix="agentos_next_t043_ev1_consolidate_") as td:
            root = Path(td)
            pkg_dir = root / "pkg"
            data_dir = root / "data"
            make_minimal_skill_package(pkg_dir)
            env = _make_envelope(update_id=7250, workspace_id="ws_mem1", text="记住我是王五")
            fake_orch = _FakeOrchestrator()
            with patch("agentos_next.pa.ev1_runtime.Orchestrator.for_data_dir", return_value=fake_orch):
                rt = EV1Runtime(
                    EV1Config(
                        data_dir=data_dir,
                        skill_ref=str(pkg_dir),
                        message_input_key="q",
                    )
                )
                out = rt.handle_envelope(env, replay_mode=False)
            self.assertTrue(out.get("ok"))
            records = FileMemoryStore(data_dir).list_by_memory_key(memory_key="profile.identity.name")
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0].kind, "profile")
            self.assertEqual(records[0].payload["name"], "王五")


if __name__ == "__main__":  # pragma: no cover
    unittest.main(verbosity=2)
