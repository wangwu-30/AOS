from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path
from typing import Any
from unittest.mock import patch

from tests.admission_helpers import make_minimal_skill_package as _unused_make_minimal_skill_package
from agentos_next import cli as cli_mod
from agentos_next.apps.assistant_loop import AssistantLoopResult
from agentos_next.apps.pa_polling_service import PAPollingService, PAPollingServiceConfig
from agentos_next.kernel.evidence_store import FileEvidenceStore
from agentos_next.kernel.memory_store import FileMemoryStore
from agentos_next.kernel.scheduler_store import FileSchedulerStore
from agentos_next.kernel.types import TraceContext
from agentos_next.pa.event_log import FileEventLog
from agentos_next.pa.outbox_store import FileOutboxStore, OutboxItem
from agentos_next.runtime.playwright_web_runtime import PlaywrightProbeResult


class _FakeHTTPResponse:
    def __init__(self, payload: dict) -> None:
        self._raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self) -> bytes:
        return self._raw


def _updates_payload(*, update_id: int, text: str = "hello") -> dict:
    return {
        "ok": True,
        "result": [
            {
                "update_id": update_id,
                "message": {
                    "message_id": 1,
                    "date": 1600000000,
                    "chat": {"id": 12345, "type": "private"},
                    "from": {"id": 777, "is_bot": False, "first_name": "User"},
                    "text": text,
                },
            }
        ],
    }


def _updates_payload_non_text(*, update_id: int) -> dict:
    return {
        "ok": True,
        "result": [
            {
                "update_id": update_id,
                "message": {
                    "message_id": 1,
                    "date": 1600000000,
                    "chat": {"id": 12345, "type": "private"},
                    "from": {"id": 777, "is_bot": False, "first_name": "User"},
                    "sticker": {"emoji": "👍"},
                },
            }
        ],
    }


def _last_json_line(raw: str) -> dict:
    lines = [ln.strip() for ln in str(raw).splitlines() if ln.strip()]
    for ln in reversed(lines):
        if ln.startswith("{") and ln.endswith("}"):
            return json.loads(ln)
    return {}


def _assistant_skill_source_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "examples" / "skills" / "personal_assistant_brief"


def make_minimal_skill_package(pkg_dir: Path) -> None:
    shutil.copytree(_assistant_skill_source_dir(), pkg_dir, dirs_exist_ok=True)


def _send_message_delivery(*, text: str, stage: str = "final", key: str = "task_test") -> dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "ok": True,
        "operator_ref": "builtin://channel.send_message",
        "channel": "assistant_runtime",
        "audience": "user",
        "text": text,
        "message_key": key,
        "delivery_stage": stage,
        "update_preference": "prefer_update",
        "delivery_mode": "update",
        "metadata": {"source_phase": "communicator", "task_id": key},
    }


class TestThread044PAPolling(unittest.TestCase):
    def test_polling_happy_path_processes_and_replies(self) -> None:
        with tempfile.TemporaryDirectory(prefix="agentos_next_t044_ok_") as td:
            root = Path(td)
            pkg_dir = root / "pkg"
            make_minimal_skill_package(pkg_dir)
            sent: list[dict] = []

            def _send(url: str, payload: dict) -> bool:
                sent.append({"url": url, "payload": dict(payload)})
                return True

            svc = PAPollingService(
                PAPollingServiceConfig(
                    data_dir=str(root / "data"),
                    bot_token="token-044",
                    workspace_id="ws044",
                    skill_ref=str(pkg_dir),
                    verify_asvp=False,
                ),
                send_func=_send,
            )

            with patch(
                "agentos_next.apps.pa_polling_service.urllib.request.urlopen",
                return_value=_FakeHTTPResponse(_updates_payload(update_id=4401)),
            ):
                out = svc.run_once(offset=None)

            self.assertTrue(out.get("ok"))
            self.assertEqual(out.get("processed"), 1)
            self.assertEqual(out.get("dedup"), 0)
            self.assertEqual(out.get("reply_sent"), 1)
            self.assertEqual(out.get("next_offset"), 4402)
            msg_calls = [x for x in sent if str(x.get("url") or "").endswith("/sendMessage")]
            self.assertEqual(len(msg_calls), 1)

    def test_capability_self_check_prunes_unavailable_runtime_capabilities(self) -> None:
        with tempfile.TemporaryDirectory(prefix="agentos_next_t044_caps_") as td:
            root = Path(td)
            pkg_dir = root / "pkg"
            make_minimal_skill_package(pkg_dir)
            svc = PAPollingService(
                PAPollingServiceConfig(
                    data_dir=str(root / "data"),
                    bot_token="",
                    workspace_id="ws044",
                    skill_ref=str(pkg_dir),
                    verify_asvp=False,
                    allow_network_egress=False,
                    capabilities=("web_search", "web_browse", "memory_search"),
                ),
                send_func=lambda url, payload: True,
            )

            snapshot = svc.capability_self_check_snapshot()
            self.assertEqual(snapshot["effective_capabilities"], ["memory_search"])
            disabled = {item["name"]: item["reason"] for item in snapshot["disabled_capabilities"]}
            self.assertIn("web_search", disabled)
            self.assertIn("web_browse", disabled)
            self.assertIn("network egress is disabled", disabled["web_browse"])

    def test_capability_self_check_uses_strict_search_health_gate(self) -> None:
        with tempfile.TemporaryDirectory(prefix="agentos_next_t044_caps_health_") as td:
            root = Path(td)
            pkg_dir = root / "pkg"
            make_minimal_skill_package(pkg_dir)
            with patch(
                "agentos_next.runtime.builtin_web._probe_search_provider",
                side_effect=[
                    {"available": False, "detail": "BRAVE_SEARCH_API_KEY is not configured"},
                    {"available": False, "detail": "DuckDuckGo HTTP search returned no usable results"},
                    {"available": False, "detail": "Browser-assisted search returned no usable results"},
                ],
            ), patch(
                "agentos_next.runtime.builtin_web.probe_playwright_runtime",
                return_value=PlaywrightProbeResult(available=True),
            ):
                svc = PAPollingService(
                    PAPollingServiceConfig(
                        data_dir=str(root / "data"),
                        bot_token="",
                        workspace_id="ws044",
                        skill_ref=str(pkg_dir),
                        verify_asvp=False,
                        allow_network_egress=True,
                        capabilities=("web_search", "web_browse", "memory_search"),
                    ),
                    send_func=lambda url, payload: True,
                )

            snapshot = svc.capability_self_check_snapshot()
            self.assertEqual(snapshot["effective_capabilities"], ["web_browse", "memory_search"])
            disabled = {item["name"]: item["reason"] for item in snapshot["disabled_capabilities"]}
            self.assertIn("web_search", disabled)
            self.assertNotIn("web_browse", disabled)

    def test_capability_self_check_keeps_search_when_browser_fallback_is_healthy(self) -> None:
        with tempfile.TemporaryDirectory(prefix="agentos_next_t044_caps_browser_fallback_") as td:
            root = Path(td)
            pkg_dir = root / "pkg"
            make_minimal_skill_package(pkg_dir)
            with patch(
                "agentos_next.runtime.builtin_web._probe_search_provider",
                side_effect=[
                    {"available": False, "detail": "BRAVE_SEARCH_API_KEY is not configured"},
                    {"available": False, "detail": "DuckDuckGo HTTP search returned no usable results"},
                    {"available": True, "detail": "available"},
                ],
            ), patch(
                "agentos_next.runtime.builtin_web.probe_playwright_runtime",
                return_value=PlaywrightProbeResult(available=True),
            ):
                svc = PAPollingService(
                    PAPollingServiceConfig(
                        data_dir=str(root / "data"),
                        bot_token="",
                        workspace_id="ws044",
                        skill_ref=str(pkg_dir),
                        verify_asvp=False,
                        allow_network_egress=True,
                        capabilities=("web_search",),
                    ),
                    send_func=lambda url, payload: True,
                )

            snapshot = svc.capability_self_check_snapshot()
            self.assertEqual(snapshot["effective_capabilities"], ["web_search"])
            self.assertIn("web_search=available(playwright_search)", snapshot["summary_lines"])

    def test_pa_polling_cli_prints_capability_self_check_summary(self) -> None:
        with tempfile.TemporaryDirectory(prefix="agentos_next_t044_cli_caps_") as td:
            root = Path(td)
            pkg_dir = root / "pkg"
            make_minimal_skill_package(pkg_dir)
            stdout = io.StringIO()

            argv = [
                "mvp",
                "pa-polling",
                "--bot-token",
                "token-044",
                "--data-dir",
                str(root / "data"),
                "--workspace-id",
                "ws044",
                "--skill-ref",
                str(pkg_dir),
                "--no-verify-asvp",
                "--max-cycles",
                "1",
                "--capabilities",
                "web_search,web_browse,memory_search",
            ]

            with contextlib.redirect_stdout(stdout):
                with patch.object(sys, "argv", ["agentos_next.cli", *argv]):
                    with patch(
                        "agentos_next.apps.pa_polling_service.urllib.request.urlopen",
                        return_value=_FakeHTTPResponse({"ok": True, "result": []}),
                    ):
                        rc = cli_mod.main(argv)

            self.assertEqual(rc, 0)
            output = stdout.getvalue()
            self.assertIn("[PA] Capability self-check: web_search=disabled", output)
            self.assertIn("[PA] Capability self-check: web_browse=disabled", output)

    def test_polling_restart_resumes_from_persisted_offset(self) -> None:
        with tempfile.TemporaryDirectory(prefix="agentos_next_t044_resume_") as td:
            root = Path(td)
            pkg_dir = root / "pkg"
            data_dir = root / "data"
            make_minimal_skill_package(pkg_dir)
            sent: list[dict] = []
            fetched_urls: list[str] = []

            def _send(url: str, payload: dict) -> bool:
                sent.append({"url": url, "payload": dict(payload)})
                return True

            svc1 = PAPollingService(
                PAPollingServiceConfig(
                    data_dir=str(data_dir),
                    bot_token="token-044",
                    workspace_id="ws044",
                    skill_ref=str(pkg_dir),
                    verify_asvp=False,
                ),
                send_func=_send,
            )
            with patch(
                "agentos_next.apps.pa_polling_service.urllib.request.urlopen",
                return_value=_FakeHTTPResponse(_updates_payload(update_id=4405, text="resume seed")),
            ):
                out1 = svc1.run_once(offset=None)

            self.assertTrue(out1.get("ok"))
            self.assertEqual(out1.get("next_offset"), 4406)

            svc2 = PAPollingService(
                PAPollingServiceConfig(
                    data_dir=str(data_dir),
                    bot_token="token-044",
                    workspace_id="ws044",
                    skill_ref=str(pkg_dir),
                    verify_asvp=False,
                ),
                send_func=_send,
            )

            def _fake_urlopen(req, timeout=0):
                full_url = str(getattr(req, "full_url", ""))
                fetched_urls.append(full_url)
                if "getUpdates" in full_url:
                    return _FakeHTTPResponse({"ok": True, "result": []})
                raise AssertionError(f"unexpected url: {full_url}")

            with patch("agentos_next.apps.pa_polling_service.urllib.request.urlopen", side_effect=_fake_urlopen):
                out2 = svc2.run_once(offset=None)

            self.assertTrue(out2.get("ok"))
            self.assertEqual(out2.get("processed"), 0)
            self.assertEqual(out2.get("reply_sent"), 0)
            self.assertEqual(out2.get("next_offset"), 4406)
            self.assertTrue(any("offset=4406" in url for url in fetched_urls))

    def test_offset_checkpoint_log_is_suppressed_when_value_is_unchanged(self) -> None:
        with tempfile.TemporaryDirectory(prefix="agentos_next_t044_offset_log_") as td:
            root = Path(td)
            pkg_dir = root / "pkg"
            data_dir = root / "data"
            make_minimal_skill_package(pkg_dir)
            buf = io.StringIO()

            svc = PAPollingService(
                PAPollingServiceConfig(
                    data_dir=str(data_dir),
                    bot_token="token-044",
                    workspace_id="ws044",
                    skill_ref=str(pkg_dir),
                    verify_asvp=False,
                ),
                send_func=lambda url, payload: True,
            )

            with contextlib.redirect_stdout(buf):
                with patch(
                    "agentos_next.apps.pa_polling_service.urllib.request.urlopen",
                    return_value=_FakeHTTPResponse(_updates_payload(update_id=4410, text="seed")),
                ):
                    out1 = svc.run_once(offset=None)
                with patch(
                    "agentos_next.apps.pa_polling_service.urllib.request.urlopen",
                    return_value=_FakeHTTPResponse({"ok": True, "result": []}),
                ):
                    out2 = svc.run_once(offset=4411)

            self.assertTrue(out1.get("ok"))
            self.assertTrue(out2.get("ok"))
            saved_lines = [ln for ln in buf.getvalue().splitlines() if "Offset checkpoint saved" in ln]
            self.assertEqual(saved_lines, ["[PA] Offset checkpoint saved: next_offset=4411"])

    def test_polling_ignored_non_text_does_not_send_or_reuse_stale_outbox(self) -> None:
        with tempfile.TemporaryDirectory(prefix="agentos_next_t044_non_text_") as td:
            root = Path(td)
            pkg_dir = root / "pkg"
            make_minimal_skill_package(pkg_dir)
            sent: list[dict] = []

            def _send(url: str, payload: dict) -> bool:
                sent.append({"url": url, "payload": dict(payload)})
                return True

            svc = PAPollingService(
                PAPollingServiceConfig(
                    data_dir=str(root / "data"),
                    bot_token="token-044",
                    workspace_id="ws044",
                    skill_ref=str(pkg_dir),
                    verify_asvp=False,
                ),
                send_func=_send,
            )

            with patch(
                "agentos_next.apps.pa_polling_service.urllib.request.urlopen",
                return_value=_FakeHTTPResponse(_updates_payload(update_id=4491, text="text only")),
            ):
                out_text = svc.run_once(offset=None)
            with patch(
                "agentos_next.apps.pa_polling_service.urllib.request.urlopen",
                return_value=_FakeHTTPResponse(_updates_payload_non_text(update_id=4492)),
            ):
                out_non_text = svc.run_once(offset=4492)

            self.assertTrue(out_text.get("ok"))
            self.assertEqual(out_text.get("reply_sent"), 1)
            self.assertTrue(out_non_text.get("ok"))
            self.assertEqual(out_non_text.get("processed"), 0)
            self.assertEqual(out_non_text.get("ignored_non_text"), 1)
            self.assertEqual(out_non_text.get("reply_sent"), 0)
            msg_calls = [x for x in sent if str(x.get("url") or "").endswith("/sendMessage")]
            self.assertEqual(len(msg_calls), 1)

    def test_polling_dedup_same_update_id(self) -> None:
        with tempfile.TemporaryDirectory(prefix="agentos_next_t044_dedup_") as td:
            root = Path(td)
            pkg_dir = root / "pkg"
            make_minimal_skill_package(pkg_dir)
            sent: list[dict] = []
            buf = io.StringIO()

            def _send(url: str, payload: dict) -> bool:
                sent.append({"url": url, "payload": dict(payload)})
                return True

            svc = PAPollingService(
                PAPollingServiceConfig(
                    data_dir=str(root / "data"),
                    bot_token="token-044",
                    workspace_id="ws044",
                    skill_ref=str(pkg_dir),
                    verify_asvp=False,
                ),
                send_func=_send,
            )

            with contextlib.redirect_stdout(buf):
                with patch(
                    "agentos_next.apps.pa_polling_service.urllib.request.urlopen",
                    return_value=_FakeHTTPResponse(_updates_payload(update_id=4402)),
                ):
                    out1 = svc.run_once(offset=None)
                with patch(
                    "agentos_next.apps.pa_polling_service.urllib.request.urlopen",
                    return_value=_FakeHTTPResponse(_updates_payload(update_id=4402)),
                ):
                    out2 = svc.run_once(offset=None)

            self.assertTrue(out1.get("ok"))
            self.assertTrue(out2.get("ok"))
            self.assertEqual(out1.get("reply_sent"), 1)
            self.assertEqual(out2.get("dedup"), 1)
            self.assertEqual(out2.get("reply_sent"), 0)
            msg_calls = [x for x in sent if str(x.get("url") or "").endswith("/sendMessage")]
            self.assertEqual(len(msg_calls), 1)
            log_text = buf.getvalue()
            self.assertIn("Dedup hit for update 4402", log_text)
            self.assertIn("Offset checkpoint saved: next_offset=4403", log_text)

    def test_polling_replay_mode_zero_write(self) -> None:
        with tempfile.TemporaryDirectory(prefix="agentos_next_t044_replay_") as td:
            root = Path(td)
            pkg_dir = root / "pkg"
            make_minimal_skill_package(pkg_dir)
            data_dir = root / "data"

            svc = PAPollingService(
                PAPollingServiceConfig(
                    data_dir=str(data_dir),
                    bot_token="token-044",
                    workspace_id="ws044",
                    replay_mode=True,
                    skill_ref=str(pkg_dir),
                    verify_asvp=False,
                ),
            )

            with patch(
                "agentos_next.apps.pa_polling_service.urllib.request.urlopen",
                return_value=_FakeHTTPResponse(_updates_payload(update_id=4403)),
            ):
                out = svc.run_once(offset=None)

            self.assertTrue(out.get("ok"))
            self.assertEqual(out.get("reply_sent"), 0)
            self.assertEqual(out.get("processed"), 1)
            self.assertFalse((data_dir / "pa").exists())

    def test_cli_polling_requires_bot_token(self) -> None:
        root = Path(__file__).resolve().parents[1]
        src = root / "src"
        env = dict(os.environ)
        env["PYTHONPATH"] = str(src) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")

        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "agentos_next.cli",
                "mvp",
                "pa-polling",
                "--workspace-id",
                "ws044",
            ],
            cwd=str(root),
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

    def test_cli_max_cycles_zero_runs_infinite_mode_until_interrupt(self) -> None:
        calls = {"n": 0}

        class _StubService:
            def __init__(self, _cfg) -> None:
                return

            def run_once(self, offset=None) -> dict:
                calls["n"] += 1
                if calls["n"] == 1:
                    return {
                        "ok": True,
                        "processed": 1,
                        "dedup": 0,
                        "reply_sent": 1,
                        "rejected": 0,
                        "error_code": None,
                        "next_offset": 4404,
                    }
                raise KeyboardInterrupt()

        args = argparse.Namespace(
            bot_token="token-044",
            workspace_id="ws044",
            routing_file=None,
            data_dir="/tmp/agentos_next_t044_cli",
            budget_slice_remote_llm_calls=None,
            replay_mode=False,
            skill_ref="/tmp/skill",
            message_input_key="request",
            verify_asvp=False,
            keys_dir=None,
            backend="local_mock",
            model=None,
            remote_calls_armed=False,
            allow_network_egress=False,
            approved_by_human=False,
            target="local",
            deadline_ms=60000,
            memory_context_enabled=False,
            memory_context_retrieval_limit=8,
            memory_context_include_stale=False,
            memory_context_continuity_event_limit=50,
            memory_context_audit_mode=False,
            timeout_seconds=20,
            limit=20,
            max_cycles=0,
            offset=None,
        )

        buf = io.StringIO()
        with patch("agentos_next.cli.PAPollingService", _StubService):
            with contextlib.redirect_stdout(buf):
                rc = cli_mod.cmd_mvp_pa_polling(args)

        self.assertEqual(rc, 0)
        out = _last_json_line(buf.getvalue())
        self.assertEqual(out.get("ok"), True)
        self.assertEqual(out.get("infinite_mode"), True)
        self.assertEqual(out.get("max_cycles"), 0)
        self.assertEqual(out.get("cycles_run"), 1)
        self.assertEqual(out.get("next_offset"), 4404)

    def test_cli_auto_capabilities_for_remote_model(self) -> None:
        captured = {"cfg": None}

        class _StubService:
            def __init__(self, cfg) -> None:
                captured["cfg"] = cfg

            def run_once(self, offset=None) -> dict:
                return {
                    "ok": True,
                    "processed": 0,
                    "dedup": 0,
                    "reply_sent": 0,
                    "rejected": 0,
                    "error_code": None,
                    "next_offset": offset,
                }

        args = argparse.Namespace(
            bot_token="token-044",
            workspace_id="ws044",
            routing_file=None,
            data_dir="/tmp/agentos_next_t044_cli_caps",
            budget_slice_remote_llm_calls=10,
            replay_mode=False,
            skill_ref="/tmp/skill",
            message_input_key="request",
            verify_asvp=False,
            keys_dir=None,
            backend="codex_oauth",
            capabilities="",
            model=None,
            remote_calls_armed=True,
            allow_network_egress=True,
            approved_by_human=False,
            target="local",
            deadline_ms=60000,
            memory_context_enabled=False,
            memory_context_retrieval_limit=8,
            memory_context_include_stale=False,
            memory_context_continuity_event_limit=50,
            memory_context_audit_mode=False,
            timeout_seconds=20,
            limit=20,
            max_cycles=1,
            offset=None,
        )

        buf = io.StringIO()
        with patch("agentos_next.cli.PAPollingService", _StubService):
            with contextlib.redirect_stdout(buf):
                rc = cli_mod.cmd_mvp_pa_polling(args)

        self.assertEqual(rc, 0)
        out = _last_json_line(buf.getvalue())
        self.assertEqual(out.get("ok"), True)
        cfg = captured["cfg"]
        self.assertIsNotNone(cfg)
        self.assertIn("llm_remote", set(getattr(cfg, "capabilities")))
        self.assertIn("net_egress", set(getattr(cfg, "capabilities")))

    def test_polling_webhook_conflict_auto_recovers_once(self) -> None:
        with tempfile.TemporaryDirectory(prefix="agentos_next_t044_conflict_") as td:
            root = Path(td)
            pkg_dir = root / "pkg"
            make_minimal_skill_package(pkg_dir)
            sent: list[dict] = []
            calls = {"get_updates": 0, "delete_webhook": 0}

            def _send(url: str, payload: dict) -> bool:
                sent.append({"url": url, "payload": dict(payload)})
                return True

            def _fake_urlopen(req, timeout=0):
                full_url = str(getattr(req, "full_url", ""))
                if "deleteWebhook" in full_url:
                    calls["delete_webhook"] += 1
                    return _FakeHTTPResponse({"ok": True, "result": True})
                if "getUpdates" in full_url:
                    calls["get_updates"] += 1
                    if calls["get_updates"] == 1:
                        body = json.dumps(
                            {
                                "ok": False,
                                "error_code": 409,
                                "description": "Conflict: can't use getUpdates method while webhook is active",
                            }
                        ).encode("utf-8")
                        raise urllib.error.HTTPError(
                            url=full_url,
                            code=409,
                            msg="Conflict",
                            hdrs=None,
                            fp=io.BytesIO(body),
                        )
                    return _FakeHTTPResponse(_updates_payload(update_id=4493, text="hello after reset"))
                raise AssertionError(f"unexpected url: {full_url}")

            svc = PAPollingService(
                PAPollingServiceConfig(
                    data_dir=str(root / "data"),
                    bot_token="token-044",
                    workspace_id="ws044",
                    skill_ref=str(pkg_dir),
                    verify_asvp=False,
                ),
                send_func=_send,
            )

            with patch("agentos_next.apps.pa_polling_service.urllib.request.urlopen", side_effect=_fake_urlopen):
                out = svc.run_once(offset=None)

            self.assertTrue(out.get("ok"))
            self.assertEqual(out.get("processed"), 1)
            self.assertEqual(out.get("reply_sent"), 1)
            self.assertEqual(calls["delete_webhook"], 1)
            self.assertGreaterEqual(calls["get_updates"], 2)

    def test_polling_transient_ssl_error_retries_once(self) -> None:
        with tempfile.TemporaryDirectory(prefix="agentos_next_t044_ssl_retry_") as td:
            root = Path(td)
            pkg_dir = root / "pkg"
            make_minimal_skill_package(pkg_dir)
            sent: list[dict] = []
            calls = {"get_updates": 0}

            def _send(url: str, payload: dict) -> bool:
                sent.append({"url": url, "payload": dict(payload)})
                return True

            def _fake_urlopen(req, timeout=0):
                full_url = str(getattr(req, "full_url", ""))
                if "getUpdates" in full_url:
                    calls["get_updates"] += 1
                    if calls["get_updates"] == 1:
                        raise urllib.error.URLError(
                            "[SSL: UNEXPECTED_EOF_WHILE_READING] EOF occurred in violation of protocol (_ssl.c:1081)"
                        )
                    return _FakeHTTPResponse(_updates_payload(update_id=4494, text="retry success"))
                raise AssertionError(f"unexpected url: {full_url}")

            svc = PAPollingService(
                PAPollingServiceConfig(
                    data_dir=str(root / "data"),
                    bot_token="token-044",
                    workspace_id="ws044",
                    skill_ref=str(pkg_dir),
                    verify_asvp=False,
                ),
                send_func=_send,
            )

            with patch("agentos_next.apps.pa_polling_service.urllib.request.urlopen", side_effect=_fake_urlopen):
                out = svc.run_once(offset=None)

            self.assertTrue(out.get("ok"))
            self.assertEqual(out.get("processed"), 1)
            self.assertEqual(out.get("reply_sent"), 1)
            self.assertGreaterEqual(calls["get_updates"], 2)

    def test_polling_failed_execute_still_sends_fallback_reply(self) -> None:
        with tempfile.TemporaryDirectory(prefix="agentos_next_t044_fallback_") as td:
            root = Path(td)
            data_dir = root / "data"
            pkg_dir = root / "pkg"
            make_minimal_skill_package(pkg_dir)
            sent: list[dict] = []
            buf = io.StringIO()

            evidence = FileEvidenceStore(data_dir=data_dir)
            event_log = FileEventLog(data_dir=data_dir)
            event_log.write_once(
                workspace_id="ws044",
                event_id="tg_update_4495",
                envelope={"conversation_id": "12345", "schema_version": "1.0.0"},
            )
            err_ref = evidence.add_json(
                {
                    "error_code": "E_PROVIDER_BAD_RESPONSE",
                    "message": (
                        "provider transport error: codex request failed; "
                        'status=429; body_preview={"error":{"type":"usage_limit_reached"}}'
                    ),
                },
                kind="error",
            )

            outbox = OutboxItem(
                schema_version="1.0.0",
                stored_at_utc="2026-03-07T00:00:00Z",
                workspace_id="ws044",
                event_id="tg_update_4495",
                idempotency_key="idem_tg_4495",
                trace_id="tr_4495",
                turn_id="turn_4495",
                span_id="span_4495",
                execute_status="failed",
                execute_error_code="E_PROVIDER_BAD_RESPONSE",
                evidence_refs=(err_ref.ref,),
                reply_text="远端模型服务返回异常，请稍后再试。",
                deliveries=(
                    _send_message_delivery(
                        text="远端模型服务返回异常，请稍后再试。",
                        stage="blocker",
                        key="tg_update_4495",
                    ),
                ),
                metering_evidence_refs=(),
            )

            def _send(url: str, payload: dict) -> bool:
                sent.append({"url": url, "payload": dict(payload)})
                return True

            svc = PAPollingService(
                PAPollingServiceConfig(
                    data_dir=str(data_dir),
                    bot_token="token-044",
                    workspace_id="ws044",
                    skill_ref=str(pkg_dir),
                    verify_asvp=False,
                ),
                send_func=_send,
            )

            with contextlib.redirect_stdout(buf):
                with patch(
                    "agentos_next.apps.pa_polling_service.run_assistant_runtime_async",
                    return_value=AssistantLoopResult(
                        ok=False,
                        final_output=_send_message_delivery(
                            text="远端模型服务返回异常，请稍后再试。",
                            stage="blocker",
                            key="tg_update_4495",
                        ),
                        error_code="E_PROVIDER_BAD_RESPONSE",
                        steps=[],
                        trace=TraceContext(trace_id="tr_4495", turn_id="turn_4495", span_id="span_4495"),
                        evidence_refs=[err_ref.ref],
                        followup_plan_ref="",
                        followup_task_id=None,
                    ),
                ):
                    with patch(
                        "agentos_next.apps.pa_polling_service.urllib.request.urlopen",
                        return_value=_FakeHTTPResponse(_updates_payload(update_id=4495, text="retry me")),
                    ):
                        out = svc.run_once(offset=None)

            self.assertTrue(out.get("ok"))
            self.assertEqual(out.get("processed"), 1)
            self.assertEqual(out.get("reply_sent"), 1)
            self.assertEqual(out.get("rejected"), 0)
            msg_calls = [x for x in sent if str(x.get("url") or "").endswith("/sendMessage")]
            self.assertEqual(len(msg_calls), 1)
            self.assertEqual(msg_calls[0]["payload"].get("text"), "远端模型服务返回异常，请稍后再试。")
            log_text = buf.getvalue()
            self.assertIn("Runtime execution failed for update 4495", log_text)
            self.assertIn("Reply sent for update 4495", log_text)
            self.assertIn("status=429", log_text)
            self.assertIn("usage_limit_reached", log_text)

    def test_polling_send_failure_is_logged(self) -> None:
        with tempfile.TemporaryDirectory(prefix="agentos_next_t044_send_fail_") as td:
            root = Path(td)
            pkg_dir = root / "pkg"
            make_minimal_skill_package(pkg_dir)
            buf = io.StringIO()

            svc = PAPollingService(
                PAPollingServiceConfig(
                    data_dir=str(root / "data"),
                    bot_token="token-044",
                    workspace_id="ws044",
                    skill_ref=str(pkg_dir),
                    verify_asvp=False,
                ),
                send_func=lambda _url, _payload: False,
            )

            with contextlib.redirect_stdout(buf):
                with patch(
                    "agentos_next.apps.pa_polling_service.urllib.request.urlopen",
                    return_value=_FakeHTTPResponse(_updates_payload(update_id=4496, text="hello")),
                ):
                    out = svc.run_once(offset=None)

            self.assertFalse(out.get("ok"))
            self.assertEqual(out.get("reply_sent"), 0)
            self.assertEqual(out.get("rejected"), 1)
            self.assertEqual(out.get("error_code"), "E_PA_POLLING_FAILED")
            self.assertIn("Reply send failed for update 4496", buf.getvalue())

    def test_polling_send_failure_logs_runtime_and_delivery_layers(self) -> None:
        with tempfile.TemporaryDirectory(prefix="agentos_next_t044_runtime_send_fail_") as td:
            root = Path(td)
            data_dir = root / "data"
            pkg_dir = root / "pkg"
            make_minimal_skill_package(pkg_dir)
            buf = io.StringIO()

            evidence = FileEvidenceStore(data_dir=data_dir)
            err_ref = evidence.add_json(
                {
                    "error_code": "E_PROVIDER_BAD_RESPONSE",
                    "message": "provider transport error: upstream returned malformed payload",
                },
                kind="error",
            )

            def _send(_url: str, _payload: dict) -> bool:
                return False

            svc = PAPollingService(
                PAPollingServiceConfig(
                    data_dir=str(data_dir),
                    bot_token="token-044",
                    workspace_id="ws044",
                    skill_ref=str(pkg_dir),
                    verify_asvp=False,
                ),
                send_func=_send,
            )

            with contextlib.redirect_stdout(buf):
                with patch(
                    "agentos_next.apps.pa_polling_service.run_assistant_runtime_async",
                    return_value=AssistantLoopResult(
                        ok=False,
                        final_output=_send_message_delivery(
                            text="远端模型服务返回异常，请稍后再试。",
                            stage="blocker",
                            key="tg_update_4497",
                        ),
                        error_code="E_PROVIDER_BAD_RESPONSE",
                        steps=[],
                        trace=TraceContext(trace_id="tr_4497", turn_id="turn_4497", span_id="span_4497"),
                        evidence_refs=[err_ref.ref],
                        followup_plan_ref="",
                        followup_task_id=None,
                    ),
                ):
                    with patch(
                        "agentos_next.apps.pa_polling_service.urllib.request.urlopen",
                        return_value=_FakeHTTPResponse(_updates_payload(update_id=4497, text="hello")),
                    ):
                        out = svc.run_once(offset=None)

            self.assertFalse(out.get("ok"))
            self.assertEqual(out.get("error_code"), "E_PA_POLLING_FAILED")
            log_text = buf.getvalue()
            self.assertIn("Runtime execution failed for update 4497", log_text)
            self.assertIn("Reply send failed for update 4497", log_text)

    def test_polling_hold_runtime_synthesizes_hitl_delivery(self) -> None:
        with tempfile.TemporaryDirectory(prefix="agentos_next_t044_hold_delivery_") as td:
            root = Path(td)
            data_dir = root / "data"
            pkg_dir = root / "pkg"
            make_minimal_skill_package(pkg_dir)
            sent: list[dict[str, Any]] = []
            buf = io.StringIO()

            evidence = FileEvidenceStore(data_dir=data_dir)
            err_ref = evidence.add_json(
                {
                    "error_code": "E_HITL_REQUIRED",
                    "message": "execution paused for HITL after budget exhaustion",
                },
                kind="error",
            )

            def _send(url: str, payload: dict[str, Any]) -> bool:
                sent.append({"url": url, "payload": dict(payload)})
                return True

            svc = PAPollingService(
                PAPollingServiceConfig(
                    data_dir=str(data_dir),
                    bot_token="token-044",
                    workspace_id="ws044",
                    skill_ref=str(pkg_dir),
                    verify_asvp=False,
                ),
                send_func=_send,
            )

            with contextlib.redirect_stdout(buf):
                with patch(
                    "agentos_next.apps.pa_polling_service.run_assistant_runtime_async",
                    return_value=AssistantLoopResult(
                        ok=False,
                        final_output=None,
                        error_code="E_HITL_REQUIRED",
                        steps=[],
                        trace=TraceContext(trace_id="tr_hold", turn_id="turn_hold", span_id="span_hold"),
                        evidence_refs=[err_ref.ref],
                        followup_plan_ref="",
                        followup_task_id=None,
                        delivery_state="hold",
                    ),
                ):
                    with patch(
                        "agentos_next.apps.pa_polling_service.urllib.request.urlopen",
                        return_value=_FakeHTTPResponse(_updates_payload(update_id=4498, text="可以叫我王五")),
                    ):
                        out = svc.run_once(offset=None)

            self.assertTrue(out.get("ok"))
            self.assertEqual(out.get("reply_sent"), 1)
            msg_calls = [x for x in sent if str(x.get("url") or "").endswith("/sendMessage")]
            self.assertEqual(len(msg_calls), 1)
            self.assertEqual(msg_calls[0]["payload"].get("text"), "这次处理已暂停，需要人工继续处理后才能完成。")

            outbox = FileOutboxStore(data_dir=data_dir).get(workspace_id="ws044", event_id="tg_update_4498")
            self.assertIsNotNone(outbox)
            assert outbox is not None
            self.assertEqual(outbox.execute_status, "hold")
            self.assertEqual(outbox.reply_text, "这次处理已暂停，需要人工继续处理后才能完成。")
            self.assertEqual(outbox.deliveries[0].get("delivery_stage"), "hold")

            log_text = buf.getvalue()
            self.assertIn("Runtime execution failed for update 4498", log_text)
            self.assertIn("Reply sent for update 4498", log_text)

    def test_polling_memory_context_is_forwarded_to_assistant_runtime(self) -> None:
        with tempfile.TemporaryDirectory(prefix="agentos_next_t044_memctx_") as td:
            root = Path(td)
            data_dir = root / "data"
            pkg_dir = root / "pkg"
            make_minimal_skill_package(pkg_dir)
            captured: dict[str, Any] = {}
            sample_context = {
                "schema_version": "2.0.0",
                "l0_continuity": {"workspace_id": "ws044", "conversation_id": "12345"},
                "l1_query": {"query": "hello mem", "intent": "generic", "scope": {"workspace_id": "ws044"}},
                "l2_hits": [],
                "conflicts": [],
                "retrieval_ref": "ev_ctx_1",
            }

            async def _fake_runtime(ingress, **_kwargs):
                captured["memory_context"] = ingress.loop_request.memory_context
                captured["response_language"] = ingress.loop_request.response_language
                return AssistantLoopResult(
                    ok=True,
                    final_output=_send_message_delivery(text="收到", key="tg_update_44965"),
                    error_code=None,
                    steps=[],
                    trace=TraceContext(trace_id="tr_mem", turn_id="turn_mem", span_id="span_mem"),
                    evidence_refs=[],
                    followup_plan_ref="",
                    followup_task_id=None,
                )

            svc = PAPollingService(
                PAPollingServiceConfig(
                    data_dir=str(data_dir),
                    bot_token="token-044",
                    workspace_id="ws044",
                    skill_ref=str(pkg_dir),
                    verify_asvp=False,
                    memory_context_enabled=True,
                    memory_context_retrieval_limit=4,
                    response_language="zh-CN",
                ),
                send_func=lambda _url, _payload: True,
            )

            with patch(
                "agentos_next.apps.pa_polling_service._AssistantRuntimeDispatcher._build_memory_context",
                return_value=(sample_context, ("ev_ctx_1",), None),
            ):
                with patch(
                    "agentos_next.apps.pa_polling_service.run_assistant_runtime_async",
                    side_effect=_fake_runtime,
                ):
                    with patch(
                        "agentos_next.apps.pa_polling_service.urllib.request.urlopen",
                        return_value=_FakeHTTPResponse(_updates_payload(update_id=44965, text="hello mem")),
                    ):
                        out = svc.run_once(offset=None)

            self.assertTrue(out.get("ok"))
            self.assertEqual(captured.get("memory_context"), sample_context)
            self.assertEqual(captured.get("response_language"), "zh-CN")

    def test_polling_without_memory_context_does_not_inject_memory_context(self) -> None:
        with tempfile.TemporaryDirectory(prefix="agentos_next_t044_inline_memctx_") as td:
            root = Path(td)
            pkg_dir = root / "pkg"
            data_dir = root / "data"
            make_minimal_skill_package(pkg_dir)
            captured: dict[str, Any] = {}

            async def _fake_runtime(ingress, **_kwargs):
                captured["memory_context"] = ingress.loop_request.memory_context
                return AssistantLoopResult(
                    ok=True,
                    final_output=_send_message_delivery(text="收到", key="tg_update_44966"),
                    error_code=None,
                    steps=[],
                    trace=TraceContext(trace_id="tr_inline_mem", turn_id="turn_inline_mem", span_id="span_inline_mem"),
                    evidence_refs=[],
                    followup_plan_ref="",
                    followup_task_id=None,
                )

            svc = PAPollingService(
                PAPollingServiceConfig(
                    data_dir=str(data_dir),
                    bot_token="token-044",
                    workspace_id="ws044",
                    skill_ref=str(pkg_dir),
                    verify_asvp=False,
                    memory_context_enabled=False,
                ),
                send_func=lambda _url, _payload: True,
            )

            with patch(
                "agentos_next.apps.pa_polling_service.run_assistant_runtime_async",
                side_effect=_fake_runtime,
            ):
                with patch(
                    "agentos_next.apps.pa_polling_service.urllib.request.urlopen",
                    return_value=_FakeHTTPResponse(_updates_payload(update_id=44966, text="我是谁")),
                ):
                    out = svc.run_once(offset=None)

            self.assertTrue(out.get("ok"))
            mc = captured.get("memory_context")
            self.assertIsNone(mc)

    def test_polling_restores_streaming_to_assistant_runtime(self) -> None:
        with tempfile.TemporaryDirectory(prefix="agentos_next_t044_stream_rt_") as td:
            root = Path(td)
            pkg_dir = root / "pkg"
            data_dir = root / "data"
            make_minimal_skill_package(pkg_dir)
            sent: list[dict] = []
            fake_stream_sessions: list[Any] = []
            captured: dict[str, Any] = {}

            class _FakeStreamSession:
                def __init__(self) -> None:
                    self.events: list[dict[str, Any]] = []
                    self.progress: list[str] = []
                    self.finished_with: str | None = None

                def handle_event(self, event: dict[str, Any]) -> None:
                    self.events.append(dict(event))

                def update_progress(self, text: str) -> bool:
                    self.progress.append(str(text))
                    return True

                def finish(self, *, final_text: str) -> bool:
                    self.finished_with = str(final_text)
                    return True

            async def _fake_runtime(ingress, **_kwargs):
                captured["stream_callback_present"] = callable(ingress.loop_request.llm_stream_callback)
                captured["telegram_stream_session"] = ingress.loop_request.telegram_stream_session
                if callable(ingress.loop_request.llm_stream_callback):
                    ingress.loop_request.llm_stream_callback({"type": "start"})
                    ingress.loop_request.llm_stream_callback({"type": "delta", "delta": "{\"reply\":\"流式"})
                    ingress.loop_request.llm_stream_callback({"type": "completed"})
                return AssistantLoopResult(
                    ok=True,
                    final_output=_send_message_delivery(text="流式完成", key="tg_update_44966"),
                    error_code=None,
                    steps=[],
                    trace=TraceContext(trace_id="tr_stream", turn_id="turn_stream", span_id="span_stream"),
                    evidence_refs=[],
                    followup_plan_ref="",
                    followup_task_id=None,
                )

            def _send(url: str, payload: dict) -> bool:
                sent.append({"url": url, "payload": dict(payload)})
                return True

            svc = PAPollingService(
                PAPollingServiceConfig(
                    data_dir=str(data_dir),
                    bot_token="token-044",
                    workspace_id="ws044",
                    skill_ref=str(pkg_dir),
                    verify_asvp=False,
                ),
                send_func=_send,
            )
            svc._reply.streaming_enabled = True

            with patch(
                "agentos_next.apps.pa_polling_service.TelegramReplyAdapter.start_stream_session",
                side_effect=lambda chat_id, initial_text="处理中...": fake_stream_sessions.append(_FakeStreamSession()) or fake_stream_sessions[-1],
            ):
                with patch(
                    "agentos_next.apps.pa_polling_service.run_assistant_runtime_async",
                    side_effect=_fake_runtime,
                ):
                    with patch(
                        "agentos_next.apps.pa_polling_service.urllib.request.urlopen",
                        return_value=_FakeHTTPResponse(_updates_payload(update_id=44966, text="stream please")),
                    ):
                        out = svc.run_once(offset=None)

            self.assertTrue(out.get("ok"))
            self.assertFalse(captured.get("stream_callback_present"))
            self.assertIsNone(captured.get("telegram_stream_session"))
            self.assertEqual(len(fake_stream_sessions), 0)
            msg_calls = [x for x in sent if str(x.get("url") or "").endswith("/sendMessage")]
            self.assertEqual(len(msg_calls), 1)
            self.assertEqual(msg_calls[0]["payload"].get("text"), "流式完成")

    def test_polling_skips_outbox_send_when_reply_was_streamed_live(self) -> None:
        with tempfile.TemporaryDirectory(prefix="agentos_next_t044_stream_live_") as td:
            root = Path(td)
            pkg_dir = root / "pkg"
            data_dir = root / "data"
            make_minimal_skill_package(pkg_dir)
            sent: list[dict] = []

            streamed_outbox = OutboxItem(
                schema_version="1.0.0",
                stored_at_utc="2026-03-07T00:00:00Z",
                workspace_id="ws044",
                event_id="tg_update_4497",
                idempotency_key="idem_tg_4497",
                trace_id="tr_4497",
                turn_id="turn_4497",
                span_id="span_4497",
                execute_status="accepted",
                execute_error_code=None,
                evidence_refs=(),
                reply_text="final streamed reply",
                deliveries=(
                    _send_message_delivery(text="final streamed reply", key="tg_update_4497"),
                ),
                metering_evidence_refs=(),
                reply_sent_live=True,
                reply_delivery_mode="telegram_stream",
            )

            def _send(url: str, payload: dict) -> bool:
                sent.append({"url": url, "payload": dict(payload)})
                return True

            svc = PAPollingService(
                PAPollingServiceConfig(
                    data_dir=str(data_dir),
                    bot_token="token-044",
                    workspace_id="ws044",
                    skill_ref=str(pkg_dir),
                    verify_asvp=False,
                ),
                send_func=_send,
            )

            with patch(
                "agentos_next.apps.pa_polling_service._AssistantRuntimeDispatcher._build_outbox_item",
                return_value=streamed_outbox,
            ):
                with patch(
                    "agentos_next.apps.pa_polling_service.urllib.request.urlopen",
                    return_value=_FakeHTTPResponse(_updates_payload(update_id=4497, text="streamed already")),
                ):
                    out = svc.run_once(offset=None)

            self.assertTrue(out.get("ok"))
            self.assertEqual(out.get("reply_sent"), 1)
            msg_calls = [x for x in sent if str(x.get("url") or "").endswith("/sendMessage")]
            self.assertEqual(len(msg_calls), 0, msg="live streamed replies must not send final outbox again")

    def test_polling_auto_scheduler_tick_fires_due_task(self) -> None:
        with tempfile.TemporaryDirectory(prefix="agentos_next_t044_tick_") as td:
            root = Path(td)
            data_dir = root / "data"
            pkg_dir = root / "pkg"
            make_minimal_skill_package(pkg_dir)

            store = FileSchedulerStore(data_dir=data_dir)
            task = store.create_at(
                workspace_id="ws044",
                run_at="2000-01-01T00:00:00Z",
                execute_request_draft={
                    "operator_ref": "builtin://channel.send_message",
                    "arguments": {
                        "text": "提醒你：喝水",
                        "metadata": {"channel": "telegram", "conversation_id": "12345"},
                    },
                    "deadline_ms": 5000,
                    "policy_context": {
                        "capabilities": [{"name": "channel_send", "scope": "workspace"}],
                    },
                    "preferred_target": "local",
                },
                idempotency_root="sched:test_t044",
            )

            svc = PAPollingService(
                PAPollingServiceConfig(
                    data_dir=str(data_dir),
                    bot_token="token-044",
                    workspace_id="ws044",
                    skill_ref=str(pkg_dir),
                    verify_asvp=False,
                    scheduler_auto_tick_enabled=True,
                    scheduler_tick_max_fires=10,
                ),
                send_func=lambda _url, _payload: True,
            )

            with patch(
                "urllib.request.urlopen",
                side_effect=lambda req, timeout=0: (
                    _FakeHTTPResponse({"ok": True, "result": {"message_id": 99}})
                    if "sendMessage" in str(getattr(req, "full_url", ""))
                    else _FakeHTTPResponse({"ok": True, "result": []})
                ),
            ):
                    out = svc.run_once(offset=None)

            self.assertTrue(out.get("ok"))
            self.assertEqual(out.get("processed"), 0)
            self.assertEqual(out.get("scheduler_fired"), 1)
            task_after = store.get(task_id=task.task_id)
            self.assertIsNotNone(task_after)
            self.assertEqual(task_after.status, "done")


if __name__ == "__main__":  # pragma: no cover
    unittest.main(verbosity=2)
