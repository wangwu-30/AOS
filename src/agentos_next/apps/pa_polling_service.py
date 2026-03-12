from __future__ import annotations

import asyncio
import hashlib
import http.client
import json
import urllib.parse
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from agentos_next.apps.assistant_runtime import run_assistant_runtime_async
from agentos_next.apps.pa_assistant_runtime_dispatcher import (
    AssistantRuntimeDispatcher as _AssistantRuntimeDispatcher,
    AssistantRuntimeDispatcherOptions,
    build_assistant_runtime_capability_self_check,
)
from agentos_next.apps.scheduler_tick import SchedulerTickRequest, run_scheduler_tick_async
from agentos_next.apps.pa_workspace_router import PAWorkspaceRouteUnmappedError, PAWorkspaceRouter
from agentos_next.apps.telegram_connector import MISSING_BUDGET, TelegramChannelAdapter
from agentos_next.apps.telegram_reply import TelegramReplyAdapter
from agentos_next.kernel.evidence_store import FileEvidenceStore
from agentos_next.kernel.orchestrator import Orchestrator
from agentos_next.pa.outbox_store import OutboxItem
from agentos_next.pa.runtime_error_codes import PA_RUNTIME_ERROR_REPLAY_DENY
from agentos_next.runtime.local_executor import LocalExecutor
PA_POLLING_ERROR_FAILED = "E_PA_POLLING_FAILED"
PA_POLLING_ERROR_PAYLOAD_INVALID = "E_PA_POLLING_PAYLOAD_INVALID"
PA_POLLING_ERROR_WORKSPACE_UNMAPPED = "E_PA_WORKSPACE_UNMAPPED"
PA_POLLING_ERROR_WEBHOOK_CONFLICT = "E_PA_POLLING_WEBHOOK_CONFLICT"
PA_POLLING_ERROR_TRANSIENT_NETWORK = "E_PA_POLLING_TRANSIENT_NETWORK"
PA_POLLING_ERROR_RUNTIME_FAILED = "E_PA_RUNTIME_FAILED"


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class _PollingOffsetStore:
    schema_version = "1.0.0"

    def __init__(self, *, data_dir: str, bot_token: str) -> None:
        self._data_dir = Path(data_dir).resolve()
        self._root = self._data_dir / "pa" / "polling_offsets"
        token = str(bot_token or "").strip()
        self._bot_key = hashlib.sha256(token.encode("utf-8")).hexdigest()[:24] if token else "default"

    def _path(self) -> Path:
        root = self._root.resolve()
        path = (root / f"{self._bot_key}.json").resolve()
        if not path.is_relative_to(root):
            raise ValueError("polling offset path resolves outside polling root")
        return path

    def get(self) -> Optional[int]:
        path = self._path()
        if not path.exists():
            return None
        try:
            obj = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
        try:
            value = int(obj.get("next_offset"))
        except Exception:
            return None
        return value if value >= 0 else None

    def put(self, *, next_offset: int) -> bool:
        if int(next_offset) < 0:
            raise ValueError("next_offset must be >= 0")
        current = self.get()
        if current == int(next_offset):
            return False
        path = self._path()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        payload = {
            "schema_version": self.schema_version,
            "stored_at_utc": _utc_iso(),
            "next_offset": int(next_offset),
            "bot_key": self._bot_key,
        }
        tmp.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
        tmp.replace(path)
        return True


@dataclass(frozen=True)
class PAPollingServiceConfig:
    data_dir: str = "data"
    workspace_id: str = "local"
    routing_file: Optional[str] = None
    budget_slice_remote_llm_calls: Any = None
    replay_mode: bool = False
    bot_token: str = ""
    operator_ref: str = ""
    skill_ref: str = ""
    message_input_key: str = "request"
    verify_asvp: bool = True
    keys_dir: Optional[str] = None
    backend: str = "local_mock"
    model: Optional[str] = None
    intent_backend: Optional[str] = None
    intent_model: Optional[str] = None
    communicator_backend: Optional[str] = None
    communicator_model: Optional[str] = None
    response_language: Optional[str] = None
    remote_calls_armed: bool = False
    allow_network_egress: bool = False
    approved_by_human: bool = False
    target: str = "local"
    deadline_ms: int = 60000
    capabilities: tuple[str, ...] = ()
    # Memory V2 passthrough
    memory_context_enabled: bool = False
    memory_context_retrieval_limit: int = 8
    memory_context_include_stale: bool = False
    memory_context_continuity_event_limit: int = 50
    memory_context_audit_mode: bool = False
    # polling knobs
    timeout_seconds: int = 20
    limit: int = 20
    scheduler_auto_tick_enabled: bool = True
    scheduler_tick_max_fires: int = 20

    @property
    def resolved_operator_ref(self) -> str:
        return str(self.operator_ref or self.skill_ref).strip()


class PAPollingService:
    """THREAD-044: local polling mode for Telegram (no public webhook required)."""

    def __init__(
        self,
        config: PAPollingServiceConfig,
        *,
        send_func: Optional[Callable[[str, dict[str, Any]], bool]] = None,
    ) -> None:
        self._cfg = config
        self._router = (
            PAWorkspaceRouter.from_json_file(config.routing_file)
            if config.routing_file
            else None
        )

        self._reply = TelegramReplyAdapter(
            data_dir=config.data_dir,
            bot_token=config.bot_token,
            send_func=send_func,
        )
        self._capability_self_check = build_assistant_runtime_capability_self_check(config)
        self._dispatcher = _AssistantRuntimeDispatcher(
            config=config,
            telegram_reply_adapter=self._reply,
            effective_runtime_capabilities=self._capability_self_check,
            run_assistant_runtime_async_fn=lambda *args, **kwargs: run_assistant_runtime_async(*args, **kwargs),
            options=AssistantRuntimeDispatcherOptions(
                submitter="telegram.polling",
                consumer="telegram.reply",
                invalid_payload_error_code=PA_POLLING_ERROR_PAYLOAD_INVALID,
                internal_error_code=PA_POLLING_ERROR_RUNTIME_FAILED,
                internal_error_delivery_source="pa_polling.internal_error",
            ),
        )
        # Polling is trusted local ingress; adapter auth check is intentionally bypassed by using
        # an internal secret that we provide to both sides here.
        self._trusted_secret = "polling-local-trusted"
        self._ingress = TelegramChannelAdapter(
            expected_secret_token=self._trusted_secret,
            kernel_dispatcher=self._dispatcher,
        )
        self._offset_store = _PollingOffsetStore(data_dir=str(config.data_dir), bot_token=config.bot_token)
        self._webhook_reset_attempted = False

    def capability_self_check_snapshot(self) -> dict[str, Any]:
        return dict(self._capability_self_check)

    def resume_offset(self) -> Optional[int]:
        return self._offset_store.get()

    def _summarize_outbox_result(self, item: OutboxItem) -> str:
        parts: list[str] = []
        if str(item.execute_status or "").strip():
            parts.append(f"execute_status={item.execute_status}")
        if str(item.execute_error_code or "").strip():
            parts.append(f"execute_error_code={item.execute_error_code}")
        detail = self._extract_error_detail(item.evidence_refs)
        if detail:
            parts.append(f"detail={detail}")
        return "; ".join(parts)

    def _extract_error_detail(self, evidence_refs: tuple[str, ...]) -> str | None:
        refs = tuple(str(ref or "").strip() for ref in tuple(evidence_refs or ()) if str(ref or "").strip())
        if not refs:
            return None
        try:
            evidence = FileEvidenceStore(data_dir=str(self._cfg.data_dir))
            for ref in reversed(refs):
                blob = evidence.get_blob(ref)
                if blob is None or blob.content_type != "application/json":
                    continue
                try:
                    obj = json.loads(blob.content.decode("utf-8", errors="replace"))
                except Exception:
                    continue
                if not isinstance(obj, dict):
                    continue
                msg = " ".join(str(obj.get("message") or "").split()).strip()
                code = str(obj.get("error_code") or "").strip()
                if code and msg:
                    return f"{code}; {msg[:240]}"
                if msg:
                    return msg[:240]
                if code:
                    return code
        except Exception:
            return None
        return None

    def _run_scheduler_tick_once(self) -> tuple[int, bool]:
        if bool(self._cfg.replay_mode):
            return 0, False
        if not bool(self._cfg.scheduler_auto_tick_enabled):
            return 0, False
        try:
            local_exec = LocalExecutor.for_data_dir(self._cfg.data_dir)
            orch = Orchestrator.for_data_dir(str(self._cfg.data_dir), local_executor=local_exec)
            tick_req = SchedulerTickRequest(
                data_dir=str(self._cfg.data_dir),
                replay_mode=False,
                remote_calls_armed=bool(self._cfg.remote_calls_armed),
                allow_network_egress=bool(self._cfg.allow_network_egress),
                approved_by_human=bool(self._cfg.approved_by_human),
                max_fires=max(1, int(self._cfg.scheduler_tick_max_fires)),
            )
            tick_res = _run_async(run_scheduler_tick_async(tick_req, orchestrator=orch))
            if not tick_res.ok:
                return 0, True
            return len(tuple(tick_res.fired)), False
        except Exception:
            return 0, True

    def _reset_webhook_once(self) -> bool:
        url = (
            f"https://api.telegram.org/bot{self._cfg.bot_token}/deleteWebhook?"
            + urllib.parse.urlencode({"drop_pending_updates": "false"})
        )
        try:
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=max(5, int(self._cfg.timeout_seconds))) as resp:
                raw = resp.read()
        except Exception:
            return False
        try:
            obj = json.loads(raw.decode("utf-8"))
        except Exception:
            return False
        return isinstance(obj, dict) and obj.get("ok") is True

    @staticmethod
    def _extract_polling_error(payload: Any) -> tuple[str, Optional[str]]:
        if isinstance(payload, dict):
            code = str(payload.get("error_code") or PA_POLLING_ERROR_FAILED)
            detail = str(payload.get("description") or "").strip() or None
            return code, detail
        if isinstance(payload, str) and payload.strip():
            return payload.strip(), None
        return PA_POLLING_ERROR_FAILED, None

    @staticmethod
    def _looks_like_transient_network_error(detail: str) -> bool:
        txt = str(detail or "").lower()
        if not txt:
            return False
        transient_tokens = (
            "unexpected eof while reading",
            "remote end closed connection without response",
            "connection reset by peer",
            "timed out",
            "temporary failure",
            "eof occurred in violation of protocol",
        )
        return any(tok in txt for tok in transient_tokens)

    def _fetch_updates(self, *, offset: Optional[int]) -> tuple[bool, Any]:
        params: dict[str, Any] = {
            "timeout": int(self._cfg.timeout_seconds),
            "limit": int(self._cfg.limit),
        }
        if offset is not None:
            params["offset"] = int(offset)
        url = f"https://api.telegram.org/bot{self._cfg.bot_token}/getUpdates?{urllib.parse.urlencode(params)}"
        attempts = 2
        raw: bytes | None = None
        for idx in range(attempts):
            is_last = idx >= attempts - 1
            try:
                req = urllib.request.Request(
                    url,
                    method="GET",
                    headers={
                        "Connection": "close",
                        "User-Agent": "agentos-next-pa-polling/1.0",
                    },
                )
                with urllib.request.urlopen(req, timeout=max(1, int(self._cfg.timeout_seconds) + 3)) as resp:
                    raw = resp.read()
                break
            except urllib.error.HTTPError as exc:
                detail = None
                try:
                    err_raw = exc.read()
                    err_obj = json.loads(err_raw.decode("utf-8"))
                    if isinstance(err_obj, dict):
                        detail = str(err_obj.get("description") or "").strip() or None
                except Exception:
                    detail = str(exc)
                code = int(getattr(exc, "code", 0) or 0)
                if code == 409:
                    return False, {
                        "error_code": PA_POLLING_ERROR_WEBHOOK_CONFLICT,
                        "description": detail or "Conflict: webhook is active; polling unavailable",
                    }
                if (code in (502, 503, 504) or self._looks_like_transient_network_error(str(detail or exc))) and not is_last:
                    continue
                return False, {
                    "error_code": (
                        PA_POLLING_ERROR_TRANSIENT_NETWORK
                        if self._looks_like_transient_network_error(str(detail or exc))
                        else PA_POLLING_ERROR_FAILED
                    ),
                    "description": detail or str(exc),
                }
            except (urllib.error.URLError, http.client.RemoteDisconnected, TimeoutError, OSError) as exc:
                detail = str(exc)
                if self._looks_like_transient_network_error(detail) and not is_last:
                    continue
                return False, {
                    "error_code": (
                        PA_POLLING_ERROR_TRANSIENT_NETWORK
                        if self._looks_like_transient_network_error(detail)
                        else PA_POLLING_ERROR_FAILED
                    ),
                    "description": detail,
                }
            except Exception as exc:
                detail = str(exc)
                if self._looks_like_transient_network_error(detail) and not is_last:
                    continue
                return False, {
                    "error_code": (
                        PA_POLLING_ERROR_TRANSIENT_NETWORK
                        if self._looks_like_transient_network_error(detail)
                        else PA_POLLING_ERROR_FAILED
                    ),
                    "description": detail,
                }
        if raw is None:
            return False, {
                "error_code": PA_POLLING_ERROR_TRANSIENT_NETWORK,
                "description": "polling request failed after retry",
            }
        try:
            obj = json.loads(raw.decode("utf-8"))
        except Exception:
            return False, {
                "error_code": PA_POLLING_ERROR_PAYLOAD_INVALID,
                "description": "invalid JSON payload from Telegram getUpdates",
            }
        if not isinstance(obj, dict):
            return False, {
                "error_code": PA_POLLING_ERROR_PAYLOAD_INVALID,
                "description": "unexpected Telegram getUpdates payload shape",
            }
        if obj.get("ok") is not True:
            api_code = int(obj.get("error_code") or 0)
            description = str(obj.get("description") or "").strip() or None
            mapped = PA_POLLING_ERROR_WEBHOOK_CONFLICT if api_code == 409 else PA_POLLING_ERROR_FAILED
            return False, {"error_code": mapped, "description": description}
        return True, obj

    def _resolve_offset(self, offset: Optional[int]) -> Optional[int]:
        if offset is not None:
            return int(offset)
        return self._offset_store.get()

    def run_once(self, *, offset: Optional[int]) -> dict[str, Any]:
        effective_offset = self._resolve_offset(offset)
        scheduler_fired = 0
        scheduler_errors = 0
        fired_before, err_before = self._run_scheduler_tick_once()
        scheduler_fired += int(fired_before)
        scheduler_errors += int(bool(err_before))

        ok, payload = self._fetch_updates(offset=effective_offset)
        if not ok:
            code, _ = self._extract_polling_error(payload)
            if code == PA_POLLING_ERROR_WEBHOOK_CONFLICT and not self._webhook_reset_attempted:
                self._webhook_reset_attempted = True
                if self._reset_webhook_once():
                    ok, payload = self._fetch_updates(offset=effective_offset)
        if not ok:
            error_code, error_detail = self._extract_polling_error(payload)
            return {
                "ok": False,
                "error_code": error_code,
                "error_detail": error_detail,
                "processed": 0,
                "dedup": 0,
                "ignored_non_text": 0,
                "reply_sent": 0,
                "scheduler_fired": scheduler_fired,
                "scheduler_errors": scheduler_errors,
                "next_offset": effective_offset,
            }
        if not isinstance(payload, dict) or payload.get("ok") is not True:
            return {
                "ok": False,
                "error_code": PA_POLLING_ERROR_PAYLOAD_INVALID,
                "processed": 0,
                "dedup": 0,
                "ignored_non_text": 0,
                "reply_sent": 0,
                "scheduler_fired": scheduler_fired,
                "scheduler_errors": scheduler_errors,
                "next_offset": effective_offset,
            }
        result = payload.get("result")
        if not isinstance(result, list):
            return {
                "ok": False,
                "error_code": PA_POLLING_ERROR_PAYLOAD_INVALID,
                "processed": 0,
                "dedup": 0,
                "ignored_non_text": 0,
                "reply_sent": 0,
                "scheduler_fired": scheduler_fired,
                "scheduler_errors": scheduler_errors,
                "next_offset": effective_offset,
            }

        processed = 0
        dedup = 0
        ignored_non_text = 0
        reply_sent = 0
        rejected = 0
        last_update_id: Optional[int] = effective_offset

        for update in result:
            if not isinstance(update, dict):
                rejected += 1
                continue
            try:
                update_id = int(update.get("update_id"))
            except Exception:
                rejected += 1
                continue
            last_update_id = max(update_id + 1, int(last_update_id or 0))

            print(f"--- [PA] Received Telegram Update id={update_id} ---")
            
            payload_str = json.dumps(update, ensure_ascii=False, sort_keys=True)
            workspace_id = self._cfg.workspace_id
            budget: Any
            if self._cfg.budget_slice_remote_llm_calls is None:
                budget = MISSING_BUDGET
            else:
                budget = self._cfg.budget_slice_remote_llm_calls

            if self._router is not None:
                try:
                    route = self._router.route_for_payload(payload_str)
                except PAWorkspaceRouteUnmappedError:
                    rejected += 1
                    continue
                if route is not None:
                    workspace_id = route.workspace_id
                    if route.budget_slice_remote_llm_calls is not MISSING_BUDGET:
                        budget = route.budget_slice_remote_llm_calls

            # Reset per-update dispatcher output to avoid stale reuse on ignored updates.
            self._dispatcher.runtime_out = None
            if budget is MISSING_BUDGET:
                code, body = self._ingress.handle_webhook(
                    payload_str=payload_str,
                    secret_token=self._trusted_secret,
                    workspace_id=workspace_id,
                    replay_mode=bool(self._cfg.replay_mode),
                )
            else:
                code, body = self._ingress.handle_webhook(
                    payload_str=payload_str,
                    secret_token=self._trusted_secret,
                    workspace_id=workspace_id,
                    budget_slice_remote_llm_calls=budget,
                    replay_mode=bool(self._cfg.replay_mode),
                )

            if code != 200:
                rejected += 1
                continue
            if not isinstance(body, dict) or body.get("ok") is not True:
                rejected += 1
                continue
            if str(body.get("status") or "") == "ignored_non_text":
                ignored_non_text += 1
                continue
            processed += 1

            if bool(self._cfg.replay_mode):
                continue
            runtime_out = self._dispatcher.runtime_out
            if not isinstance(runtime_out, dict):
                rejected += 1
                continue
            item = OutboxItem.from_json(runtime_out.get("outbox"))
            if bool(runtime_out.get("dedup")):
                print(
                    f"[PA] Dedup hit for update {update_id}; existing outbox found, "
                    "skipping resend and advancing offset."
                )
                dedup += 1
                continue
            if item is not None and bool(item.reply_sent_live):
                summary = self._summarize_outbox_result(item)
                if summary:
                    print(f"[PA] Reply streamed for update {update_id}: {summary}")
                reply_sent += 1
                continue
            if item is not None and self._reply.handle_outbox_item(item):
                summary = self._summarize_outbox_result(item)
                if summary and str(item.execute_status or "") != "accepted":
                    print(f"[PA] Runtime execution failed for update {update_id}: {summary}")
                if summary and str(item.execute_status or "") != "accepted":
                    print(f"[PA] Reply sent for update {update_id}: {summary}")
                reply_sent += 1
                continue
            if item is not None:
                reply_detail = str(getattr(self._reply, "last_error_detail", "") or "").strip()
                summary = self._summarize_outbox_result(item)
                if summary and str(item.execute_status or "") != "accepted":
                    print(f"[PA] Runtime execution failed for update {update_id}: {summary}")
                msg = f"[PA] Reply send failed for update {update_id}"
                if summary:
                    msg += f": {summary}"
                if reply_detail:
                    msg += f"; telegram={reply_detail}"
                print(msg)
                rejected += 1
                continue
            error_msg = str(runtime_out.get("error_code") or "UNKNOWN_ERROR")
            print(f"[PA] Dispatch failure for {update.get('update_id')}: {error_msg}")
            rejected += 1

        fired_after, err_after = self._run_scheduler_tick_once()
        scheduler_fired += int(fired_after)
        scheduler_errors += int(bool(err_after))

        if not bool(self._cfg.replay_mode) and last_update_id is not None:
            try:
                changed = self._offset_store.put(next_offset=int(last_update_id))
                if changed:
                    print(f"[PA] Offset checkpoint saved: next_offset={int(last_update_id)}")
            except Exception:
                return {
                    "ok": False,
                    "error_code": PA_POLLING_ERROR_FAILED,
                    "error_detail": "failed to persist polling offset checkpoint",
                    "processed": processed,
                    "dedup": dedup,
                    "ignored_non_text": ignored_non_text,
                    "reply_sent": reply_sent,
                    "rejected": rejected,
                    "scheduler_fired": scheduler_fired,
                    "scheduler_errors": scheduler_errors,
                    "next_offset": last_update_id,
                    "replay_mode": bool(self._cfg.replay_mode),
                    "replay_error_code": (PA_RUNTIME_ERROR_REPLAY_DENY if bool(self._cfg.replay_mode) else None),
                }

        return {
            "ok": True if (rejected == 0 and scheduler_errors == 0) else False,
            "error_code": None if (rejected == 0 and scheduler_errors == 0) else PA_POLLING_ERROR_FAILED,
            "processed": processed,
            "dedup": dedup,
            "ignored_non_text": ignored_non_text,
            "reply_sent": reply_sent,
            "rejected": rejected,
            "scheduler_fired": scheduler_fired,
            "scheduler_errors": scheduler_errors,
            "next_offset": last_update_id,
            "replay_mode": bool(self._cfg.replay_mode),
            "replay_error_code": (PA_RUNTIME_ERROR_REPLAY_DENY if bool(self._cfg.replay_mode) else None),
        }


def _run_async(coro: Any) -> Any:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    if loop.is_running():
        import nest_asyncio
        nest_asyncio.apply()
        return loop.run_until_complete(coro)
    return asyncio.run(coro)
