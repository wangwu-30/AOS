from __future__ import annotations

from typing import Any

PROMPT_PROFILE_IDS_V1 = (
    "intent_router",
    "planner",
    "executor",
    "verifier_replanner",
    "communicator",
)

ALLOWED_REWRITE_SLOTS_V1 = (
    "retrieval_query",
    "task_framing",
    "hypothesis_condensation",
    "communication_brief",
)

IMMUTABLE_PROMPT_SECTIONS_V1 = (
    "global_soul",
    "role_axioms",
    "safety_boundaries",
    "tool_constraints",
    "output_schema",
    "send_message_policy",
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


def _statement_list(items: Any) -> list[str]:
    if not isinstance(items, list):
        return []
    out: list[str] = []
    for item in items:
        if isinstance(item, dict):
            value = str(item.get("statement") or item.get("text") or "").strip()
        else:
            value = str(item or "").strip()
        if value:
            out.append(value)
    return out


def _normalize_response_language(raw: Any) -> str:
    value = str(raw or "").strip()
    return value


def _pick_style_pack(
    *,
    soul_profile: dict[str, Any],
    context_planes: dict[str, Any],
) -> dict[str, Any]:
    style_packs = dict(soul_profile.get("style_packs") or {})
    communication_plane = dict((context_planes or {}).get("communication_plane") or {})
    requested = [
        str(x).strip()
        for x in (
            (communication_plane.get("style_constraints") or [])
            or (communication_plane.get("communication_style") or [])
            or []
        )
        if str(x).strip()
    ]
    requested_lower = {x.lower() for x in requested}
    for pack_id, pack in style_packs.items():
        if not isinstance(pack, dict):
            continue
        aliases = {str(pack_id).strip().lower()}
        aliases.update(str(x).strip().lower() for x in (pack.get("traits") or []) if str(x).strip())
        if requested_lower & aliases:
            out = dict(pack)
            out["pack_id"] = str(pack_id)
            return out
    defaults = dict(soul_profile.get("communication_defaults") or {})
    default_traits = [str(x).strip() for x in (defaults.get("style") or []) if str(x).strip()]
    if "formal" in requested_lower and isinstance(style_packs.get("formal"), dict):
        out = dict(style_packs["formal"])
        out["pack_id"] = "formal"
        return out
    if isinstance(style_packs.get("concise"), dict):
        out = dict(style_packs["concise"])
        out["pack_id"] = "concise"
        return out
    return {
        "pack_id": "session_style",
        "tone": str(defaults.get("tone") or "direct").strip() or "direct",
        "verbosity": str(defaults.get("verbosity") or "concise").strip() or "concise",
        "traits": requested or default_traits or ["clear", "honest", "concise"],
        "guidance": "style constraints only affect user-visible communication, not factual judgment",
    }


def _pick_doctrine_pack(
    *,
    soul_profile: dict[str, Any],
    mode: str,
    interaction_mode: str,
    task_requirements: dict[str, Any] | None,
) -> dict[str, Any]:
    reqs = dict(task_requirements or {})
    doctrine_packs = dict(soul_profile.get("doctrine_packs") or {})
    explicit = str(reqs.get("selected_doctrine_pack") or "").strip()
    if explicit and isinstance(doctrine_packs.get(explicit), dict):
        out = dict(doctrine_packs[explicit])
        out["pack_id"] = explicit
        return out
    use_scientific = (
        interaction_mode not in {"chat", "status"}
        and (
            str(mode) != "simple"
            or bool(reqs.get("requires_workspace_observation"))
            or bool(reqs.get("requires_external_evidence"))
            or bool(reqs.get("requires_multi_step_plan"))
            or bool(reqs.get("forbid_speculation_without_evidence"))
        )
    )
    selected = "scientific_hypothesis_mode" if use_scientific else "fast_path_mode"
    pack = doctrine_packs.get(selected)
    if isinstance(pack, dict):
        out = dict(pack)
        out["pack_id"] = selected
        return out
    if use_scientific:
        return {
            "pack_id": selected,
            "summary": "propose hypothesis, verify, then revise or pass",
            "steps": ["hypothesis", "verify", "revise_or_pass"],
            "verification_required": True,
        }
    return {
        "pack_id": selected,
        "summary": "use a shorter path for low-risk tasks while keeping evidence visible",
        "steps": ["act", "quick_check", "deliver_or_escalate"],
        "verification_required": True,
    }


def _role_axioms_for_profile(
    *,
    profile_id: str,
    agent_profile: dict[str, Any],
    soul_profile: dict[str, Any],
) -> dict[str, Any]:
    soul_role_axioms = dict(soul_profile.get("role_axioms") or {})
    execution_axioms = _statement_list(agent_profile.get("execution_axioms") or agent_profile.get("axioms") or [])
    communication_axioms = _statement_list(agent_profile.get("communication_axioms") or [])
    if profile_id == "communicator":
        statements = communication_axioms + _statement_list(soul_role_axioms.get("communication_axioms"))
    elif profile_id == "planner":
        statements = execution_axioms + _statement_list(soul_role_axioms.get("planning_axioms"))
    elif profile_id == "verifier_replanner":
        statements = execution_axioms + _statement_list(soul_role_axioms.get("verification_axioms"))
    elif profile_id == "intent_router":
        statements = communication_axioms + _statement_list(soul_role_axioms.get("planning_axioms"))
    else:
        statements = execution_axioms + _statement_list(soul_role_axioms.get("task_processing_axioms"))
    return {
        "profile_id": str(profile_id),
        "statements": _uniq(statements)[:8],
    }


def _domain_policy_pack(
    *,
    domain_tags: list[str],
    interaction_mode: str,
    task_requirements: dict[str, Any] | None,
    solution_query: dict[str, Any] | None,
) -> dict[str, Any]:
    reqs = dict(task_requirements or {})
    solution = dict(solution_query or {})
    rules: list[str] = []
    for domain in domain_tags:
        if domain == "chat":
            rules.append("natural conversation is allowed, but truthfulness still dominates style")
        elif domain == "intent_routing":
            rules.append("bind low-signal follow-ups to pending contracts before creating new tasks")
        elif domain == "project_work":
            rules.append("inspect workspace artifacts before concluding about the codebase")
        elif domain == "calendar_meeting":
            rules.append("treat time, participants, and action ownership as explicit facts")
        elif domain == "web_research":
            rules.append("separate verified external evidence from prior memory and assumptions")
        elif domain == "memory_lookup":
            rules.append("distinguish retrieved memory from fresh observation")
        elif domain == "follow_up":
            rules.append("preserve continuity contracts instead of overwriting them with short acknowledgements")
    if bool(reqs.get("forbid_speculation_without_evidence")):
        rules.append("when evidence is required, stop instead of filling gaps with speculation")
    if bool(reqs.get("research_required")):
        rules.append("for research tasks, perform bounded search -> browse -> compare -> cite before claiming convergence")
    if bool(reqs.get("citation_required")):
        rules.append("when citations are required, preserve a bounded citation set or report a blocker")
    if bool(reqs.get("self_adversarial_required")):
        rules.append("for self-adversarial mode, run hypothesis -> challenge -> revision with explicit evidence each round")
    if str(solution.get("approach_strategy") or "").strip():
        rules.append(f"preferred approach: {str(solution.get('approach_strategy') or '').strip()}")
    return {
        "domain_tags": list(domain_tags),
        "interaction_mode": str(interaction_mode),
        "rules": _uniq(rules)[:8],
    }


def _output_contract_for_profile(profile_id: str) -> dict[str, Any]:
    contracts = {
        "intent_router": {
            "result_kind": "IntentDecision",
            "requirements": [
                "return a bounded intent decision",
                "surface missing information only when local state cannot bind safely",
            ],
        },
        "planner": {
            "result_kind": "PlanDecision",
            "requirements": [
                "return worker tasks, dependencies, and context needs",
                "declare domain shifts explicitly",
            ],
        },
        "executor": {
            "result_kind": "ExecutionDecision",
            "requirements": [
                "return worker-local reasoning plus the next bounded tool actions",
                "do not emit direct user-visible delivery; delivery must flow through send_message task",
                "when emitting multiple tool actions, make dependencies explicit with action ids",
            ],
        },
        "verifier_replanner": {
            "result_kind": "VerifyDecision",
            "requirements": [
                "judge pass, revise worker tasks, or blocked against evidence and delivery contract",
                "record why the current hypothesis passed or failed",
            ],
        },
        "communicator": {
            "result_kind": "MessageDecision",
            "requirements": [
                "prepare a communication brief without changing task truth",
                "all final delivery still requires send_message task",
            ],
        },
    }
    return dict(contracts.get(profile_id) or {})


def _render_reasoning_prompt(
    *,
    profile_id: str,
    stable_head: str,
    dynamic_slots: dict[str, Any],
) -> str:
    lines = [stable_head, "", "[DYNAMIC_SLOTS]"]
    for key in (
        "goal",
        "constraints",
        "relevant_facts",
        "verified_evidence_refs",
        "recent_trial_records",
        "dependency_task_results",
        "playbook_refs",
        "domain_tags",
        "allowed_context_actions",
        "retrieval_query",
        "task_framing",
        "hypothesis_condensation",
        "communication_brief",
        "response_language",
    ):
        value = dynamic_slots.get(key)
        if isinstance(value, list):
            rendered = " | ".join(str(x).strip() for x in value if str(x).strip()) or "-"
        else:
            rendered = str(value or "").strip() or "-"
        lines.append(f"{key.upper()}={rendered}")
    lines.append(f"PROFILE_ID={profile_id}")
    return "\n".join(lines).strip()


def compile_prompt_bundle_v1(
    *,
    agent_profile: dict[str, Any],
    soul_profile: dict[str, Any],
    context_planes: dict[str, Any],
    context_graph: dict[str, Any],
    task_context_views: dict[str, Any],
    interaction_mode: str,
    mode: str,
    task_requirements: dict[str, Any] | None,
    solution_query: dict[str, Any] | None,
    response_language: str | None = None,
) -> dict[str, Any]:
    global_soul = dict(soul_profile.get("global_soul") or {})
    views = dict(task_context_views.get("views") or {})
    domain_tags = [str(x).strip() for x in (context_graph.get("domain_tags") or []) if str(x).strip()]
    style_pack = _pick_style_pack(soul_profile=soul_profile, context_planes=context_planes)
    language_value = _normalize_response_language(
        response_language or dict((context_planes or {}).get("communication_plane") or {}).get("response_language")
    )
    doctrine_pack = _pick_doctrine_pack(
        soul_profile=soul_profile,
        mode=str(mode),
        interaction_mode=str(interaction_mode),
        task_requirements=task_requirements,
    )
    domain_policy_pack = _domain_policy_pack(
        domain_tags=domain_tags,
        interaction_mode=interaction_mode,
        task_requirements=task_requirements,
        solution_query=solution_query,
    )
    reqs = dict(task_requirements or {})
    required_media_kinds = [str(x).strip() for x in (reqs.get("required_media_kinds") or []) if str(x).strip()]
    reachability = dict(reqs.get("downstream_modality_reachability") or {})

    profiles: dict[str, Any] = {}
    for profile_id in PROMPT_PROFILE_IDS_V1:
        view = dict(views.get(profile_id) or {})
        role_axioms = _role_axioms_for_profile(
            profile_id=profile_id,
            agent_profile=agent_profile,
            soul_profile=soul_profile,
        )
        output_contract = _output_contract_for_profile(profile_id)
        head_lines = [
            f"PROMPT_PROFILE={profile_id}",
            f"GLOBAL_SOUL={str(global_soul.get('identity_summary') or soul_profile.get('identity_summary') or '').strip()}",
            f"STYLE_PACK={str(style_pack.get('pack_id') or 'session_style')}",
            f"RESPONSE_LANGUAGE={language_value or 'auto'}",
            f"DOCTRINE_PACK={str(doctrine_pack.get('pack_id') or 'scientific_hypothesis_mode')}",
            f"DOMAINS={'|'.join(domain_tags) if domain_tags else '-'}",
            f"ATTACHMENTS_PRESENT={bool(reqs.get('attachments_present'))}",
            f"ATTACHMENT_USAGE_MODE={str(reqs.get('attachment_usage_mode') or 'none')}",
            f"REQUIRED_MEDIA_KINDS={'|'.join(required_media_kinds) if required_media_kinds else '-'}",
            f"TEXT_ONLY_FALLBACK_ALLOWED={bool(reqs.get('text_only_fallback_allowed'))}",
            f"MULTIMODAL_CHAIN_SUPPORTED={bool(reqs.get('multimodal_chain_supported'))}",
            "IMMUTABLE=global_soul|role_axioms|safety_boundaries|tool_constraints|output_schema|send_message_policy",
            "REWRITEABLE=retrieval_query|task_framing|hypothesis_condensation|communication_brief",
            "SEND_MESSAGE_POLICY=direct user-visible delivery must be expressed as send_message task",
            "ROLE_AXIOMS=" + (" | ".join(role_axioms.get("statements") or []) or "-"),
            "DOMAIN_POLICY=" + (" | ".join(domain_policy_pack.get("rules") or []) or "-"),
            "OUTPUT_CONTRACT=" + (" | ".join(output_contract.get("requirements") or []) or "-"),
        ]
        stable_head = "\n".join(str(x).strip() for x in head_lines if str(x).strip())
        dynamic_slots = {
            "goal": str(view.get("goal") or "").strip() or "execute the current profile responsibly",
            "constraints": list(view.get("constraints") or []),
            "relevant_facts": list(view.get("relevant_facts") or []),
            "verified_evidence_refs": list(view.get("verified_evidence_refs") or []),
            "recent_trial_records": list(view.get("recent_trial_records") or []),
            "dependency_task_results": list(view.get("dependency_task_results") or []),
            "playbook_refs": list(view.get("playbook_refs") or []),
            "domain_tags": list(view.get("domain_tags") or []),
            "allowed_context_actions": list(view.get("allowed_context_actions") or []),
            "retrieval_query": str(view.get("goal") or "").strip(),
            "hypothesis_condensation": str(doctrine_pack.get("summary") or "").strip(),
            "communication_brief": (
                "speak in the active style pack without changing facts"
                if profile_id == "communicator"
                else "not_applicable"
            ),
            "response_language": language_value or "auto",
            "task_framing": " | ".join(
                [
                    str(view.get("goal") or "").strip() or "execute the current profile responsibly",
                    f"evidence_expectation={str((task_requirements or {}).get('evidence_expectation') or 'local_state')}",
                    f"citation_required={bool((task_requirements or {}).get('citation_required'))}",
                    f"attachment_usage_mode={str(reqs.get('attachment_usage_mode') or 'none')}",
                    f"multimodal_chain_supported={bool(reqs.get('multimodal_chain_supported'))}",
                    (
                        "downstream_supports_required_media="
                        + str(bool((reachability.get(profile_id) or {}).get("supports_required_media")))
                    ),
                ]
            ),
        }
        profiles[profile_id] = {
            "schema_version": "1.0.0",
            "type": "prompt_profile_v1",
            "profile_id": profile_id,
            "stable_head": stable_head,
            "dynamic_slots": dynamic_slots,
            "rewrite_slots_allowed": list(ALLOWED_REWRITE_SLOTS_V1),
            "immutable_sections": list(IMMUTABLE_PROMPT_SECTIONS_V1),
            "role_axioms": role_axioms,
            "style_pack": dict(style_pack),
            "doctrine_pack": dict(doctrine_pack),
            "domain_policy_pack": dict(domain_policy_pack),
            "output_contract": output_contract,
            "source_node_ids": list(view.get("source_node_ids") or []),
            "reasoning_prompt": _render_reasoning_prompt(
                profile_id=profile_id,
                stable_head=stable_head,
                dynamic_slots=dynamic_slots,
            ),
        }

    return {
        "schema_version": "1.0.0",
        "type": "prompt_compilation_v1",
        "compiler_mode": "deterministic_with_rewrite_slots",
        "global_soul": global_soul,
        "active_style_pack": style_pack,
        "active_response_language": language_value or None,
        "active_doctrine_pack": doctrine_pack,
        "domain_policy_pack": domain_policy_pack,
        "profiles": profiles,
    }
