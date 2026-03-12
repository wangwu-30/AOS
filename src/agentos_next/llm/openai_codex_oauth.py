from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, MutableMapping, Optional, Protocol


class RemoteCallsDisabledError(RuntimeError):
    pass


class OpenAICodexOAuthTokenError(RuntimeError):
    pass


class OpenAICodexOAuthTransportError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        status: Optional[int] = None,
        body_preview: str = "",
        retryable: bool = False,
        before_first_delta: bool = True,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.body_preview = body_preview
        self.retryable = bool(retryable)
        self.before_first_delta = bool(before_first_delta)


@dataclass(frozen=True)
class HttpResponse:
    status: int
    headers: Mapping[str, str]
    body: bytes


@dataclass(frozen=True)
class OpenAICodexOAuthLoginSession:
    state: str
    code_verifier: str
    authorize_url: str


class HttpTransport(Protocol):
    def request(
        self,
        *,
        method: str,
        url: str,
        headers: Mapping[str, str],
        body: bytes | None,
        timeout_s: float,
    ) -> HttpResponse:  # pragma: no cover (protocol)
        raise NotImplementedError


class UrllibHttpTransport:
    def request(
        self,
        *,
        method: str,
        url: str,
        headers: Mapping[str, str],
        body: bytes | None,
        timeout_s: float,
    ) -> HttpResponse:
        req = urllib.request.Request(url=url, method=method, headers=dict(headers), data=body)
        try:
            with urllib.request.urlopen(req, timeout=timeout_s) as resp:
                raw = resp.read()
                # urllib normalizes headers in a case-insensitive mapping; convert to plain str dict.
                resp_headers = {k: v for k, v in resp.headers.items()}
                return HttpResponse(status=int(resp.status), headers=resp_headers, body=raw)
        except urllib.error.HTTPError as e:
            raw = e.read() if hasattr(e, "read") else b""
            resp_headers = {k: v for k, v in getattr(e, "headers", {}).items()}  # type: ignore[union-attr]
            return HttpResponse(status=int(e.code), headers=resp_headers, body=raw)
        except urllib.error.URLError as e:
            raise OpenAICodexOAuthTransportError(f"transport error: {e}") from e


def _parse_expires_at(value: Any) -> Optional[float]:
    """Return expiry as epoch seconds if parseable."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        v = float(value)
        # Heuristic: treat > 1e12 as milliseconds.
        if v > 1e12:
            v = v / 1000.0
        return v
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return None
        # numeric strings
        try:
            v = float(s)
        except ValueError:
            v = None
        if v is not None:
            if v > 1e12:
                v = v / 1000.0
            return v
        # ISO-8601-ish, e.g. 2026-02-13T12:34:56Z
        try:
            if s.endswith("Z"):
                s = s[:-1] + "+00:00"
            # Python 3.10 supports fromisoformat with offset, but not 'Z'.
            from datetime import datetime

            dt = datetime.fromisoformat(s)
            if dt.tzinfo is None:
                # Treat naive as UTC to avoid surprising local-time behavior.
                from datetime import timezone

                dt = dt.replace(tzinfo=timezone.utc)
            return dt.timestamp()
        except Exception:
            return None
    return None


def _as_token_container(raw: Mapping[str, Any]) -> Mapping[str, Any]:
    tokens = raw.get("tokens")
    if isinstance(tokens, dict):
        return tokens
    return raw


def _atomic_write_json(path: Path, data: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=True, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


@dataclass
class OAuthToken:
    access_token: str
    refresh_token: Optional[str]
    expires_at: Optional[float]
    raw: MutableMapping[str, Any]


class OpenAICodexOAuthProvider:
    """OpenAI Codex provider using ChatGPT OAuth tokens.

    - Token file: `OPENAI_OAUTH_TOKEN_PATH` (default `openai_oauth_token.json`)
    - Refresh endpoint: `https://auth.openai.com/oauth/token`
    - Codex endpoint: `OPENAI_CODEX_ENDPOINT` (default `https://chatgpt.com/backend-api/codex/responses`)

    All remote calls are gated by `remote_calls_armed=True` AND `allow_network_egress=True`.
    """

    def __init__(
        self,
        *,
        remote_calls_armed: bool = False,
        allow_network_egress: bool = False,
        token_path: str | Path | None = None,
        codex_endpoint: str | None = None,
        refresh_endpoint: str = "https://auth.openai.com/oauth/token",
        transport: HttpTransport | None = None,
        now_fn: Callable[[], float] | None = None,
        refresh_skew_s: float = 60.0,
        timeout_s: float = 30.0,
    ) -> None:
        self.remote_calls_armed = remote_calls_armed
        self.allow_network_egress = allow_network_egress
        self.token_path = Path(
            token_path
            or os.environ.get("OPENAI_OAUTH_TOKEN_PATH", "openai_oauth_token.json")
        )
        self.codex_endpoint = codex_endpoint or os.environ.get(
            "OPENAI_CODEX_ENDPOINT", "https://chatgpt.com/backend-api/codex/responses"
        )
        self.refresh_endpoint = refresh_endpoint
        self.transport = transport or UrllibHttpTransport()
        self.now_fn = now_fn or time.time
        self.refresh_skew_s = float(refresh_skew_s)
        self.timeout_s = float(timeout_s)
        self.transient_retry_attempts = 1

    def create_login_session(
        self,
        *,
        client_id: str = "app_EMoamEEZ73f0CkXaXp7hrann",
        redirect_uri: str = "http://localhost:1455/auth/callback",
    ) -> OpenAICodexOAuthLoginSession:
        state = secrets.token_urlsafe(16)
        verifier = secrets.token_urlsafe(32)
        # S256 challenge: hash, then base64url without padding
        challenge_digest = hashlib.sha256(verifier.encode("ascii")).digest()
        challenge = base64.urlsafe_b64encode(challenge_digest).decode("ascii").rstrip("=")

        params = {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "scope": "openid profile email offline_access",
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "id_token_add_organizations": "true",
            "codex_cli_simplified_flow": "true",
            "originator": "pi",
        }
        url = f"https://auth.openai.com/oauth/authorize?{urllib.parse.urlencode(params)}"
        return OpenAICodexOAuthLoginSession(state=state, code_verifier=verifier, authorize_url=url)

    def exchange_code_for_token(
        self,
        *,
        code: str,
        code_verifier: str,
        client_id: str,
        redirect_uri: str,
    ) -> OAuthToken:
        # Note: exchange_code_for_token requires remote access to talk to token endpoint.
        self._require_remote()
        form = {
            "grant_type": "authorization_code",
            "client_id": client_id,
            "code": code,
            "code_verifier": code_verifier,
            "redirect_uri": redirect_uri,
        }
        body = urllib.parse.urlencode(form).encode("utf-8")
        resp = self.transport.request(
            method="POST",
            url=self.refresh_endpoint,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
            },
            body=body,
            timeout_s=self.timeout_s,
        )
        if resp.status < 200 or resp.status >= 300:
            preview = resp.body[:512].decode("utf-8", errors="replace")
            raise OpenAICodexOAuthTransportError(
                "token exchange failed",
                status=resp.status,
                body_preview=preview,
            )
        try:
            data = json.loads(resp.body.decode("utf-8"))
        except Exception as e:
            preview = resp.body[:512].decode("utf-8", errors="replace")
            raise OpenAICodexOAuthTransportError(
                "token exchange returned non-JSON",
                status=resp.status,
                body_preview=preview,
            ) from e

        if not isinstance(data, dict):
            raise OpenAICodexOAuthTransportError("token exchange returned non-object JSON", status=resp.status)

        access_token = data.get("access_token")
        if not isinstance(access_token, str) or not access_token:
            raise OpenAICodexOAuthTokenError("exchange response missing `access_token`")

        refresh_token = data.get("refresh_token")

        expires_at = _parse_expires_at(data.get("expires_at"))
        if expires_at is None:
            expires_in = data.get("expires_in")
            if isinstance(expires_in, (int, float)):
                expires_at = self.now_fn() + float(expires_in)

        # Build raw dict to save
        raw = dict(data)
        raw["client_id"] = client_id
        raw["redirect_uri"] = redirect_uri
        if expires_at is not None:
            raw["expires_at"] = int(expires_at)

        _atomic_write_json(self.token_path, raw)

        return OAuthToken(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_at=expires_at,
            raw=raw,
        )

    def _require_remote(self) -> None:
        if not self.remote_calls_armed:
            raise RemoteCallsDisabledError("remote calls disabled (remote_calls_armed=False)")
        if not self.allow_network_egress:
            raise RemoteCallsDisabledError("remote calls disabled (allow_network_egress=False)")

    def _load_token_file(self) -> OAuthToken:
        try:
            raw = json.loads(self.token_path.read_text(encoding="utf-8"))
        except FileNotFoundError as e:
            raise OpenAICodexOAuthTokenError(f"token file not found: {self.token_path}") from e
        except json.JSONDecodeError as e:
            raise OpenAICodexOAuthTokenError(f"invalid token JSON: {self.token_path}") from e

        if not isinstance(raw, dict):
            raise OpenAICodexOAuthTokenError("token JSON must be an object")

        token_container = _as_token_container(raw)

        refresh_token = token_container.get("refresh_token")
        if refresh_token is not None and not isinstance(refresh_token, str):
            raise OpenAICodexOAuthTokenError("`refresh_token` must be a string when present")

        access_token = token_container.get("access_token")
        if access_token is None and refresh_token:
            access_token = ""
        if not isinstance(access_token, str):
            raise OpenAICodexOAuthTokenError("`access_token` must be a string when present")

        expires_at = _parse_expires_at(token_container.get("expires_at"))
        if expires_at is None:
            expires_at = _parse_expires_at(raw.get("expires_at"))

        return OAuthToken(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_at=expires_at,
            raw=raw,
        )

    def _needs_refresh(self, tok: OAuthToken) -> bool:
        if not tok.access_token:
            return True
        if tok.expires_at is None:
            # Some token stores provide a valid access token without explicit expiry metadata.
            # In that case, use the token as-is and let the request fail if it is actually stale.
            return False
        return self.now_fn() >= (tok.expires_at - self.refresh_skew_s)

    def _refresh(self, tok: OAuthToken) -> OAuthToken:
        self._require_remote()
        if not tok.refresh_token:
            raise OpenAICodexOAuthTokenError("access token expired/unknown but no `refresh_token` available")

        # OAuth 2.0 token refresh typically uses x-www-form-urlencoded.
        form: dict[str, str] = {
            "grant_type": "refresh_token",
            "refresh_token": tok.refresh_token,
        }
        # If token JSON includes client fields, pass them through.
        for k in ("client_id", "client_secret", "scope", "redirect_uri", "audience"):
            v = tok.raw.get(k)
            if isinstance(v, str) and v:
                form[k] = v

        body = urllib.parse.urlencode(form).encode("utf-8")
        resp = self.transport.request(
            method="POST",
            url=self.refresh_endpoint,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
            },
            body=body,
            timeout_s=self.timeout_s,
        )
        if resp.status < 200 or resp.status >= 300:
            preview = resp.body[:512].decode("utf-8", errors="replace")
            raise OpenAICodexOAuthTransportError(
                "token refresh failed",
                status=resp.status,
                body_preview=preview,
            )
        try:
            data = json.loads(resp.body.decode("utf-8"))
        except Exception as e:
            preview = resp.body[:512].decode("utf-8", errors="replace")
            raise OpenAICodexOAuthTransportError(
                "token refresh returned non-JSON",
                status=resp.status,
                body_preview=preview,
            ) from e

        if not isinstance(data, dict):
            raise OpenAICodexOAuthTransportError("token refresh returned non-object JSON", status=resp.status)

        access_token = data.get("access_token")
        if not isinstance(access_token, str) or not access_token:
            raise OpenAICodexOAuthTokenError("refresh response missing `access_token`")

        refresh_token = data.get("refresh_token")
        if refresh_token is None:
            refresh_token = tok.refresh_token
        if refresh_token is not None and not isinstance(refresh_token, str):
            raise OpenAICodexOAuthTokenError("refresh response `refresh_token` must be a string when present")

        expires_at = _parse_expires_at(data.get("expires_at"))
        if expires_at is None:
            expires_in = data.get("expires_in")
            if isinstance(expires_in, (int, float)):
                expires_at = self.now_fn() + float(expires_in)

        # Persist updated token, preserving unknown keys from existing file.
        new_raw = dict(tok.raw)
        new_raw.update(data)
        new_raw["access_token"] = access_token
        new_raw["refresh_token"] = refresh_token
        if expires_at is not None:
            new_raw["expires_at"] = int(expires_at)
        existing_tokens = tok.raw.get("tokens")
        if isinstance(existing_tokens, dict):
            new_tokens = dict(existing_tokens)
            new_tokens.update(data)
            new_tokens["access_token"] = access_token
            new_tokens["refresh_token"] = refresh_token
            if expires_at is not None:
                new_tokens["expires_at"] = int(expires_at)
            new_raw["tokens"] = new_tokens
        _atomic_write_json(self.token_path, new_raw)

        return OAuthToken(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_at=expires_at,
            raw=new_raw,
        )

    def _get_access_token(self) -> str:
        tok = self._load_token_file()
        if self._needs_refresh(tok):
            tok = self._refresh(tok)
        return tok.access_token

    def codex_responses(
        self,
        payload: Mapping[str, Any],
        *,
        stream_callback: Optional[Callable[[dict[str, Any]], None]] = None,
    ) -> dict[str, Any]:
        """Call the Codex responses endpoint with the given JSON payload."""
        self._require_remote()
        access_token = self._get_access_token()
        account_id = None
        try:
            raw = json.loads(self.token_path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                account_id = raw.get("account_id") or raw.get("accountId")
                if account_id is None:
                    tokens = raw.get("tokens")
                    if isinstance(tokens, dict):
                        account_id = tokens.get("account_id") or tokens.get("accountId")
        except Exception:
            account_id = None

        if account_id is None:
            try:
                parts = access_token.split(".")
                if len(parts) >= 2:
                    pld = parts[1]
                    pld += "=" * (4 - len(pld) % 4)
                    decoded = json.loads(base64.urlsafe_b64decode(pld).decode("utf-8"))
                    auth_claim = decoded.get("https://api.openai.com/auth", {})
                    if isinstance(auth_claim, dict):
                        account_id = auth_claim.get("chatgpt_account_id")
            except Exception:
                pass
        body = json.dumps(payload, ensure_ascii=True).encode("utf-8")
        headers: dict[str, str] = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
            "OpenAI-Beta": "responses=experimental",
            "Originator": "pi",
            "Connection": "close",
        }
        if isinstance(account_id, str) and account_id.strip():
            headers["ChatGPT-Account-Id"] = account_id.strip()

        attempts = max(1, int(self.transient_retry_attempts) + 1)
        last_err: OpenAICodexOAuthTransportError | None = None
        for attempt in range(1, attempts + 1):
            try:
                if stream_callback is not None and isinstance(self.transport, UrllibHttpTransport):
                    return self._codex_responses_streaming(
                        payload=payload,
                        body=body,
                        headers=headers,
                        stream_callback=stream_callback,
                    )

                resp = self.transport.request(
                    method="POST",
                    url=self.codex_endpoint,
                    headers=headers,
                    body=body,
                    timeout_s=self.timeout_s,
                )

                full_body = resp.body.decode("utf-8", errors="replace")
                if resp.status < 200 or resp.status >= 300:
                    raise OpenAICodexOAuthTransportError(
                        "codex request failed",
                        status=resp.status,
                        body_preview=full_body[:512],
                    )
                try:
                    parsed = json.loads(full_body)
                    if isinstance(parsed, dict):
                        return parsed
                except Exception:
                    pass
                return _parse_sse_payload(full_body, stream_callback=stream_callback)
            except OpenAICodexOAuthTransportError as err:
                last_err = err
                if attempt >= attempts or not _should_retry_codex_transport(err):
                    raise
                time.sleep(0.15 * attempt)
        assert last_err is not None
        raise last_err

    def _codex_responses_streaming(
        self,
        *,
        payload: Mapping[str, Any],
        body: bytes,
        headers: Mapping[str, str],
        stream_callback: Callable[[dict[str, Any]], None],
    ) -> dict[str, Any]:
        req = urllib.request.Request(
            url=self.codex_endpoint,
            method="POST",
            headers=dict(headers),
            data=body,
        )
        emitted_delta = False
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
                status = int(resp.status)
                if status < 200 or status >= 300:
                    raw = resp.read().decode("utf-8", errors="replace")
                    raise OpenAICodexOAuthTransportError(
                        "codex request failed",
                        status=status,
                        body_preview=raw[:512],
                    )
                stream_callback({"type": "start", "model": str(payload.get("model") or "")})
                final_response: Optional[dict[str, Any]] = None
                collected_text = ""
                for raw_line in resp:
                    line = raw_line.decode("utf-8", errors="replace").strip()
                    if not line.startswith("data:"):
                        continue
                    payload_str = line[len("data:"):].strip()
                    if payload_str == "[DONE]":
                        continue
                    prev_text = collected_text
                    final_response, collected_text = _consume_sse_chunk(
                        payload_str=payload_str,
                        final_response=final_response,
                        collected_text=collected_text,
                        stream_callback=stream_callback,
                    )
                    if collected_text != prev_text:
                        emitted_delta = True
                stream_callback({"type": "completed"})
                if final_response is not None:
                    return final_response
                return {
                    "output": [
                        {
                            "type": "message",
                            "content": [{"type": "output_text", "text": collected_text}],
                        }
                    ]
                }
        except urllib.error.HTTPError as exc:
            preview = ""
            try:
                preview = exc.read().decode("utf-8", errors="replace")
            except Exception:
                preview = ""
            raise OpenAICodexOAuthTransportError(
                "codex request failed",
                status=int(exc.code),
                body_preview=preview[:512],
            ) from exc
        except urllib.error.URLError as exc:
            raise OpenAICodexOAuthTransportError(
                f"transport error: {exc}",
                retryable=_is_transient_transport_message(str(exc)),
                before_first_delta=not emitted_delta,
            ) from exc


def _parse_sse_payload(
    full_body: str,
    *,
    stream_callback: Optional[Callable[[dict[str, Any]], None]] = None,
) -> dict[str, Any]:
    final_response: Optional[dict[str, Any]] = None
    collected_text = ""
    if stream_callback is not None:
        stream_callback({"type": "start"})
    for line in full_body.splitlines():
        raw = line.strip()
        if not raw.startswith("data:"):
            continue
        payload_str = raw[len("data:"):].strip()
        if payload_str == "[DONE]":
            continue
        final_response, collected_text = _consume_sse_chunk(
            payload_str=payload_str,
            final_response=final_response,
            collected_text=collected_text,
            stream_callback=stream_callback,
        )
    if stream_callback is not None:
        stream_callback({"type": "completed"})
    if final_response is not None:
        return final_response
    return {
        "output": [
            {
                "type": "message",
                "content": [{"type": "output_text", "text": collected_text}],
            }
        ]
    }


def _consume_sse_chunk(
    *,
    payload_str: str,
    final_response: Optional[dict[str, Any]],
    collected_text: str,
    stream_callback: Optional[Callable[[dict[str, Any]], None]],
) -> tuple[Optional[dict[str, Any]], str]:
    try:
        chunk = json.loads(payload_str)
    except Exception:
        return final_response, collected_text
    if not isinstance(chunk, dict):
        return final_response, collected_text
    if chunk.get("type") == "response.completed" and "response" in chunk and isinstance(chunk.get("response"), dict):
        return dict(chunk["response"]), collected_text
    delta_text = _extract_delta_text(chunk)
    if delta_text:
        collected_text += delta_text
        if stream_callback is not None:
            stream_callback({"type": "delta", "delta": delta_text})
    return final_response, collected_text


def _extract_delta_text(chunk: dict[str, Any]) -> str:
    chunk_type = chunk.get("type")
    if chunk_type in ("response.output_text.delta", "output_text") and "delta" in chunk:
        return str(chunk["delta"])
    if "choices" in chunk and isinstance(chunk["choices"], list) and len(chunk["choices"]) > 0:
        delta = chunk["choices"][0].get("delta", {})
        if isinstance(delta, dict) and "content" in delta:
            return str(delta["content"])
    return ""


def _is_transient_transport_message(message: str) -> bool:
    text = str(message or "").lower()
    needles = (
        "unexpected_eof_while_reading",
        "eof occurred in violation of protocol",
        "remote end closed connection without response",
        "connection reset by peer",
        "temporarily unavailable",
        "tlsv1 alert internal error",
    )
    return any(needle in text for needle in needles)


def _should_retry_codex_transport(err: OpenAICodexOAuthTransportError) -> bool:
    if not bool(getattr(err, "retryable", False)):
        return False
    return bool(getattr(err, "before_first_delta", True))
