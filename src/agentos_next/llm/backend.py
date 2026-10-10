from __future__ import annotations

import base64
import json
import os
import threading
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Optional, Protocol

from agentos_next.skills.jsonschema_subset import (
    ValidationError,
    synthesize_instance,
    validate_instance,
)

from .openai_codex_oauth import (
    OpenAICodexOAuthProvider,
    OpenAICodexOAuthTransportError,
    RemoteCallsDisabledError,
)


class RemoteLLMCallBudget:
    """THREAD-029: Budget v1 for remote LLM calls (remote_llm_calls).

    The budget is per-execution and is enforced atomically per remote call.
    """

    def __init__(self, remaining: int) -> None:
        self._lock = threading.Lock()
        self.initial = int(remaining)
        self.remaining = int(remaining)
        self.consumed = 0

    def try_consume(self, n: int = 1) -> bool:
        if n <= 0:
            return True
        with self._lock:
            if self.remaining < n:
                return False
            self.remaining -= n
            self.consumed += n
            return True


@dataclass(frozen=True)
class LLMSafetyGate:
    remote_calls_armed: bool = False
    allow_network_egress: bool = False
    requires_human_approval: bool = False
    approved_by_human: bool = False
    replay_mode: bool = False
    remote_llm_calls_budget: Optional[RemoteLLMCallBudget] = None


class LLMCallError(RuntimeError):
    def __init__(self, error_code: str, message: str) -> None:
        super().__init__(message)
        self.error_code = error_code


class LLMBackend(Protocol):
    def complete_json(
        self,
        *,
        prompt: str,
        json_schema: Mapping[str, Any],
        safety: LLMSafetyGate,
        model_id: Optional[str] = None,
        stream_callback: Optional[Callable[[dict[str, Any]], None]] = None,
        input_media: Optional[list[dict[str, Any]]] = None,
    ) -> dict[str, Any]:  # pragma: no cover (protocol)
        raise NotImplementedError


REMOTE_LLM_BACKEND_NAMES = frozenset({"codex_oauth", "doubao_ark", "minimax"})


def is_remote_llm_backend(backend_name: str | None) -> bool:
    return str(backend_name or "").strip().lower() in REMOTE_LLM_BACKEND_NAMES


class LocalMockLLMBackend:
    """Deterministic local backend for default runs.

    Produces a minimal instance that should satisfy `json_schema`.
    """

    def complete_json(
        self,
        *,
        prompt: str,
        json_schema: Mapping[str, Any],
        safety: LLMSafetyGate,
        model_id: Optional[str] = None,
        stream_callback: Optional[Callable[[dict[str, Any]], None]] = None,
        input_media: Optional[list[dict[str, Any]]] = None,
    ) -> dict[str, Any]:
        del input_media
        out = synthesize_instance(json_schema)
        if not isinstance(out, dict):
            raise LLMCallError(
                "E_PROVIDER_BAD_RESPONSE",
                "mock backend only supports object-shaped output schemas",
            )
        _enrich_mock_output(out, json_schema, prompt)
        validate_instance(out, json_schema)
        return dict(out)


class CodexOAuthLLMBackend:
    """Remote backend using OpenAICodexOAuthProvider (Codex OAuth mode)."""

    def __init__(self, provider: OpenAICodexOAuthProvider) -> None:
        self.provider = provider

    def complete_json(
        self,
        *,
        prompt: str,
        json_schema: Mapping[str, Any],
        safety: LLMSafetyGate,
        model_id: Optional[str] = None,
        stream_callback: Optional[Callable[[dict[str, Any]], None]] = None,
        input_media: Optional[list[dict[str, Any]]] = None,
    ) -> dict[str, Any]:
        if safety.replay_mode:
            raise LLMCallError("E_REPLAY_REMOTE_DISABLED", "replay_mode=True forbids remote LLM calls")
        if safety.requires_human_approval and not safety.approved_by_human:
            raise LLMCallError("E_HITL_REQUIRED", "human approval required")

        # Enforce the ADR-0007 double gate. Provider also enforces this, but keep the error code stable.
        if not safety.remote_calls_armed:
            raise LLMCallError("E_REMOTE_CALL_NOT_ARMED", "remote_calls_armed=false")
        if not safety.allow_network_egress:
            raise LLMCallError("E_NETWORK_EGRESS_DENY", "allow_network_egress=false")

        budget = safety.remote_llm_calls_budget
        if budget is not None:
            # Must be atomic and must happen before the remote request.
            if not budget.try_consume(1):
                raise LLMCallError(
                    "E_BUDGET_EXHAUSTED",
                    f"remote_llm_calls budget exhausted (remaining={budget.remaining}, consumed={budget.consumed})",
                )

        # Per-call gating.
        self.provider.remote_calls_armed = safety.remote_calls_armed
        self.provider.allow_network_egress = safety.allow_network_egress

        # Use model_id directly as requested (no auto-mapping to -codex)
        effective_model = model_id or "gpt-4o"

        # Split prompt into instructions and input for the Responses API
        # We look for "Logic:" and "Input JSON:" as pivot points.
        instructions = "You are an agent executing a skill contract."
        input_text = prompt
        
        if "Logic:" in prompt:
            parts = prompt.split("Logic:", 1)
            # The part before "Logic:" is meta-info, after is logic
            rest = parts[1]
            if "Input JSON:" in rest:
                p2 = rest.split("Input JSON:", 1)
                instructions = parts[0].strip() + "\nLogic:" + p2[0].strip()
                input_text = "Input JSON:" + p2[1].strip()
            else:
                instructions = prompt.strip()
                input_text = "Execute the logic above."

        content_items: list[dict[str, Any]] = [{"type": "input_text", "text": input_text.strip()}]
        content_items.extend(_openai_input_media_items(input_media))
        payload: dict[str, Any] = {
            "model": effective_model,
            "instructions": instructions.strip(),
            "input": [
                {
                    "type": "message",
                    "role": "user",
                    "content": content_items,
                }
            ],
            "store": False,
            "stream": True,
        }

        try:
            resp = self.provider.codex_responses(payload, stream_callback=stream_callback)
        except RemoteCallsDisabledError as e:
            raise LLMCallError("E_REMOTE_CALL_NOT_ARMED", str(e)) from e
        except OpenAICodexOAuthTransportError as e:
            raise LLMCallError("E_PROVIDER_BAD_RESPONSE", _format_provider_transport_error(e)) from e
        except Exception as e:
            raise LLMCallError("E_PROVIDER_BAD_RESPONSE", f"provider error: {e}") from e

        out = _extract_json_object(resp)
        try:
            validate_instance(out, json_schema)
        except ValidationError as e:
            raise LLMCallError("E_PROVIDER_BAD_RESPONSE", f"output failed schema validation: {e}") from e
        return out


class DoubaoArkLLMBackend:
    """Remote backend using Volcengine Ark Chat Completions compatibility API."""

    default_base_url = "https://ark.cn-beijing.volces.com/api/v3"

    def __init__(self, *, api_key: Optional[str] = None, base_url: Optional[str] = None, timeout_sec: float = 60.0) -> None:
        self.api_key = str(api_key or os.environ.get("ARK_API_KEY") or "").strip()
        self.base_url = str(base_url or os.environ.get("ARK_BASE_URL") or self.default_base_url).strip().rstrip("/")
        self.timeout_sec = float(timeout_sec)

    def complete_json(
        self,
        *,
        prompt: str,
        json_schema: Mapping[str, Any],
        safety: LLMSafetyGate,
        model_id: Optional[str] = None,
        stream_callback: Optional[Callable[[dict[str, Any]], None]] = None,
        input_media: Optional[list[dict[str, Any]]] = None,
    ) -> dict[str, Any]:
        del stream_callback  # v1: non-streaming Ark integration
        if input_media:
            raise LLMCallError("E_MULTIMODAL_UNSUPPORTED", "doubao_ark backend is not configured for multimodal attachments")
        if safety.replay_mode:
            raise LLMCallError("E_REPLAY_REMOTE_DISABLED", "replay_mode=True forbids remote LLM calls")
        if safety.requires_human_approval and not safety.approved_by_human:
            raise LLMCallError("E_HITL_REQUIRED", "human approval required")
        if not safety.remote_calls_armed:
            raise LLMCallError("E_REMOTE_CALL_NOT_ARMED", "remote_calls_armed=false")
        if not safety.allow_network_egress:
            raise LLMCallError("E_NETWORK_EGRESS_DENY", "allow_network_egress=false")

        if not self.api_key:
            raise LLMCallError("E_PROVIDER_AUTH_MISSING", "ARK_API_KEY is required for doubao_ark backend")
        effective_model = str(model_id or os.environ.get("ARK_MODEL_ID") or "").strip()
        if not effective_model:
            raise LLMCallError("E_MODEL_ID_REQUIRED", "doubao_ark backend requires endpoint_id as model_id")

        budget = safety.remote_llm_calls_budget
        if budget is not None and not budget.try_consume(1):
            raise LLMCallError(
                "E_BUDGET_EXHAUSTED",
                f"remote_llm_calls budget exhausted (remaining={budget.remaining}, consumed={budget.consumed})",
            )

        payload = {
            "model": effective_model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
        }
        req = urllib.request.Request(
            url=f"{self.base_url}/chat/completions",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_sec) as resp:
                raw = resp.read()
        except urllib.error.HTTPError as e:
            body_preview = ""
            try:
                body_preview = e.read().decode("utf-8", errors="replace")
            except Exception:
                body_preview = ""
            raise LLMCallError(
                "E_PROVIDER_BAD_RESPONSE",
                _format_http_transport_error(status=e.code, body_preview=body_preview),
            ) from e
        except urllib.error.URLError as e:
            raise LLMCallError("E_PROVIDER_BAD_RESPONSE", f"provider transport error: {e}") from e
        except Exception as e:
            raise LLMCallError("E_PROVIDER_BAD_RESPONSE", f"provider error: {e}") from e

        try:
            resp_obj = json.loads(raw.decode("utf-8"))
        except Exception as e:
            raise LLMCallError("E_PROVIDER_BAD_RESPONSE", f"provider returned non-JSON response: {e}") from e

        out = _extract_json_object(resp_obj)
        try:
            validate_instance(out, json_schema)
        except ValidationError as e:
            raise LLMCallError("E_PROVIDER_BAD_RESPONSE", f"output failed schema validation: {e}") from e
        return out


class MiniMaxLLMBackend:
    """Remote backend using MiniMax OpenAI-compatible Chat Completions API."""

    default_base_url = "https://api.minimax.io/v1"
    default_model = "codex-MiniMax-M2.5"

    def __init__(self, *, api_key: Optional[str] = None, base_url: Optional[str] = None, timeout_sec: float = 60.0) -> None:
        self.api_key = str(api_key or os.environ.get("MINIMAX_API_KEY") or "").strip()
        self.base_url = str(base_url or os.environ.get("MINIMAX_BASE_URL") or self.default_base_url).strip().rstrip("/")
        self.timeout_sec = float(timeout_sec)

    def complete_json(
        self,
        *,
        prompt: str,
        json_schema: Mapping[str, Any],
        safety: LLMSafetyGate,
        model_id: Optional[str] = None,
        stream_callback: Optional[Callable[[dict[str, Any]], None]] = None,
        input_media: Optional[list[dict[str, Any]]] = None,
    ) -> dict[str, Any]:
        del stream_callback  # v1: non-streaming MiniMax integration
        if input_media:
            raise LLMCallError("E_MULTIMODAL_UNSUPPORTED", "minimax backend is not configured for multimodal attachments")
        if safety.replay_mode:
            raise LLMCallError("E_REPLAY_REMOTE_DISABLED", "replay_mode=True forbids remote LLM calls")
        if safety.requires_human_approval and not safety.approved_by_human:
            raise LLMCallError("E_HITL_REQUIRED", "human approval required")
        if not safety.remote_calls_armed:
            raise LLMCallError("E_REMOTE_CALL_NOT_ARMED", "remote_calls_armed=false")
        if not safety.allow_network_egress:
            raise LLMCallError("E_NETWORK_EGRESS_DENY", "allow_network_egress=false")

        if not self.api_key:
            raise LLMCallError("E_PROVIDER_AUTH_MISSING", "MINIMAX_API_KEY is required for minimax backend")
        effective_model = str(model_id or os.environ.get("MINIMAX_MODEL_ID") or self.default_model).strip()
        if not effective_model:
            raise LLMCallError("E_MODEL_ID_REQUIRED", "minimax backend requires model_id or MINIMAX_MODEL_ID")

        budget = safety.remote_llm_calls_budget
        if budget is not None and not budget.try_consume(1):
            raise LLMCallError(
                "E_BUDGET_EXHAUSTED",
                f"remote_llm_calls budget exhausted (remaining={budget.remaining}, consumed={budget.consumed})",
            )

        payload = {
            "model": effective_model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
        }
        req = urllib.request.Request(
            url=f"{self.base_url}/chat/completions",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_sec) as resp:
                raw = resp.read()
        except urllib.error.HTTPError as e:
            body_preview = ""
            try:
                body_preview = e.read().decode("utf-8", errors="replace")
            except Exception:
                body_preview = ""
            raise LLMCallError(
                "E_PROVIDER_BAD_RESPONSE",
                _format_http_transport_error(status=e.code, body_preview=body_preview),
            ) from e
        except urllib.error.URLError as e:
            raise LLMCallError("E_PROVIDER_BAD_RESPONSE", f"provider transport error: {e}") from e
        except Exception as e:
            raise LLMCallError("E_PROVIDER_BAD_RESPONSE", f"provider error: {e}") from e

        try:
            resp_obj = json.loads(raw.decode("utf-8"))
        except Exception as e:
            raise LLMCallError("E_PROVIDER_BAD_RESPONSE", f"provider returned non-JSON response: {e}") from e

        out = _extract_json_object(resp_obj)
        try:
            validate_instance(out, json_schema)
        except ValidationError as e:
            raise LLMCallError("E_PROVIDER_BAD_RESPONSE", f"output failed schema validation: {e}") from e
        return out


def _extract_json_object(resp: Mapping[str, Any]) -> dict[str, Any]:
    choices = resp.get("choices")
    if isinstance(choices, list):
        for item in choices:
            if not isinstance(item, dict):
                continue
            message = item.get("message")
            if not isinstance(message, dict):
                continue
            parsed = _try_parse_json_object_text(_coerce_message_content_text(message.get("content")))
            if parsed is not None:
                return parsed
    # Allow a couple of loose shapes; this is a skeleton and the endpoint's exact response may differ.
    if "output" in resp and isinstance(resp["output"], dict):
        return dict(resp["output"])
    if "result" in resp and isinstance(resp["result"], dict):
        return dict(resp["result"])
    # OpenAI Responses API: output is a list of items, e.g.
    # [{"type": "message", "content": [{"type": "output_text", "text": "{...}"}]}]
    if "output" in resp and isinstance(resp["output"], list):
        for item in resp["output"]:
            if not isinstance(item, dict):
                continue
            # Direct text field on output item
            text_val = item.get("text")
            if isinstance(text_val, str) and text_val.strip():
                try:
                    parsed = json.loads(text_val)
                    if isinstance(parsed, dict):
                        return parsed
                except Exception:
                    pass
            # Nested content array (Responses API message format)
            content = item.get("content")
            if isinstance(content, list):
                for c in content:
                    if not isinstance(c, dict):
                        continue
                    t = c.get("text")
                    if isinstance(t, str) and t.strip():
                        try:
                            parsed = json.loads(t)
                            if isinstance(parsed, dict):
                                return parsed
                        except Exception:
                            continue
    for k in ("output", "text", "content", "message"):
        v = resp.get(k)
        if isinstance(v, str) and v.strip():
            try:
                parsed = json.loads(v)
            except Exception:
                continue
            if isinstance(parsed, dict):
                return parsed
    preview = json.dumps(dict(resp), ensure_ascii=False)[:240]
    raise LLMCallError(
        "E_PROVIDER_BAD_RESPONSE",
        f"could not extract JSON object from provider response; preview={preview}",
    )


def _coerce_message_content_text(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str) and item.strip():
                parts.append(item.strip())
                continue
            if not isinstance(item, dict):
                continue
            text = item.get("text")
            if isinstance(text, str) and text.strip():
                parts.append(text.strip())
                continue
            nested = item.get("content")
            if isinstance(nested, str) and nested.strip():
                parts.append(nested.strip())
        return "\n".join(parts).strip()
    return ""


def _try_parse_json_object_text(text: str) -> Optional[dict[str, Any]]:
    raw = str(text or "").strip()
    if not raw:
        return None
    candidates = [raw]
    if raw.startswith("```"):
        stripped = raw.strip("`").strip()
        if stripped.lower().startswith("json"):
            stripped = stripped[4:].strip()
        candidates.append(stripped)
    start = raw.find("{")
    end = raw.rfind("}")
    if start >= 0 and end > start:
        candidates.append(raw[start : end + 1].strip())
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except Exception:
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


def _format_provider_transport_error(err: OpenAICodexOAuthTransportError) -> str:
    parts = [f"provider transport error: {err}"]
    if err.status is not None:
        parts.append(f"status={err.status}")
    preview = str(err.body_preview or "").strip()
    if preview:
        preview = " ".join(preview.split())
        parts.append(f"body_preview={preview[:240]}")
    return "; ".join(parts)


def _format_http_transport_error(*, status: Optional[int], body_preview: str) -> str:
    parts = ["provider transport error"]
    if status is not None:
        parts.append(f"status={status}")
    preview = str(body_preview or "").strip()
    if preview:
        preview = " ".join(preview.split())
        parts.append(f"body_preview={preview[:240]}")
    return "; ".join(parts)


def _openai_input_media_items(items: Optional[list[dict[str, Any]]]) -> list[dict[str, Any]]:
    content: list[dict[str, Any]] = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        local_path = str(item.get("local_path") or "").strip()
        if not local_path:
            continue
        media_kind = str(item.get("media_kind") or "").strip().lower()
        file_path = Path(local_path)
        if not file_path.exists():
            raise LLMCallError("E_ATTACHMENT_ARTIFACT_MISSING", f"attachment file is missing: {local_path}")
        mime_type = str(item.get("mime_type") or "application/octet-stream").split(";")[0].strip() or "application/octet-stream"
        raw = file_path.read_bytes()
        encoded = base64.b64encode(raw).decode("ascii")
        if media_kind == "image":
            content.append({"type": "input_image", "image_url": f"data:{mime_type};base64,{encoded}"})
            continue
        if media_kind == "document":
            filename = str(item.get("filename") or file_path.name).strip() or file_path.name
            content.append(
                {
                    "type": "input_file",
                    "filename": filename,
                    "file_data": f"data:{mime_type};base64,{encoded}",
                }
            )
            continue
        raise LLMCallError(
            "E_MULTIMODAL_UNSUPPORTED",
            f"unsupported attachment media kind for codex_oauth backend: {media_kind or 'unknown'}",
        )
    return content


def _enrich_mock_output(out: dict[str, Any], json_schema: Mapping[str, Any], prompt: str) -> None:
    """Make LocalMock output less trivial while remaining deterministic and schema-safe.

    Only fills string fields that do not have enum/const constraints.
    """

    props = json_schema.get("properties")
    if not isinstance(props, dict):
        return

    inp = _try_extract_input_json(prompt)
    request = inp.get("request") if isinstance(inp, dict) else None
    if not isinstance(request, str) or not request.strip():
        request = None

    for name, ps in props.items():
        if not isinstance(name, str) or not isinstance(ps, dict):
            continue
        if ps.get("type") != "string":
            continue
        if "enum" in ps or "const" in ps:
            continue
        if name not in out:
            continue
        if not isinstance(out.get(name), str):
            continue

        if name == "reply":
            out[name] = f"[mock] {request.strip()}" if request else "[mock] ok"
        else:
            out[name] = out[name] or "[mock]"


def _try_extract_input_json(prompt: str) -> dict[str, Any]:
    m1 = "Input JSON:"
    i1 = prompt.find(m1)
    if i1 < 0:
        return {}
    markers = (
        "Skill Output Validation Contract:",
        "Skill Output Contract:",
        "Output JSON Schema:",
    )
    i2 = -1
    for marker in markers:
        idx = prompt.find(marker, i1)
        if idx >= 0 and (i2 < 0 or idx < i2):
            i2 = idx
    if i2 < 0:
        i2 = len(prompt)
    chunk = prompt[i1 + len(m1) : i2].strip()
    try:
        parsed = json.loads(chunk)
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}
