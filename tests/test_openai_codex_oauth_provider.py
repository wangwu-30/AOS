from __future__ import annotations

import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
from typing import Any, Mapping, Optional
from unittest.mock import patch

from agentos_next.llm.openai_codex_oauth import (
    HttpResponse,
    OpenAICodexOAuthProvider,
    RemoteCallsDisabledError,
)


class FakeTransport:
    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []
        self._responses: dict[tuple[str, str], HttpResponse] = {}

    def add_response(self, *, method: str, url: str, status: int, json_body: Any) -> None:
        body = json.dumps(json_body, ensure_ascii=True).encode("utf-8")
        self._responses[(method.upper(), url)] = HttpResponse(
            status=status,
            headers={"Content-Type": "application/json"},
            body=body,
        )

    def request(
        self,
        *,
        method: str,
        url: str,
        headers: Mapping[str, str],
        body: Optional[bytes],
        timeout_s: float,
    ) -> HttpResponse:
        self.requests.append(
            {"method": method.upper(), "url": url, "headers": dict(headers), "body": body, "timeout_s": timeout_s}
        )
        key = (method.upper(), url)
        if key not in self._responses:
            raise AssertionError(f"no fake response registered for {key}")
        return self._responses[key]


class TestOpenAICodexOAuthProvider(unittest.TestCase):
    def test_allow_remote_gate_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            token_path = Path(td) / "openai_oauth_token.json"
            token_path.write_text(json.dumps({"access_token": "x", "expires_at": 9999999999}), encoding="utf-8")
            p = OpenAICodexOAuthProvider(
                remote_calls_armed=False,
                allow_network_egress=False,
                token_path=token_path,
                transport=FakeTransport(),
            )
            with self.assertRaises(RemoteCallsDisabledError):
                p.codex_responses({"input": "hi"})

    def test_refresh_when_expired_then_calls_codex(self) -> None:
        now = 1_700_000_000.0
        refresh_url = "https://auth.openai.com/oauth/token"
        codex_url = "https://chatgpt.com/backend-api/codex/responses"

        with tempfile.TemporaryDirectory() as td:
            token_path = Path(td) / "openai_oauth_token.json"
            token_path.write_text(
                json.dumps(
                    {
                        "access_token": "old_access",
                        "refresh_token": "rtok",
                        "expires_at": int(now - 10),
                    }
                ),
                encoding="utf-8",
            )

            ft = FakeTransport()
            ft.add_response(
                method="POST",
                url=refresh_url,
                status=200,
                json_body={"access_token": "new_access", "expires_in": 3600, "refresh_token": "rtok2"},
            )
            ft.add_response(method="POST", url=codex_url, status=200, json_body={"id": "resp_1"})

            p = OpenAICodexOAuthProvider(
                remote_calls_armed=True,
                allow_network_egress=True,
                token_path=token_path,
                refresh_endpoint=refresh_url,
                codex_endpoint=codex_url,
                transport=ft,
                now_fn=lambda: now,
                refresh_skew_s=60.0,
            )
            out = p.codex_responses({"input": "ping"})
            self.assertEqual(out["id"], "resp_1")

            self.assertEqual([r["url"] for r in ft.requests], [refresh_url, codex_url])

            # Refresh call uses x-www-form-urlencoded and sends refresh_token.
            refresh_req = ft.requests[0]
            self.assertEqual(refresh_req["headers"]["Content-Type"], "application/x-www-form-urlencoded")
            self.assertIn(b"grant_type=refresh_token", refresh_req["body"])
            self.assertIn(b"refresh_token=rtok", refresh_req["body"])

            codex_req = ft.requests[1]
            self.assertEqual(codex_req["headers"]["Authorization"], "Bearer new_access")

            persisted = json.loads(token_path.read_text(encoding="utf-8"))
            self.assertEqual(persisted["access_token"], "new_access")
            self.assertEqual(persisted["refresh_token"], "rtok2")
            self.assertGreaterEqual(persisted["expires_at"], int(now + 3500))

    def test_no_refresh_when_token_is_fresh(self) -> None:
        now = 1_700_000_000.0
        refresh_url = "https://auth.openai.com/oauth/token"
        codex_url = "https://chatgpt.com/backend-api/codex/responses"

        with tempfile.TemporaryDirectory() as td:
            token_path = Path(td) / "openai_oauth_token.json"
            token_path.write_text(
                json.dumps(
                    {
                        "access_token": "access_ok",
                        "refresh_token": "rtok",
                        "expires_at": int(now + 10_000),
                    }
                ),
                encoding="utf-8",
            )

            ft = FakeTransport()
            # Intentionally do not register a refresh response; refresh must not be called.
            ft.add_response(method="POST", url=codex_url, status=200, json_body={"ok": True})

            p = OpenAICodexOAuthProvider(
                remote_calls_armed=True,
                allow_network_egress=True,
                token_path=token_path,
                refresh_endpoint=refresh_url,
                codex_endpoint=codex_url,
                transport=ft,
                now_fn=lambda: now,
                refresh_skew_s=60.0,
            )
            out = p.codex_responses({"input": "ping"})
            self.assertTrue(out["ok"])

            self.assertEqual(len(ft.requests), 1)
            self.assertEqual(ft.requests[0]["url"], codex_url)
            self.assertEqual(ft.requests[0]["headers"]["Authorization"], "Bearer access_ok")

    def test_account_id_header_is_sent_when_present(self) -> None:
        now = 1_700_000_000.0
        codex_url = "https://chatgpt.com/backend-api/codex/responses"
        with tempfile.TemporaryDirectory() as td:
            token_path = Path(td) / "openai_oauth_token.json"
            token_path.write_text(
                json.dumps(
                    {
                        "access_token": "access_ok",
                        "refresh_token": "rtok",
                        "expires_at": int(now + 10_000),
                        "account_id": "acct_123",
                    }
                ),
                encoding="utf-8",
            )
            ft = FakeTransport()
            ft.add_response(method="POST", url=codex_url, status=200, json_body={"ok": True})
            p = OpenAICodexOAuthProvider(
                remote_calls_armed=True,
                allow_network_egress=True,
                token_path=token_path,
                codex_endpoint=codex_url,
                transport=ft,
                now_fn=lambda: now,
            )
            _ = p.codex_responses({"input": "ping"})
            self.assertEqual(ft.requests[0]["headers"]["ChatGPT-Account-Id"], "acct_123")

    def test_nested_tokens_layout_is_supported(self) -> None:
        now = 1_700_000_000.0
        codex_url = "https://chatgpt.com/backend-api/codex/responses"
        with tempfile.TemporaryDirectory() as td:
            token_path = Path(td) / "auth.json"
            token_path.write_text(
                json.dumps(
                    {
                        "auth_mode": "chatgpt",
                        "tokens": {
                            "access_token": "nested_access_ok",
                            "refresh_token": "nested_rtok",
                            "expires_at": int(now + 10_000),
                            "account_id": "acct_nested_123",
                        },
                    }
                ),
                encoding="utf-8",
            )
            ft = FakeTransport()
            ft.add_response(method="POST", url=codex_url, status=200, json_body={"ok": True})
            p = OpenAICodexOAuthProvider(
                remote_calls_armed=True,
                allow_network_egress=True,
                token_path=token_path,
                codex_endpoint=codex_url,
                transport=ft,
                now_fn=lambda: now,
            )
            out = p.codex_responses({"input": "ping"})
            self.assertTrue(out["ok"])
            self.assertEqual(ft.requests[0]["headers"]["Authorization"], "Bearer nested_access_ok")
            self.assertEqual(ft.requests[0]["headers"]["ChatGPT-Account-Id"], "acct_nested_123")

    def test_sse_callback_receives_deltas(self) -> None:
        now = 1_700_000_000.0
        codex_url = "https://chatgpt.com/backend-api/codex/responses"
        with tempfile.TemporaryDirectory() as td:
            token_path = Path(td) / "auth.json"
            token_path.write_text(
                json.dumps({"access_token": "access_ok", "expires_at": int(now + 10_000)}),
                encoding="utf-8",
            )
            ft = FakeTransport()
            sse_body = "\n".join(
                [
                    'data: {"type":"response.output_text.delta","delta":"{\\"reply\\":\\"Hel"}',
                    'data: {"type":"response.output_text.delta","delta":"lo\\"}"}',
                    'data: {"type":"response.completed","response":{"output":[{"type":"message","content":[{"type":"output_text","text":"{\\"reply\\":\\"Hello\\"}"}]}]}}',
                    "data: [DONE]",
                ]
            )
            ft._responses[("POST", codex_url)] = HttpResponse(
                status=200,
                headers={"Content-Type": "text/event-stream"},
                body=sse_body.encode("utf-8"),
            )
            events: list[dict[str, Any]] = []
            p = OpenAICodexOAuthProvider(
                remote_calls_armed=True,
                allow_network_egress=True,
                token_path=token_path,
                codex_endpoint=codex_url,
                transport=ft,
                now_fn=lambda: now,
            )
            out = p.codex_responses({"input": "ping"}, stream_callback=events.append)
            self.assertIn("output", out)
            self.assertEqual([e.get("type") for e in events[:2]], ["start", "delta"])
            self.assertTrue(any(e.get("type") == "completed" for e in events))

    def test_streaming_retries_once_on_transient_eof_before_first_delta(self) -> None:
        now = 1_700_000_000.0
        codex_url = "https://chatgpt.com/backend-api/codex/responses"

        class _Resp:
            def __init__(self, lines: list[str]) -> None:
                self.status = 200
                self._lines = [line.encode("utf-8") for line in lines]

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def __iter__(self):
                return iter(self._lines)

        with tempfile.TemporaryDirectory() as td:
            token_path = Path(td) / "auth.json"
            token_path.write_text(
                json.dumps({"access_token": "access_ok", "expires_at": int(now + 10_000)}),
                encoding="utf-8",
            )
            responses = [
                urllib.error.URLError(
                    "[SSL: UNEXPECTED_EOF_WHILE_READING] EOF occurred in violation of protocol (_ssl.c:1081)"
                ),
                _Resp(
                    [
                        'data: {"type":"response.output_text.delta","delta":"{\\"reply\\":\\"ok\\"}"}',
                        'data: {"type":"response.completed","response":{"output":[{"type":"message","content":[{"type":"output_text","text":"{\\"reply\\":\\"ok\\"}"}]}]}}',
                        "data: [DONE]",
                    ]
                ),
            ]
            events: list[dict[str, Any]] = []
            p = OpenAICodexOAuthProvider(
                remote_calls_armed=True,
                allow_network_egress=True,
                token_path=token_path,
                codex_endpoint=codex_url,
                now_fn=lambda: now,
            )

            def _fake_urlopen(req, timeout=0):
                item = responses.pop(0)
                if isinstance(item, Exception):
                    raise item
                return item

            with patch("agentos_next.llm.openai_codex_oauth.urllib.request.urlopen", side_effect=_fake_urlopen):
                out = p.codex_responses({"input": "ping"}, stream_callback=events.append)

            self.assertIn("output", out)
            self.assertEqual(out["output"][0]["content"][0]["text"], '{"reply":"ok"}')
            self.assertTrue(any(e.get("type") == "delta" for e in events))
