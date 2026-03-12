import unittest
import tempfile
import json
import io
import time
import urllib.error
from unittest.mock import MagicMock, patch
from agentos_next.pa.event_log import FileEventLog
from agentos_next.pa.outbox_store import OutboxItem
from agentos_next.apps.telegram_reply import TelegramReplyAdapter

class TestThread040TelegramReply(unittest.TestCase):
    @staticmethod
    def _texts(calls):
        return [payload["text"] for _url, payload in calls if "text" in payload]

    def _wait_for_text(self, calls, expected: str, *, timeout_s: float = 0.5) -> list[str]:
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            texts = self._texts(calls)
            if expected in texts or (texts and texts[-1] == expected):
                return texts
            time.sleep(0.01)
        return self._texts(calls)

    def test_reply_adapter_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            elog = FileEventLog(data_dir=tmp)
            elog.write_once(
                workspace_id="ws1", 
                event_id="evt1", 
                envelope={"conversation_id": "chat123", "schema_version": "1.0.0"}
            )
            
            outbox_item = OutboxItem(
                schema_version="1.0.0",
                stored_at_utc="2026",
                workspace_id="ws1",
                event_id="evt1",
                idempotency_key="idm1",
                trace_id="tr1",
                turn_id="tn1",
                span_id="sp1",
                execute_status="accepted",
                execute_error_code=None,
                evidence_refs=(),
                reply_text="Hello Context",
                metering_evidence_refs=()
            )
            
            captured = []
            def dummy_send(url, payload):
                captured.append((url, payload))
                return True
                
            adapter = TelegramReplyAdapter(data_dir=tmp, bot_token="test", send_func=dummy_send)
            res = adapter.handle_outbox_item(outbox_item)
            self.assertTrue(res)
            self.assertEqual(len(captured), 1)
            self.assertEqual(captured[0][1]["chat_id"], "chat123")
            self.assertEqual(captured[0][1]["text"], "Hello Context")

    def test_reply_adapter_missing_envelope(self):
        with tempfile.TemporaryDirectory() as tmp:
            outbox_item = OutboxItem(
                schema_version="1.0.0",
                stored_at_utc="2026",
                workspace_id="ws1",
                event_id="evt-missing",
                idempotency_key="idm1",
                trace_id="tr1",
                turn_id="tn1",
                span_id="sp1",
                execute_status="accepted",
                execute_error_code=None,
                evidence_refs=(),
                reply_text="Hello Context",
                metering_evidence_refs=()
            )
            adapter = TelegramReplyAdapter(data_dir=tmp, bot_token="test")
            res = adapter.handle_outbox_item(outbox_item)
            self.assertFalse(res)

    def test_reply_adapter_non_stub_token_uses_http_send(self):
        with tempfile.TemporaryDirectory() as tmp:
            elog = FileEventLog(data_dir=tmp)
            elog.write_once(
                workspace_id="ws1",
                event_id="evt-http",
                envelope={"conversation_id": "chat-http", "schema_version": "1.0.0"},
            )

            outbox_item = OutboxItem(
                schema_version="1.0.0",
                stored_at_utc="2026",
                workspace_id="ws1",
                event_id="evt-http",
                idempotency_key="idm-http",
                trace_id="tr-http",
                turn_id="tn-http",
                span_id="sp-http",
                execute_status="accepted",
                execute_error_code=None,
                evidence_refs=(),
                reply_text="Hello HTTP",
                metering_evidence_refs=(),
            )

            adapter = TelegramReplyAdapter(data_dir=tmp, bot_token="real-token")
            with patch("agentos_next.apps.telegram_reply.urllib.request.urlopen") as mocked_urlopen:
                mocked_response = MagicMock()
                mocked_response.read.return_value = b'{"ok": true}'
                mocked_urlopen.return_value.__enter__.return_value = mocked_response

                res = adapter.handle_outbox_item(outbox_item)

            self.assertTrue(res)
            mocked_urlopen.assert_called_once()
            req = mocked_urlopen.call_args.args[0]
            self.assertEqual(req.full_url, "https://api.telegram.org/botreal-token/sendMessage")
            self.assertEqual(req.get_method(), "POST")
            self.assertEqual(mocked_urlopen.call_args.kwargs.get("timeout"), 10)
            payload = json.loads(req.data.decode("utf-8"))
            self.assertEqual(payload.get("chat_id"), "chat-http")
            self.assertEqual(payload.get("text"), "Hello HTTP")

    def test_reply_adapter_http_send_failure_returns_false(self):
        with tempfile.TemporaryDirectory() as tmp:
            elog = FileEventLog(data_dir=tmp)
            elog.write_once(
                workspace_id="ws1",
                event_id="evt-http-fail",
                envelope={"conversation_id": "chat-http-fail", "schema_version": "1.0.0"},
            )

            outbox_item = OutboxItem(
                schema_version="1.0.0",
                stored_at_utc="2026",
                workspace_id="ws1",
                event_id="evt-http-fail",
                idempotency_key="idm-http-fail",
                trace_id="tr-http-fail",
                turn_id="tn-http-fail",
                span_id="sp-http-fail",
                execute_status="accepted",
                execute_error_code=None,
                evidence_refs=(),
                reply_text="Hello HTTP fail",
                metering_evidence_refs=(),
            )

            adapter = TelegramReplyAdapter(data_dir=tmp, bot_token="real-token")
            with patch(
                "agentos_next.apps.telegram_reply.urllib.request.urlopen",
                side_effect=OSError("network-down"),
            ):
                res = adapter.handle_outbox_item(outbox_item)
            self.assertFalse(res)

    def test_stream_session_sends_placeholder_and_edits(self):
        with tempfile.TemporaryDirectory() as tmp:
            adapter = TelegramReplyAdapter(data_dir=tmp, bot_token="real-token")
            responses = [
                b'{"ok": true, "result": {"message_id": 42}}',
                b'{"ok": true, "result": {"message_id": 42}}',
                b'{"ok": true, "result": {"message_id": 42}}',
            ]

            def _urlopen(req, timeout=0):
                mocked_response = MagicMock()
                mocked_response.read.return_value = responses.pop(0)
                cm = MagicMock()
                cm.__enter__.return_value = mocked_response
                cm.__exit__.return_value = False
                return cm

            with patch("agentos_next.apps.telegram_reply.urllib.request.urlopen", side_effect=_urlopen) as mocked_urlopen:
                session = adapter.start_stream_session("chat-stream", initial_text="处理中...")
                self.assertIsNotNone(session)
                assert session is not None
                session.handle_event({"type": "start"})
                session.handle_event(
                    {"type": "delta", "delta": '{"reply":"这是一段足够长的流式回复内容，用来触发一次编辑刷新。'}
                )
                ok = session.finish(final_text="这是最终回复")

            self.assertTrue(ok)
            self.assertEqual(mocked_urlopen.call_count, 3)
            edit_req = mocked_urlopen.call_args_list[-1].args[0]
            self.assertEqual(edit_req.full_url, "https://api.telegram.org/botreal-token/editMessageText")
            payload = json.loads(edit_req.data.decode("utf-8"))
            self.assertEqual(payload["message_id"], 42)
            self.assertEqual(payload["text"], "这是最终回复")

    def test_stream_progress_is_replaced_by_reply_and_not_overwritten_after_reply_starts(self):
        with tempfile.TemporaryDirectory() as tmp:
            calls = []

            def _send(url, payload):
                calls.append((url, dict(payload)))
                return {"ok": True, "result": {"message_id": 77}}

            adapter = TelegramReplyAdapter(data_dir=tmp, bot_token="test", send_func=_send)
            session = adapter.start_stream_session("chat77", initial_text="处理中...")
            self.assertIsNotNone(session)
            assert session is not None
            session.reply_initial_min_chars = 1
            session.reply_initial_max_wait_s = 0.0
            session.reply_initial_chunk_buffer = 1
            session.reply_chunk_buffer = 1
            session.reply_min_update_interval_s = 0.0
            session.reply_min_chars_delta = 1

            self.assertTrue(session.update_progress("正在执行 builtin://web.search..."))
            session.handle_event({"type": "start"})
            session.handle_event({"type": "delta", "delta": '{"reply":"已经有答复前缀"}'})
            self.assertFalse(session.update_progress("正在执行 builtin://fs.read..."))
            self.assertTrue(session.finish(final_text="最终答复"))

            texts = self._wait_for_text(calls, "最终答复")
            self.assertEqual(texts[0], "处理中...")
            self.assertIn("已经有答复前缀", texts)
            self.assertEqual(texts[-1], "最终答复")
            self.assertNotIn("正在执行 builtin://fs.read...", texts)

    def test_stream_first_reply_chunk_flushes_immediately_even_under_throttle(self):
        with tempfile.TemporaryDirectory() as tmp:
            calls = []

            def _send(url, payload):
                calls.append((url, dict(payload)))
                return {"ok": True, "result": {"message_id": 88}}

            adapter = TelegramReplyAdapter(data_dir=tmp, bot_token="test", send_func=_send)
            session = adapter.start_stream_session("chat88", initial_text="处理中...")
            self.assertIsNotNone(session)
            assert session is not None
            session.reply_initial_min_chars = 1
            session.reply_initial_max_wait_s = 0.0
            session.reply_initial_chunk_buffer = 1
            session.reply_chunk_buffer = 1
            session.reply_min_update_interval_s = 60.0
            session.reply_min_chars_delta = 999

            self.assertTrue(session.update_progress("正在分析请求..."))
            session.handle_event({"type": "start"})
            session.handle_event({"type": "delta", "delta": '{"reply":"首个答复片段"}'})

            texts = self._wait_for_text(calls, "首个答复片段")
            self.assertEqual(texts[0], "处理中...")
            self.assertEqual(texts[-1], "首个答复片段")

    def test_stream_smooths_tiny_first_reply_chunks_until_phrase_is_ready(self):
        with tempfile.TemporaryDirectory() as tmp:
            calls = []

            def _send(url, payload):
                calls.append((url, dict(payload)))
                return {"ok": True, "result": {"message_id": 99}}

            adapter = TelegramReplyAdapter(data_dir=tmp, bot_token="test", send_func=_send)
            session = adapter.start_stream_session("chat99", initial_text="处理中...")
            self.assertIsNotNone(session)
            assert session is not None
            session.reply_initial_min_chars = 8
            session.reply_initial_max_wait_s = 10.0
            session.reply_initial_chunk_buffer = 3

            session.handle_event({"type": "start"})
            session.handle_event({"type": "delta", "delta": '{"reply":"你'})
            texts = self._texts(calls)
            self.assertEqual(texts, ["处理中..."])

            session.handle_event({"type": "delta", "delta": "好"})
            texts = self._texts(calls)
            self.assertEqual(texts, ["处理中..."])

            session.handle_event({"type": "delta", "delta": '，今天继续"}'})
            texts = self._wait_for_text(calls, "你好，今天继续")
            self.assertEqual(texts[-1], "你好，今天继续")

    def test_stream_smooths_small_reply_deltas_without_boundary(self):
        with tempfile.TemporaryDirectory() as tmp:
            calls = []

            def _send(url, payload):
                calls.append((url, dict(payload)))
                return {"ok": True, "result": {"message_id": 100}}

            adapter = TelegramReplyAdapter(data_dir=tmp, bot_token="test", send_func=_send)
            session = adapter.start_stream_session("chat100", initial_text="处理中...")
            self.assertIsNotNone(session)
            assert session is not None
            session.reply_initial_min_chars = 1
            session.reply_initial_max_wait_s = 0.0
            session.reply_initial_chunk_buffer = 1
            session.reply_chunk_buffer = 2
            session.reply_min_update_interval_s = 10.0
            session.reply_min_chars_delta = 12

            session.handle_event({"type": "start"})
            session.handle_event({"type": "delta", "delta": '{"reply":"先给你一个完整短句'})
            initial_texts = self._wait_for_text(calls, "先给你一个完整短句")
            initial_count = len(initial_texts)
            session.handle_event({"type": "delta", "delta": '继续补"}'})
            time.sleep(0.05)
            after_small_delta = len(self._texts(calls))

            self.assertEqual(initial_count, 2)
            self.assertEqual(after_small_delta, initial_count)

    def test_stream_flushes_after_configured_chunk_buffer_even_without_boundary(self):
        with tempfile.TemporaryDirectory() as tmp:
            calls = []

            def _send(url, payload):
                calls.append((url, dict(payload)))
                return {"ok": True, "result": {"message_id": 101}}

            adapter = TelegramReplyAdapter(data_dir=tmp, bot_token="test", send_func=_send)
            session = adapter.start_stream_session("chat101", initial_text="处理中...")
            self.assertIsNotNone(session)
            assert session is not None
            session.reply_initial_min_chars = 1
            session.reply_initial_max_wait_s = 0.0
            session.reply_initial_chunk_buffer = 1
            session.reply_chunk_buffer = 3
            session.reply_min_update_interval_s = 10.0
            session.reply_min_chars_delta = 999

            session.handle_event({"type": "start"})
            session.handle_event({"type": "delta", "delta": '{"reply":"第一段'})
            first_visible = self._wait_for_text(calls, "第一段")
            self.assertEqual(first_visible[-1], "第一段")

            session.handle_event({"type": "delta", "delta": "第二段"})
            session.handle_event({"type": "delta", "delta": "第三段"})
            time.sleep(0.05)
            texts = self._texts(calls)
            self.assertEqual(texts[-1], "第一段")

            session.handle_event({"type": "delta", "delta": '第四段"}'})
            texts = self._wait_for_text(calls, "第一段第二段第三段第四段")
            self.assertEqual(texts[-1], "第一段第二段第三段第四段")

    def test_edit_message_text_treats_message_not_modified_as_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            adapter = TelegramReplyAdapter(data_dir=tmp, bot_token="real-token")
            err = urllib.error.HTTPError(
                url="https://api.telegram.org/botreal-token/editMessageText",
                code=400,
                msg="Bad Request",
                hdrs=None,
                fp=io.BytesIO(
                    b'{"ok":false,"error_code":400,"description":"Bad Request: message is not modified: specified new message content and reply markup are exactly the same as a current content and reply markup of the message"}'
                ),
            )
            with patch("agentos_next.apps.telegram_reply.urllib.request.urlopen", side_effect=err):
                ok = adapter.edit_message_text("chat-noop", 42, "same text")

            self.assertTrue(ok)
            self.assertIsNone(adapter.last_error_detail)

    def test_typing_session_sends_heartbeat_until_stopped(self):
        with tempfile.TemporaryDirectory() as tmp:
            calls = []

            def _send(url, payload):
                calls.append((url, dict(payload)))
                return {"ok": True, "result": {"message_id": 1}}

            adapter = TelegramReplyAdapter(data_dir=tmp, bot_token="test", send_func=_send)
            session = adapter.start_typing_session("chat-typing", interval_s=0.05)
            self.assertIsNotNone(session)
            assert session is not None
            time.sleep(0.14)
            session.stop()
            call_count_after_stop = len(calls)
            time.sleep(0.08)

            typing_calls = [payload for _url, payload in calls if payload.get("action") == "typing"]
            self.assertGreaterEqual(len(typing_calls), 2)
            self.assertEqual(len(calls), call_count_after_stop)
