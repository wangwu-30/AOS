from __future__ import annotations

import asyncio
import hashlib
import json
import mimetypes
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional
import urllib.error
import urllib.parse
import urllib.request

from agentos_next.apps.assistant_loop import AssistantLoopRequest, AssistantLoopResult
from agentos_next.apps.canonical_task_ingress import build_canonical_task_ingress_request
from agentos_next.apps.telegram_reply import TelegramReplyAdapter
from agentos_next.kernel.executor import ExecuteRequest, ExecuteResult
from agentos_next.kernel.effective_runtime_capabilities import (
    build_effective_runtime_capabilities_v1,
    capability_names_from_effective_runtime_capabilities,
)
from agentos_next.kernel.evidence_store import FileEvidenceStore
from agentos_next.kernel.orchestrator import Orchestrator
from agentos_next.kernel.types import TraceContext
from agentos_next.pa.event_envelope import envelope_to_dict, validate_envelope_v0
from agentos_next.pa.event_log import FileEventLog
from agentos_next.pa.memory_pipeline import PAMemoryPipelineConfig, build_memory_context_for_event
from agentos_next.pa.outbox_store import FileOutboxStore, OutboxItem
from agentos_next.pa.runtime_error_codes import PA_RUNTIME_ERROR_CONTEXT_FAILED
from agentos_next.runtime.local_executor import LocalExecutor


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


def _string_tuple(raw: Any) -> tuple[str, ...]:
    if isinstance(raw, (list, tuple, set)):
        return tuple(str(item).strip() for item in raw if str(item).strip())
    txt = str(raw or "").strip()
    return (txt,) if txt else ()


def _int_or(default: int, raw: Any) -> int:
    try:
        return int(raw)
    except Exception:
        return int(default)


def build_assistant_runtime_capability_self_check(config: Any) -> dict[str, Any]:
    return build_effective_runtime_capabilities_v1(
        requested_capabilities=_string_tuple(getattr(config, "capabilities", ()) or ()),
        allow_network_egress=bool(getattr(config, "allow_network_egress", False)),
        bot_token=str(getattr(config, "bot_token", "") or ""),
        submitter="telegram",
        backend=str(getattr(config, "backend", "local_mock") or "local_mock"),
        model=(str(getattr(config, "model")) if getattr(config, "model", None) else None),
        planner_backend=(str(getattr(config, "planner_backend")) if getattr(config, "planner_backend", None) else None),
        planner_model=(str(getattr(config, "planner_model")) if getattr(config, "planner_model", None) else None),
        intent_backend=(str(getattr(config, "intent_backend")) if getattr(config, "intent_backend", None) else None),
        intent_model=(str(getattr(config, "intent_model")) if getattr(config, "intent_model", None) else None),
        communicator_backend=(
            str(getattr(config, "communicator_backend")) if getattr(config, "communicator_backend", None) else None
        ),
        communicator_model=(
            str(getattr(config, "communicator_model")) if getattr(config, "communicator_model", None) else None
        ),
    )


@dataclass(frozen=True)
class AssistantRuntimeDispatcherOptions:
    submitter: str = "telegram.ingress"
    consumer: str = "telegram.reply"
    invalid_payload_error_code: str = "E_PA_RUNTIME_PAYLOAD_INVALID"
    internal_error_code: str = "E_PA_RUNTIME_FAILED"
    internal_error_delivery_source: str = "pa_runtime.internal_error"
    fail_closed_error_codes: tuple[str, ...] = ()


class _FailClosedRuntimeError(RuntimeError):
    def __init__(self, error_code: str) -> None:
        super().__init__(str(error_code))
        self.error_code = str(error_code)


class AssistantRuntimeDispatcher:
    def __init__(
        self,
        config: Any,
        *,
        telegram_reply_adapter: TelegramReplyAdapter,
        effective_runtime_capabilities: dict[str, Any],
        run_assistant_runtime_async_fn: Callable[..., Any],
        options: AssistantRuntimeDispatcherOptions | None = None,
    ) -> None:
        self._cfg = config
        self._reply = telegram_reply_adapter
        self._effective_runtime_capabilities = dict(effective_runtime_capabilities or {})
        self._run_assistant_runtime_async = run_assistant_runtime_async_fn
        self._options = options or AssistantRuntimeDispatcherOptions()
        self._event_log = FileEventLog(data_dir=str(getattr(config, "data_dir", "data")))
        self._outbox = FileOutboxStore(data_dir=str(getattr(config, "data_dir", "data")))
        self.runtime_out: Optional[dict[str, Any]] = None

    def dispatch(self, envelope: Any, idempotency_key: str) -> None:
        self.runtime_out = None
        try:
            env = envelope_to_dict(envelope)
            ok, reason = validate_envelope_v0(env)
            if not ok:
                self.runtime_out = {
                    "ok": False,
                    "error_code": str(reason or self._options.invalid_payload_error_code),
                }
                return

            workspace_id = str(env.get("workspace_id") or self._cfg.workspace_id)
            event_id = str(env.get("event_id") or "").strip()
            existing = self._outbox.get(workspace_id=workspace_id, event_id=event_id)
            if existing is not None:
                self.runtime_out = self._runtime_output_from_item(item=existing, dedup=True)
                return

            try:
                self._event_log.write_once(workspace_id=workspace_id, event_id=event_id, envelope=env)
            except FileExistsError:
                pass

            typing_session = self._maybe_start_typing(env=env)
            stream_session = self._maybe_start_stream(env=env)
            try:
                res = self._execute_assistant_runtime(
                    env=env,
                    idempotency_key=idempotency_key,
                    stream_session=stream_session,
                )
                item = self._build_outbox_item(
                    env=env,
                    idempotency_key=idempotency_key,
                    res=res,
                    stream_session=stream_session,
                )
            except _FailClosedRuntimeError as exc:
                self.runtime_out = {"ok": False, "error_code": exc.error_code}
                return
            except Exception as exc:
                item = self._build_internal_error_outbox(
                    env=env,
                    idempotency_key=idempotency_key,
                    detail=str(exc),
                )
            finally:
                if typing_session is not None:
                    try:
                        typing_session.stop()
                    except Exception:
                        pass

            self._outbox.put_if_absent(item=item)
            self.runtime_out = self._runtime_output_from_item(item=item, dedup=False)
        except Exception:
            self.runtime_out = {"ok": False, "error_code": self._options.internal_error_code}

    def _maybe_start_typing(self, *, env: dict[str, Any]) -> Any:
        chat_id = str(env.get("conversation_id") or "").strip()
        if not chat_id:
            return None
        return self._reply.start_typing_session(chat_id)

    def _maybe_start_stream(self, *, env: dict[str, Any]) -> Any:
        return None

    def _execute_assistant_runtime(
        self,
        *,
        env: dict[str, Any],
        idempotency_key: str,
        stream_session: Any,
    ) -> AssistantLoopResult:
        prepared_attachments, attachment_refs = self._prepare_attachments(env=env)
        query = self._effective_query_text(
            message_text=str(env.get("message_text") or ""),
            attachments=prepared_attachments,
        )
        skill_dir = self._resolved_operator_ref()
        capabilities_csv = ",".join(
            capability_names_from_effective_runtime_capabilities(self._effective_runtime_capabilities)
        ) or None
        trace = self._build_trace(env=env)
        memory_context, memory_context_refs, memory_context_error = self._build_memory_context(env=env, trace=trace)
        if memory_context_error is not None:
            if memory_context_error in set(self._options.fail_closed_error_codes):
                raise _FailClosedRuntimeError(memory_context_error)
            return AssistantLoopResult(
                ok=False,
                final_output={
                    "schema_version": "1.0.0",
                    "ok": True,
                    "operator_ref": "builtin://channel.send_message",
                    "channel": "assistant_runtime",
                    "audience": "user",
                    "text": "我暂时无法读取所需记忆上下文，请稍后再试。",
                    "message_key": str(env.get("event_id") or "").strip() or "memory_context_error",
                    "delivery_stage": "blocker",
                    "update_preference": "new_message",
                    "delivery_mode": "create",
                    "metadata": {"source": "pa_runtime.memory_context_error"},
                },
                error_code=memory_context_error,
                steps=[],
                trace=trace,
                evidence_refs=list(memory_context_refs),
                followup_plan_ref="",
                followup_task_id=None,
                delivery_state="blocker",
                graph_id=str(env.get("event_id") or "").strip() or None,
            )

        loop_req = AssistantLoopRequest(
            query=query,
            assistant_skill_dir=Path(skill_dir) if skill_dir else None,
            workspace_id=str(env.get("workspace_id") or self._cfg.workspace_id),
            data_dir=str(getattr(self._cfg, "data_dir", "data")),
            trace=trace,
            idempotency_key=idempotency_key,
            deadline_ms=_int_or(60000, getattr(self._cfg, "deadline_ms", 60000)),
            verify_asvp=bool(getattr(self._cfg, "verify_asvp", True)),
            public_keys_dir=(
                Path(str(getattr(self._cfg, "keys_dir")))
                if getattr(self._cfg, "keys_dir", None)
                else None
            ),
            backend=str(getattr(self._cfg, "backend", "local_mock") or "local_mock"),
            model=(str(getattr(self._cfg, "model")) if getattr(self._cfg, "model", None) else None),
            intent_backend=(
                str(getattr(self._cfg, "intent_backend"))
                if getattr(self._cfg, "intent_backend", None)
                else None
            ),
            intent_model=(
                str(getattr(self._cfg, "intent_model"))
                if getattr(self._cfg, "intent_model", None)
                else None
            ),
            communicator_backend=(
                str(getattr(self._cfg, "communicator_backend"))
                if getattr(self._cfg, "communicator_backend", None)
                else None
            ),
            communicator_model=(
                str(getattr(self._cfg, "communicator_model"))
                if getattr(self._cfg, "communicator_model", None)
                else None
            ),
            response_language=(
                str(getattr(self._cfg, "response_language"))
                if getattr(self._cfg, "response_language", None)
                else None
            ),
            remote_calls_armed=bool(getattr(self._cfg, "remote_calls_armed", False)),
            allow_network_egress=bool(getattr(self._cfg, "allow_network_egress", False)),
            approved_by_human=bool(getattr(self._cfg, "approved_by_human", False)),
            replay_mode=False,
            capabilities=capabilities_csv,
            effective_runtime_capabilities=dict(self._effective_runtime_capabilities),
            memory_context=memory_context,
            llm_stream_callback=(stream_session.handle_event if stream_session is not None else None),
            telegram_stream_session=stream_session,
            output_event_sink=(
                (lambda event: self._handle_output_event(event=event, stream_session=stream_session))
                if stream_session is not None
                else None
            ),
            message_received_at_utc=(
                str(env.get("received_at_utc")).strip()
                if str(env.get("received_at_utc") or "").strip()
                else None
            ),
            agent_id="telegram_assistant",
            conversation_id=str(env.get("conversation_id") or "").strip() or None,
            attachments=tuple(prepared_attachments),
            graph_id=str(env.get("event_id") or "").strip() or None,
        )
        ingress = build_canonical_task_ingress_request(
            loop_req,
            submitter=self._options.submitter,
            consumer=self._options.consumer,
            raw_input=query,
            metadata={
                "source": str(env.get("source") or "telegram"),
                "event_id": str(env.get("event_id") or ""),
                "conversation_id": str(env.get("conversation_id") or ""),
                "sender_id": str(env.get("sender_id") or ""),
                "budget_slice_remote_llm_calls": _int_or(0, env.get("budget_slice_remote_llm_calls") or 0),
                "attachment_count": len(prepared_attachments),
            },
        )
        res = _run_async(
            self._run_assistant_runtime_async(
                ingress,
                runtime_mode="hybrid",
                direct_fallback=True,
            )
        )
        if self._should_use_legacy_skill_fallback(res=res):
            res = self._execute_legacy_operator_skill(
                env=env,
                idempotency_key=idempotency_key,
                trace=trace,
                prior_result=res,
            )
        if not memory_context_refs:
            return res
        return AssistantLoopResult(
            ok=res.ok,
            final_output=res.final_output,
            error_code=res.error_code,
            steps=list(res.steps),
            trace=res.trace,
            evidence_refs=list(dict.fromkeys([*list(memory_context_refs), *list(attachment_refs), *list(res.evidence_refs)])),
            followup_plan_ref=res.followup_plan_ref,
            followup_task_id=res.followup_task_id,
            delivery_state=res.delivery_state,
            graph_id=res.graph_id,
        )

    def _effective_query_text(self, *, message_text: str, attachments: list[dict[str, Any]]) -> str:
        text = str(message_text or "").strip()
        if text:
            return text
        if not attachments:
            return ""
        media_kinds = [str(item.get("media_kind") or "").strip() for item in attachments if str(item.get("media_kind") or "").strip()]
        if not media_kinds:
            return "请处理我发送的附件。"
        return f"请处理我发送的附件：{'、'.join(media_kinds)}。"

    def _prepare_attachments(self, *, env: dict[str, Any]) -> tuple[list[dict[str, Any]], tuple[str, ...]]:
        raw_items = env.get("message_attachments")
        if not isinstance(raw_items, (list, tuple)):
            return [], ()
        evidence = FileEvidenceStore(data_dir=str(getattr(self._cfg, "data_dir", "data")))
        prepared: list[dict[str, Any]] = []
        evidence_refs: list[str] = []
        for index, raw in enumerate(raw_items, start=1):
            if not isinstance(raw, dict):
                continue
            item = dict(raw)
            attachment_id = str(item.get("attachment_id") or f"attachment_{index}").strip() or f"attachment_{index}"
            media_kind = str(item.get("media_kind") or "").strip().lower()
            file_id = str(item.get("telegram_file_id") or "").strip()
            mime_type = str(item.get("mime_type") or "").strip() or self._default_mime_type(item=item)
            file_name = str(item.get("filename") or "").strip() or self._default_file_name(
                attachment_id=attachment_id,
                media_kind=media_kind,
                mime_type=mime_type,
            )
            enriched = dict(item)
            enriched["mime_type"] = mime_type or None
            enriched["filename"] = file_name or None
            enriched["download_status"] = str(item.get("download_status") or "pending").strip() or "pending"
            enriched["availability"] = str(item.get("availability") or "metadata_only").strip() or "metadata_only"
            if file_id and str(getattr(self._cfg, "bot_token", "") or "").strip():
                try:
                    blob = self._download_telegram_file(file_id=file_id)
                except Exception as exc:
                    enriched["download_status"] = "failed"
                    enriched["download_error"] = str(exc)[:240]
                    prepared.append(enriched)
                    error_ref = evidence.add_json(
                        {
                            "schema_version": "1.0.0",
                            "type": "telegram_attachment_download_failure_v1",
                            "attachment_id": attachment_id,
                            "telegram_file_id": file_id,
                            "media_kind": media_kind,
                            "message": str(exc),
                        },
                        kind="error",
                    )
                    evidence_refs.append(error_ref.ref)
                    continue
                media_ref = evidence.add_bytes(blob["content"], kind="artifact_draft", content_type=blob["content_type"])
                artifact = evidence.commit_artifact(
                    ref=media_ref.ref,
                    kind=f"telegram_{media_kind or 'attachment'}",
                    title=file_name or attachment_id,
                    visibility="internal",
                )
                enriched["download_status"] = "downloaded"
                enriched["availability"] = "downloaded"
                enriched["size_bytes"] = int(blob["size_bytes"])
                enriched["sha256"] = str(blob["sha256"])
                enriched["local_artifact_ref"] = artifact.id
                enriched["evidence_ref"] = media_ref.ref
                enriched["local_path"] = blob["local_path"]
                evidence_refs.append(media_ref.ref)
            prepared.append(enriched)
        if prepared:
            summary_ref = evidence.add_json(
                {
                    "schema_version": "1.0.0",
                    "type": "telegram_attachment_bundle_v1",
                    "attachments": prepared,
                },
                kind="artifact_draft",
            )
            evidence_refs.append(summary_ref.ref)
        return prepared, tuple(dict.fromkeys(evidence_refs))

    def _download_telegram_file(self, *, file_id: str) -> dict[str, Any]:
        token = str(getattr(self._cfg, "bot_token", "") or "").strip()
        if not token:
            raise RuntimeError("telegram bot token is not configured for attachment download")
        get_file_url = (
            f"https://api.telegram.org/bot{token}/getFile?"
            + urllib.parse.urlencode({"file_id": str(file_id)})
        )
        req = urllib.request.Request(get_file_url, method="GET")
        with urllib.request.urlopen(req, timeout=max(5, _int_or(20, getattr(self._cfg, "timeout_seconds", 20)))) as resp:
            raw = resp.read()
        try:
            obj = json.loads(raw.decode("utf-8"))
        except Exception as exc:
            raise RuntimeError(f"telegram getFile returned invalid JSON for file_id={file_id}") from exc
        if not isinstance(obj, dict) or obj.get("ok") is not True:
            raise RuntimeError(f"telegram getFile failed for file_id={file_id}")
        result = dict(obj.get("result") or {})
        file_path = str(result.get("file_path") or "").strip()
        if not file_path:
            raise RuntimeError(f"telegram getFile returned no file_path for file_id={file_id}")
        download_url = f"https://api.telegram.org/file/bot{token}/{file_path}"
        download_req = urllib.request.Request(download_url, method="GET")
        with urllib.request.urlopen(download_req, timeout=max(5, _int_or(20, getattr(self._cfg, "timeout_seconds", 20)))) as resp:
            content = resp.read()
            content_type = str(resp.headers.get("Content-Type") or "").strip()
        media_dir = Path(str(getattr(self._cfg, "data_dir", "data"))) / "pa" / "telegram_media"
        media_dir.mkdir(parents=True, exist_ok=True)
        local_path = media_dir / hashlib.sha256(f"{file_id}|{file_path}".encode("utf-8")).hexdigest()[:24]
        local_path.write_bytes(content)
        if not content_type:
            guessed_type, _ = mimetypes.guess_type(file_path)
            content_type = guessed_type or "application/octet-stream"
        return {
            "content": content,
            "content_type": content_type,
            "size_bytes": len(content),
            "sha256": hashlib.sha256(content).hexdigest(),
            "local_path": str(local_path),
        }

    @staticmethod
    def _default_mime_type(*, item: dict[str, Any]) -> str:
        media_kind = str(item.get("media_kind") or "").strip().lower()
        if media_kind == "image":
            return "image/jpeg"
        if media_kind == "audio":
            return "audio/ogg"
        if media_kind == "video":
            return "video/mp4"
        return "application/octet-stream"

    @staticmethod
    def _default_file_name(*, attachment_id: str, media_kind: str, mime_type: str) -> str:
        extension = mimetypes.guess_extension(str(mime_type or "").split(";")[0].strip()) or ""
        base = str(attachment_id or "attachment").strip().replace(":", "_")
        if extension and not base.endswith(extension):
            return f"{base}{extension}"
        return base

    def _handle_output_event(self, *, event: dict[str, Any], stream_session: Any) -> None:
        if stream_session is None or not isinstance(event, dict):
            return
        typ = str(event.get("event_type") or "").strip()
        payload = dict(event.get("payload") or {})
        if typ in {"ack", "progress"}:
            summary = str(payload.get("summary") or payload.get("operator_ref") or "").strip()
            if summary:
                try:
                    stream_session.update_progress(summary)
                except Exception:
                    return
            return
        if typ == "reply_delta":
            try:
                stream_session.handle_event({"type": "delta", "delta": str(payload.get("delta") or "")})
            except Exception:
                return

    def _build_memory_context(
        self,
        *,
        env: dict[str, Any],
        trace: TraceContext,
    ) -> tuple[dict[str, Any] | None, tuple[str, ...], str | None]:
        if not bool(getattr(self._cfg, "memory_context_enabled", False)):
            return None, (), None
        mem_out = build_memory_context_for_event(
            config=PAMemoryPipelineConfig(
                enabled=True,
                retrieval_limit=_int_or(8, getattr(self._cfg, "memory_context_retrieval_limit", 8)),
                include_stale=bool(getattr(self._cfg, "memory_context_include_stale", False)),
                continuity_event_limit=_int_or(
                    50,
                    getattr(self._cfg, "memory_context_continuity_event_limit", 50),
                ),
                audit_mode=bool(getattr(self._cfg, "memory_context_audit_mode", False)),
            ),
            data_dir=Path(str(getattr(self._cfg, "data_dir", "data"))),
            workspace_id=str(env.get("workspace_id") or self._cfg.workspace_id),
            conversation_id=str(env.get("conversation_id") or ""),
            trace_id=str(trace.trace_id),
            turn_id=str(trace.turn_id),
            user_message=str(env.get("message_text") or ""),
            project_id=str(env.get("project_id") or "").strip() or None,
            replay_mode=False,
        )
        if not mem_out.ok:
            return None, tuple(mem_out.evidence_refs), PA_RUNTIME_ERROR_CONTEXT_FAILED
        return (
            dict(mem_out.memory_context or {}) if isinstance(mem_out.memory_context, dict) else None,
            tuple(mem_out.evidence_refs),
            None,
        )

    def _build_trace(self, *, env: dict[str, Any]) -> TraceContext:
        seed = "|".join(
            [
                str(env.get("event_id") or ""),
                str(env.get("idempotency_key") or ""),
                str(env.get("workspace_id") or self._cfg.workspace_id),
            ]
        )
        digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]
        return TraceContext(
            trace_id=f"tr_tg_{digest}",
            turn_id=f"turn_tg_{digest}",
            span_id="span_tg_ingress",
        )

    def _build_outbox_item(
        self,
        *,
        env: dict[str, Any],
        idempotency_key: str,
        res: AssistantLoopResult,
        stream_session: Any,
    ) -> OutboxItem:
        deliveries_list = self._deliveries_from_result(res)
        if not deliveries_list:
            fallback_delivery = self._fallback_delivery_from_result(env=env, res=res)
            if fallback_delivery is not None:
                deliveries_list.append(fallback_delivery)
        deliveries = tuple(deliveries_list)
        reply_text = str(deliveries[-1].get("text") or "").strip() if deliveries else ""
        execute_status = "accepted" if bool(res.ok) else ("hold" if str(res.delivery_state or "").strip() == "hold" else "failed")
        return OutboxItem(
            schema_version="1.0.0",
            stored_at_utc=_utc_iso(),
            workspace_id=str(env.get("workspace_id") or self._cfg.workspace_id),
            event_id=str(env.get("event_id") or ""),
            idempotency_key=idempotency_key,
            trace_id=str(res.trace.trace_id),
            turn_id=str(res.trace.turn_id),
            span_id=str(res.trace.span_id),
            execute_status=execute_status,
            execute_error_code=(str(res.error_code) if res.error_code else None),
            evidence_refs=tuple(str(ref) for ref in list(res.evidence_refs)),
            reply_text=reply_text,
            deliveries=deliveries,
            metering_evidence_refs=(),
            reply_sent_live=False,
            reply_delivery_mode=None,
        )

    def _fallback_delivery_from_result(
        self,
        *,
        env: dict[str, Any],
        res: AssistantLoopResult,
    ) -> Optional[dict[str, Any]]:
        if str(res.delivery_state or "").strip() != "hold":
            return None
        text = self._hold_reply_text(res=res)
        if not text:
            return None
        return {
            "schema_version": "1.0.0",
            "ok": True,
            "operator_ref": "builtin://channel.send_message",
            "channel": "assistant_runtime",
            "audience": "user",
            "text": text,
            "message_key": str(env.get("event_id") or "").strip() or "runtime_hold",
            "delivery_stage": "hold",
            "update_preference": "new_message",
            "delivery_mode": "create",
            "metadata": {
                "source": "pa_runtime.hold_fallback",
                "error_code": str(res.error_code or "").strip() or None,
            },
        }

    @staticmethod
    def _hold_reply_text(*, res: AssistantLoopResult) -> str:
        error_code = str(res.error_code or "").strip()
        if error_code == "E_HITL_REQUIRED":
            return "这次处理已暂停，需要人工继续处理后才能完成。"
        return "这次处理已暂停，请稍后再试。"

    def _build_internal_error_outbox(
        self,
        *,
        env: dict[str, Any],
        idempotency_key: str,
        detail: str,
    ) -> OutboxItem:
        evidence = FileEvidenceStore(data_dir=str(getattr(self._cfg, "data_dir", "data")))
        err_ref = evidence.add_json(
            {
                "schema_version": "1.0.0",
                "ok": False,
                "error_code": self._options.internal_error_code,
                "message": str(detail or "assistant runtime execution failed"),
            },
            kind="error",
        )
        trace = self._build_trace(env=env)
        return OutboxItem(
            schema_version="1.0.0",
            stored_at_utc=_utc_iso(),
            workspace_id=str(env.get("workspace_id") or self._cfg.workspace_id),
            event_id=str(env.get("event_id") or ""),
            idempotency_key=idempotency_key,
            trace_id=str(trace.trace_id),
            turn_id=str(trace.turn_id),
            span_id=str(trace.span_id),
            execute_status="failed",
            execute_error_code=self._options.internal_error_code,
            evidence_refs=(err_ref.ref,),
            reply_text="我暂时没能完成这次处理，请稍后再试。",
            deliveries=(
                {
                    "schema_version": "1.0.0",
                    "ok": True,
                    "operator_ref": "builtin://channel.send_message",
                    "channel": "assistant_runtime",
                    "audience": "user",
                    "text": "我暂时没能完成这次处理，请稍后再试。",
                    "message_key": str(env.get("event_id") or "").strip() or "runtime_error",
                    "delivery_stage": "blocker",
                    "update_preference": "new_message",
                    "delivery_mode": "create",
                    "metadata": {"source": self._options.internal_error_delivery_source},
                },
            ),
            metering_evidence_refs=(),
            reply_sent_live=False,
            reply_delivery_mode=None,
        )

    def _deliveries_from_result(self, res: AssistantLoopResult) -> list[dict[str, Any]]:
        deliveries: list[dict[str, Any]] = []
        seen: set[tuple[str, str, str]] = set()

        def _add(obj: dict[str, Any]) -> None:
            operator_ref = str(obj.get("operator_ref") or "").strip()
            text = str(obj.get("text") or "").strip()
            stage = str(obj.get("delivery_stage") or "").strip()
            key = str(obj.get("message_key") or "").strip()
            if operator_ref != "builtin://channel.send_message" or not text:
                return
            dedup_key = (key, stage, text)
            if dedup_key in seen:
                return
            seen.add(dedup_key)
            deliveries.append(dict(obj))

        final_output = dict(res.final_output or {}) if isinstance(res.final_output, dict) else {}
        if final_output:
            _add(final_output)

        evidence = FileEvidenceStore(data_dir=str(getattr(self._cfg, "data_dir", "data")))
        for step in list(res.steps):
            if not isinstance(step, dict):
                continue
            if str(step.get("operator_ref") or "").strip() != "builtin://channel.send_message":
                continue
            if str(step.get("status") or "").strip() != "accepted":
                continue
            for ref in reversed(list(step.get("evidence_refs") or [])):
                blob = evidence.get_blob(str(ref))
                if blob is None or blob.content_type != "application/json":
                    continue
                try:
                    obj = json.loads(blob.content.decode("utf-8", errors="replace"))
                except Exception:
                    continue
                if isinstance(obj, dict):
                    _add(obj)
                    break
        return deliveries

    @staticmethod
    def _runtime_output_from_item(*, item: OutboxItem, dedup: bool) -> dict[str, Any]:
        return {
            "ok": str(item.execute_status or "").strip() == "accepted",
            "error_code": item.execute_error_code,
            "outbox": item.to_json(),
            "dedup": bool(dedup),
        }

    def _resolved_operator_ref(self) -> str:
        return str(
            getattr(self._cfg, "resolved_operator_ref", "")
            or getattr(self._cfg, "operator_ref", "")
            or getattr(self._cfg, "skill_ref", "")
        ).strip()

    def _should_use_legacy_skill_fallback(self, *, res: AssistantLoopResult) -> bool:
        if str(res.error_code or "").strip() != "E_INPUT_SCHEMA":
            return False
        return self._legacy_skill_contract_path() is not None

    def _execute_legacy_operator_skill(
        self,
        *,
        env: dict[str, Any],
        idempotency_key: str,
        trace: TraceContext,
        prior_result: AssistantLoopResult,
    ) -> AssistantLoopResult:
        operator_ref = self._resolved_operator_ref()
        contract = self._load_legacy_skill_contract()
        input_key = self._legacy_message_input_key(contract=contract)
        req = ExecuteRequest(
            workspace_id=str(env.get("workspace_id") or self._cfg.workspace_id),
            operator_ref=operator_ref,
            arguments={
                input_key: str(env.get("message_text") or ""),
                "metadata": {
                    "source": str(env.get("source", "telegram")),
                    "sender_id": str(env.get("sender_id", "")),
                    "chat_id": str(env.get("conversation_id", "")),
                    "received_at_utc": str(env.get("received_at_utc", "")),
                },
            },
            idempotency_key=idempotency_key,
            deadline_ms=_int_or(60000, getattr(self._cfg, "deadline_ms", 60000)),
            trace=trace,
            policy_context={
                "verify_asvp": bool(getattr(self._cfg, "verify_asvp", True)),
                "public_keys_dir": getattr(self._cfg, "keys_dir", None),
                "backend": str(getattr(self._cfg, "backend", "local_mock") or "local_mock"),
                "model": getattr(self._cfg, "model", None),
                "remote_calls_armed": bool(getattr(self._cfg, "remote_calls_armed", False)),
                "allow_network_egress": bool(getattr(self._cfg, "allow_network_egress", False)),
                "approved_by_human": bool(getattr(self._cfg, "approved_by_human", False)),
                "replay_mode": False,
                "bot_token": getattr(self._cfg, "bot_token", None),
            },
            preferred_target=str(getattr(self._cfg, "target", "local") or "local"),
            budget_slice=_int_or(0, env.get("budget_slice_remote_llm_calls") or 0),
        )
        local_exec = LocalExecutor.for_data_dir(str(getattr(self._cfg, "data_dir", "data")))
        orch = Orchestrator.for_data_dir(
            str(getattr(self._cfg, "data_dir", "data")),
            local_executor=local_exec,
        )
        exec_res = _run_async(orch.execute(req))
        reply_text = self._legacy_reply_text(exec_res=exec_res)
        merged_refs = list(
            dict.fromkeys(
                [
                    *list(prior_result.evidence_refs),
                    *[str(ref.ref) for ref in list(exec_res.evidence_refs)],
                ]
            )
        )
        return AssistantLoopResult(
            ok=str(exec_res.status or "").strip() == "accepted",
            final_output={
                "schema_version": "1.0.0",
                "ok": True,
                "operator_ref": "builtin://channel.send_message",
                "channel": "assistant_runtime",
                "audience": "user",
                "text": reply_text,
                "message_key": str(env.get("event_id") or "").strip() or "legacy_skill_reply",
                "delivery_stage": ("final" if str(exec_res.status or "").strip() == "accepted" else "blocker"),
                "update_preference": "new_message",
                "delivery_mode": "create",
                "metadata": {
                    "source": "pa_runtime.legacy_operator_skill",
                    "legacy_input_key": input_key,
                },
            },
            error_code=exec_res.error_code,
            steps=[],
            trace=trace,
            evidence_refs=merged_refs,
            followup_plan_ref="",
            followup_task_id=None,
            delivery_state=("done" if str(exec_res.status or "").strip() == "accepted" else "blocker"),
            graph_id=prior_result.graph_id,
        )

    def _legacy_reply_text(self, *, exec_res: ExecuteResult) -> str:
        if str(exec_res.status or "").strip() == "accepted":
            text = self._extract_execute_result_text(exec_res=exec_res)
            if text:
                return text
            return "已收到。"
        if str(exec_res.error_code or "").strip() == "E_PROVIDER_BAD_RESPONSE":
            return "远端模型服务返回异常，请稍后再试。"
        return f"Execution {exec_res.status}. Error: {exec_res.error_code or 'None'}"

    def _extract_execute_result_text(self, *, exec_res: ExecuteResult) -> str:
        evidence = FileEvidenceStore(data_dir=str(getattr(self._cfg, "data_dir", "data")))
        io_refs = [
            ref
            for ref in list(exec_res.evidence_refs)
            if str(getattr(ref, "kind", "")).strip() in {"llm_io", "tool_io"}
        ]
        llm_refs = [ref for ref in io_refs if str(getattr(ref, "kind", "")).strip() == "llm_io"]
        search_order = [*reversed(llm_refs), *reversed(io_refs)]
        for ref in search_order:
            blob = evidence.get_blob(str(getattr(ref, "ref", "")))
            if blob is None or blob.content_type != "application/json":
                continue
            try:
                obj = json.loads(blob.content.decode("utf-8", errors="replace"))
            except Exception:
                continue
            if not isinstance(obj, dict):
                continue
            output = obj.get("output")
            if not isinstance(output, dict):
                output = {}
            for key in ("reply", "message", "summary", "text", "result"):
                val = obj.get(key)
                if not isinstance(val, str):
                    val = output.get(key)
                if isinstance(val, str) and val.strip():
                    return val.strip()
        return ""

    def _legacy_skill_contract_path(self) -> Path | None:
        operator_ref = self._resolved_operator_ref()
        if not operator_ref or "://" in operator_ref:
            return None
        try:
            root = Path(operator_ref)
        except Exception:
            return None
        path = root / "contract.skill"
        return path if path.is_file() else None

    def _load_legacy_skill_contract(self) -> dict[str, Any] | None:
        path = self._legacy_skill_contract_path()
        if path is None:
            return None
        try:
            obj = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
        return dict(obj) if isinstance(obj, dict) else None

    def _legacy_message_input_key(self, *, contract: dict[str, Any] | None) -> str:
        configured = str(getattr(self._cfg, "message_input_key", "request") or "request").strip() or "request"
        if not isinstance(contract, dict):
            return configured
        inputs_schema = contract.get("inputs_schema")
        if not isinstance(inputs_schema, dict):
            return configured
        properties = inputs_schema.get("properties")
        prop_keys = [str(key).strip() for key in (properties or {}).keys() if str(key).strip()]
        if configured in prop_keys:
            return configured
        required = [str(key).strip() for key in (inputs_schema.get("required") or []) if str(key).strip()]
        if len(required) == 1:
            return required[0]
        if len(prop_keys) == 1:
            return prop_keys[0]
        return configured


def _utc_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
