import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional
from pathlib import Path
import json
import urllib.error
import urllib.request

from agentos_next.pa.event_log import FileEventLog
from agentos_next.pa.outbox_store import OutboxItem

logger = logging.getLogger(__name__)


class TelegramTypingSession:
    def __init__(self, adapter: "TelegramReplyAdapter", chat_id: str, *, interval_s: float = 4.0) -> None:
        self._adapter = adapter
        self._chat_id = str(chat_id or "").strip()
        self._interval_s = max(0.05, float(interval_s))
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name=f"tg-typing-{self._chat_id}", daemon=True)
        self._started = False

    def start(self) -> bool:
        if not self._chat_id:
            return False
        if self._started:
            return True
        self._started = True
        self._thread.start()
        return True

    def stop(self) -> None:
        self._stop.set()
        if self._started and self._thread.is_alive():
            self._thread.join(timeout=0.2)

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self._adapter.send_typing_action(self._chat_id)
            except Exception:
                return
            if self._stop.wait(self._interval_s):
                return


@dataclass
class TelegramStreamSession:
    adapter: "TelegramReplyAdapter"
    chat_id: str
    message_id: Optional[int]
    reply_min_update_interval_s: float = 0.30
    reply_min_chars_delta: int = 12
    reply_initial_min_chars: int = 8
    reply_initial_max_wait_s: float = 0.35
    reply_initial_chunk_buffer: int = 3
    reply_chunk_buffer: int = 2
    _last_sent_text: str = ""
    _last_flush_monotonic: float = 0.0
    _raw_json_buffer: str = ""
    _active: bool = True
    _reply_started: bool = False
    _reply_first_seen_monotonic: float = 0.0
    _reply_visible: bool = False
    _reply_chunk_count: int = 0
    _reply_chunks_since_flush: int = 0
    _pending_text: str = ""
    _sender_stop: threading.Event = field(default_factory=threading.Event)
    _sender_wakeup: threading.Event = field(default_factory=threading.Event)
    _sender_thread: threading.Thread | None = None
    _lock: threading.RLock = field(default_factory=threading.RLock)

    def __post_init__(self) -> None:
        self._sender_thread = threading.Thread(
            target=self._run_sender,
            name=f"tg-stream-send-{self.chat_id}",
            daemon=True,
        )
        self._sender_thread.start()

    def handle_event(self, event: dict[str, Any]) -> None:
        with self._lock:
            if not self._active or not isinstance(event, dict):
                return
            typ = str(event.get("type") or "").strip()
            if typ == "start":
                self._raw_json_buffer = ""
                return
            if typ != "delta":
                return
            delta = str(event.get("delta") or "")
            if not delta:
                return
            self._raw_json_buffer += delta
            preview = _extract_partial_reply_text(self._raw_json_buffer)
            if preview:
                self._reply_chunk_count += 1
                self._reply_chunks_since_flush += 1
                if not self._reply_started:
                    self._reply_started = True
                    self._reply_first_seen_monotonic = time.monotonic()
                self._maybe_flush_reply(preview)

    def finish(self, *, final_text: str) -> bool:
        text = str(final_text or "").strip()
        with self._lock:
            self._active = False
        self._sender_stop.set()
        self._sender_wakeup.set()
        if self._sender_thread is not None and self._sender_thread.is_alive():
            self._sender_thread.join(timeout=1.0)
        if not text:
            return False
        with self._lock:
            last_sent = self._last_sent_text
        if self.message_id is not None:
            if text == last_sent:
                return True
            if self.adapter.edit_message_text(self.chat_id, self.message_id, text):
                with self._lock:
                    self._last_sent_text = text
                    self._reply_started = True
                    self._reply_visible = True
                    self._last_flush_monotonic = time.monotonic()
                return True
        if last_sent != text:
            sent = self.adapter.send_direct_message(self.chat_id, text)
            if sent:
                with self._lock:
                    self._reply_started = True
                    self._reply_visible = True
            return sent
        return True

    def update_progress(self, text: str) -> bool:
        with self._lock:
            if not self._active or self._reply_started:
                return False
            clean = str(text or "").strip()
            if not clean:
                return False
            return self._queue_text(clean)

    @property
    def reply_started(self) -> bool:
        with self._lock:
            return bool(self._reply_started)

    def _maybe_flush_reply(self, text: str, *, force: bool = False) -> bool:
        clean = str(text or "").strip()
        if not clean or clean == self._last_sent_text:
            return False
        now = time.monotonic()
        if force:
            return self._queue_text(clean)
        baseline = self._last_sent_text
        if not self._reply_visible:
            baseline = ""
        if not baseline:
            boundary = _has_reply_flush_boundary(clean)
            enough_chunks = self._reply_chunk_count >= self.reply_initial_chunk_buffer
            if len(clean) < self.reply_initial_min_chars and not boundary:
                first_seen = self._reply_first_seen_monotonic or now
                if (now - first_seen < self.reply_initial_max_wait_s) and not enough_chunks:
                    return False
            flushed = self._queue_text(clean)
            if flushed:
                self._reply_visible = True
            return flushed
        chars_added = len(clean) - len(baseline)
        elapsed = now - self._last_flush_monotonic
        enough_chunks = self._reply_chunks_since_flush >= self.reply_chunk_buffer
        if chars_added < self.reply_min_chars_delta and elapsed < self.reply_min_update_interval_s and not enough_chunks:
            suffix = clean[len(baseline):] if clean.startswith(baseline) else clean
            if not _has_reply_flush_boundary(suffix):
                return False
        flushed = self._queue_text(clean)
        if flushed:
            self._reply_visible = True
        return flushed

    def _queue_text(self, text: str) -> bool:
        clean = str(text or "").strip()
        with self._lock:
            if self.message_id is None:
                return False
            if clean == self._last_sent_text or clean == self._pending_text:
                return False
            self._pending_text = clean
        self._sender_wakeup.set()
        return True

    def _run_sender(self) -> None:
        while True:
            self._sender_wakeup.wait(timeout=0.5)
            self._sender_wakeup.clear()
            while True:
                with self._lock:
                    text = str(self._pending_text or "").strip()
                    if not text or text == self._last_sent_text:
                        self._pending_text = ""
                        should_stop = bool(self._sender_stop.is_set())
                        break
                    message_id = self.message_id
                if message_id is None:
                    should_stop = bool(self._sender_stop.is_set())
                    break
                if self.adapter.edit_message_text(self.chat_id, int(message_id), text):
                    with self._lock:
                        if self._pending_text == text:
                            self._pending_text = ""
                        self._last_sent_text = text
                        self._last_flush_monotonic = time.monotonic()
                        self._reply_chunks_since_flush = 0
                else:
                    should_stop = bool(self._sender_stop.is_set())
                    break
            if should_stop:
                return

    def _flush_text(self, text: str, *, now: float | None = None) -> bool:
        clean = str(text or "").strip()
        if self.message_id is None:
            return False
        if self.adapter.edit_message_text(self.chat_id, self.message_id, clean):
            self._last_sent_text = clean
            self._last_flush_monotonic = time.monotonic() if now is None else float(now)
            self._reply_chunks_since_flush = 0
            return True
        return False

class TelegramReplyAdapter:
    def __init__(
        self, 
        data_dir: str | Path, 
        bot_token: str = "stub-token",
        send_func: Callable[[str, dict[str, Any]], Any] | None = None,
    ) -> None:
        self.bot_token = bot_token
        self._event_log = FileEventLog(data_dir=data_dir)
        self.last_error_detail: str | None = None
        self.streaming_enabled = True
        if send_func is not None:
            self._send_func = send_func
        elif self._is_stub_token(bot_token):
            self._send_func = self._stub_send
            self.streaming_enabled = True
        else:
            self._send_func = self._http_send
            self.streaming_enabled = True

    def _record_error(self, detail: str) -> None:
        msg = str(detail or "").strip() or "unknown telegram outbound error"
        self.last_error_detail = msg
        logger.error(msg)
        print(f"[Telegram] {msg}")

    @staticmethod
    def _is_stub_token(bot_token: str) -> bool:
        return not bot_token or bot_token == "stub-token"

    def _stub_send(self, endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Stub implementation mapping outbound to stdout"""
        print(f"[Telegram Stub] POST {endpoint}")
        print(f"[Telegram Stub] Payload: {json.dumps(payload, ensure_ascii=False)}")
        return {"ok": True, "result": {"message_id": 1}}

    def _http_send(self, endpoint: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        self.last_error_detail = None
        try:
            req = urllib.request.Request(
                endpoint,
                data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                headers={"Content-Type": "application/json; charset=utf-8"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10) as response:
                raw = response.read()
        except urllib.error.HTTPError as exc:
            preview = ""
            try:
                preview = exc.read().decode("utf-8", errors="replace").strip()
            except Exception:
                preview = ""
            if endpoint.endswith("/editMessageText") and _is_telegram_message_not_modified(preview):
                self.last_error_detail = None
                return {"ok": True, "result": {"noop": True}}
            detail = f"Telegram outbound send failed: HTTP {int(exc.code)}"
            if preview:
                detail += f"; body_preview={' '.join(preview.split())[:240]}"
            self._record_error(detail)
            return None
        except Exception as exc:
            self._record_error(f"Telegram outbound send failed: {exc}")
            return None

        try:
            body = json.loads(raw.decode("utf-8"))
        except Exception:
            self._record_error("Telegram outbound send failed: invalid response payload")
            return None
        if not isinstance(body, dict):
            self._record_error("Telegram outbound send failed: unexpected response shape")
            return None
        if body.get("ok") is not True:
            detail = str(body.get("description") or "").strip() or "unexpected Telegram API response"
            self._record_error(f"Telegram outbound send failed: {detail}")
            return None
        return body

    def handle_outbox_item(self, item: OutboxItem) -> bool:
        """
        Reads target conversation_id from the original EventEnvelope and sends explicit deliveries.
        """
        self.last_error_detail = None
        event_record = self._event_log.read(workspace_id=item.workspace_id, event_id=item.event_id)
        if not event_record:
            self._record_error(f"Cannot find original event {item.event_id} in workspace {item.workspace_id}")
            return False
            
        envelope = event_record.envelope
        chat_id = envelope.get("conversation_id")
        if not chat_id:
            self._record_error(f"Original envelope for {item.event_id} missing conversation_id")
            return False
        deliveries = [dict(x) for x in item.deliveries if isinstance(x, dict)]
        if deliveries:
            return self._deliver_explicit_messages(chat_id=str(chat_id), deliveries=deliveries)
        return self.send_direct_message(chat_id, item.reply_text)

    def _deliver_explicit_messages(self, *, chat_id: str, deliveries: list[dict[str, Any]]) -> bool:
        message_ids_by_key: dict[str, int] = {}
        results: list[bool] = []
        for delivery in deliveries:
            text = str(delivery.get("text") or "").strip()
            if not text:
                continue
            message_key = str(delivery.get("message_key") or "").strip()
            update_preference = str(delivery.get("update_preference") or "prefer_update").strip() or "prefer_update"
            sent_ok = False
            if message_key and update_preference == "prefer_update" and message_key in message_ids_by_key:
                sent_ok = self.edit_message_text(chat_id, int(message_ids_by_key[message_key]), text)
                if sent_ok:
                    delivery["delivery_mode"] = "update"
            if not sent_ok:
                sent_ok, message_id = self.send_direct_message_result(chat_id, text)
                if sent_ok:
                    delivery["delivery_mode"] = "create"
                    if message_key and message_id is not None:
                        message_ids_by_key[message_key] = int(message_id)
                    if message_id is not None:
                        delivery["channel_message_id"] = int(message_id)
            results.append(sent_ok)
            if not sent_ok:
                break
        return all(results) if results else False

    def send_direct_message(self, chat_id: str, text: str) -> bool:
        ok, _ = self.send_direct_message_result(chat_id, text)
        return ok

    def send_direct_message_result(self, chat_id: str, text: str) -> tuple[bool, Optional[int]]:
        """Sends a message directly to a chat_id."""
        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        self.last_error_detail = None
        
        # Split text into chunks of 4000 chars (Telegram limit is ~4096)
        chunk_size = 4000
        chunks = [text[i : i + chunk_size] for i in range(0, len(text), chunk_size)]
        
        results = []
        last_message_id: Optional[int] = None
        for i, chunk in enumerate(chunks):
            payload = {
                "chat_id": chat_id,
                "text": chunk
            }
            ok, body = self._dispatch(url, payload)
            results.append(ok)
            if ok and isinstance(body, dict):
                try:
                    message_id = int((((body.get("result") or {}).get("message_id"))))
                except Exception:
                    message_id = None
                if message_id is not None:
                    last_message_id = message_id
            if not ok:
                if not self.last_error_detail:
                    self._record_error(
                        f"Failed to send direct message chunk {i+1}/{len(chunks)} to {chat_id}"
                    )

        return (all(results) if results else False), last_message_id

    def send_typing_action(self, chat_id: str) -> bool:
        """Sends a 'typing' chat action to a chat_id."""
        url = f"https://api.telegram.org/bot{self.bot_token}/sendChatAction"
        payload = {
            "chat_id": chat_id,
            "action": "typing"
        }
        ok, _ = self._dispatch(url, payload)
        return ok

    def edit_message_text(self, chat_id: str, message_id: int, text: str) -> bool:
        url = f"https://api.telegram.org/bot{self.bot_token}/editMessageText"
        ok, _ = self._dispatch(
            url,
            {
                "chat_id": chat_id,
                "message_id": int(message_id),
                "text": str(text),
            },
        )
        return ok

    def start_stream_session(self, chat_id: str, *, initial_text: str = "处理中...") -> TelegramStreamSession | None:
        if not bool(self.streaming_enabled):
            return None
        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        ok, body = self._dispatch(url, {"chat_id": chat_id, "text": str(initial_text)})
        if not ok:
            return None
        message_id = None
        if isinstance(body, dict):
            try:
                message_id = int((((body.get("result") or {}).get("message_id"))))
            except Exception:
                message_id = None
        if message_id is None:
            return None
        return TelegramStreamSession(
            adapter=self,
            chat_id=chat_id,
            message_id=message_id,
            _last_sent_text=str(initial_text),
            _last_flush_monotonic=time.monotonic(),
        )

    def start_typing_session(self, chat_id: str, *, interval_s: float = 4.0) -> TelegramTypingSession | None:
        session = TelegramTypingSession(self, chat_id, interval_s=interval_s)
        if not session.start():
            return None
        return session

    def _dispatch(self, endpoint: str, payload: dict[str, Any]) -> tuple[bool, dict[str, Any] | None]:
        result = self._send_func(endpoint, payload)
        if isinstance(result, dict):
            ok = bool(result.get("ok", True))
            if not ok and not self.last_error_detail:
                self._record_error("Telegram outbound send failed: custom send_func returned ok=false")
            return ok, result
        ok = bool(result)
        return ok, None


def _extract_partial_reply_text(raw_json_stream: str) -> str:
    data = str(raw_json_stream or "")
    needle = '"reply"'
    start = data.find(needle)
    if start < 0:
        return ""
    colon = data.find(":", start + len(needle))
    if colon < 0:
        return ""
    i = colon + 1
    while i < len(data) and data[i].isspace():
        i += 1
    if i >= len(data) or data[i] != '"':
        return ""
    i += 1
    chars: list[str] = []
    escaping = False
    unicode_remaining = 0
    unicode_buf = ""
    while i < len(data):
        ch = data[i]
        i += 1
        if unicode_remaining > 0:
            if ch.lower() in "0123456789abcdef":
                unicode_buf += ch
                unicode_remaining -= 1
                if unicode_remaining == 0:
                    try:
                        chars.append(chr(int(unicode_buf, 16)))
                    except Exception:
                        pass
                    unicode_buf = ""
                continue
            unicode_remaining = 0
            unicode_buf = ""
        if escaping:
            escaping = False
            if ch == "n":
                chars.append("\n")
            elif ch == "t":
                chars.append("\t")
            elif ch == "r":
                chars.append("\r")
            elif ch == "u":
                unicode_remaining = 4
                unicode_buf = ""
            else:
                chars.append(ch)
            continue
        if ch == "\\":
            escaping = True
            continue
        if ch == '"':
            break
        chars.append(ch)
    return "".join(chars).strip()


def _has_reply_flush_boundary(text: str) -> bool:
    data = str(text or "")
    if not data:
        return False
    boundaries = ("。", "！", "？", "；", "，", ".", "!", "?", ";", ",", "\n")
    return any(token in data for token in boundaries)


def _is_telegram_message_not_modified(body_preview: str) -> bool:
    text = str(body_preview or "").strip()
    if not text:
        return False
    try:
        payload = json.loads(text)
    except Exception:
        payload = None
    if isinstance(payload, dict):
        desc = str(payload.get("description") or "").strip().lower()
        return "message is not modified" in desc
    return "message is not modified" in text.lower()
