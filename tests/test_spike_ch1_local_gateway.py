from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import bootstrap  # noqa: F401

from agentos_next.apps.channel_gateway import ChannelGatewayConfig, ChannelGatewayService
from agentos_next.cli import _channel_http_process_body
from agentos_next.llm.backend import LocalMockLLMBackend


class TestSpikeCH1LocalGateway(unittest.TestCase):
    def _service(self, *, data_dir: str, backend: str = "local_mock", replay_mode: bool = False) -> ChannelGatewayService:
        root = Path(__file__).resolve().parents[1]
        return ChannelGatewayService(
            ChannelGatewayConfig(
                data_dir=data_dir,
                operator_ref=str(root / "examples" / "skills" / "personal_assistant_brief"),
                keys_dir=str(root / "examples" / "keys"),
                verify_asvp=True,
                target="auto",
                backend=backend,
                model=None,
                remote_calls_armed=True if backend == "codex_oauth" else False,
                allow_network_egress=True if backend == "codex_oauth" else False,
                approved_by_human=False,
                replay_mode=bool(replay_mode),
                workspace_id="local",
                deadline_ms=60000,
            )
        )

    def test_ch1_happy_path_returns_stable_contract_and_writes_trace(self) -> None:
        with tempfile.TemporaryDirectory(prefix="agentos_next_ch1_happy_") as td:
            service = self._service(data_dir=td)
            raw = json.dumps({"message": "hello", "trace_id": "tr_ch1_happy"}, ensure_ascii=False).encode("utf-8")
            code, out = _channel_http_process_body(raw_body=raw, service=service)

            self.assertEqual(code, 200)
            self.assertEqual(
                set(out.keys()),
                {"ok", "status", "error_code", "trace_id", "turn_id", "span_id", "evidence_refs", "artifact_refs"},
            )
            self.assertTrue(out["ok"])
            self.assertEqual(out["trace_id"], "tr_ch1_happy")

            trace_path = Path(td) / "traces" / "tr_ch1_happy.jsonl"
            self.assertTrue(trace_path.exists())

    def test_ch1_invalid_json_returns_400_and_stable_error(self) -> None:
        with tempfile.TemporaryDirectory(prefix="agentos_next_ch1_badjson_") as td:
            service = self._service(data_dir=td)
            code, out = _channel_http_process_body(raw_body=b"{", service=service)
            self.assertEqual(code, 400)
            self.assertEqual(out["ok"], False)
            self.assertEqual(out["error_code"], "E_BAD_CHANNEL_INPUT")
            self.assertEqual(
                set(out.keys()),
                {"ok", "status", "error_code", "trace_id", "turn_id", "span_id", "evidence_refs", "artifact_refs"},
            )

    def test_ch1_model_override_via_policy_context_model(self) -> None:
        seen: dict[str, str | None] = {}
        orig = LocalMockLLMBackend.complete_json

        def wrapped(
            self: LocalMockLLMBackend,
            *,
            prompt: str,
            json_schema: dict,
            safety,
            model_id: str | None = None,
            stream_callback=None,
        ):
            seen["model_id"] = model_id
            return orig(
                self,
                prompt=prompt,
                json_schema=json_schema,
                safety=safety,
                model_id=model_id,
                stream_callback=stream_callback,
            )

        with tempfile.TemporaryDirectory(prefix="agentos_next_ch1_model_") as td:
            service = self._service(data_dir=td)
            raw = json.dumps(
                {"message": "hello", "policy_context": {"model": "ch1_override_model"}},
                ensure_ascii=False,
            ).encode("utf-8")
            with patch.object(LocalMockLLMBackend, "complete_json", wrapped):
                code, out = _channel_http_process_body(raw_body=raw, service=service)
            self.assertEqual(code, 200)
            self.assertTrue(out.get("ok"))
            self.assertEqual(seen.get("model_id"), "ch1_override_model")

    def test_ch1_idempotency_replay_does_not_append_trace(self) -> None:
        with tempfile.TemporaryDirectory(prefix="agentos_next_ch1_idem_") as td:
            service = self._service(data_dir=td)
            payload = {
                "message": "hello",
                "workspace_id": "ws_ch1",
                "idempotency_key": "idem_ch1_1",
                "trace_id": "tr_ch1_idem",
                "turn_id": "turn_ch1_idem",
                "span_id": "span_ch1_idem",
            }
            raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")

            code1, out1 = _channel_http_process_body(raw_body=raw, service=service)
            trace_path = Path(td) / "traces" / "tr_ch1_idem.jsonl"
            lines_before = trace_path.read_text(encoding="utf-8").splitlines()
            code2, out2 = _channel_http_process_body(raw_body=raw, service=service)
            lines_after = trace_path.read_text(encoding="utf-8").splitlines()

            self.assertEqual(code1, 200)
            self.assertEqual(code2, 200)
            self.assertEqual(out1, out2)
            self.assertEqual(lines_before, lines_after)

    def test_ch1_replay_mode_blocks_remote_side_effects(self) -> None:
        with tempfile.TemporaryDirectory(prefix="agentos_next_ch1_replay_") as td:
            service = self._service(data_dir=td, backend="codex_oauth", replay_mode=True)
            raw = json.dumps({"message": "hello"}, ensure_ascii=False).encode("utf-8")
            code, out = _channel_http_process_body(raw_body=raw, service=service)
            self.assertEqual(code, 200)
            self.assertFalse(out.get("ok"))
            self.assertEqual(out.get("error_code"), "E_REPLAY_REMOTE_DISABLED")


if __name__ == "__main__":  # pragma: no cover
    unittest.main(verbosity=2)
