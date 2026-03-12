from __future__ import annotations

from typing import Any


def _contains_any(text: str, hints: tuple[str, ...]) -> bool:
    lowered = str(text or "").lower()
    return any(hint in lowered or hint in text for hint in hints)


def derive_research_requirements_v1(
    *,
    query_text: str,
    task_requirements: dict[str, Any] | None,
    mode: str,
    risk: str,
    context_planes: dict[str, Any] | None = None,
) -> dict[str, Any]:
    text = " ".join(str(query_text or "").split())
    reqs = dict(task_requirements or {})
    retrospective = dict((context_planes or {}).get("retrospective_plane") or {})
    recent_failures = list(retrospective.get("recent_failures") or [])
    requires_external_evidence = bool(reqs.get("requires_external_evidence"))
    requires_workspace_observation = bool(reqs.get("requires_workspace_observation"))
    requires_multi_step_plan = bool(reqs.get("requires_multi_step_plan"))

    research_hints = (
        "deep research",
        "research report",
        "compare research",
        "multi-source",
        "multiple sources",
        "with citations",
        "citations",
        "citation",
        "sources",
        "report",
        "深入调研",
        "调研报告",
        "对比研究",
        "多来源",
        "带引用",
        "引用结论",
        "引用",
        "来源",
        "报告",
        "调研",
    )
    ambiguity_hints = (
        "best",
        "better",
        "should",
        "whether",
        "if",
        "哪个",
        "哪个更",
        "是否",
        "怎么选",
        "要不要",
    )
    research_required = bool(requires_external_evidence and _contains_any(text, research_hints))
    high_ambiguity = _contains_any(text, ambiguity_hints)
    repeated_failure_pressure = len(recent_failures) >= 2
    citation_required = bool(research_required)
    self_adversarial_required = bool(
        risk == "high"
        or (
            research_required
            and (
                str(mode) == "complex"
                or high_ambiguity
                or repeated_failure_pressure
            )
        )
    )

    if research_required:
        research_depth = "deep" if self_adversarial_required else "standard"
        evidence_expectation = "research_citation_set"
    elif requires_external_evidence:
        research_depth = "lookup"
        evidence_expectation = "external_lookup"
    elif requires_workspace_observation:
        research_depth = "workspace"
        evidence_expectation = "workspace_observation"
    else:
        research_depth = "none"
        evidence_expectation = "local_state"

    if self_adversarial_required:
        selected_doctrine_pack = "self_adversarial_mode"
    elif research_required:
        selected_doctrine_pack = "browser_research_mode"
    elif requires_external_evidence or requires_workspace_observation or requires_multi_step_plan or str(mode) != "simple":
        selected_doctrine_pack = "scientific_hypothesis_mode"
    else:
        selected_doctrine_pack = "fast_path_mode"

    source_count_min = 2 if research_required else (1 if requires_external_evidence else 0)
    return {
        "schema_version": "1.0.0",
        "type": "research_doctrine_v1",
        "research_required": research_required,
        "research_depth": research_depth,
        "selected_doctrine_pack": selected_doctrine_pack,
        "evidence_expectation": evidence_expectation,
        "citation_required": citation_required,
        "self_adversarial_required": self_adversarial_required,
        "research_max_rounds": 3 if self_adversarial_required else (2 if research_required else 1),
        "source_count_min": int(source_count_min),
    }


def build_research_evidence_pack_v1(
    *,
    task_id: str,
    objective: str,
    task_requirements: dict[str, Any] | None,
    exec_summaries: list[dict[str, Any]],
    step_outputs: list[dict[str, Any]],
    error_code: str | None = None,
) -> dict[str, Any] | None:
    reqs = dict(task_requirements or {})
    if not bool(reqs.get("requires_external_evidence")):
        return None

    query_history: list[dict[str, Any]] = []
    visited_sources: list[dict[str, Any]] = []
    accepted_evidence: list[dict[str, Any]] = []
    contradictions: list[str] = []
    gaps: list[str] = []
    final_citation_set: list[dict[str, Any]] = []
    seen_urls: set[str] = set()

    for index, step in enumerate(exec_summaries):
        if not isinstance(step, dict):
            continue
        output_obj = step_outputs[index] if index < len(step_outputs) and isinstance(step_outputs[index], dict) else {}
        operator_ref = str(step.get("operator_ref") or "").strip()
        arguments = dict(step.get("arguments") or {}) if isinstance(step.get("arguments"), dict) else {}
        if operator_ref == "builtin://web.search":
            results = output_obj.get("results")
            query_history.append(
                {
                    "query": str(arguments.get("query") or output_obj.get("query") or "").strip(),
                    "status": str(step.get("status") or "").strip() or "unknown",
                    "error_code": str(step.get("error_code") or output_obj.get("error_code") or "").strip() or None,
                    "result_count": len(results) if isinstance(results, list) else 0,
                }
            )
            if isinstance(results, list):
                for item in results[:5]:
                    if not isinstance(item, dict):
                        continue
                    url = str(item.get("url") or "").strip()
                    if not url or url in seen_urls:
                        continue
                    seen_urls.add(url)
                    accepted_evidence.append(
                        {
                            "kind": "search_result",
                            "title": str(item.get("title") or "").strip(),
                            "url": url,
                            "snippet": str(item.get("snippet") or "").strip(),
                        }
                    )
        elif operator_ref == "builtin://web.browse":
            payload = dict(output_obj.get("output") or {}) if isinstance(output_obj.get("output"), dict) else {}
            url = str(payload.get("url") or output_obj.get("final_url") or output_obj.get("url") or arguments.get("url") or "").strip()
            if not url:
                continue
            summary = str(payload.get("reply") or output_obj.get("text") or "").strip()
            title = str(payload.get("title") or output_obj.get("title") or "").strip()
            if url not in seen_urls:
                seen_urls.add(url)
            visited_sources.append(
                {
                    "url": url,
                    "title": title or url,
                    "status": str(step.get("status") or "").strip() or "unknown",
                }
            )
            final_citation_set.append({"title": title or url, "url": url})
            if summary:
                accepted_evidence.append(
                    {
                        "kind": "page_extract",
                        "title": title or url,
                        "url": url,
                        "summary": summary[:320],
                    }
                )
        elif operator_ref == "builtin://research.run":
            search_queries = output_obj.get("search_queries")
            if isinstance(search_queries, list):
                for item in search_queries:
                    if not isinstance(item, dict):
                        continue
                    query = str(item.get("query") or "").strip()
                    if not query:
                        continue
                    query_history.append(
                        {
                            "query": query,
                            "status": str(step.get("status") or "").strip() or "unknown",
                            "error_code": str(step.get("error_code") or output_obj.get("error_code") or "").strip() or None,
                            "result_count": int(item.get("result_count") or 0),
                        }
                    )
            visited = output_obj.get("visited_sources")
            if isinstance(visited, list):
                for item in visited:
                    if not isinstance(item, dict):
                        continue
                    url = str(item.get("url") or "").strip()
                    if not url:
                        continue
                    visited_sources.append(
                        {
                            "url": url,
                            "title": str(item.get("title") or url).strip() or url,
                            "status": str(item.get("status") or step.get("status") or "").strip() or "unknown",
                            "error_code": str(item.get("error_code") or "").strip() or None,
                        }
                    )
            citations = output_obj.get("citations")
            if isinstance(citations, list):
                seen_citation_urls = {
                    str(item.get("url") or "").strip()
                    for item in final_citation_set
                    if isinstance(item, dict) and str(item.get("url") or "").strip()
                }
                for item in citations:
                    if not isinstance(item, dict):
                        continue
                    url = str(item.get("url") or "").strip()
                    if not url or url in seen_citation_urls:
                        continue
                    seen_citation_urls.add(url)
                    final_citation_set.append(
                        {
                            "title": str(item.get("title") or url).strip() or url,
                            "url": url,
                        }
                    )
            sources = output_obj.get("sources")
            if isinstance(sources, list):
                for item in sources:
                    if not isinstance(item, dict):
                        continue
                    url = str(item.get("url") or "").strip()
                    if not url or url in seen_urls:
                        continue
                    seen_urls.add(url)
                    accepted_evidence.append(
                        {
                            "kind": "research_source",
                            "title": str(item.get("title") or url).strip() or url,
                            "url": url,
                            "summary": str(item.get("excerpt") or output_obj.get("summary") or "").strip()[:320],
                        }
                    )

    if not query_history and not visited_sources and not accepted_evidence:
        return None
    if error_code and not accepted_evidence:
        gaps.append(f"external evidence unavailable: {error_code}")
    if bool(reqs.get("citation_required")) and not final_citation_set:
        gaps.append("citation set is empty")

    return {
        "schema_version": "1.0.0",
        "type": "research_evidence_pack_v1",
        "task_id": str(task_id or "").strip(),
        "objective": str(objective or "").strip(),
        "research_required": bool(reqs.get("research_required")),
        "research_depth": str(reqs.get("research_depth") or "lookup").strip() or "lookup",
        "selected_doctrine_pack": str(reqs.get("selected_doctrine_pack") or "").strip() or None,
        "evidence_expectation": str(reqs.get("evidence_expectation") or "").strip() or None,
        "citation_required": bool(reqs.get("citation_required")),
        "query_history": query_history,
        "visited_sources": visited_sources,
        "accepted_evidence": accepted_evidence,
        "contradictions": contradictions,
        "gaps": gaps,
        "final_citation_set": final_citation_set,
        "max_rounds": int(reqs.get("research_max_rounds") or 1),
    }
