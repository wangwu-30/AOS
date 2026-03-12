from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
TESTS = ROOT / "tests"
for p in (str(TESTS), str(SRC)):
    if p not in sys.path:
        sys.path.insert(0, p)

from admission_helpers import make_minimal_skill_package
from agentos_next.apps.pa_webhook_server import PAWebhookService, PAWebhookServiceConfig
from agentos_next.apps.assistant_loop import AssistantLoopResult
from agentos_next.kernel.types import TraceContext
from fixtures.telegram_webhook_fixtures import generate_telegram_webhook_fixture


def _send_message_delivery(*, text: str, key: str) -> dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "ok": True,
        "operator_ref": "builtin://channel.send_message",
        "channel": "assistant_runtime",
        "audience": "user",
        "text": text,
        "message_key": key,
        "delivery_stage": "final",
        "update_preference": "new_message",
        "delivery_mode": "create",
        "metadata": {"source_phase": "communicator", "task_id": key},
    }


class TestThread041PAWebhookServer(unittest.TestCase):
    def test_service_routing_file_maps_workspace_and_budget(self) -> None:
        with TemporaryDirectory(prefix="agentos_next_t041_route_ok_") as td:
            pkg_dir = Path(td) / "pkg"
            make_minimal_skill_package(pkg_dir)
            data_dir = Path(td) / "data"
            routing_file = Path(td) / "routing.json"
            routing_file.write_text(
                json.dumps(
                    {
                        "routes": {
                            "42001": {
                                "workspace_id": "ws041_mapped",
                                "budget_slice_remote_llm_calls": 2,
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )

            service = PAWebhookService(
                PAWebhookServiceConfig(
                    data_dir=str(data_dir),
                    workspace_id="ws041_default",
                    routing_file=str(routing_file),
                    expected_secret_token="s041",
                    skill_ref=str(pkg_dir),
                    verify_asvp=False,
                ),
            )

            payload = generate_telegram_webhook_fixture(
                update_id=4201,
                chat_id=42001,
                text="route me",
            ).encode("utf-8")
            code, out = service.handle_webhook_request(raw_body=payload, secret_token="s041")

            self.assertEqual(code, 200)
            self.assertTrue(out.get("ok"))
            self.assertIs(out.get("runtime"), out.get("ev1"))
            ev1 = out.get("ev1") or {}
            outbox = ev1.get("outbox") or {}
            self.assertEqual(outbox.get("workspace_id"), "ws041_mapped")

            event_path = data_dir / "pa" / "events" / "ws041_mapped" / "tg_update_4201.json"
            self.assertTrue(event_path.exists())
            event_obj = json.loads(event_path.read_text(encoding="utf-8"))
            envelope = event_obj.get("envelope") if isinstance(event_obj, dict) else {}
            self.assertEqual(envelope.get("workspace_id"), "ws041_mapped")
            self.assertEqual(envelope.get("budget_slice_remote_llm_calls"), 2)

    def test_service_routing_file_unmapped_conversation_is_fail_closed(self) -> None:
        with TemporaryDirectory(prefix="agentos_next_t041_route_miss_") as td:
            pkg_dir = Path(td) / "pkg"
            make_minimal_skill_package(pkg_dir)
            data_dir = Path(td) / "data"
            routing_file = Path(td) / "routing.json"
            routing_file.write_text(
                json.dumps({"routes": {"42001": {"workspace_id": "ws041_mapped"}}}),
                encoding="utf-8",
            )

            service = PAWebhookService(
                PAWebhookServiceConfig(
                    data_dir=str(data_dir),
                    workspace_id="ws041_default",
                    routing_file=str(routing_file),
                    expected_secret_token="s041",
                    skill_ref=str(pkg_dir),
                    verify_asvp=False,
                ),
            )

            payload = generate_telegram_webhook_fixture(
                update_id=4202,
                chat_id=99999,
                text="no route",
            ).encode("utf-8")
            code, out = service.handle_webhook_request(raw_body=payload, secret_token="s041")

            self.assertEqual(code, 403)
            self.assertFalse(out.get("ok"))
            self.assertEqual(out.get("error_code"), "E_PA_WORKSPACE_UNMAPPED")
            self.assertEqual((out.get("webhook") or {}).get("error_code"), "E_PA_WORKSPACE_UNMAPPED")
            self.assertIsNone(out.get("runtime"))
            self.assertIsNone(out.get("ev1"))
            self.assertFalse(out.get("reply_sent"))
            self.assertFalse((data_dir / "pa").exists())

    def test_service_without_routing_file_keeps_workspace_behavior(self) -> None:
        with TemporaryDirectory(prefix="agentos_next_t041_route_off_") as td:
            pkg_dir = Path(td) / "pkg"
            make_minimal_skill_package(pkg_dir)

            service = PAWebhookService(
                PAWebhookServiceConfig(
                    data_dir=str(Path(td) / "data"),
                    workspace_id="ws041_default",
                    expected_secret_token="s041",
                    skill_ref=str(pkg_dir),
                    verify_asvp=False,
                ),
            )

            payload = generate_telegram_webhook_fixture(
                update_id=4203,
                chat_id=77777,
                text="no routing file",
            ).encode("utf-8")
            code, out = service.handle_webhook_request(raw_body=payload, secret_token="s041")

            self.assertEqual(code, 200)
            self.assertTrue(out.get("ok"))
            self.assertIs(out.get("runtime"), out.get("ev1"))
            ev1 = out.get("ev1") or {}
            outbox = ev1.get("outbox") or {}
            self.assertEqual(outbox.get("workspace_id"), "ws041_default")

    def test_service_dedup_does_not_send_duplicate_reply(self) -> None:
        with TemporaryDirectory(prefix="agentos_next_t041_service_") as td:
            pkg_dir = Path(td) / "pkg"
            make_minimal_skill_package(pkg_dir)

            sent: list[dict] = []

            def _send(url: str, payload: dict[str, str]) -> bool:
                sent.append({"url": url, "payload": dict(payload)})
                return True

            service = PAWebhookService(
                PAWebhookServiceConfig(
                    data_dir=str(Path(td) / "data"),
                    workspace_id="ws041",
                    expected_secret_token="s041",
                    skill_ref=str(pkg_dir),
                    verify_asvp=False,
                ),
                send_func=_send,
            )

            payload = generate_telegram_webhook_fixture(update_id=4100, text="hello 041").encode("utf-8")

            code1, out1 = service.handle_webhook_request(raw_body=payload, secret_token="s041")
            code2, out2 = service.handle_webhook_request(raw_body=payload, secret_token="s041")

            self.assertEqual(code1, 200)
            self.assertEqual(code2, 200)
            self.assertTrue(out1.get("ok"))
            self.assertTrue(out2.get("ok"))
            self.assertIs(out2.get("runtime"), out2.get("ev1"))
            self.assertFalse(out1.get("dedup"))
            self.assertTrue(out2.get("dedup"))
            self.assertTrue(out1.get("reply_sent"))
            self.assertFalse(out2.get("reply_sent"))
            send_message_calls = [item for item in sent if str(item.get("url") or "").endswith("/sendMessage")]
            self.assertEqual(len(send_message_calls), 1)
            self.assertEqual(out1.get("runtime"), out1.get("ev1"))

    def test_service_failed_execute_still_sends_fallback_reply(self) -> None:
        with TemporaryDirectory(prefix="agentos_next_t041_fallback_") as td:
            pkg_dir = Path(td) / "pkg"
            make_minimal_skill_package(pkg_dir)
            sent: list[dict] = []

            def _send(url: str, payload: dict[str, str]) -> bool:
                sent.append({"url": url, "payload": dict(payload)})
                return True

            service = PAWebhookService(
                PAWebhookServiceConfig(
                    data_dir=str(Path(td) / "data"),
                    workspace_id="ws041",
                    expected_secret_token="s041",
                    skill_ref=str(pkg_dir),
                    verify_asvp=False,
                ),
                send_func=_send,
            )

            payload = generate_telegram_webhook_fixture(update_id=4103, text="hello fallback").encode("utf-8")
            final_output = {
                "schema_version": "1.0.0",
                "ok": True,
                "operator_ref": "builtin://channel.send_message",
                "channel": "assistant_runtime",
                "audience": "user",
                "text": "远端模型服务返回异常，请稍后再试。",
                "message_key": "tg_update_4103",
                "delivery_stage": "blocker",
                "update_preference": "new_message",
                "delivery_mode": "create",
                "metadata": {"source_phase": "communicator"},
            }

            with patch(
                "agentos_next.apps.pa_webhook_server.run_assistant_runtime_async",
                return_value=AssistantLoopResult(
                    ok=False,
                    final_output=final_output,
                    error_code="E_PROVIDER_BAD_RESPONSE",
                    steps=[],
                    trace=TraceContext(trace_id="tr_4103", turn_id="turn_4103", span_id="span_4103"),
                    evidence_refs=[],
                    followup_plan_ref="",
                    followup_task_id=None,
                ),
            ):
                code, out = service.handle_webhook_request(raw_body=payload, secret_token="s041")

            self.assertEqual(code, 200)
            self.assertTrue(out.get("ok"))
            self.assertIsNone(out.get("error_code"))
            self.assertTrue(out.get("reply_sent"))
            self.assertEqual((out.get("runtime") or {}).get("error_code"), "E_PROVIDER_BAD_RESPONSE")
            msg_calls = [item for item in sent if str(item.get("url") or "").endswith("/sendMessage")]
            self.assertEqual(len(msg_calls), 1)
            self.assertEqual(msg_calls[0]["payload"].get("text"), "远端模型服务返回异常，请稍后再试。")

    def test_service_uses_canonical_runtime_and_sets_runtime_alias(self) -> None:
        with TemporaryDirectory(prefix="agentos_next_t041_runtime_alias_") as td:
            pkg_dir = Path(td) / "pkg"
            make_minimal_skill_package(pkg_dir)
            sent: list[dict[str, Any]] = []
            captured: dict[str, Any] = {}

            async def _fake_runtime(ingress, **_kwargs):
                captured["submitter"] = ingress.submitter
                captured["consumer"] = ingress.consumer
                captured["query"] = ingress.loop_request.query
                return AssistantLoopResult(
                    ok=True,
                    final_output=_send_message_delivery(text="patched runtime reply", key="tg_update_4106"),
                    error_code=None,
                    steps=[],
                    trace=TraceContext(
                        trace_id="tr_t041_runtime",
                        turn_id="turn_t041_runtime",
                        span_id="span_t041_runtime",
                    ),
                    evidence_refs=[],
                    followup_plan_ref="",
                    followup_task_id=None,
                )

            def _send(url: str, payload: dict[str, Any]) -> bool:
                sent.append({"url": url, "payload": dict(payload)})
                return True

            service = PAWebhookService(
                PAWebhookServiceConfig(
                    data_dir=str(Path(td) / "data"),
                    workspace_id="ws041",
                    expected_secret_token="s041",
                    skill_ref=str(pkg_dir),
                    verify_asvp=False,
                ),
                send_func=_send,
            )

            payload = generate_telegram_webhook_fixture(update_id=4106, text="hello runtime").encode("utf-8")
            with patch("agentos_next.apps.pa_webhook_server.run_assistant_runtime_async", side_effect=_fake_runtime):
                code, out = service.handle_webhook_request(raw_body=payload, secret_token="s041")

            self.assertEqual(code, 200)
            self.assertTrue(out.get("ok"))
            self.assertIs(out.get("runtime"), out.get("ev1"))
            self.assertEqual(captured.get("submitter"), "telegram.webhook")
            self.assertEqual(captured.get("consumer"), "telegram.reply")
            self.assertEqual(captured.get("query"), "hello runtime")
            msg_calls = [item for item in sent if str(item.get("url") or "").endswith("/sendMessage")]
            self.assertEqual(len(msg_calls), 1)
            self.assertEqual(msg_calls[0]["payload"].get("text"), "patched runtime reply")

    def test_service_forwards_photo_attachment_into_runtime_ingress(self) -> None:
        with TemporaryDirectory(prefix="agentos_next_t041_media_ingress_") as td:
            pkg_dir = Path(td) / "pkg"
            make_minimal_skill_package(pkg_dir)
            captured: dict[str, Any] = {}

            async def _fake_runtime(ingress, **_kwargs):
                captured["query"] = ingress.loop_request.query
                captured["attachments"] = list(ingress.ingress_envelope.attachments)
                return AssistantLoopResult(
                    ok=True,
                    final_output=_send_message_delivery(text="patched runtime reply", key="tg_update_4109"),
                    error_code=None,
                    steps=[],
                    trace=TraceContext(
                        trace_id="tr_t041_media",
                        turn_id="turn_t041_media",
                        span_id="span_t041_media",
                    ),
                    evidence_refs=[],
                    followup_plan_ref="",
                    followup_task_id=None,
                )

            service = PAWebhookService(
                PAWebhookServiceConfig(
                    data_dir=str(Path(td) / "data"),
                    workspace_id="ws041",
                    expected_secret_token="s041",
                    skill_ref=str(pkg_dir),
                    verify_asvp=False,
                ),
                send_func=lambda _url, _payload: True,
            )

            payload = json.dumps(
                {
                    "update_id": 4109,
                    "message": {
                        "message_id": 1,
                        "date": 1600000000,
                        "chat": {"id": 12345, "type": "private"},
                        "from": {"id": 777, "is_bot": False, "first_name": "FixtureUser"},
                        "caption": "看图",
                        "photo": [
                            {"file_id": "p1", "file_unique_id": "u1", "width": 40, "height": 40, "file_size": 100},
                            {"file_id": "p2", "file_unique_id": "u2", "width": 400, "height": 300, "file_size": 1000},
                        ],
                    },
                },
                ensure_ascii=False,
            ).encode("utf-8")

            with patch("agentos_next.apps.pa_webhook_server.run_assistant_runtime_async", side_effect=_fake_runtime):
                code, out = service.handle_webhook_request(raw_body=payload, secret_token="s041")

            self.assertEqual(code, 200)
            self.assertTrue(out.get("ok"))
            self.assertEqual(captured.get("query"), "看图")
            attachments = captured.get("attachments") or []
            self.assertEqual(len(attachments), 1)
            self.assertEqual(attachments[0]["media_kind"], "image")
            self.assertEqual(attachments[0]["telegram_file_id"], "p2")

    def test_service_ignored_non_text_does_not_reuse_stale_runtime(self) -> None:
        with TemporaryDirectory(prefix="agentos_next_t041_non_text_") as td:
            pkg_dir = Path(td) / "pkg"
            make_minimal_skill_package(pkg_dir)
            sent: list[dict[str, Any]] = []

            def _send(url: str, payload: dict[str, Any]) -> bool:
                sent.append({"url": url, "payload": dict(payload)})
                return True

            service = PAWebhookService(
                PAWebhookServiceConfig(
                    data_dir=str(Path(td) / "data"),
                    workspace_id="ws041",
                    expected_secret_token="s041",
                    skill_ref=str(pkg_dir),
                    verify_asvp=False,
                ),
                send_func=_send,
            )

            text_payload = generate_telegram_webhook_fixture(update_id=4107, text="hello text").encode("utf-8")
            non_text_payload = json.dumps(
                {
                    "update_id": 4108,
                    "message": {
                        "message_id": 1,
                        "date": 1600000000,
                        "chat": {"id": 12345, "type": "private"},
                        "from": {"id": 777, "is_bot": False, "first_name": "FixtureUser"},
                        "sticker": {"emoji": "👍"},
                    },
                },
                ensure_ascii=False,
            ).encode("utf-8")

            code1, out1 = service.handle_webhook_request(raw_body=text_payload, secret_token="s041")
            code2, out2 = service.handle_webhook_request(raw_body=non_text_payload, secret_token="s041")

            self.assertEqual(code1, 200)
            self.assertEqual(code2, 200)
            self.assertTrue(out1.get("ok"))
            self.assertTrue(out2.get("ok"))
            self.assertEqual((out2.get("webhook") or {}).get("status"), "ignored_non_text")
            self.assertIsNone(out2.get("runtime"))
            self.assertIsNone(out2.get("ev1"))
            self.assertFalse(out2.get("reply_sent"))
            msg_calls = [item for item in sent if str(item.get("url") or "").endswith("/sendMessage")]
            self.assertEqual(len(msg_calls), 1)

    def test_service_replay_mode_is_zero_write(self) -> None:
        with TemporaryDirectory(prefix="agentos_next_t041_replay_") as td:
            pkg_dir = Path(td) / "pkg"
            make_minimal_skill_package(pkg_dir)
            data_dir = Path(td) / "data"

            service = PAWebhookService(
                PAWebhookServiceConfig(
                    data_dir=str(data_dir),
                    workspace_id="ws041",
                    expected_secret_token="s041",
                    replay_mode=True,
                    skill_ref=str(pkg_dir),
                    verify_asvp=False,
                ),
            )

            payload = generate_telegram_webhook_fixture(update_id=4101, text="hello replay").encode("utf-8")
            code, out = service.handle_webhook_request(raw_body=payload, secret_token="s041")

            self.assertEqual(code, 200)
            self.assertFalse(out.get("ok"))
            self.assertEqual(out.get("error_code"), "E_PA_EV_REPLAY_DENY")
            self.assertIsNone(out.get("runtime"))
            self.assertIsNone(out.get("ev1"))
            self.assertFalse((data_dir / "pa").exists())

    def test_service_memory_context_enabled_invalid_config_is_fail_closed(self) -> None:
        with TemporaryDirectory(prefix="agentos_next_t041_mem_fail_") as td:
            pkg_dir = Path(td) / "pkg"
            make_minimal_skill_package(pkg_dir)
            data_dir = Path(td) / "data"

            service = PAWebhookService(
                PAWebhookServiceConfig(
                    data_dir=str(data_dir),
                    workspace_id="ws041",
                    expected_secret_token="s041",
                    skill_ref=str(pkg_dir),
                    verify_asvp=False,
                    memory_context_enabled=True,
                    memory_context_retrieval_limit=0,
                ),
            )

            payload = generate_telegram_webhook_fixture(update_id=4102, text="hello mem").encode("utf-8")
            code, out = service.handle_webhook_request(raw_body=payload, secret_token="s041")

            self.assertEqual(code, 200)
            self.assertFalse(out.get("ok"))
            self.assertEqual(out.get("error_code"), "E_PA_EV_CONTEXT_FAILED")
            self.assertIs(out.get("runtime"), out.get("ev1"))
            ev1 = out.get("ev1") or {}
            self.assertEqual(ev1.get("error_code"), "E_PA_EV_CONTEXT_FAILED")
            self.assertFalse((data_dir / "pa" / "outbox").exists())

    def test_cli_server_rejects_non_loopback_host(self) -> None:
        with TemporaryDirectory(prefix="agentos_next_t041_cli_") as td:
            pkg_dir = Path(td) / "pkg"
            make_minimal_skill_package(pkg_dir)
            data_dir = Path(td) / "data"

            env = dict(os.environ)
            env["PYTHONPATH"] = str(SRC) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")

            proc = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "agentos_next.cli",
                    "mvp",
                    "pa-webhook-server",
                    "--host",
                    "0.0.0.0",
                    "--expected-secret-token",
                    "demo-secret-041",
                    "--workspace-id",
                    "ws041",
                    "--data-dir",
                    str(data_dir),
                    "--skill-ref",
                    str(pkg_dir),
                    "--no-verify-asvp",
                ],
                cwd=str(ROOT),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )

            self.assertEqual(proc.returncode, 2, msg=f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}")
            out = json.loads(proc.stdout.strip() or "{}")
            self.assertEqual(out.get("ok"), False)
            self.assertEqual(out.get("error_code"), "E_INPUT_SCHEMA")


if __name__ == "__main__":  # pragma: no cover
    unittest.main(verbosity=2)
