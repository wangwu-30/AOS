from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import bootstrap  # noqa: F401
from admission_helpers import make_minimal_skill_package
from fixtures.telegram_webhook_fixtures import (
    generate_secret_token_fixture,
    generate_telegram_webhook_fixture,
)

from agentos_next.apps.telegram_connector import TelegramChannelAdapter
from agentos_next.kernel.evidence_store import FileEvidenceStore
from agentos_next.pa.ev1_runtime import PA_EV_ERROR_REPLAY_DENY, EV1Config, EV1Runtime


class _CaptureDispatcher:
    def __init__(self) -> None:
        self.last_envelope = None

    def dispatch(self, envelope, idempotency_key: str) -> None:  # noqa: ANN001
        self.last_envelope = envelope


def _make_envelope(*, update_id: int) -> object:
    secret = generate_secret_token_fixture()
    cap = _CaptureDispatcher()
    adapter = TelegramChannelAdapter(expected_secret_token=secret, kernel_dispatcher=cap)
    payload = generate_telegram_webhook_fixture(update_id=update_id)
    code, body = adapter.handle_webhook(payload_str=payload, secret_token=secret, workspace_id="ws_pa")
    assert code == 200, body
    assert cap.last_envelope is not None
    return cap.last_envelope


class TestThread035PAMTR0MeteringEvidence(unittest.TestCase):
    def test_metering_evidence_written_and_replayable(self) -> None:
        with tempfile.TemporaryDirectory(prefix="agentos_next_t035_meter_") as td:
            root = Path(td)
            pkg_dir = root / "pkg"
            data_dir = root / "data"
            make_minimal_skill_package(pkg_dir)

            env = _make_envelope(update_id=2000)
            rt = EV1Runtime(EV1Config(data_dir=data_dir, skill_ref=str(pkg_dir), message_input_key="q"))
            out = rt.handle_envelope(env, replay_mode=False)
            self.assertTrue(out.get("ok"))
            ob = out.get("outbox") or {}
            mrefs = ob.get("metering_evidence_refs") or []
            self.assertEqual(len(mrefs), 1)

            ev = FileEvidenceStore(data_dir=data_dir)
            blob = ev.get_blob(str(mrefs[0]))
            self.assertIsNotNone(blob)
            self.assertEqual(blob.content_type, "application/json")
            payload = json.loads(blob.content.decode("utf-8"))
            self.assertEqual(payload.get("type"), "metering_v0")
            self.assertEqual(payload.get("workspace_id"), "ws_pa")
            self.assertEqual(payload.get("event_id"), "tg_update_2000")
            self.assertIn("trace_id", payload)
            self.assertIn("turn_id", payload)

    def test_replay_mode_no_metering_evidence(self) -> None:
        with tempfile.TemporaryDirectory(prefix="agentos_next_t035_replay_") as td:
            root = Path(td)
            pkg_dir = root / "pkg"
            data_dir = root / "data"
            make_minimal_skill_package(pkg_dir)

            env = _make_envelope(update_id=2001)
            rt = EV1Runtime(EV1Config(data_dir=data_dir, skill_ref=str(pkg_dir), message_input_key="q"))
            out = rt.handle_envelope(env, replay_mode=True)
            self.assertFalse(out.get("ok"))
            self.assertEqual(out.get("error_code"), PA_EV_ERROR_REPLAY_DENY)
            self.assertFalse((data_dir / "evidence").exists())


if __name__ == "__main__":  # pragma: no cover
    unittest.main(verbosity=2)

