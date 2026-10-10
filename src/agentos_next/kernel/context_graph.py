from __future__ import annotations

from typing import Any

CONTEXT_ACTIONS_V1 = (
    "context_expand",
    "context_shift",
    "context_narrow",
    "context_fork",
    "context_merge",
)

PROMPT_PROFILE_IDS_V1 = (
    "intent_router",
    "planner",
    "executor",
    "verifier_replanner",
    "communicator",
)


def _uniq(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for raw in items:
        value = str(raw or "").strip()
        if not value or value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


def _node(
    *,
    node_id: str,
    node_type: str,
    tags: list[str],
    scope: str,
    trust_level: str,
    freshness: str,
    source: str,
    cost: int,
    ref: str | None,
    summary: str,
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "node_id": str(node_id),
        "type": str(node_type),
        "tags": _uniq(tags),
        "scope": str(scope),
        "trust_level": str(trust_level),
        "freshness": str(freshness),
        "source": str(source),
        "cost": int(cost),
        "ref": str(ref).strip() if str(ref or "").strip() else None,
        "summary": str(summary or "").strip(),
        "data": dict(data or {}),
    }


def _edge(*, edge_id: str, relation: str, from_id: str, to_id: str, note: str = "") -> dict[str, Any]:
    return {
        "edge_id": str(edge_id),
        "relation": str(relation),
        "from": str(from_id),
        "to": str(to_id),
        "note": str(note or "").strip(),
    }


def infer_domain_tags_v1(
    *,
    query_text: str,
    interaction_mode: str,
    task_requirements: dict[str, Any] | None,
    intent_recovery: dict[str, Any] | None,
) -> list[str]:
    text = " ".join(str(query_text or "").lower().split())
    reqs = dict(task_requirements or {})
    intent = dict(intent_recovery or {})
    domains: list[str] = []
    option = str(intent.get("intent_option") or "").strip().upper()
    if interaction_mode == "chat" or option == "CHAT_SMALLTALK":
        domains.append("chat")
    if option in {"UNKNOWN", "ACK_CONTINUE", "ACK_EXECUTE", "ACK_CONFIRM"} or interaction_mode == "confirm":
        domains.append("intent_routing")
    if bool(reqs.get("requires_workspace_observation")):
        domains.append("project_work")
    if bool(reqs.get("requires_external_evidence")):
        domains.append("web_research")
    if any(token in text for token in ("会议", "日程", "calendar", "meeting", "schedule", "安排")):
        domains.append("calendar_meeting")
    if any(token in text for token in ("记住", "remember", "memory", "回忆", "想起来", "查记忆")):
        domains.append("memory_lookup")
    if any(token in text for token in ("跟进", "follow up", "follow-up", "提醒", "稍后", "明天")) or option in {
        "FOLLOWUP_PENDING",
        "ASK_STATUS",
    }:
        domains.append("follow_up")
    if not domains:
        domains.append("intent_routing" if interaction_mode in {"confirm", "status"} else "chat")
    return _uniq(domains)


def build_context_graph_v1(
    *,
    query_text: str,
    workspace_id: str,
    trace_id: str,
    turn_id: str,
    task_envelope: dict[str, Any],
    context_planes: dict[str, Any],
    task_requirements: dict[str, Any] | None,
    solution_query: dict[str, Any] | None,
    intent_recovery: dict[str, Any] | None,
    interaction_mode: str,
    agent_profile: dict[str, Any],
    soul_profile: dict[str, Any],
) -> dict[str, Any]:
    execution_plane = dict((context_planes or {}).get("execution_plane") or {})
    communication_plane = dict((context_planes or {}).get("communication_plane") or {})
    retrospective_plane = dict((context_planes or {}).get("retrospective_plane") or {})
    constraint_plane = dict((context_planes or {}).get("constraint_plane") or {})
    recovery_plane = dict((context_planes or {}).get("intent_recovery_plane") or {})
    reqs = dict(task_requirements or {})
    solution = dict(solution_query or {})
    intent = dict(intent_recovery or {})
    global_soul = dict(soul_profile.get("global_soul") or {})
    global_capsule = dict(communication_plane.get("global_capsule") or {})
    project_capsule = dict(execution_plane.get("project_capsule") or {})
    temporal_anchor = dict(execution_plane.get("temporal_anchor") or {})
    domain_tags = infer_domain_tags_v1(
        query_text=query_text,
        interaction_mode=interaction_mode,
        task_requirements=reqs,
        intent_recovery=intent,
    )
    task_id = str(task_envelope.get("task_id") or "").strip() or f"task_{trace_id}_{turn_id}"
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []

    identity_id = f"identity:{str(soul_profile.get('soul_profile_id') or 'default_assistant').strip() or 'default_assistant'}"
    nodes.append(
        _node(
            node_id=identity_id,
            node_type="identity",
            tags=["identity", *domain_tags],
            scope="assistant/global",
            trust_level="trusted",
            freshness="stable",
            source="soul_profile",
            cost=1,
            ref=str(soul_profile.get("soul_profile_id") or "").strip() or "default_assistant",
            summary=str(global_soul.get("identity_summary") or global_capsule.get("identity_summary") or "").strip()
            or f"agent:{str(agent_profile.get('agent_id') or 'assistant').strip()}",
            data={
                "boundary_rules": list(global_soul.get("boundary_rules") or soul_profile.get("boundary_rules") or []),
                "trust_principles": list(global_soul.get("trust_principles") or []),
                "style_defaults": list(
                    (
                        dict(soul_profile.get("communication_defaults") or {}).get("style")
                        or global_capsule.get("communication_style")
                        or []
                    )
                ),
            },
        )
    )

    turn_node_id = f"conversation_turn:{turn_id}"
    nodes.append(
        _node(
            node_id=turn_node_id,
            node_type="conversation_turn",
            tags=["conversation", interaction_mode, *domain_tags],
            scope="conversation",
            trust_level="trusted",
            freshness="turn",
            source="runtime_ingress",
            cost=1,
            ref=f"turn:{turn_id}",
            summary=" ".join(str(query_text or "").split())[:160],
            data={
                "workspace_id": str(workspace_id),
                "trace_id": str(trace_id),
                "turn_id": str(turn_id),
                "message_received_at_utc": execution_plane.get("message_received_at_utc"),
                "temporal_anchor": temporal_anchor or None,
            },
        )
    )
    edges.append(_edge(edge_id="edge_identity_turn", relation="parent_of", from_id=identity_id, to_id=turn_node_id))

    intent_node_id = f"user_intent:{task_id}"
    nodes.append(
        _node(
            node_id=intent_node_id,
            node_type="user_intent",
            tags=["intent", interaction_mode, *domain_tags],
            scope="task",
            trust_level="derived",
            freshness="current",
            source="query_gated_runtime",
            cost=1,
            ref=str(intent.get("intent_option") or "").strip() or "DIRECT_TASK",
            summary=str(solution.get("resolved_objective") or task_envelope.get("objective") or query_text).strip(),
            data={
                "intent_option": str(intent.get("intent_option") or "DIRECT_TASK"),
                "interaction_mode": str(interaction_mode),
                "solution_strategy": str(solution.get("approach_strategy") or ""),
                "requires_workspace_observation": bool(reqs.get("requires_workspace_observation")),
                "requires_external_evidence": bool(reqs.get("requires_external_evidence")),
                "research_required": bool(reqs.get("research_required")),
                "research_depth": str(reqs.get("research_depth") or "none").strip() or "none",
                "selected_doctrine_pack": str(reqs.get("selected_doctrine_pack") or "").strip() or None,
            },
        )
    )
    edges.append(_edge(edge_id="edge_turn_intent", relation="relevant_to", from_id=turn_node_id, to_id=intent_node_id))

    policy_node_id = f"policy:{str(agent_profile.get('agent_id') or 'assistant_loop').strip() or 'assistant_loop'}"
    nodes.append(
        _node(
            node_id=policy_node_id,
            node_type="policy",
            tags=["policy", "constraints", *domain_tags],
            scope="assistant/policy",
            trust_level="trusted",
            freshness="stable",
            source="agent_profile",
            cost=1,
            ref=str(agent_profile.get("agent_id") or "").strip() or "assistant_loop",
            summary="agent profile, constraints, and execution policy",
            data={
                "execution_axiom_ids": list(constraint_plane.get("execution_axiom_ids") or []),
                "communication_axiom_ids": list(constraint_plane.get("communication_axiom_ids") or []),
                "active_constraint_ids": list(constraint_plane.get("active_constraint_ids") or []),
            },
        )
    )
    edges.append(_edge(edge_id="edge_policy_intent", relation="supports", from_id=policy_node_id, to_id=intent_node_id))

    project_id = str(project_capsule.get("project_id") or recovery_plane.get("active_project_id") or "").strip()
    if project_id:
        project_node_id = f"project_artifact:{project_id}"
        nodes.append(
            _node(
                node_id=project_node_id,
                node_type="project_artifact",
                tags=["project", "workspace", "artifact", "project_work"],
                scope="workspace/project",
                trust_level="trusted",
                freshness="session",
                source="project_capsule",
                cost=2,
                ref=project_id,
                summary=str(project_capsule.get("summary") or project_capsule.get("title") or project_id).strip(),
                data={
                    "title": str(project_capsule.get("title") or project_id).strip(),
                    "evidence_refs": list(project_capsule.get("evidence_refs") or []),
                },
            )
        )
        edges.append(_edge(edge_id="edge_project_intent", relation="relevant_to", from_id=project_node_id, to_id=intent_node_id))

    pending_contract = dict(recovery_plane.get("pending_contract") or {}) if isinstance(recovery_plane.get("pending_contract"), dict) else {}
    if pending_contract or str(recovery_plane.get("last_delivery_summary") or "").strip():
        task_result_id = f"task_result:{task_id}:continuity"
        nodes.append(
            _node(
                node_id=task_result_id,
                node_type="task_result",
                tags=["continuity", "task_result", *domain_tags],
                scope="conversation/task",
                trust_level="trusted",
                freshness="session",
                source="runtime_snapshot",
                cost=1,
                ref=str(pending_contract.get("type") or "continuity_contract_v1"),
                summary=str(
                    pending_contract.get("objective")
                    or recovery_plane.get("last_delivery_summary")
                    or recovery_plane.get("last_pending_task")
                    or ""
                ).strip(),
                data={
                    "pending_contract": pending_contract,
                    "last_delivery_state": recovery_plane.get("last_delivery_state"),
                    "last_delivery_summary": recovery_plane.get("last_delivery_summary"),
                },
            )
        )
        edges.append(_edge(edge_id="edge_continuity_intent", relation="depends_on", from_id=intent_node_id, to_id=task_result_id))

    for idx, failure in enumerate(retrospective_plane.get("recent_failures") or [], start=1):
        node_id = f"failure_record:{idx}"
        nodes.append(
            _node(
                node_id=node_id,
                node_type="failure_record",
                tags=["failure", "retrospective", *domain_tags],
                scope="assistant/retrospective",
                trust_level="trusted",
                freshness="recent",
                source="hypothesis_store",
                cost=1,
                ref=f"recent_failure:{idx}",
                summary=str(failure).strip()[:180],
                data={"index": idx},
            )
        )
        edges.append(_edge(edge_id=f"edge_failure_{idx}", relation="contradicts", from_id=node_id, to_id=intent_node_id))

    theorem_ids = [str(x).strip() for x in (solution.get("retrieved_theorem_ids") or []) if str(x).strip()]
    theorem_summaries = [str(x).strip() for x in (solution.get("retrieved_theorem_summaries") or []) if str(x).strip()]
    for idx, theorem_id in enumerate(theorem_ids, start=1):
        summary = theorem_summaries[idx - 1] if idx - 1 < len(theorem_summaries) else theorem_id
        node_id = f"playbook:{theorem_id}"
        nodes.append(
            _node(
                node_id=node_id,
                node_type="playbook",
                tags=["playbook", "procedure", *domain_tags],
                scope="assistant/procedure",
                trust_level="trusted",
                freshness="stable",
                source="theorem_store",
                cost=1,
                ref=theorem_id,
                summary=summary,
                data={"theorem_id": theorem_id},
            )
        )
        edges.append(_edge(edge_id=f"edge_playbook_{idx}", relation="supports", from_id=node_id, to_id=intent_node_id))

    if bool(reqs.get("requires_external_evidence")):
        nodes.append(
            _node(
                node_id=f"knowledge_doc:{task_id}",
                node_type="knowledge_doc",
                tags=["knowledge", "external_evidence", "web_research"],
                scope="task",
                trust_level="derived",
                freshness="current",
                source="task_requirements",
                cost=2,
                ref=str(solution.get("approach_strategy") or "external_evidence"),
                summary="task requires external evidence before final delivery",
                data={"must_stop_without_evidence": bool(solution.get("must_stop_without_evidence"))},
            )
        )
        edges.append(
            _edge(
                edge_id="edge_knowledge_intent",
                relation="supports",
                from_id=f"knowledge_doc:{task_id}",
                to_id=intent_node_id,
            )
        )

    return {
        "schema_version": "1.0.0",
        "type": "context_graph_v1",
        "workspace_id": str(workspace_id),
        "trace_id": str(trace_id),
        "turn_id": str(turn_id),
        "task_id": task_id,
        "domain_tags": domain_tags,
        "context_actions": list(CONTEXT_ACTIONS_V1),
        "nodes": nodes,
        "edges": edges,
    }


def _node_ids_by_type(context_graph: dict[str, Any], *node_types: str) -> list[str]:
    allow = {str(x) for x in node_types}
    out: list[str] = []
    for node in context_graph.get("nodes") or []:
        if not isinstance(node, dict):
            continue
        if str(node.get("type") or "") in allow:
            node_id = str(node.get("node_id") or "").strip()
            if node_id:
                out.append(node_id)
    return out


def build_task_context_views_v1(
    *,
    context_graph: dict[str, Any],
    task_envelope: dict[str, Any],
    delivery_contract: dict[str, Any],
    context_planes: dict[str, Any],
    task_requirements: dict[str, Any] | None,
    solution_query: dict[str, Any] | None,
    intent_recovery: dict[str, Any] | None,
    interaction_mode: str,
) -> dict[str, Any]:
    execution_plane = dict((context_planes or {}).get("execution_plane") or {})
    communication_plane = dict((context_planes or {}).get("communication_plane") or {})
    retrospective_plane = dict((context_planes or {}).get("retrospective_plane") or {})
    reqs = dict(task_requirements or {})
    solution = dict(solution_query or {})
    intent = dict(intent_recovery or {})
    domain_tags = list(context_graph.get("domain_tags") or [])
    evidence_refs = [str(x).strip() for x in (execution_plane.get("evidence_refs") or []) if str(x).strip()]
    temporal_anchor = dict(execution_plane.get("temporal_anchor") or {})
    recent_failures = [str(x).strip() for x in (retrospective_plane.get("recent_failures") or []) if str(x).strip()]
    recent_successes = [
        str(x).strip() for x in (retrospective_plane.get("recent_success_patterns") or []) if str(x).strip()
    ]
    known_facts = [str(x).strip() for x in (task_envelope.get("known_facts") or []) if str(x).strip()]
    temporal_facts = [
        str(x).strip()
        for x in known_facts
        if str(x).startswith("anchor_time_")
        or str(x).startswith("timezone_local=")
        or str(x).startswith("date_local=")
        or str(x).startswith("weekday_local=")
        or str(x).startswith("relative_date_")
    ]
    open_questions = [str(x).strip() for x in (task_envelope.get("open_questions") or []) if str(x).strip()]
    playbook_refs = _node_ids_by_type(context_graph, "playbook")
    dependency_refs = _node_ids_by_type(context_graph, "task_result", "project_artifact")
    communication_style = [
        str(x).strip()
        for x in (
            (communication_plane.get("style_constraints") or [])
            or (communication_plane.get("communication_style") or [])
        )
        if str(x).strip()
    ]
    response_language = str(communication_plane.get("response_language") or "").strip()
    attachment_media_kinds = [
        str(x).strip()
        for x in (reqs.get("attachment_media_kinds") or [])
        if str(x).strip()
    ]
    attachment_reachability = dict(reqs.get("downstream_modality_reachability") or {})

    def _view(
        *,
        profile_id: str,
        goal: str,
        constraints: list[str],
        relevant_facts: list[str],
        source_node_ids: list[str],
    ) -> dict[str, Any]:
        return {
            "schema_version": "1.0.0",
            "type": "task_context_view_v1",
            "profile_id": str(profile_id),
            "goal": str(goal).strip(),
            "constraints": _uniq(constraints),
            "relevant_facts": _uniq(relevant_facts),
            "verified_evidence_refs": evidence_refs,
            "recent_trial_records": recent_failures[:4],
            "recent_success_patterns": recent_successes[:4],
            "dependency_task_results": dependency_refs,
            "playbook_refs": playbook_refs[:4],
            "allowed_context_actions": list(CONTEXT_ACTIONS_V1),
            "source_node_ids": _uniq(source_node_ids),
            "domain_tags": domain_tags,
            "minimal_sufficient_context": True,
        }

    views = {
        "intent_router": _view(
            profile_id="intent_router",
            goal=str(solution.get("resolved_objective") or task_envelope.get("objective") or "").strip()
            or "bind the user's intent to a concrete task",
            constraints=[
                "prefer deterministic intent binding before model fallback",
                "separate communication style from execution constraints",
                "ask for clarification only when local state cannot bind intent safely",
            ],
            relevant_facts=[
                f"intent_option={str(intent.get('intent_option') or 'DIRECT_TASK')}",
                f"interaction_mode={str(interaction_mode)}",
                f"continuity_binding={str(solution.get('continuity_binding') or 'raw_input')}",
                f"attachments_present={bool(reqs.get('attachments_present'))}",
                f"attachment_usage_mode={str(reqs.get('attachment_usage_mode') or 'none')}",
                *temporal_facts[:4],
                *open_questions[:2],
            ],
            source_node_ids=_node_ids_by_type(context_graph, "conversation_turn", "user_intent", "task_result"),
        ),
        "planner": _view(
            profile_id="planner",
            goal=str(task_envelope.get("objective") or "").strip(),
            constraints=[
                "select domains and dependencies before execution",
                "request context expansion instead of hallucinating when context is insufficient",
                "respect task requirements and active constraints",
            ],
            relevant_facts=[
                f"deliverable={str(task_envelope.get('deliverable') or '')}",
                f"approach_strategy={str(solution.get('approach_strategy') or '')}",
                f"requires_workspace_observation={bool(reqs.get('requires_workspace_observation'))}",
                f"requires_external_evidence={bool(reqs.get('requires_external_evidence'))}",
                f"attachments_present={bool(reqs.get('attachments_present'))}",
                f"attachment_usage_mode={str(reqs.get('attachment_usage_mode') or 'none')}",
                f"required_media_kinds={'|'.join(attachment_media_kinds) if attachment_media_kinds else '-'}",
                f"multimodal_chain_supported={bool(reqs.get('multimodal_chain_supported'))}",
                f"research_required={bool(reqs.get('research_required'))}",
                f"research_depth={str(reqs.get('research_depth') or 'none')}",
                f"requires_multi_step_plan={bool(reqs.get('requires_multi_step_plan'))}",
                *temporal_facts[:4],
                *known_facts[:3],
                *open_questions[:2],
            ],
            source_node_ids=_node_ids_by_type(
                context_graph,
                "user_intent",
                "policy",
                "project_artifact",
                "playbook",
                "failure_record",
            ),
        ),
        "executor": _view(
            profile_id="executor",
            goal=str(task_envelope.get("objective") or "").strip(),
            constraints=[
                "use minimal sufficient context",
                "default to hypothesis -> verify -> revise for non-trivial tasks",
                "do not conclude without evidence when evidence is required",
                *[str(x).strip() for x in (task_envelope.get("constraints") or []) if str(x).strip()],
            ],
            relevant_facts=[
                f"deliverable={str(task_envelope.get('deliverable') or '')}",
                f"done_definition={str(delivery_contract.get('done_definition') or '')}",
                f"state_summary={str(execution_plane.get('state_summary') or '')}",
                f"attachment_usage_mode={str(reqs.get('attachment_usage_mode') or 'none')}",
                f"required_media_kinds={'|'.join(attachment_media_kinds) if attachment_media_kinds else '-'}",
                f"executor_supports_required_media={bool((attachment_reachability.get('executor') or {}).get('supports_required_media'))}",
                *temporal_facts[:4],
                *known_facts[:4],
            ],
            source_node_ids=_node_ids_by_type(
                context_graph,
                "user_intent",
                "policy",
                "project_artifact",
                "knowledge_doc",
                "playbook",
            ),
        ),
        "verifier_replanner": _view(
            profile_id="verifier_replanner",
            goal=str(task_envelope.get("objective") or "").strip()
            or str(delivery_contract.get("done_definition") or "").strip()
            or "verify whether delivery criteria are met",
            constraints=[
                "verification must inspect evidence and delivery criteria before success",
                "if evidence is insufficient, request revise or more context",
                "rejected paths require new evidence or a revised hypothesis",
                "treat web.search as candidate discovery and web.browse as source verification; do not confuse them",
                "when research is required, preserve a bounded citation set or report an explicit blocker",
            ],
            relevant_facts=[
                f"objective={str(task_envelope.get('objective') or '')}",
                f"done_definition={str(delivery_contract.get('done_definition') or '')}",
                f"requires_external_evidence={bool(reqs.get('requires_external_evidence'))}",
                f"attachment_usage_mode={str(reqs.get('attachment_usage_mode') or 'none')}",
                f"required_media_kinds={'|'.join(attachment_media_kinds) if attachment_media_kinds else '-'}",
                f"verifier_supports_required_media={bool((attachment_reachability.get('verifier_replanner') or {}).get('supports_required_media'))}",
                f"text_only_fallback_allowed={bool(reqs.get('text_only_fallback_allowed'))}",
                f"research_required={bool(reqs.get('research_required'))}",
                f"citation_required={bool(reqs.get('citation_required'))}",
                f"required_operator_hints={'|'.join(str(x).strip() for x in (reqs.get('required_operator_hints') or []) if str(x).strip()) or '-'}",
                *temporal_facts[:4],
                *[str(x).strip() for x in (delivery_contract.get("verification_requirements") or []) if str(x).strip()],
                *[str(x).strip() for x in (task_envelope.get("acceptance_criteria") or []) if str(x).strip()][:4],
            ],
            source_node_ids=_node_ids_by_type(context_graph, "failure_record", "playbook", "task_result", "user_intent"),
        ),
        "communicator": _view(
            profile_id="communicator",
            goal="prepare a user-visible communication brief that preserves truthfulness and task boundaries",
            constraints=[
                "communication style must not override execution truth",
                "all user-visible delivery must eventually flow through send_message task",
                "preserve citations, uncertainty, and blockers when research doctrine requires them",
                *([f"response_language={response_language}"] if response_language else []),
                *[f"style={x}" for x in communication_style[:4]],
            ],
            relevant_facts=[
                f"role_hint={str(communication_plane.get('role_hint') or communication_plane.get('soul_profile_id') or 'assistant')}",
                f"interaction_mode={str(interaction_mode)}",
                f"citation_required={bool(reqs.get('citation_required'))}",
                f"attachment_usage_mode={str(reqs.get('attachment_usage_mode') or 'none')}",
                *([f"date_local={str(temporal_anchor.get('date_local') or '').strip()}"] if str(temporal_anchor.get("date_local") or "").strip() else []),
                *([f"timezone_local={str(temporal_anchor.get('timezone_local') or '').strip()}"] if str(temporal_anchor.get("timezone_local") or "").strip() else []),
                *([f"response_language={response_language}"] if response_language else []),
                *recent_successes[:2],
            ],
            source_node_ids=_node_ids_by_type(context_graph, "identity", "conversation_turn", "user_intent", "task_result"),
        ),
    }
    return {
        "schema_version": "1.0.0",
        "type": "task_context_views_v1",
        "views": views,
    }
