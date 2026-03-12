from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from agentos_next.kernel.evidence_store import FileEvidenceStore
from agentos_next.kernel.executor import ExecuteRequest, ExecuteResult, ExecuteTiming
from agentos_next.kernel.trace_logger import FileTraceLogger
from agentos_next.kernel.types import EvidenceRef, TraceEvent
from agentos_next.runtime.builtin_web import (
    _attempt_notice,
    _normalize_provider_attempts,
    _normalize_search_result,
    _provider_attempts_from_exception,
    _run_search_provider,
)
from agentos_next.runtime.playwright_web_runtime import PlaywrightRuntimeError, playwright_browse


@dataclass(frozen=True)
class BuiltinDispatchResult:
    handled: bool
    result: Optional[ExecuteResult] = None


class BuiltinResearchRuntimeError(RuntimeError):
    def __init__(self, error_code: str, message: str, *, payload: Optional[dict[str, Any]] = None) -> None:
        super().__init__(message)
        self.error_code = str(error_code or "E_RESEARCH_INCOMPLETE").strip() or "E_RESEARCH_INCOMPLETE"
        self.payload = dict(payload or {})


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def maybe_execute_builtin_research(*, req: ExecuteRequest, data_dir: str) -> BuiltinDispatchResult:
    if not req.operator_ref.startswith("builtin://research."):
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
        if name != "research.run":
            raise ValueError(f"unknown builtin: {name}")
        output = _research_run(req=req)
        out_ref = evidence.add_json(output, kind="tool_io")
        evidence_refs.append(out_ref)
        _emit("TOOL_CALL_FINISHED", ers=(out_ref,), data={"builtin": name, "ok": True})
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
    except BuiltinResearchRuntimeError as exc:
        err_ref = evidence.add_json(
            {
                "schema_version": "1.0.0",
                "ok": False,
                "error_code": exc.error_code,
                "message": str(exc),
                **dict(exc.payload or {}),
            },
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
            {
                "schema_version": "1.0.0",
                "ok": False,
                "error_code": exc.error_code,
                "message": str(exc),
            },
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
            {
                "schema_version": "1.0.0",
                "ok": False,
                "error_code": "E_EXECUTION_FAILED",
                "message": str(exc),
            },
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


def _research_run(*, req: ExecuteRequest) -> dict[str, Any]:
    inp = dict(req.arguments or {})
    objective = str(inp.get("objective") or inp.get("query") or "").strip()
    if not objective:
        raise ValueError("objective is required")
    depth = _normalize_depth(inp.get("depth"))
    report_format = str(inp.get("report_format") or "markdown").strip().lower() or "markdown"
    if report_format != "markdown":
        raise ValueError("report_format must be markdown")
    min_sources = _coerce_positive_int(inp.get("min_sources"), default=3, maximum=8)
    rounds = 2 if depth == "standard" else 3
    search_limit = max(5, min(10, min_sources * 2))

    query_variants = _research_query_variants(objective=objective, rounds=rounds)
    search_queries: list[dict[str, Any]] = []
    visited_sources: list[dict[str, Any]] = []
    sources: list[dict[str, Any]] = []
    provider_attempts: list[dict[str, Any]] = []
    notices: list[str] = []
    seen_urls: set[str] = set()

    for query in query_variants:
        search_payload = _search_candidates(query=query, limit=search_limit)
        provider_attempts.extend([dict(item) for item in search_payload.get("provider_attempts") or [] if isinstance(item, dict)])
        search_queries.append(
            {
                "query": query,
                "provider_used": str(search_payload.get("provider_used") or "").strip() or None,
                "result_count": len(search_payload.get("results") or []),
                "degraded": bool(search_payload.get("degraded")),
            }
        )
        for notice in search_payload.get("notices") or []:
            text = str(notice or "").strip()
            if text and text not in notices:
                notices.append(text)
        for rank, item in enumerate(search_payload.get("results") or [], start=1):
            if not isinstance(item, dict):
                continue
            url = str(item.get("url") or "").strip()
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            try:
                browse_payload = playwright_browse(url=url)
            except PlaywrightRuntimeError as exc:
                visited_sources.append(
                    {
                        "url": url,
                        "title": str(item.get("title") or url).strip() or url,
                        "status": "failed",
                        "error_code": exc.error_code,
                        "message": str(exc),
                        "search_query": query,
                        "search_rank": rank,
                    }
                )
                continue
            excerpt = _compact_text(str(browse_payload.get("text") or ""), limit=600)
            title = str(browse_payload.get("title") or item.get("title") or url).strip() or url
            final_url = str(browse_payload.get("final_url") or url).strip() or url
            source = {
                "title": title,
                "url": final_url,
                "excerpt": excerpt,
                "search_query": query,
                "search_rank": rank,
            }
            sources.append(source)
            visited_sources.append(
                {
                    "url": final_url,
                    "title": title,
                    "status": "accepted",
                    "search_query": query,
                    "search_rank": rank,
                }
            )
            if len(sources) >= min_sources:
                break
        if len(sources) >= min_sources:
            break

    if len(sources) < min_sources:
        raise BuiltinResearchRuntimeError(
            "E_RESEARCH_INCOMPLETE",
            "explicit research could not collect enough readable sources within the current search and browse budget",
            payload={
                "objective": objective,
                "depth": depth,
                "report_format": report_format,
                "min_sources": min_sources,
                "source_count": len(sources),
                "search_queries": search_queries,
                "visited_sources": visited_sources,
                "provider_attempts": provider_attempts,
                "notices": notices,
            },
        )

    citations = [
        {
            "id": f"[{index}]",
            "title": str(item.get("title") or "").strip(),
            "url": str(item.get("url") or "").strip(),
        }
        for index, item in enumerate(sources, start=1)
    ]
    summary = _render_research_summary(objective=objective, sources=sources, citations=citations)
    report = _render_research_report(
        objective=objective,
        depth=depth,
        min_sources=min_sources,
        sources=sources,
        citations=citations,
        search_queries=search_queries,
    )
    return {
        "schema_version": "1.0.0",
        "ok": True,
        "objective": objective,
        "depth": depth,
        "report_format": report_format,
        "min_sources": min_sources,
        "summary": summary,
        "report": report,
        "citations": citations,
        "sources": sources,
        "visited_sources": visited_sources,
        "search_queries": search_queries,
        "provider_attempts": provider_attempts,
        "notices": notices,
    }


def _normalize_depth(value: Any) -> str:
    raw = str(value or "standard").strip().lower() or "standard"
    if raw not in {"standard", "deep"}:
        return "standard"
    return raw


def _coerce_positive_int(value: Any, *, default: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except Exception:
        return default
    if parsed <= 0:
        return default
    return min(parsed, maximum)


def _research_query_variants(*, objective: str, rounds: int) -> list[str]:
    raw = " ".join(str(objective or "").split()).strip()
    cleaned = raw
    for token in (
        "深入调研",
        "调研报告",
        "调研",
        "对比研究",
        "多来源",
        "带引用",
        "引用",
        "sources",
        "citations",
        "report",
    ):
        cleaned = cleaned.replace(token, " ")
    cleaned = " ".join(cleaned.split()).strip()
    variants = [raw]
    if cleaned and cleaned != raw:
        variants.append(cleaned)
    return variants[: max(1, int(rounds))]


def _search_candidates(*, query: str, limit: int) -> dict[str, Any]:
    attempts: list[dict[str, Any]] = []
    notices: list[str] = []
    providers = ["brave", "duckduckgo_html", "playwright_search"]
    selected_provider = ""
    results: list[dict[str, Any]] = []
    for provider in providers:
        try:
            payload = _run_search_provider(provider=provider, query=query, limit=limit)
            selected_provider = str(payload.get("provider_used") or provider).strip() or provider
            provider_attempts = payload.get("attempts")
            if isinstance(provider_attempts, list) and provider_attempts:
                normalized_attempts = _normalize_provider_attempts(provider_attempts)
            else:
                normalized_attempts = [{"provider": provider, "status": "ok"}]
            normalized_results = [_normalize_search_result(item) for item in (payload.get("results") or []) if isinstance(item, dict)]
            if not normalized_results:
                normalized_attempts = [dict(item) for item in normalized_attempts]
                normalized_attempts[-1]["status"] = "failed"
                normalized_attempts[-1]["error_code"] = "E_WEB_SEARCH_NO_RESULTS"
                normalized_attempts[-1]["detail"] = "provider returned no usable search results after normalization"
                attempts.extend(normalized_attempts)
                notices.extend(_attempt_notice(item) for item in normalized_attempts)
                continue
            attempts.extend(normalized_attempts)
            results = normalized_results[:limit]
            break
        except Exception as exc:
            provider_attempts = _normalize_provider_attempts(_provider_attempts_from_exception(provider=provider, exc=exc))
            attempts.extend(provider_attempts)
            notices.extend(_attempt_notice(item) for item in provider_attempts)
    if not results:
        raise BuiltinResearchRuntimeError(
            "E_RESEARCH_SEARCH_UNAVAILABLE",
            f"explicit research could not retrieve usable search candidates for objective={query!r}",
            payload={
                "query": query,
                "provider_attempts": attempts,
                "notices": notices,
            },
        )
    degraded = bool(selected_provider and selected_provider != providers[0])
    if degraded:
        notices.append("research degraded to fallback search backend")
    deduped_notices = list(dict.fromkeys(str(item).strip() for item in notices if str(item).strip()))
    return {
        "query": query,
        "provider_used": selected_provider,
        "degraded": degraded,
        "provider_attempts": attempts,
        "results": results,
        "notices": deduped_notices,
    }


def _compact_text(value: str, *, limit: int) -> str:
    text = " ".join(str(value or "").split()).strip()
    return text[: max(1, int(limit))]


def _render_research_summary(
    *,
    objective: str,
    sources: list[dict[str, Any]],
    citations: list[dict[str, Any]],
) -> str:
    lines = [f"已围绕“{objective}”收集 {len(sources)} 个已读来源。"]
    for source, citation in zip(sources[:3], citations[:3], strict=False):
        excerpt = _compact_text(str(source.get("excerpt") or ""), limit=120)
        title = str(source.get("title") or "").strip() or str(source.get("url") or "").strip()
        if excerpt:
            lines.append(f"{citation['id']} {title}: {excerpt}")
        else:
            lines.append(f"{citation['id']} {title}")
    return "\n".join(lines)


def _render_research_report(
    *,
    objective: str,
    depth: str,
    min_sources: int,
    sources: list[dict[str, Any]],
    citations: list[dict[str, Any]],
    search_queries: list[dict[str, Any]],
) -> str:
    lines = [
        "# 调研报告",
        "",
        "## 目标",
        objective,
        "",
        "## 调研设置",
        f"- depth: {depth}",
        f"- min_sources: {min_sources}",
    ]
    if search_queries:
        lines.extend(["", "## 查询轨迹"])
        for item in search_queries:
            lines.append(
                "- "
                + " | ".join(
                    part
                    for part in [
                        f"query={str(item.get('query') or '').strip()}",
                        f"provider={str(item.get('provider_used') or '').strip()}",
                        f"result_count={int(item.get('result_count') or 0)}",
                        f"degraded={bool(item.get('degraded'))}",
                    ]
                    if part
                )
            )
    lines.extend(["", "## 来源摘录"])
    for source, citation in zip(sources, citations, strict=False):
        title = str(source.get("title") or "").strip() or str(source.get("url") or "").strip()
        url = str(source.get("url") or "").strip()
        excerpt = str(source.get("excerpt") or "").strip()
        lines.extend(
            [
                f"### {citation['id']} {title}",
                f"- URL: {url}",
                f"- Search Query: {str(source.get('search_query') or '').strip()}",
                f"- Search Rank: {int(source.get('search_rank') or 0)}",
                "",
                excerpt or "无可用摘录。",
                "",
            ]
        )
    lines.extend(["## 引用", *[f"- {item['id']} {item['title']} <{item['url']}>" for item in citations]])
    return "\n".join(lines).strip()
