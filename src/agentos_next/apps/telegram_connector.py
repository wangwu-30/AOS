import datetime
import json
from dataclasses import dataclass
from typing import Any, Literal, Optional

from agentos_next.apps.telegram_models import TelegramUpdate


# Spec-only V0 envelope from THREAD-033 Phase-1 freeze
@dataclass(frozen=True)
class EventEnvelopeV0:
    schema_version: Literal["1.0.0"]
    event_id: str
    idempotency_key: str
    source: Literal["telegram"]
    received_at_utc: str
    workspace_id: str
    conversation_id: str
    sender_id: str
    message_text: str
    budget_slice_remote_llm_calls: int
    message_attachments: tuple[dict[str, Any], ...] = ()

MISSING_BUDGET = object()

class TelegramChannelAdapter:
    def __init__(self, expected_secret_token: str, kernel_dispatcher: Any):
        """
        kernel_dispatcher should have the signature:
        dispatch(envelope: EventEnvelopeV0, idempotency_key: str) -> None
        """
        self.expected_secret_token = expected_secret_token
        self.kernel_dispatcher = kernel_dispatcher

    def handle_webhook(
        self,
        payload_str: str,
        secret_token: Optional[str],
        workspace_id: str,
        budget_slice_remote_llm_calls: Any = MISSING_BUDGET,
        replay_mode: bool = False
    ) -> tuple[int, dict[str, Any]]:
        # 1. Security Check (Kill Criteria 4: 验签绕过)
        if not secret_token or secret_token != self.expected_secret_token:
            return 401, {"ok": False, "error_code": "E_AUTH_FAILED"}

        # 2. Stability Schema Check (Kill Criteria 6: traceback 泄漏)
        try:
            data = json.loads(payload_str)
            if not isinstance(data, dict):
                raise ValueError("Payload is not a JSON object")
            update = TelegramUpdate.from_dict(data)
        except Exception:
            # Stable JSON format without leaking any tracebacks
            return 400, {"ok": False, "error_code": "E_CHANNEL_PAYLOAD_INVALID"}

        # 3. Budget Check (Kill Criteria 3: Budget 接缝隐式无限制)
        # Missing -> fallback=10
        # Explicit None -> fail-closed
        # Illegal (not int or < 0) -> fail-closed
        if budget_slice_remote_llm_calls is MISSING_BUDGET:
            actual_budget = 10
        elif budget_slice_remote_llm_calls is None:
            return 403, {"ok": False, "error_code": "E_BUDGET_REJECTED"}
        elif not isinstance(budget_slice_remote_llm_calls, int) or budget_slice_remote_llm_calls < 0:
            return 403, {"ok": False, "error_code": "E_BUDGET_REJECTED"}
        else:
            actual_budget = budget_slice_remote_llm_calls

        attachments = self._extract_message_attachments(update)
        message_text = (
            str(update.message.effective_text).strip()
            if update.message is not None
            else ""
        )
        if not update.message or (not message_text and not attachments):
            return 200, {"ok": True, "status": "ignored_non_text"}

        sender_id = str(update.message.from_user.id) if update.message.from_user else "unknown"

        # 4. Construct Envelope (Aligned to V0 freeze)
        idempotency_key = f"idem_tg_{update.update_id}"
        
        envelope = EventEnvelopeV0(
            schema_version="1.0.0",
            event_id=f"tg_update_{update.update_id}",
            idempotency_key=idempotency_key,
            source="telegram",
            received_at_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
            workspace_id=workspace_id,
            conversation_id=str(update.message.chat.id),
            sender_id=sender_id,
            message_text=message_text,
            budget_slice_remote_llm_calls=actual_budget,
            message_attachments=tuple(attachments),
        )
        
        # 5. Replay Mode Side Effect Check (Kill Criteria 2: replay 写盘 / 副作用)
        if not replay_mode:
            self.kernel_dispatcher.dispatch(envelope, idempotency_key=idempotency_key)
        
        return 200, {"ok": True, "event_id": envelope.event_id}

    @staticmethod
    def _extract_message_attachments(update: TelegramUpdate) -> list[dict[str, Any]]:
        message = update.message
        if message is None:
            return []
        caption = str(message.caption or "").strip() or None
        media_group_id = str(message.media_group_id or "").strip() or None
        attachments: list[dict[str, Any]] = []
        if message.photo:
            largest = max(message.photo, key=lambda item: (item.width * item.height, item.file_size or 0))
            attachments.append(
                {
                    "attachment_id": f"tg:{update.update_id}:photo:{largest.file_unique_id or largest.file_id}",
                    "media_kind": "image",
                    "telegram_file_id": largest.file_id,
                    "telegram_file_unique_id": largest.file_unique_id,
                    "caption": caption,
                    "filename": None,
                    "mime_type": "image/jpeg",
                    "size_bytes": largest.file_size,
                    "media_group_id": media_group_id,
                    "availability": "metadata_only",
                    "download_status": "pending",
                    "width": largest.width,
                    "height": largest.height,
                }
            )
        if message.document is not None and message.document.file_id:
            attachments.append(
                {
                    "attachment_id": f"tg:{update.update_id}:document:{message.document.file_unique_id or message.document.file_id}",
                    "media_kind": "document",
                    "telegram_file_id": message.document.file_id,
                    "telegram_file_unique_id": message.document.file_unique_id,
                    "caption": caption,
                    "filename": message.document.file_name,
                    "mime_type": message.document.mime_type,
                    "size_bytes": message.document.file_size,
                    "media_group_id": media_group_id,
                    "availability": "metadata_only",
                    "download_status": "pending",
                }
            )
        if message.voice is not None and message.voice.file_id:
            attachments.append(
                {
                    "attachment_id": f"tg:{update.update_id}:voice:{message.voice.file_unique_id or message.voice.file_id}",
                    "media_kind": "audio",
                    "telegram_file_id": message.voice.file_id,
                    "telegram_file_unique_id": message.voice.file_unique_id,
                    "caption": caption,
                    "filename": None,
                    "mime_type": message.voice.mime_type,
                    "size_bytes": message.voice.file_size,
                    "media_group_id": media_group_id,
                    "availability": "metadata_only",
                    "download_status": "pending",
                    "duration_seconds": message.voice.duration,
                }
            )
        if message.video is not None and message.video.file_id:
            attachments.append(
                {
                    "attachment_id": f"tg:{update.update_id}:video:{message.video.file_unique_id or message.video.file_id}",
                    "media_kind": "video",
                    "telegram_file_id": message.video.file_id,
                    "telegram_file_unique_id": message.video.file_unique_id,
                    "caption": caption,
                    "filename": None,
                    "mime_type": message.video.mime_type,
                    "size_bytes": message.video.file_size,
                    "media_group_id": media_group_id,
                    "availability": "metadata_only",
                    "download_status": "pending",
                    "duration_seconds": message.video.duration,
                    "width": message.video.width,
                    "height": message.video.height,
                }
            )
        return attachments
