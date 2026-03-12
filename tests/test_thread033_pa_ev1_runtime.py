from __future__ import annotations

import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path

import bootstrap  # noqa: F401

from admission_helpers import make_minimal_skill_package
from agentos_next.apps.telegram_connector import TelegramChannelAdapter
from agentos_next.kernel.executor import ExecuteResult, ExecuteTiming
from agentos_next.kernel.types import EvidenceRef
from agentos_next.pa.ev1_runtime import (
    EV1Config,
    EV1Runtime,
    PA_EV_ERROR_REPLAY_DENY,
    PA_EV_ERROR_SCHEMA_INVALID,
    _default_reply_text,
)
from agentos_next.kernel.scheduler_store import FileSchedulerStore
from fixtures.telegram_webhook_fixtures import (
    generate_secret_token_fixture,
    generate_telegram_webhook_fixture,
)


class _CaptureDispatcher:
    def __init__(self) -> None:
        self.last_envelope = None
        self.last_idem = None

    def dispatch(self, envelope, idempotency_key: str) -> None:  # noqa: ANN001
        self.last_envelope = envelope
        self.last_idem = idempotency_key


def _make_envelope_from_thread034(*, update_id: int = 1000, text: str = "Hello Assistant") -> object:
    secret = generate_secret_token_fixture()
    cap = _CaptureDispatcher()
    adapter = TelegramChannelAdapter(expected_secret_token=secret, kernel_dispatcher=cap)
    payload = generate_telegram_webhook_fixture(update_id=update_id, text=text)

    code, body = adapter.handle_webhook(
        payload_str=payload,
        secret_token=secret,
        workspace_id="ws_pa",
        replay_mode=False,
    )
    assert code == 200, body
    assert cap.last_envelope is not None
    return cap.last_envelope


class TestThread033PAEV1Runtime(unittest.TestCase):
    def test_idempotency_drop_uses_outbox_short_circuit(self) -> None:
        with tempfile.TemporaryDirectory(prefix="agentos_next_t033_idem_") as td:
            root = Path(td)
            pkg_dir = root / "pkg"
            data_dir = root / "data"
            make_minimal_skill_package(pkg_dir)

            env1 = _make_envelope_from_thread034(update_id=1000)
            rt = EV1Runtime(EV1Config(data_dir=data_dir, skill_ref=str(pkg_dir), message_input_key="q"))

            out1 = rt.handle_envelope(env1, replay_mode=False)
            self.assertTrue(out1.get("ok"))
            self.assertFalse(out1.get("dedup"))

            files_before = len(list(data_dir.rglob("*")))

            # Same event_id, but intentionally different idempotency_key.
            # EV1 MUST dedup by event_id and short-circuit before calling Orchestrator.
            d2 = asdict(env1)
            d2["idempotency_key"] = "idem_tg_1000_tampered"
            env2 = type(env1)(**d2)

            out2 = rt.handle_envelope(env2, replay_mode=False)
            self.assertTrue(out2.get("ok"))
            self.assertTrue(out2.get("dedup"))
            self.assertEqual(out1.get("outbox"), out2.get("outbox"))

            files_after = len(list(data_dir.rglob("*")))
            self.assertEqual(files_before, files_after)

    def test_replay_mode_strict_zero_write(self) -> None:
        from unittest.mock import patch

        with tempfile.TemporaryDirectory(prefix="agentos_next_t033_replay_") as td:
            root = Path(td)
            pkg_dir = root / "pkg"
            data_dir = root / "data"
            make_minimal_skill_package(pkg_dir)

            env = _make_envelope_from_thread034(update_id=1001)
            rt = EV1Runtime(EV1Config(data_dir=data_dir, skill_ref=str(pkg_dir), message_input_key="q"))

            files_before = len(list(data_dir.rglob("*")))

            with patch("pathlib.Path.mkdir", side_effect=RuntimeError("mkdir prohibited")):
                out = rt.handle_envelope(env, replay_mode=True)

            self.assertFalse(out.get("ok"))
            self.assertEqual(out.get("error_code"), PA_EV_ERROR_REPLAY_DENY)

            files_after = len(list(data_dir.rglob("*")))
            self.assertEqual(files_before, files_after)

    def test_schema_missing_required_fields_is_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory(prefix="agentos_next_t033_schema_") as td:
            root = Path(td)
            pkg_dir = root / "pkg"
            data_dir = root / "data"
            make_minimal_skill_package(pkg_dir)

            rt = EV1Runtime(EV1Config(data_dir=data_dir, skill_ref=str(pkg_dir), message_input_key="q"))

            bad = {
                "schema_version": "1.0.0",
                "event_id": "tg_update_1",
                # idempotency_key missing (REQUIRED)
                "source": "telegram",
                "received_at_utc": "2026-01-01T00:00:00Z",
                "workspace_id": "ws_pa",
                "conversation_id": "c1",
                "sender_id": "u1",
                "message_text": "hi",
                "budget_slice_remote_llm_calls": 10,
            }
            out = rt.handle_envelope(bad, replay_mode=False)
            self.assertFalse(out.get("ok"))
            self.assertEqual(out.get("error_code"), PA_EV_ERROR_SCHEMA_INVALID)

            # No PA directories should have been created.
            self.assertFalse((data_dir / "pa").exists())

    def test_reminder_request_creates_scheduler_task(self) -> None:
        with tempfile.TemporaryDirectory(prefix="agentos_next_t033_sched_") as td:
            root = Path(td)
            pkg_dir = Path(__file__).resolve().parents[1] / "examples" / "skills" / "personal_assistant_brief"
            data_dir = root / "data"

            env = _make_envelope_from_thread034(update_id=1002, text="10分钟后提醒我喝水")
            rt = EV1Runtime(
                EV1Config(
                    data_dir=data_dir,
                    skill_ref=str(pkg_dir),
                    message_input_key="request",
                    verify_asvp=False,
                    bot_token="stub-token",
                )
            )
            out = rt.handle_envelope(env, replay_mode=False)
            self.assertTrue(out.get("ok"))
            outbox = out.get("outbox") or {}
            self.assertIn("已设置提醒", str(outbox.get("reply_text") or ""))

            store = FileSchedulerStore(data_dir=data_dir)
            tasks = store.list_tasks()
            self.assertEqual(len(tasks), 1)
            task = tasks[0]
            self.assertEqual(task.kind, "at")
            self.assertEqual(task.execute_request.get("operator_ref"), "builtin://channel.send_message")
            task_input = dict(task.execute_request.get("arguments") or {})
            metadata = dict(task_input.get("metadata") or {})
            self.assertEqual(metadata.get("conversation_id"), "12345")
            self.assertEqual(metadata.get("channel"), "telegram")
            self.assertIn("喝水", str(task_input.get("text") or ""))

    def test_default_reply_text_hides_provider_bad_response_details(self) -> None:
        res = ExecuteResult(
            status="failed",
            evidence_refs=(
                EvidenceRef(ref="ev_err", kind="error", ts="2026-03-07T00:00:00Z", size_bytes=12, preview=None),
            ),
            artifact_refs=(),
            error_code="E_PROVIDER_BAD_RESPONSE",
            timing=ExecuteTiming(started_at="2026-03-07T00:00:00Z", ended_at="2026-03-07T00:00:01Z"),
            target="local",
        )

        text = _default_reply_text(res=res, msg="hi", data_dir=Path("/tmp"))
        self.assertEqual(text, "远端模型服务返回异常，请稍后再试。")


if __name__ == "__main__":  # pragma: no cover
    unittest.main(verbosity=2)
