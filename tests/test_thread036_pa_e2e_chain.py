from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

# Make this test runnable via:
#   PYTHONPATH=src python3 -m unittest tests/test_thread036_pa_e2e_chain.py -v
ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
TESTS = ROOT / "tests"
for p in (str(TESTS), str(SRC)):
    if p not in sys.path:
        sys.path.insert(0, p)

from admission_helpers import make_minimal_skill_package
from fixtures.telegram_webhook_fixtures import (
    generate_secret_token_fixture,
    generate_telegram_webhook_fixture,
)

from agentos_next.apps.telegram_connector import TelegramChannelAdapter
from agentos_next.kernel.evidence_store import FileEvidenceStore
from agentos_next.pa.ev1_runtime import EV1Config, EV1Runtime


class _CaptureDispatcher:
    def __init__(self) -> None:
        self.last_envelope = None
        self.last_idem = None

    def dispatch(self, envelope, idempotency_key: str) -> None:  # noqa: ANN001
        self.last_envelope = envelope
        self.last_idem = idempotency_key


def _build_envelope_from_webhook(*, update_id: int, replay_mode: bool) -> tuple[object | None, dict]:
    secret = generate_secret_token_fixture()
    cap = _CaptureDispatcher()
    adapter = TelegramChannelAdapter(expected_secret_token=secret, kernel_dispatcher=cap)
    payload = generate_telegram_webhook_fixture(update_id=update_id)
    code, body = adapter.handle_webhook(
        payload_str=payload,
        secret_token=secret,
        workspace_id="ws_pa",
        replay_mode=replay_mode,
    )
    return cap.last_envelope, {"http_status": code, "body": body, "idempotency_key": cap.last_idem}


class TestThread036PAE2EChain(unittest.TestCase):
    def test_happy_path_creates_outbox_and_metering(self) -> None:
        with tempfile.TemporaryDirectory(prefix="agentos_next_t036_ok_") as td:
            root = Path(td)
            pkg_dir = root / "pkg"
            data_dir = root / "data"
            make_minimal_skill_package(pkg_dir)

            env, http = _build_envelope_from_webhook(update_id=3000, replay_mode=False)
            self.assertEqual(http["http_status"], 200)
            self.assertIsNotNone(env)

            rt = EV1Runtime(EV1Config(data_dir=data_dir, skill_ref=str(pkg_dir), message_input_key="q"))
            out = rt.handle_envelope(env, replay_mode=False)
            self.assertTrue(out.get("ok"))
            ob = out.get("outbox") or {}
            self.assertEqual(ob.get("event_id"), "tg_update_3000")
            self.assertEqual(ob.get("idempotency_key"), "idem_tg_3000")

            mrefs = ob.get("metering_evidence_refs") or []
            self.assertEqual(len(mrefs), 1)
            ev = FileEvidenceStore(data_dir=data_dir)
            blob = ev.get_blob(str(mrefs[0]))
            self.assertIsNotNone(blob)
            payload = json.loads(blob.content.decode("utf-8"))
            self.assertEqual(payload.get("type"), "metering_v0")
            self.assertEqual(payload.get("event_id"), "tg_update_3000")

    def test_same_update_id_is_dedup_short_circuit(self) -> None:
        with tempfile.TemporaryDirectory(prefix="agentos_next_t036_dedup_") as td:
            root = Path(td)
            pkg_dir = root / "pkg"
            data_dir = root / "data"
            make_minimal_skill_package(pkg_dir)

            env1, _ = _build_envelope_from_webhook(update_id=3001, replay_mode=False)
            env2, _ = _build_envelope_from_webhook(update_id=3001, replay_mode=False)
            self.assertIsNotNone(env1)
            self.assertIsNotNone(env2)

            rt = EV1Runtime(EV1Config(data_dir=data_dir, skill_ref=str(pkg_dir), message_input_key="q"))
            out1 = rt.handle_envelope(env1, replay_mode=False)
            out2 = rt.handle_envelope(env2, replay_mode=False)
            self.assertTrue(out1.get("ok"))
            self.assertTrue(out2.get("ok"))
            self.assertFalse(out1.get("dedup"))
            self.assertTrue(out2.get("dedup"))
            self.assertEqual(out1.get("outbox"), out2.get("outbox"))

    def test_replay_mode_double_zero_side_effects(self) -> None:
        from unittest.mock import patch

        with tempfile.TemporaryDirectory(prefix="agentos_next_t036_replay_") as td:
            root = Path(td)
            pkg_dir = root / "pkg"
            data_dir = root / "data"
            make_minimal_skill_package(pkg_dir)

            # CH1 replay-mode: adapter should not dispatch.
            env, http = _build_envelope_from_webhook(update_id=3002, replay_mode=True)
            self.assertEqual(http["http_status"], 200)
            self.assertIsNone(env)

            rt = EV1Runtime(EV1Config(data_dir=data_dir, skill_ref=str(pkg_dir), message_input_key="q"))
            files_before = len(list(data_dir.rglob("*"))) if data_dir.exists() else 0

            # EV1 replay-mode: strict deny, and must not create additional side effects beyond constructor setup.
            with patch("pathlib.Path.mkdir", side_effect=RuntimeError("mkdir prohibited")):
                out = rt.handle_envelope(
                    {
                        "schema_version": "1.0.0",
                        "event_id": "tg_update_3002",
                        "idempotency_key": "idem_tg_3002",
                        "source": "telegram",
                        "received_at_utc": "2026-01-01T00:00:00Z",
                        "workspace_id": "ws_pa",
                        "conversation_id": "c",
                        "sender_id": "u",
                        "message_text": "hi",
                        "budget_slice_remote_llm_calls": 10,
                    },
                    replay_mode=True,
                )
            self.assertFalse(out.get("ok"))
            files_after = len(list(data_dir.rglob("*"))) if data_dir.exists() else 0
            self.assertEqual(files_before, files_after)


if __name__ == "__main__":  # pragma: no cover
    unittest.main(verbosity=2)
