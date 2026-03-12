from __future__ import annotations

import json
import logging
import os
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from agentos_next.kernel.evidence_store import FileEvidenceStore
from agentos_next.kernel.executor import ExecuteRequest, ExecuteResult, ExecuteTiming
from agentos_next.kernel.trace_logger import FileTraceLogger
from agentos_next.kernel.types import EvidenceRef, TraceEvent
from agentos_next.runtime.playwright_web_runtime import (
    PlaywrightRuntimeError,
    SearchRuntimeError,
    duckduckgo_html_search,
    duckduckgo_http_search,
    playwright_browse,
    playwright_search,
    probe_playwright_runtime,
)

logger = logging.getLogger(__name__)
_BRAVE_SEARCH_ENDPOINT = "https://api.search.brave.com/res/v1/web/search"
_SEARCH_HEALTH_QUERY = "OpenAI"
_SEARCH_HEALTH_PROBE_TTL_SECONDS = 600.0
_SEARCH_PROVIDER_PROBE_CACHE: dict[tuple[str, ...], dict[str, Any]] = {}


@dataclass(frozen=True)
class BuiltinDispatchResult:
    handled: bool
    result: Optional[ExecuteResult] = None


class BuiltinWebRuntimeError(RuntimeError):
    def __init__(self, error_code: str, message: str, *, payload: Optional[dict[str, Any]] = None) -> None:
        super().__init__(message)
        self.error_code = str(error_code or "E_EXECUTION_FAILED").strip() or "E_EXECUTION_FAILED"
        self.payload = dict(payload or {})


def _search_provider_cache_key(provider: str) -> tuple[str, ...]:
    name = str(provider or "").strip()
    if name == "brave":
        return (name, _brave_api_key())
    return (name,)


def _set_search_provider_probe(provider: str, *, available: bool, detail: str) -> dict[str, Any]:
    entry = {
        "available": bool(available),
        "detail": str(detail or "").strip(),
        "expires_at": time.monotonic() + _SEARCH_HEALTH_PROBE_TTL_SECONDS,
    }
    _SEARCH_PROVIDER_PROBE_CACHE[_search_provider_cache_key(provider)] = entry
    return entry


def _get_search_provider_probe(provider: str) -> dict[str, Any] | None:
    entry = _SEARCH_PROVIDER_PROBE_CACHE.get(_search_provider_cache_key(provider))
    if not isinstance(entry, dict):
        return None
    if float(entry.get("expires_at") or 0.0) <= time.monotonic():
        _SEARCH_PROVIDER_PROBE_CACHE.pop(_search_provider_cache_key(provider), None)
        return None
    return dict(entry)


def _invalidate_search_provider_probe(provider: str) -> None:
    prefix = str(provider or "").strip()
    stale = [key for key in _SEARCH_PROVIDER_PROBE_CACHE if key and key[0] == prefix]
    for key in stale:
        _SEARCH_PROVIDER_PROBE_CACHE.pop(key, None)


def _reset_search_provider_probe_cache() -> None:
    _SEARCH_PROVIDER_PROBE_CACHE.clear()


def _probe_search_provider(provider: str) -> dict[str, Any]:
    cached = _get_search_provider_probe(provider)
    if cached is not None:
        return cached
    try:
        if provider == "brave":
            _brave_search(query=_SEARCH_HEALTH_QUERY, limit=1, timeout_seconds=5)
        elif provider == "duckduckgo_html":
            duckduckgo_http_search(query=_SEARCH_HEALTH_QUERY, limit=1)
        elif provider == "playwright_search":
            playwright_search(query=_SEARCH_HEALTH_QUERY, limit=1, allow_query_resubmit=True, include_metadata=True)
        else:
            raise RuntimeError(f"unknown search provider: {provider}")
    except Exception as exc:
        detail = str(exc).strip() or f"{provider} health probe failed"
        return _set_search_provider_probe(provider, available=False, detail=detail)
    return _set_search_provider_probe(provider, available=True, detail="available")


def probe_web_runtime_capability(*, allow_network_egress: bool) -> dict[str, Any]:
    available_backends: list[str] = []
    unavailable_backends: dict[str, str] = {}
    browse_unavailable_reason: str | None = None
    if not allow_network_egress:
        unavailable_backends["brave"] = "network egress is disabled"
        unavailable_backends["duckduckgo_html"] = "network egress is disabled"
        unavailable_backends["playwright_search"] = "network egress is disabled"
        unavailable_backends["playwright"] = "network egress is disabled"
        return {
            "schema_version": "1.0.0",
            "type": "web_runtime_capability_probe_v1",
            "web_search_enabled": False,
            "web_browse_enabled": False,
            "browse_unavailable_reason": "network egress is disabled",
            "strict_health_gate": True,
            "probe_ttl_seconds": int(_SEARCH_HEALTH_PROBE_TTL_SECONDS),
            "backends": {
                "available": available_backends,
                "unavailable": unavailable_backends,
                "default": None,
            },
        }

    brave_probe = _probe_search_provider("brave")
    if bool(brave_probe.get("available")):
        available_backends.append("brave")
    else:
        unavailable_backends["brave"] = str(brave_probe.get("detail") or "brave search probe failed")

    duckduckgo_probe = _probe_search_provider("duckduckgo_html")
    if bool(duckduckgo_probe.get("available")):
        available_backends.append("duckduckgo_html")
    else:
        unavailable_backends["duckduckgo_html"] = str(
            duckduckgo_probe.get("detail") or "duckduckgo_html search probe failed"
        )

    playwright_probe = probe_playwright_runtime()
    if playwright_probe.available:
        browse_available = True
        playwright_search_probe = _probe_search_provider("playwright_search")
        if bool(playwright_search_probe.get("available")):
            available_backends.append("playwright_search")
        else:
            unavailable_backends["playwright_search"] = str(
                playwright_search_probe.get("detail") or "playwright_search probe failed"
            )
    else:
        browse_unavailable_reason = str(playwright_probe.reason or "playwright runtime is unavailable")
        unavailable_backends["playwright"] = browse_unavailable_reason
        unavailable_backends["playwright_search"] = browse_unavailable_reason
        browse_available = False

    return {
        "schema_version": "1.0.0",
        "type": "web_runtime_capability_probe_v1",
        "web_search_enabled": bool(available_backends),
        "web_browse_enabled": browse_available,
        "browse_unavailable_reason": browse_unavailable_reason,
        "strict_health_gate": True,
        "probe_ttl_seconds": int(_SEARCH_HEALTH_PROBE_TTL_SECONDS),
        "backends": {
            "available": available_backends,
            "unavailable": unavailable_backends,
            "default": (available_backends[0] if available_backends else None),
        },
    }


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def maybe_execute_builtin_web(*, req: ExecuteRequest, data_dir: str) -> BuiltinDispatchResult:
    if not req.operator_ref.startswith("builtin://web."):
        return BuiltinDispatchResult(handled=False)

    name = req.operator_ref[len("builtin://") :].strip("/")
    evidence = FileEvidenceStore(data_dir=data_dir)
    trace = FileTraceLogger(data_dir=data_dir)
    started_at = _utc_iso()
    evidence_refs: list[EvidenceRef] = []

    def _emit(event_type: str, *, ers: tuple[EvidenceRef, ...] = (), data: Optional[dict[str, Any]] = None) -> None:
        trace.emit(
            TraceEvent(
                schema_version="1.0.0",
                ctx=req.trace,
                event_type=event_type,
                ts=_utc_iso(),
                evidence_refs=ers,
                data=data,
            )
        )

    _emit("TOOL_CALL_STARTED", data={"builtin": name})

    try:
        if name == "web.search":
            _web_search(req=req, evidence=evidence, evidence_refs=evidence_refs)
        elif name == "web.browse":
            _web_browse(req=req, evidence=evidence, evidence_refs=evidence_refs)
        else:
            raise ValueError(f"unknown builtin: {name}")
    except BuiltinWebRuntimeError as exc:
        err_ref = evidence.add_json(
            _build_structured_error_payload(
                operator_ref=req.operator_ref,
                error_code=exc.error_code,
                message=str(exc),
                payload=exc.payload,
            ),
            kind="error",
        )
        evidence_refs.append(err_ref)
        _emit("ERROR", ers=(err_ref,), data={"builtin": name, "error_code": exc.error_code})
        ended_at = _utc_iso()
        return BuiltinDispatchResult(
            handled=True,
            result=ExecuteResult(
                status="failed",
                evidence_refs=tuple(evidence_refs),
                artifact_refs=(),
                error_code=exc.error_code,
                timing=ExecuteTiming(started_at=started_at, ended_at=ended_at),
                target="local",
            ),
        )
    except PlaywrightRuntimeError as exc:
        err_ref = evidence.add_json(
            _build_structured_error_payload(
                operator_ref=req.operator_ref,
                error_code=exc.error_code,
                message=str(exc),
            ),
            kind="error",
        )
        evidence_refs.append(err_ref)
        _emit("ERROR", ers=(err_ref,), data={"builtin": name, "error_code": exc.error_code})
        ended_at = _utc_iso()
        return BuiltinDispatchResult(
            handled=True,
            result=ExecuteResult(
                status="failed",
                evidence_refs=tuple(evidence_refs),
                artifact_refs=(),
                error_code=exc.error_code,
                timing=ExecuteTiming(started_at=started_at, ended_at=ended_at),
                target="local",
            ),
        )
    except Exception as exc:
        err_ref = evidence.add_json(
            {"schema_version": "1.0.0", "ok": False, "error_code": "E_EXECUTION_FAILED", "message": str(exc)},
            kind="error",
        )
        evidence_refs.append(err_ref)
        _emit("ERROR", ers=(err_ref,), data={"builtin": name, "error_code": "E_EXECUTION_FAILED"})
        ended_at = _utc_iso()
        return BuiltinDispatchResult(
            handled=True,
            result=ExecuteResult(
                status="failed",
                evidence_refs=tuple(evidence_refs),
                artifact_refs=(),
                error_code="E_EXECUTION_FAILED",
                timing=ExecuteTiming(started_at=started_at, ended_at=ended_at),
                target="local",
            ),
        )

    _emit("TOOL_CALL_FINISHED", data={"builtin": name, "ok": True})
    ended_at = _utc_iso()
    return BuiltinDispatchResult(
        handled=True,
        result=ExecuteResult(
            status="accepted",
            evidence_refs=tuple(evidence_refs),
            artifact_refs=(),
            error_code=None,
            timing=ExecuteTiming(started_at=started_at, ended_at=ended_at),
            target="local",
        ),
    )


def _web_search(*, req: ExecuteRequest, evidence: FileEvidenceStore, evidence_refs: list[EvidenceRef]) -> None:
    inp = dict(req.arguments or {})
    query = str(inp.get("query") or "").strip()
    if not query:
        raise ValueError("query is required")
    if "provider" in inp:
        raise ValueError("provider is no longer supported; runtime selects the backend automatically")

    limit = _coerce_positive_int(inp.get("limit"), default=5, maximum=10)
    attempts: list[dict[str, Any]] = []
    notices: list[str] = []
    results: list[dict[str, Any]] = []
    selected_provider = ""
    providers = ["brave", "duckduckgo_html", "playwright_search"]
    for provider in providers:
        try:
            payload = _run_search_provider(provider=provider, query=query, limit=limit)
            selected_provider = str(payload.get("provider_used") or provider).strip() or provider
            provider_attempts = payload.get("attempts")
            if isinstance(provider_attempts, list) and provider_attempts:
                normalized_attempts = _normalize_provider_attempts(provider_attempts)
            else:
                normalized_attempts = [{"provider": provider, "status": "ok"}]
            results = _curate_search_results(
                provider=selected_provider,
                query=query,
                results=list(payload.get("results") or []),
                limit=limit,
                attempts=normalized_attempts,
            )
            attempts.extend(normalized_attempts)
            _set_search_provider_probe(provider, available=True, detail="available")
            break
        except Exception as exc:
            _invalidate_search_provider_probe(provider)
            provider_attempts = _normalize_provider_attempts(_provider_attempts_from_exception(provider=provider, exc=exc))
            attempts.extend(provider_attempts)
            for item in provider_attempts:
                notices.append(_attempt_notice(item))
            logger.warning("Web search provider %s failed: %s", provider, exc)

    if not results:
        _raise_search_failure(query=query, limit=limit, attempts=attempts, notices=notices)

    degraded = bool(selected_provider and selected_provider != providers[0])
    if degraded:
        notices.append("search degraded to fallback backend")
    out = {
        "schema_version": "1.0.0",
        "ok": True,
        "provider_used": selected_provider,
        "degraded": degraded,
        "expectation_mismatch": bool(degraded or notices),
        "provider_attempts": attempts,
        "results": results,
    }
    if notices:
        out["notices"] = notices
    evidence_refs.append(evidence.add_json(out, kind="tool_io"))


def _web_browse(*, req: ExecuteRequest, evidence: FileEvidenceStore, evidence_refs: list[EvidenceRef]) -> None:
    inp = dict(req.arguments or {})
    url = str(inp.get("url") or "").strip()
    if not url:
        raise ValueError("url is required")
    payload = playwright_browse(url=url)
    evidence_refs.append(
        evidence.add_json(
            {
                "schema_version": "1.0.0",
                "ok": True,
                "provider_used": payload["provider_used"],
                "url": payload["url"],
                "final_url": payload["final_url"],
                "title": payload["title"],
                "output": {
                    "reply": payload["text"],
                    "url": payload["final_url"],
                    "title": payload["title"],
                },
            },
            kind="tool_io",
        )
    )


def _run_search_provider(*, provider: str, query: str, limit: int) -> dict[str, Any]:
    name = str(provider or "").strip()
    if name == "brave":
        provider_used, results = _brave_search(query=query, limit=limit)
        return {
            "provider_used": provider_used,
            "results": results,
            "attempts": [{"provider": "brave", "status": "ok"}],
        }
    if name == "duckduckgo_html":
        payload = duckduckgo_html_search(query=query, limit=limit, include_metadata=True)
        return _normalize_provider_payload(provider=name, payload=payload)
    if name == "playwright_search":
        payload = playwright_search(query=query, limit=limit, allow_query_resubmit=True, include_metadata=True)
        return _normalize_provider_payload(provider=name, payload=payload)
    raise RuntimeError(f"unknown web search provider: {provider}")


def _normalize_provider_payload(*, provider: str, payload: Any) -> dict[str, Any]:
    if isinstance(payload, dict):
        out = dict(payload)
    elif isinstance(payload, tuple) and len(payload) >= 2:
        out = {"provider_used": str(payload[0] or provider).strip() or provider, "results": list(payload[1] or [])}
    else:
        raise RuntimeError(f"provider {provider} returned unexpected payload shape")
    attempts = out.get("attempts")
    if not isinstance(attempts, list) or not attempts:
        attempts = [{"provider": provider, "status": "ok"}]
    out["attempts"] = _normalize_provider_attempts(attempts)
    return out


def _normalize_provider_attempts(attempts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in attempts:
        if not isinstance(item, dict):
            continue
        normalized = {
            "provider": str(item.get("provider") or "unknown").strip() or "unknown",
            "status": str(item.get("status") or "failed").strip() or "failed",
        }
        variant = str(item.get("variant") or "").strip()
        error_code = str(item.get("error_code") or "").strip()
        detail = str(item.get("detail") or "").strip()
        if variant:
            normalized["variant"] = variant
        if error_code:
            normalized["error_code"] = error_code
        if detail:
            normalized["detail"] = detail[:240]
        out.append(normalized)
    return out


def _provider_attempts_from_exception(*, provider: str, exc: Exception) -> list[dict[str, Any]]:
    payload = getattr(exc, "payload", None)
    attempts = payload.get("attempts") if isinstance(payload, dict) else None
    if isinstance(attempts, list) and attempts:
        return attempts
    item: dict[str, Any] = {
        "provider": str(provider or "unknown").strip() or "unknown",
        "status": "failed",
    }
    variant = ""
    if isinstance(payload, dict):
        variant = str(payload.get("variant") or "").strip()
    error_code = str(getattr(exc, "error_code", "") or "").strip()
    detail = str(exc).strip()
    if variant:
        item["variant"] = variant
    if error_code:
        item["error_code"] = error_code
    if detail:
        item["detail"] = detail[:240]
    return [item]


def _attempt_notice(item: dict[str, Any]) -> str:
    provider = str(item.get("provider") or "unknown").strip() or "unknown"
    variant = str(item.get("variant") or "").strip()
    detail = str(item.get("detail") or "").strip()
    label = provider if not variant else f"{provider}[{variant}]"
    if detail:
        return f"{label} unavailable: {detail[:240]}"
    return f"{label} unavailable"


def _coerce_positive_int(value: Any, *, default: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except Exception:
        return default
    if parsed <= 0:
        return default
    return min(parsed, maximum)


def _curate_search_results(
    *,
    provider: str,
    query: str,
    results: list[dict[str, Any]],
    limit: int,
    attempts: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    normalized_results = [_normalize_search_result(item) for item in results if isinstance(item, dict)]
    if not normalized_results:
        _reject_provider_results(
            provider=provider,
            query=query,
            attempts=attempts,
            detail=f"{provider} returned no usable search results after normalization",
        )
    return normalized_results[:limit]


def _normalize_search_result(item: dict[str, Any]) -> dict[str, str]:
    return {
        "title": " ".join(str(item.get("title") or "").split()).strip(),
        "snippet": " ".join(str(item.get("snippet") or "").split()).strip(),
        "url": str(item.get("url") or "").strip(),
    }


def _reject_provider_results(*, provider: str, query: str, attempts: list[dict[str, Any]], detail: str) -> None:
    normalized_attempts = [dict(item) for item in attempts if isinstance(item, dict)]
    if normalized_attempts:
        normalized_attempts[-1]["status"] = "failed"
        normalized_attempts[-1]["error_code"] = "E_WEB_SEARCH_NO_RESULTS"
        normalized_attempts[-1]["detail"] = str(detail or "").strip()[:240]
    else:
        normalized_attempts = [
            {
                "provider": str(provider or "unknown").strip() or "unknown",
                "status": "failed",
                "error_code": "E_WEB_SEARCH_NO_RESULTS",
                "detail": str(detail or "").strip()[:240],
            }
        ]
    raise SearchRuntimeError(
        "E_WEB_SEARCH_NO_RESULTS",
        str(detail or "").strip() or f"{provider} returned no usable search results for query={query!r}",
        payload={"provider": provider, "attempts": normalized_attempts},
    )


def _brave_api_key() -> str:
    return str(os.getenv("BRAVE_SEARCH_API_KEY") or os.getenv("BRAVE_API_KEY") or "").strip()


def _brave_search(*, query: str, limit: int, timeout_seconds: int = 15) -> tuple[str, list[dict[str, Any]]]:
    api_key = _brave_api_key()
    if not api_key:
        raise RuntimeError("BRAVE_SEARCH_API_KEY is not configured")
    params = urllib.parse.urlencode(
        {
            "q": query,
            "count": int(limit),
            "text_decorations": "false",
            "spellcheck": "true",
        }
    )
    req = urllib.request.Request(
        f"{_BRAVE_SEARCH_ENDPOINT}?{params}",
        method="GET",
        headers={
            "Accept": "application/json",
            "X-Subscription-Token": api_key,
            "User-Agent": "agentos-next-web-search/1.0",
        },
    )
    with urllib.request.urlopen(req, timeout=max(1, int(timeout_seconds))) as resp:
        obj = json.loads(resp.read().decode("utf-8"))
    items = (((obj.get("web") or {}).get("results")) or []) if isinstance(obj, dict) else []
    if not isinstance(items, list):
        raise RuntimeError("Brave Search API returned unexpected payload shape")
    results: list[dict[str, Any]] = []
    for item in items[:limit]:
        if not isinstance(item, dict):
            continue
        title = " ".join(str(item.get("title") or "").split()).strip()
        snippet = " ".join(str(item.get("description") or "").split()).strip()
        url = str(item.get("url") or "").strip()
        if title or snippet or url:
            results.append({"title": title, "snippet": snippet, "url": url})
    if not results:
        raise SearchRuntimeError("E_WEB_SEARCH_NO_RESULTS", "Brave Search API returned no usable results")
    return "brave", results


def _build_structured_error_payload(
    *,
    operator_ref: str,
    error_code: str,
    message: str,
    payload: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    out = {
        "schema_version": "1.0.0",
        "ok": False,
        "error_code": str(error_code or "E_EXECUTION_FAILED").strip() or "E_EXECUTION_FAILED",
        "message": str(message or "").strip(),
        "operator_ref": str(operator_ref or "").strip(),
    }
    if isinstance(payload, dict):
        for key, value in payload.items():
            if key in {"schema_version", "ok", "error_code", "message", "operator_ref"}:
                continue
            out[key] = value
    return out


def _raise_search_failure(
    *,
    query: str,
    limit: int,
    attempts: list[dict[str, Any]],
    notices: list[str],
) -> None:
    error_code = _derive_search_failure_code(attempts=attempts)
    payload = {
        "schema_version": "1.0.0",
        "ok": False,
        "operator_ref": "builtin://web.search",
        "query": str(query or "").strip(),
        "limit": int(limit),
        "degraded": False,
        "expectation_mismatch": True,
        "provider_attempts": list(attempts),
        "results": [],
    }
    if notices:
        payload["notices"] = list(notices)
    raise BuiltinWebRuntimeError(
        error_code,
        _compose_search_failure(query=query, attempts=attempts),
        payload=payload,
    )


def _derive_search_failure_code(*, attempts: list[dict[str, Any]]) -> str:
    for item in reversed(attempts):
        code = str(item.get("error_code") or "").strip()
        if code:
            return code
    details = " ".join(str(item.get("detail") or "").strip() for item in attempts if str(item.get("detail") or "").strip())
    lowered = details.lower()
    if "no usable results" in lowered or "homepage/search portal" in lowered or "homepage without usable results" in lowered:
        return "E_WEB_SEARCH_NO_RESULTS"
    if "not configured" in lowered or "runtime is unavailable" in lowered or "network egress is disabled" in lowered:
        return "E_WEB_RUNTIME_UNAVAILABLE"
    return "E_EXECUTION_FAILED"


def _compose_search_failure(*, query: str, attempts: list[dict[str, Any]]) -> str:
    if not attempts:
        return f"web search failed for {query!r}: no provider attempts were made"
    parts: list[str] = []
    for item in attempts:
        provider = str(item.get("provider") or "unknown")
        variant = str(item.get("variant") or "").strip()
        status = str(item.get("status") or "failed")
        error_code = str(item.get("error_code") or "").strip()
        detail = str(item.get("detail") or "").strip()
        label = provider if not variant else f"{provider}[{variant}]"
        if error_code and detail:
            parts.append(f"{label}:{status}:{error_code}:{detail}")
        elif error_code:
            parts.append(f"{label}:{status}:{error_code}")
        elif detail:
            parts.append(f"{label}:{status}:{detail}")
        else:
            parts.append(f"{label}:{status}")
    return f"web search failed for {query!r}; attempts=" + " | ".join(parts)
