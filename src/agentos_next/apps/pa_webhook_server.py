from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional

from agentos_next.apps.assistant_runtime import run_assistant_runtime_async
from agentos_next.apps.pa_assistant_runtime_dispatcher import (
    AssistantRuntimeDispatcher as _AssistantRuntimeDispatcher,
)
from agentos_next.apps.pa_assistant_runtime_dispatcher import (
    AssistantRuntimeDispatcherOptions,
    build_assistant_runtime_capability_self_check,
)
from agentos_next.apps.pa_workspace_router import PAWorkspaceRouter, PAWorkspaceRouteUnmappedError
from agentos_next.apps.telegram_connector import MISSING_BUDGET, TelegramChannelAdapter
from agentos_next.apps.telegram_reply import TelegramReplyAdapter
from agentos_next.pa.outbox_store import OutboxItem
from agentos_next.pa.runtime_error_codes import (
    PA_RUNTIME_ERROR_CONTEXT_FAILED,
    PA_RUNTIME_ERROR_IO_FAILED,
    PA_RUNTIME_ERROR_REPLAY_DENY,
)

PA_WEBHOOK_ERROR_FAILED = "E_PA_WEBHOOK_FAILED"
PA_WEBHOOK_ERROR_OUTBOX_INVALID = "E_PA_WEBHOOK_OUTBOX_INVALID"
PA_WEBHOOK_ERROR_DISPATCH_MISSING = "E_PA_WEBHOOK_DISPATCH_MISSING"
PA_WEBHOOK_ERROR_WORKSPACE_UNMAPPED = "E_PA_WORKSPACE_UNMAPPED"


@dataclass(frozen=True)
class PAWebhookServiceConfig:
    data_dir: str = "data"
    workspace_id: str = "local"
    routing_file: Optional[str] = None
    expected_secret_token: str = ""
    budget_slice_remote_llm_calls: Any = None
    replay_mode: bool = False
    bot_token: str = "stub-token"
    operator_ref: str = ""
    skill_ref: str = ""
    message_input_key: str = "request"
    verify_asvp: bool = True
    keys_dir: Optional[str] = None
    backend: str = "local_mock"
    model: Optional[str] = None
    remote_calls_armed: bool = False
    allow_network_egress: bool = False
    approved_by_human: bool = False
    target: str = "local"
    deadline_ms: int = 60000
    memory_context_enabled: bool = False
    memory_context_retrieval_limit: int = 8
    memory_context_include_stale: bool = False
    memory_context_continuity_event_limit: int = 50
    memory_context_audit_mode: bool = False

    @property
    def resolved_operator_ref(self) -> str:
        return str(self.operator_ref or self.skill_ref).strip()


class PAWebhookService:
    """THREAD-041: Telegram webhook -> canonical runtime -> outbox -> reply adapter."""

    def __init__(
        self,
        config: PAWebhookServiceConfig,
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
                submitter="telegram.webhook",
                consumer="telegram.reply",
                invalid_payload_error_code=PA_WEBHOOK_ERROR_FAILED,
                internal_error_code=PA_RUNTIME_ERROR_IO_FAILED,
                internal_error_delivery_source="pa_webhook.internal_error",
                fail_closed_error_codes=(PA_RUNTIME_ERROR_CONTEXT_FAILED,),
            ),
        )
        self._ingress = TelegramChannelAdapter(
            expected_secret_token=config.expected_secret_token,
            kernel_dispatcher=self._dispatcher,
        )

    @staticmethod
    def _response_body(
        *,
        ok: bool,
        error_code: Optional[str],
        webhook: Any,
        runtime: Optional[dict[str, Any]],
        dedup: bool,
        reply_sent: bool,
    ) -> dict[str, Any]:
        return {
            "ok": bool(ok),
            "error_code": error_code,
            "webhook": webhook,
            "runtime": runtime,
            "ev1": runtime,
            "dedup": bool(dedup),
            "reply_sent": bool(reply_sent),
        }

    def handle_webhook_request(self, *, raw_body: bytes, secret_token: Optional[str]) -> tuple[int, dict[str, Any]]:
        try:
            payload_str = raw_body.decode("utf-8")
        except Exception:
            return 400, self._response_body(
                ok=False,
                error_code="E_CHANNEL_PAYLOAD_INVALID",
                webhook=None,
                runtime=None,
                dedup=False,
                reply_sent=False,
            )

        budget: Any
        if self._cfg.budget_slice_remote_llm_calls is None:
            budget = MISSING_BUDGET
        else:
            budget = self._cfg.budget_slice_remote_llm_calls
        workspace_id = self._cfg.workspace_id

        if (
            self._router is not None
            and secret_token
            and secret_token == self._cfg.expected_secret_token
        ):
            try:
                route = self._router.route_for_payload(payload_str)
            except PAWorkspaceRouteUnmappedError:
                return 403, self._response_body(
                    ok=False,
                    error_code=PA_WEBHOOK_ERROR_WORKSPACE_UNMAPPED,
                    webhook={
                        "ok": False,
                        "error_code": PA_WEBHOOK_ERROR_WORKSPACE_UNMAPPED,
                    },
                    runtime=None,
                    dedup=False,
                    reply_sent=False,
                )
            if route is not None:
                workspace_id = route.workspace_id
                if route.budget_slice_remote_llm_calls is not MISSING_BUDGET:
                    budget = route.budget_slice_remote_llm_calls

        self._dispatcher.runtime_out = None
        if budget is MISSING_BUDGET:
            http_code, webhook_body = self._ingress.handle_webhook(
                payload_str=payload_str,
                secret_token=secret_token,
                workspace_id=workspace_id,
                replay_mode=bool(self._cfg.replay_mode),
            )
        else:
            http_code, webhook_body = self._ingress.handle_webhook(
                payload_str=payload_str,
                secret_token=secret_token,
                workspace_id=workspace_id,
                budget_slice_remote_llm_calls=budget,
                replay_mode=bool(self._cfg.replay_mode),
            )

        if bool(self._cfg.replay_mode):
            return 200, self._response_body(
                ok=False,
                error_code=PA_RUNTIME_ERROR_REPLAY_DENY,
                webhook=webhook_body,
                runtime=None,
                dedup=False,
                reply_sent=False,
            )

        if http_code != 200 or not isinstance(webhook_body, dict) or webhook_body.get("ok") is False:
            return http_code, self._response_body(
                ok=False,
                error_code=str(
                    webhook_body.get("error_code")
                    if isinstance(webhook_body, dict)
                    else PA_WEBHOOK_ERROR_FAILED
                ),
                webhook=webhook_body,
                runtime=None,
                dedup=False,
                reply_sent=False,
            )

        if str(webhook_body.get("status") or "").strip() == "ignored_non_text":
            return 200, self._response_body(
                ok=True,
                error_code=None,
                webhook=webhook_body,
                runtime=None,
                dedup=False,
                reply_sent=False,
            )

        runtime_out = self._dispatcher.runtime_out
        if not isinstance(runtime_out, dict):
            return 500, self._response_body(
                ok=False,
                error_code=PA_WEBHOOK_ERROR_DISPATCH_MISSING,
                webhook=webhook_body,
                runtime=None,
                dedup=False,
                reply_sent=False,
            )

        outbox_json = runtime_out.get("outbox")
        item = OutboxItem.from_json(outbox_json)
        dedup = bool(runtime_out.get("dedup"))
        if item is None and runtime_out.get("ok") is not True:
            return 200, self._response_body(
                ok=False,
                error_code=str(runtime_out.get("error_code") or PA_WEBHOOK_ERROR_FAILED),
                webhook=webhook_body,
                runtime=runtime_out,
                dedup=dedup,
                reply_sent=False,
            )
        if item is None:
            return 500, self._response_body(
                ok=False,
                error_code=PA_WEBHOOK_ERROR_OUTBOX_INVALID,
                webhook=webhook_body,
                runtime=runtime_out,
                dedup=dedup,
                reply_sent=False,
            )

        reply_sent = False
        if not dedup:
            reply_sent = bool(item.reply_sent_live) or bool(self._reply.handle_outbox_item(item))
        ok = bool(reply_sent or dedup)

        return 200, self._response_body(
            ok=ok,
            error_code=(
                None
                if ok
                else (
                    str(runtime_out.get("error_code") or PA_WEBHOOK_ERROR_FAILED)
                    if runtime_out.get("ok") is not True
                    else PA_WEBHOOK_ERROR_FAILED
                )
            ),
            webhook=webhook_body,
            runtime=runtime_out,
            dedup=dedup,
            reply_sent=reply_sent,
        )
