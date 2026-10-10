import json
import unittest

from agentos_next.apps.telegram_connector import EventEnvelopeV0, TelegramChannelAdapter


class MockKernelDispatcher:
    def __init__(self):
        self.dispatched_envelopes: list[EventEnvelopeV0] = []
        self.idempotency_keys: list[str] = []

    def dispatch(self, envelope: EventEnvelopeV0, idempotency_key: str) -> None:
        self.dispatched_envelopes.append(envelope)
        self.idempotency_keys.append(idempotency_key)

class TestThread034TelegramConnector(unittest.TestCase):
    def setUp(self):
        self.expected_token = "secret123"
        self.kernel = MockKernelDispatcher()
        self.adapter = TelegramChannelAdapter(
            expected_secret_token=self.expected_token, 
            kernel_dispatcher=self.kernel
        )
        self.valid_payload = json.dumps({
            "update_id": 1001,
            "message": {
                "message_id": 200,
                "date": 1600000000,
                "chat": {"id": 12345, "type": "private"},
                "from": {"id": 555, "is_bot": False, "first_name": "Alice"},
                "text": "Hello bot"
            }
        })

    def test_verify_secret_token(self):
        # Missing token
        status, resp = self.adapter.handle_webhook(
            payload_str=self.valid_payload,
            secret_token=None,
            workspace_id="ws_1",
            budget_slice_remote_llm_calls=5
        )
        self.assertEqual(status, 401)
        self.assertEqual(resp["error_code"], "E_AUTH_FAILED")
        self.assertEqual(len(self.kernel.dispatched_envelopes), 0)

        # Invalid token
        status, resp = self.adapter.handle_webhook(
            payload_str=self.valid_payload,
            secret_token="wrong",
            workspace_id="ws_1",
            budget_slice_remote_llm_calls=5
        )
        self.assertEqual(status, 401)
        self.assertEqual(resp["error_code"], "E_AUTH_FAILED")

        # Valid token
        status, resp = self.adapter.handle_webhook(
            payload_str=self.valid_payload,
            secret_token=self.expected_token,
            workspace_id="ws_1",
            budget_slice_remote_llm_calls=5
        )
        self.assertEqual(status, 200)
        self.assertEqual(len(self.kernel.dispatched_envelopes), 1)

    def test_idempotency_routing(self):
        status, resp = self.adapter.handle_webhook(
            payload_str=self.valid_payload,
            secret_token=self.expected_token,
            workspace_id="ws_1",
            budget_slice_remote_llm_calls=5
        )
        self.assertEqual(status, 200)
        
        env = self.kernel.dispatched_envelopes[0]
        idem_key = self.kernel.idempotency_keys[0]

        self.assertEqual(env.event_id, "tg_update_1001")
        self.assertEqual(idem_key, "idem_tg_1001")

    def test_traceback_suppression(self):
        # Malformed JSON
        status, resp = self.adapter.handle_webhook(
            payload_str="{ invalid",
            secret_token=self.expected_token,
            workspace_id="ws_1",
            budget_slice_remote_llm_calls=5
        )
        self.assertEqual(status, 400)
        self.assertEqual(resp["error_code"], "E_CHANNEL_PAYLOAD_INVALID")
        
        # Missing update_id
        bad_json = json.dumps({"message": {}})
        status, resp = self.adapter.handle_webhook(
            payload_str=bad_json,
            secret_token=self.expected_token,
            workspace_id="ws_1",
            budget_slice_remote_llm_calls=5
        )
        self.assertEqual(status, 400)
        self.assertEqual(resp["error_code"], "E_CHANNEL_PAYLOAD_INVALID")

    def test_budget_rejection(self):
        # 1. Missing budget -> fallback=10
        status, resp = self.adapter.handle_webhook(
            payload_str=self.valid_payload,
            secret_token=self.expected_token,
            workspace_id="ws_1"
            # budget_slice_remote_llm_calls not provided
        )
        self.assertEqual(status, 200)
        self.assertEqual(len(self.kernel.dispatched_envelopes), 1)
        self.assertEqual(self.kernel.dispatched_envelopes[-1].budget_slice_remote_llm_calls, 10)

        # 2. Explicit None -> fail-closed
        status, resp = self.adapter.handle_webhook(
            payload_str=self.valid_payload,
            secret_token=self.expected_token,
            workspace_id="ws_1",
            budget_slice_remote_llm_calls=None
        )
        self.assertEqual(status, 403)
        self.assertEqual(resp["error_code"], "E_BUDGET_REJECTED")

        # 3. Illegal (< 0 or bad type) -> fail-closed
        status, resp = self.adapter.handle_webhook(
            payload_str=self.valid_payload,
            secret_token=self.expected_token,
            workspace_id="ws_1",
            budget_slice_remote_llm_calls=-1
        )
        self.assertEqual(status, 403)
        self.assertEqual(resp["error_code"], "E_BUDGET_REJECTED")
        
        status, resp = self.adapter.handle_webhook(
            payload_str=self.valid_payload,
            secret_token=self.expected_token,
            workspace_id="ws_1",
            budget_slice_remote_llm_calls="unlimited"
        )
        self.assertEqual(status, 403)
        self.assertEqual(resp["error_code"], "E_BUDGET_REJECTED")
        
        # 4. Valid budget -> passed
        status, resp = self.adapter.handle_webhook(
            payload_str=self.valid_payload,
            secret_token=self.expected_token,
            workspace_id="ws_1",
            budget_slice_remote_llm_calls=0  # 0 is valid, just means no remote calls
        )
        self.assertEqual(status, 200)
        self.assertEqual(self.kernel.dispatched_envelopes[-1].budget_slice_remote_llm_calls, 0)

    def test_replay_protection(self):
        # Replay mode = True should not dispatch to kernel
        status, resp = self.adapter.handle_webhook(
            payload_str=self.valid_payload,
            secret_token=self.expected_token,
            workspace_id="ws_1",
            budget_slice_remote_llm_calls=5,
            replay_mode=True
        )
        self.assertEqual(status, 200)
        self.assertEqual(len(self.kernel.dispatched_envelopes), 0)

    def test_photo_message_dispatches_caption_and_attachment_metadata(self):
        payload = json.dumps(
            {
                "update_id": 1002,
                "message": {
                    "message_id": 201,
                    "date": 1600000001,
                    "chat": {"id": 12345, "type": "private"},
                    "from": {"id": 556, "is_bot": False, "first_name": "Alice"},
                    "caption": "帮我看看这张图",
                    "photo": [
                        {"file_id": "ph-small", "file_unique_id": "uniq-small", "width": 90, "height": 90, "file_size": 512},
                        {"file_id": "ph-large", "file_unique_id": "uniq-large", "width": 1024, "height": 768, "file_size": 4096},
                    ],
                    "media_group_id": "mg-1",
                },
            },
            ensure_ascii=False,
        )
        status, resp = self.adapter.handle_webhook(
            payload_str=payload,
            secret_token=self.expected_token,
            workspace_id="ws_1",
            budget_slice_remote_llm_calls=5,
        )
        self.assertEqual(status, 200)
        self.assertTrue(resp["ok"])
        env = self.kernel.dispatched_envelopes[-1]
        self.assertEqual(env.message_text, "帮我看看这张图")
        self.assertEqual(len(env.message_attachments), 1)
        attachment = env.message_attachments[0]
        self.assertEqual(attachment["media_kind"], "image")
        self.assertEqual(attachment["telegram_file_id"], "ph-large")
        self.assertEqual(attachment["media_group_id"], "mg-1")
